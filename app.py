"""DentalDX — เว็บแอปวิเคราะห์ข้อมูล Data Exchange สภาวะทันตสุขภาพ

รันแบบ dev :  python app.py
รันแบบ exe  :  DentalDX.exe   (เปิดเบราว์เซอร์อัตโนมัติ)
"""
from __future__ import annotations

import io
import os
import sys
import threading
import time
import traceback
import webbrowser

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file

from core import export
from core import profiles as prof_mod
from core import service

# PyInstaller: templates/static ถูก bundle ไว้ใน sys._MEIPASS
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

VERSION = "2.0.0"

app = Flask(__name__,
            template_folder=os.path.join(BASE, "templates"),
            static_folder=os.path.join(BASE, "static"))

# อ่าน template ใหม่ทุกครั้งที่ไฟล์เปลี่ยน (ไม่งั้นต้องปิด-เปิดโปรแกรมใหม่ถึงจะเห็นการแก้ไข)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.jinja_env.cache = None

PROFILES = {}


def build_stamp() -> str:
    """เวลาแก้ไขไฟล์หน้าเว็บล่าสุด — ใช้ยืนยันว่าไม่ได้ติด cache"""
    try:
        path = os.path.join(BASE, "templates", "index.html")
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    except Exception:
        return "-"


def load_profiles():
    global PROFILES
    PROFILES = prof_mod.discover()
    return PROFILES


@app.after_request
def no_cache(resp):
    """กันเบราว์เซอร์ค้างหน้าเก่าเวลาอัปเดตโปรแกรม"""
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/")
def index():
    return render_template("index.html", version=VERSION, build=build_stamp())


@app.route("/api/version")
def api_version():
    return jsonify({"version": VERSION, "build": build_stamp(),
                    "server_time": time.strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/profiles")
def api_profiles():
    load_profiles()
    out = []
    for p in PROFILES.values():
        folder = p.data_folder
        n_files = 0
        if os.path.isdir(folder):
            n_files = len([f for f in os.listdir(folder)
                           if f.lower().endswith((".xlsx", ".xls", ".csv"))
                           and not f.startswith("~$")])
        out.append({"id": p.id, "label": p.label, "age_min": p.age_min,
                    "age_max": p.age_max, "folder": folder, "files": n_files})
    return jsonify(sorted(out, key=lambda x: x["age_min"]))


@app.route("/api/areas")
def api_areas():
    pid = request.args.get("profile")
    p = PROFILES.get(pid) or load_profiles().get(pid)
    if not p:
        return jsonify({"error": f"ไม่พบ profile: {pid}"}), 404
    df = service.get_dataset(p)
    return jsonify(service.area_tree(df))


@app.route("/api/report")
def api_report():
    pid = request.args.get("profile")
    p = PROFILES.get(pid) or load_profiles().get(pid)
    if not p:
        return jsonify({"error": f"ไม่พบ profile: {pid}"}), 404
    try:
        return jsonify(service.report(
            p,
            pv=request.args.get("pv") or None,
            amp=request.args.get("amp") or None,
            hos=request.args.get("hos") or None,
            refresh=request.args.get("refresh") == "1",
        ))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


# --------------------------------------------------------------------------- #
# ส่งออกตารางรายงาน
# --------------------------------------------------------------------------- #

def _report_ctx():
    pid = request.args.get("profile")
    p = PROFILES.get(pid) or load_profiles().get(pid)
    if not p:
        return None, None, None
    pv = request.args.get("pv") or None
    amp = request.args.get("amp") or None
    hos = request.args.get("hos") or None
    rep = service.report(p, pv=pv, amp=amp, hos=hos)
    suffix = hos or amp or pv or "ทั้งหมด"
    return p, rep, f"{pid}_{suffix}"


def _send(data: bytes, name: str, kind: str):
    mime = ("text/csv" if kind == "csv" else
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return send_file(io.BytesIO(data), mimetype=mime,
                     as_attachment=True, download_name=f"{name}.{kind}")


def _pick_frame(rep, which, multi):
    """which = 'overview' หรือเลขตาราง"""
    if which == "overview":
        rows = rep["units"] if rep.get("level") == "unit" else rep["districts"]
        return (export.overview_to_frame(rows, rep.get("level"), rep.get("overview_labels")),
                "ภาพรวมรายพื้นที่", [])
    t = export.find_table(rep, which)
    if t is None:
        return None, None, None
    return (export.table_to_frame(t, multi_header=multi), f"ตารางที่ {t['no']}",
            [f"ตารางที่ {t['no']} {t['title']}"] + list(t.get("conditions") or []))


@app.route("/api/table.csv")
def api_table_csv():
    p, rep, name = _report_ctx()
    if not p:
        return jsonify({"error": "ไม่พบ profile"}), 404
    which = request.args.get("table", "overview")
    df, label, _ = _pick_frame(rep, which, multi=False)
    if df is None:
        return jsonify({"error": f"ไม่พบตารางที่ {which}"}), 404
    return _send(export.csv_bytes(df), f"{label}_{name}", "csv")


@app.route("/api/table.xlsx")
def api_table_xlsx():
    p, rep, name = _report_ctx()
    if not p:
        return jsonify({"error": "ไม่พบ profile"}), 404
    which = request.args.get("table", "overview")
    if which == "all":
        return _send(export.xlsx_bytes(export.report_sheets(rep)), f"รายงานทั้งหมด_{name}", "xlsx")
    df, label, notes = _pick_frame(rep, which, multi=True)
    if df is None:
        return jsonify({"error": f"ไม่พบตารางที่ {which}"}), 404
    return _send(export.xlsx_bytes([(label, df, notes)]), f"{label}_{name}", "xlsx")


def _people_df():
    """kind = pending (ยังไม่ได้ตรวจ) | failed (ตรวจแล้วไม่ผ่านเกณฑ์)"""
    pid = request.args.get("profile")
    p = PROFILES.get(pid) or load_profiles().get(pid)
    if not p:
        return None, None
    kind = request.args.get("kind", "pending")
    if kind not in service.PERSON_KINDS:
        kind = "pending"
    df = service.person_list(
        p, kind,
        pv=request.args.get("pv") or None,
        amp=request.args.get("amp") or None,
        hos=request.args.get("hos") or None,
    )
    scope = (request.args.get("hos") or request.args.get("amp")
             or request.args.get("pv") or "ทั้งหมด")
    return p, (df, kind, f"{service.PERSON_KINDS[kind]}_{pid}_{scope}")


@app.route("/api/people")
@app.route("/api/pending")          # ชื่อเดิม เผื่อหน้าเว็บรุ่นเก่า
def api_people():
    p, res = _people_df()
    if not p:
        return jsonify({"error": "ไม่พบ profile"}), 404
    df, kind, _ = res
    limit = int(request.args.get("limit", "1000"))
    return jsonify({
        "kind": kind,
        "title": service.PERSON_KINDS[kind],
        "total": len(df),
        "shown": min(len(df), limit),
        "columns": list(df.columns),
        "rows": df.head(limit).where(df.notna(), None).to_dict("records"),
    })


@app.route("/api/people.csv")
@app.route("/api/pending.csv")
def api_people_csv():
    p, res = _people_df()
    if not p:
        return jsonify({"error": "ไม่พบ profile"}), 404
    df, _, name = res
    return _send(export.csv_bytes(df), name, "csv")


@app.route("/api/people.xlsx")
@app.route("/api/pending.xlsx")
def api_people_xlsx():
    p, res = _people_df()
    if not p:
        return jsonify({"error": "ไม่พบ profile"}), 404
    df, kind, name = res
    sheet = "ยังไม่ได้ตรวจ" if kind == "pending" else "ไม่ผ่านเกณฑ์"
    return _send(export.xlsx_bytes([(sheet, df, [])], text_cols=export.CODE_COLS),
                 name, "xlsx")


def ensure_folders():
    for d in (prof_mod.data_root(), prof_mod.reference_dir(), prof_mod.profiles_dir()):
        os.makedirs(d, exist_ok=True)
    for p in load_profiles().values():
        os.makedirs(p.data_folder, exist_ok=True)


def main():
    # console ของ Windows มักเป็น cp874 -> พิมพ์ไทยแล้ว crash ได้ จึงบังคับเป็น utf-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ensure_folders()
    port = int(os.environ.get("DENTALDX_PORT", "8765"))

    # ถ้ามีโปรแกรมเก่าค้างอยู่ที่ port เดิม ต้องบอกให้ชัด ไม่ใช่ตายเงียบ ๆ
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print("!" * 62)
            print(f"  PORT {port} IS ALREADY IN USE")
            print("  An older DentalDX is still running and serving the OLD page.")
            print("  Close it first:  run  stop.bat   (or use run.bat, it kills it for you)")
            print("!" * 62)
            input("Press Enter to exit...")
            sys.exit(1)
    # ต่อ ?v=<เวลาแก้ไขหน้าเว็บ> เพื่อให้เบราว์เซอร์ถือว่าเป็น URL ใหม่ทุกครั้งที่อัปเดต
    try:
        stamp = int(os.path.getmtime(os.path.join(BASE, "templates", "index.html")))
    except Exception:
        stamp = int(time.time())
    url = f"http://127.0.0.1:{port}/?v={stamp}"
    # ข้อความใน console เป็น ASCII ล้วน เพื่อให้อ่านออกทุก code page
    print("=" * 62)
    print(f"  DentalDX v{VERSION}  (page build {build_stamp()})")
    print(f"  Data folder : {prof_mod.data_root()}")
    print(f"  Profiles    : {prof_mod.profiles_dir()}")
    print(f"  Open at     : {url}")
    print("  To quit: press Ctrl+C or close this window")
    print("=" * 62)
    if os.environ.get("DENTALDX_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

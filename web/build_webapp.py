#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""สร้างเว็บแอปไฟล์เดียว  dist/DentalDX-Dashboard-vX.Y.Z.html

    python web/build_webapp.py [dist/ชื่อไฟล์.html]

ประกอบจาก
    templates/index.html   หน้า dashboard เดิม (ใช้ CSS และฟังก์ชันวาดหน้าจอชุดเดิม)
    web/src/*.js           อ่าน Excel + คำนวณ + ส่งออกไฟล์
    profiles/*.yaml        ฝังไว้เป็นค่าสำรอง (ถ้าไม่มีโฟลเดอร์ profiles ข้างโปรแกรม)
    reference/hospitals.csv

สิ่งที่แก้จากหน้าเดิม
    - ใส่ Content-Security-Policy ปิดการต่อเน็ตทั้งหมด (connect-src 'none')
    - เปลี่ยน api() จากยิงไป Flask เป็นคำนวณในเครื่อง
    - เปลี่ยนลิงก์ดาวน์โหลดเป็นการสร้างไฟล์ในเบราว์เซอร์
    - ตัดแท็บถาม-ตอบ (AI) ออก (แท็บสำรวจข้อมูล EDA ยังอยู่ครบ)
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "web", "src")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC_FILES = ["00-xlsx.js", "01-expr.js", "02-data.js", "03-engine.js",
             "04-service.js", "05-yaml.js", "06-save.js", "08-eda.js", "07-app.js"]

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_any(path: str) -> str:
    """reference/hospitals.csv เป็น TIS-620 ไม่ใช่ UTF-8"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp874"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def pack_hospitals(path: str) -> dict:
    """บีบตารางหน่วยบริการ — ชื่อจังหวัด/อำเภอ/ตำบลซ้ำกันเยอะ เก็บเป็นดัชนีแทน"""
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(read_any(path))))
    strip = lambda s: re.sub(r"^\d+-", "", (s or "").strip())
    pv, amp, tum, out = {}, {}, {}, []

    def idx(d, v):
        if v not in d:
            d[v] = len(d)
        return d[v]

    for r in rows:
        code = (r.get("hoscode") or "").strip()
        if not code:
            continue
        out.append("%s\t%d\t%d\t%d\t%s\t%s" % (
            code, idx(pv, strip(r.get("pvname"))), idx(amp, strip(r.get("ampname"))),
            idx(tum, strip(r.get("tumbonname"))),
            (r.get("ampcode") or "").strip(), (r.get("pvcode") or "").strip()))
    return {"pv": list(pv), "amp": list(amp), "tum": list(tum), "rows": "\n".join(out)}


def version() -> str:
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', read(os.path.join(ROOT, "app.py")), re.M)
    return m.group(1) if m else "0.0.0"


def load_profiles() -> list:
    """อ่าน profile YAML แล้วฝังเป็น JSON (ค่าสำรองเมื่อไม่มีไฟล์ข้างโปรแกรม)"""
    import yaml
    out = []
    pdir = os.path.join(ROOT, "profiles")
    for name in sorted(os.listdir(pdir)):
        if not name.endswith((".yaml", ".yml")):
            continue
        spec = yaml.safe_load(read(os.path.join(pdir, name)))
        if spec and spec.get("id"):
            out.append(spec)
    if not out:
        raise SystemExit("ไม่พบ profile ในโฟลเดอร์ profiles/")
    return out


def cut(html: str, start: str, end: str, what: str) -> str:
    """ตัดบล็อกโค้ดระหว่างเครื่องหมายสองตัวออก"""
    i = html.find(start)
    if i < 0:
        print("  ! ไม่พบจุดเริ่ม %s (ข้าม)" % what)
        return html
    j = html.find(end, i)
    if j < 0:
        raise SystemExit("ไม่พบจุดจบของ %s" % what)
    print("  ตัด %s ออก (%d ตัวอักษร)" % (what, j - i))
    return html[:i] + html[j:]


def patch_dashboard(html: str) -> str:
    # ---- ตัวแปร Jinja ของ Flask ----
    html = html.replace("{{ version }}", "__VERSION__").replace("{{ build }}", "__BUILD__")

    # ---- CSP + meta ----
    html = html.replace(
        "<style>",
        '<meta http-equiv="Content-Security-Policy" content="%s">\n'
        '<meta name="referrer" content="no-referrer">\n<style>' % CSP, 1)

    # ---- api() ใช้ตัวที่คำนวณในเครื่อง ----
    html = html.replace("""async function api(path) {
  const r = await fetch(path);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}""", """async function api(path) {
  return await window.DX.api(path);          // คำนวณในเครื่อง ไม่มีการต่อเน็ต
}""")

    # ---- คงแท็บสำรวจข้อมูล (EDA) ไว้ ตัดเฉพาะแท็บถาม-ตอบ (AI) ----
    html = html.replace(
        """      .concat([{id: 'eda', label: '🔍 สำรวจข้อมูล', sub: 'คุณภาพ · การกระจาย'},
               {id: 'ask', label: '💬 ถาม-ตอบ', sub: 'พิมพ์คำถามเป็นภาษาสนทนา'}]);""",
        """      .concat([{id: 'eda', label: '🔍 สำรวจข้อมูล', sub: 'คุณภาพ · การกระจาย'}]);""")
    html = html.replace("""      '<div class="pane" data-tab="eda" hidden></div>' +
      '<div class="pane" data-tab="ask" hidden></div>';""",
        """      '<div class="pane" data-tab="eda" hidden></div>';""")
    html = html.replace("""  if (id === 'eda') loadEda();      // คำนวณตอนเปิดแท็บครั้งแรกเท่านั้น
  if (id === 'ask') loadAsk();""",
        """  if (id === 'eda') loadEda();      // คำนวณตอนเปิดแท็บครั้งแรกเท่านั้น""")

    # ---- ปุ่มส่งออก: จากลิงก์ไป Flask เป็นสร้างไฟล์ในเบราว์เซอร์ ----
    html = html.replace("""  return `<span class="xp">
    <a class="dl sm" href="/api/table.csv?${q}" title="ส่งออกเป็น CSV">⬇ CSV</a>
    <a class="dl sm primary" href="/api/table.xlsx?${q}" title="ส่งออกเป็น Excel">⬇ Excel</a>
  </span>`;""", """  return `<span class="xp">
    <button class="dl sm" data-xp="${which}" data-kind="csv" title="ส่งออกเป็น CSV">⬇ CSV</button>
    <button class="dl sm primary" data-xp="${which}" data-kind="xlsx" title="ส่งออกเป็น Excel">⬇ Excel</button>
  </span>`;""")
    html = html.replace("""      `<a class="dl sm primary" href="/api/table.xlsx?${qa}"
          title="ทุกตารางในไฟล์เดียว แยกเป็นชีต">⬇ ส่งออกทุกตาราง (Excel)</a>`;""",
        """      `<button class="dl sm primary" data-xp="all" data-kind="xlsx"
          title="ทุกตารางในไฟล์เดียว แยกเป็นชีต">⬇ บันทึกรายงาน (Excel)</button>`;""")
    before = html
    html = html.replace("""  $('#mCsv').href = '/api/people.csv?' + q;
  $('#mXlsx').href = '/api/people.xlsx?' + q;""",
        """  $('#mCsv').onclick = ev => { ev.preventDefault(); window.DX.exportPeople(d, 'csv'); };
  $('#mXlsx').onclick = ev => { ev.preventDefault(); window.DX.exportPeople(d, 'xlsx'); };""")
    if html == before:
        raise SystemExit("แทนที่ปุ่มส่งออกรายชื่อไม่สำเร็จ — หน้า dashboard เปลี่ยนรูปแบบไปแล้ว")

    # ---- ปุ่มส่งออกต้องผูก event หลังวาดตารางใหม่ทุกครั้ง ----
    html = html.replace("""    selectTab(ACTIVE_TAB);""",
        """    selectTab(ACTIVE_TAB);
    $('#body').querySelectorAll('button[data-xp]').forEach(b => {
      b.onclick = () => window.DX.exportReport(CURRENT, b.dataset.xp, b.dataset.kind);
    });
    $('#topExport').querySelectorAll('button[data-xp]').forEach(b => {
      b.onclick = () => window.DX.exportReport(CURRENT, b.dataset.xp, b.dataset.kind);
    });""")

    # ---- ไม่ต้องเช็กรุ่นกับเซิร์ฟเวอร์ (ไม่มีเซิร์ฟเวอร์) ----
    html = cut(html, "// เตือนถ้าหน้าเว็บที่เปิดอยู่เก่ากว่าที่เซิร์ฟเวอร์มี",
               "const fmt =", "ตัวเช็ครุ่นกับเซิร์ฟเวอร์")

    # ---- ตัดเฉพาะโค้ดแท็บถาม-ตอบ (AI) — โค้ด EDA เก็บไว้ ----
    html = cut(html, "// ---------- แท็บถาม-ตอบ ----------", "// ---------- แท็บรายงาน ----------",
               "โค้ดแท็บถาม-ตอบ")

    # ---- init() รอให้ผู้ใช้เลือกโฟลเดอร์ก่อน ----
    html = html.replace("\ninit();\n", "\nwindow.DX_init = init;\n")
    return html


PICKER = """
<div id="pick" class="pick">
  <div class="pickbox">
    <h1>DentalDX — รายงานการตรวจฟันในเด็ก 0-12 ปี</h1>
    <p class="sub">เวอร์ชัน __VERSION__ · ทำงานในเบราว์เซอร์ทั้งหมด</p>

    <div class="lock">
      🔒 หน้านี้<b>ถูกล็อกไม่ให้เชื่อมต่ออินเทอร์เน็ต</b>ด้วย Content-Security-Policy
      ใช้งานได้แม้ถอดสาย LAN<br>
      ข้อมูลรายบุคคล (ชื่อ เลขบัตรประชาชน ที่อยู่) อยู่ใน<b>หน่วยความจำชั่วคราวเท่านั้น</b>
      ปิดหน้านี้แล้วหายทั้งหมด <b>ไม่มีการบันทึกลงเครื่อง</b><br>
      เบราว์เซอร์จำไว้เฉพาะ<b>ตัวเลขสรุปของรายงานล่าสุด</b> (ไม่มีข้อมูลรายบุคคล)
    </div>

    <p>เลือกโฟลเดอร์ <b>Dashboard-Exam</b> ที่มีโฟลเดอร์ <code>data\\</code> อยู่ข้างใน</p>
    <input type="file" id="pickInput" webkitdirectory directory multiple hidden>
    <button class="big" id="pickBtn">📂 เลือกโฟลเดอร์ข้อมูล</button>
    <div id="dropZone" class="drop">หรือลากโฟลเดอร์มาวางตรงนี้</div>
    <div id="loadMsg" class="msg2"></div>
    <div id="pickErr" class="err2" hidden></div>
    <div id="lastCard" class="last" hidden></div>

    <details class="help">
      <summary>โครงสร้างโฟลเดอร์ที่ถูกต้อง</summary>
<pre>Dashboard-Exam\\
├─ DentalDX-Dashboard-v__VERSION__.html   ← ไฟล์นี้
├─ profiles\\      (ไม่บังคับ — แก้เกณฑ์คำนวณเองได้)
└─ data\\
   ├─ 0-5y\\     วางไฟล์ Data Exchange 0-2 ปี และ 3-5 ปี
   └─ 6-12y\\    วางไฟล์ Data Exchange 6-12 ปี</pre>
    </details>
  </div>
</div>
"""

PICKER_CSS = """
.pick{position:fixed;inset:0;z-index:999;background:var(--bg);overflow:auto;
  display:flex;align-items:flex-start;justify-content:center;padding:34px 18px}
.pickbox{background:var(--panel);border-radius:var(--r);box-shadow:var(--sh);
  padding:26px 28px;max-width:720px;width:100%}
.pickbox h1{margin:0;font-size:20px;color:var(--ink)}
.pickbox .sub{margin:4px 0 16px;font-size:12.5px;color:var(--muted)}
.pickbox p{font-size:13.5px;color:var(--ink2)}
.lock{background:#f2fbf8;border:1px solid #a8e0d2;border-radius:var(--r2);
  padding:12px 14px;font-size:12.5px;line-height:1.85;color:#0d5f52;margin-bottom:18px}
button.big{font-family:inherit;font-size:15px;font-weight:600;padding:13px 26px;border:0;
  border-radius:var(--r2);background:linear-gradient(160deg,#2f9fdc,#4f46e5);color:#fff;
  cursor:pointer;box-shadow:var(--sh)}
button.big:disabled{opacity:.6;cursor:default}
.drop{margin-top:12px;border:2px dashed var(--line);border-radius:var(--r2);
  padding:18px;text-align:center;font-size:12.5px;color:var(--muted)}
.drop.on{border-color:var(--sky);background:#f4fbff;color:var(--sky)}
.msg2{font-size:12.5px;color:var(--ink2);margin-top:12px;min-height:18px}
.err2{background:#ffe9e5;color:#b3261e;border-radius:var(--r2);padding:11px 14px;
  font-size:12.5px;margin-top:12px;line-height:1.8;white-space:pre-wrap}
.last{margin-top:14px;border:1px solid var(--line);border-radius:var(--r2);
  padding:12px 14px;font-size:12.5px;color:var(--ink2);background:#fbfdff}
.help{margin-top:16px;font-size:12.5px;color:var(--muted)}
.help pre{background:#f6f9fc;border:1px solid var(--line);border-radius:var(--r2);
  padding:11px 13px;font-size:11.5px;line-height:1.7;overflow:auto}
.topbar{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
"""

BOOT = """
/* ---------- หน้าเลือกโฟลเดอร์ ---------- */
(function () {
  const $$ = s => document.querySelector(s);
  const errBox = $$('#pickErr');

  function fail(e) {
    errBox.hidden = false;
    errBox.textContent = (e && e.message) ? e.message : String(e);
    $$('#loadMsg').textContent = '';
    $$('#pickBtn').disabled = false;
  }

  async function start(files) {
    errBox.hidden = true;
    $$('#pickBtn').disabled = true;
    try {
      await window.DX.loadFiles(files);
      $$('#pick').remove();
      await window.DX_init();
    } catch (e) {
      fail(e);
    }
  }

  $$('#pickBtn').onclick = () => $$('#pickInput').click();
  $$('#pickInput').onchange = ev => { if (ev.target.files.length) start(ev.target.files); };

  /* ลากโฟลเดอร์มาวาง */
  const dz = $$('#dropZone');
  ['dragenter', 'dragover'].forEach(t => dz.addEventListener(t, e => {
    e.preventDefault(); dz.classList.add('on');
  }));
  ['dragleave', 'drop'].forEach(t => dz.addEventListener(t, e => {
    e.preventDefault(); dz.classList.remove('on');
  }));
  dz.addEventListener('drop', async e => {
    const items = [...(e.dataTransfer.items || [])];
    const out = [];
    async function walk(entry, prefix) {
      if (!entry) return;
      if (entry.isFile) {
        const f = await new Promise(r => entry.file(r));
        Object.defineProperty(f, 'webkitRelativePath', {value: prefix + entry.name});
        out.push(f);
        return;
      }
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise(r => reader.readEntries(r));
        if (!batch.length) break;
        for (const b of batch) await walk(b, prefix + entry.name + '/');
      }
    }
    for (const it of items) {
      const entry = it.webkitGetAsEntry && it.webkitGetAsEntry();
      await walk(entry, '');
    }
    if (out.length) start(out);
    else fail(new Error('ลากโฟลเดอร์ (ไม่ใช่ไฟล์เดี่ยว) มาวาง หรือกดปุ่มเลือกโฟลเดอร์'));
  });

  /* รายงานล่าสุดที่เบราว์เซอร์จำไว้ (ตัวเลขสรุปเท่านั้น) */
  const last = window.DX.loadLast();
  if (last && last.summary) {
    const card = $$('#lastCard');
    card.hidden = false;
    const d = new Date(last.at);
    card.innerHTML = 'รายงานล่าสุดที่เคยเปิด: <b>' + last.profile.label + '</b> · ' +
      'ตรวจแล้ว ' + Number(last.summary.examined).toLocaleString() + ' คน · ' +
      d.toLocaleString('th-TH') +
      ' <button class="dl sm" id="clrLast">ล้างความจำ</button>' +
      '<br><span style="color:var(--muted)">เป็นตัวเลขสรุปเท่านั้น ' +
      'ต้องเลือกโฟลเดอร์ใหม่ทุกครั้งเพื่อดูรายงานเต็ม</span>';
    $$('#clrLast').onclick = () => { window.DX.clearLast(); card.hidden = true; };
  }
})();
"""

RELOAD_BTN = """
/* ปุ่มโหลดใหม่: อ่านไฟล์ชุดเดิมซ้ำ (รับการแก้ profiles/*.yaml ทันที) */
(function () {
  const btn = document.querySelector('#btnRefresh');
  if (!btn) return;
  btn.onclick = async () => {
    const files = window.DX.handles();
    const old = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'กำลังโหลด…';
    try {
      if (files && files.length) await window.DX.loadFiles(files);
      await loadAreas();
      await loadReport(false);
    } catch (e) {
      alert('โหลดใหม่ไม่สำเร็จ: ' + e.message + '\\n\\nกรุณาเปิดไฟล์ HTML ใหม่แล้วเลือกโฟลเดอร์อีกครั้ง');
    }
    btn.disabled = false;
    btn.textContent = old;
  };
})();
"""


def main() -> int:
    ver = version()
    html = read(os.path.join(ROOT, "templates", "index.html"))
    print("อ่าน templates/index.html (%d บรรทัด)" % html.count("\n"))
    html = patch_dashboard(html)

    profiles = load_profiles()
    dictionary = read_any(os.path.join(ROOT, "reference", "dentalfile.csv"))
    hospitals = pack_hospitals(os.path.join(ROOT, "reference", "hospitals.csv"))
    hosp_json = json.dumps(hospitals, ensure_ascii=False)
    print("ฝัง profile %d ไฟล์, หน่วยบริการ %d แห่ง (%.0f KB)"
          % (len(profiles), hospitals["rows"].count("\n") + 1,
             len(hosp_json.encode()) / 1024))

    blocks = []
    for name in SRC_FILES:
        code = read(os.path.join(SRC, name))
        blocks.append("<script>\n/* ===== %s ===== */\n%s\n</script>" % (name, code))

    embed = (
        '<script type="application/json" id="embedded-profiles">%s</script>\n'
        '<script type="application/json" id="embedded-hospitals">%s</script>\n'
        '<script type="text/plain" id="embedded-dictionary">%s</script>'
        % (json.dumps(profiles, ensure_ascii=False).replace("</", "<\\/"),
           hosp_json.replace("</", "<\\/"),
           dictionary.replace("</", "<\\/"))
    )

    # สคริปต์ของเราต้องมาก่อนสคริปต์หน้า dashboard เดิม
    i = html.find("<script>")
    if i < 0:
        raise SystemExit("ไม่พบ <script> ในหน้า dashboard")
    html = html[:i] + PICKER + embed + "\n" + "\n".join(blocks) + "\n" + html[i:]

    html = html.replace("</style>", PICKER_CSS + "\n</style>", 1)
    html = html.replace("</body>", "<script>\n%s\n%s\n</script>\n</body>"
                        % (BOOT, RELOAD_BTN), 1)
    html = html.replace("__VERSION__", ver).replace("__BUILD__", ver)

    # ตรวจว่าไม่มีโค้ดที่จะออกเน็ตหรือยิงไปเซิร์ฟเวอร์หลงเหลือ
    # (ตัดคอมเมนต์ออกก่อน ไม่งั้นคำในคำอธิบายจะถูกนับด้วย)
    probe = re.sub(r"^\s*(//|\*|/\*).*$", "", html, flags=re.M)
    problems = [bad for bad in ("fetch(", "XMLHttpRequest", "new WebSocket",
                                "/api/table.", "/api/people.", "/api/pending.")
                if bad in probe]
    if problems:
        raise SystemExit("ยังมีโค้ดที่ติดต่อเซิร์ฟเวอร์เหลืออยู่: %s" % ", ".join(problems))
    print("  ตรวจแล้ว: ไม่มีโค้ดที่ติดต่อเครือข่ายหลงเหลือ")

    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "dist", "DentalDX-Dashboard-v%s.html" % ver)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("เขียน %s (%.0f KB)" % (dest, len(html.encode()) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""ทดสอบเร็ว ๆ ว่า engine ยังคำนวณได้ถูก — ใช้ใน CI ก่อน build exe

สร้างข้อมูลจำลองขึ้นมาเอง ไม่ต้องใช้ข้อมูลจริง (ซึ่งห้าม commit)
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# console ของ Windows (และ GitHub Actions runner) มักเป็น cp1252/cp874
# พิมพ์ภาษาไทยแล้ว UnicodeEncodeError -> สคริปต์ตายทั้งที่โปรแกรมไม่ได้พัง
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def fake_rows(n=400, seed=7):
    import random
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        examined = i % 3 != 0                      # 1 ใน 3 ยังไม่ได้ตรวจ
        age = i % 13                               # ครอบคลุมทั้ง 0-5 และ 6-12 ปี
        birth = pd.Timestamp("2026-01-15") - pd.DateOffset(years=age, days=rnd.randint(0, 200))
        rows.append({
            "hoscode": ["03929", "03930", "10973"][i % 3],
            "hosname": "หน่วยบริการทดสอบ",
            "pid": f"{i:06d}", "cid": f"1{i:012d}",
            "name": "ทดสอบ", "lname": "ระบบ",
            "sex": "1" if i % 2 else "2",
            "birth": birth.strftime("%Y-%m-%d"),
            "addr": str(i), "date_serv": "2026-01-15" if examined else "<NA>",
            "denttype": "3", "servplace": "1",
            "pteeth": rnd.randint(0, 28) if examined else "<NA>",
            "pcaries": rnd.randint(0, 3) if examined else "<NA>",
            "pfilling": rnd.randint(0, 2) if examined else "<NA>",
            "pextract": rnd.randint(0, 1) if examined else "<NA>",
            "dteeth": rnd.randint(1, 20) if examined else "<NA>",
            "dcaries": rnd.randint(0, 3) if examined else "<NA>",
            "dfilling": 0, "dextract": 0,
            "need_fluoride": rnd.choice([1, 2]) if examined else "<NA>",
            "need_scaling": rnd.choice([1, 2]) if examined else "<NA>",
            "need_sealant": rnd.randint(0, 2) if examined else "<NA>",
            "need_pfilling": rnd.randint(0, 2) if examined else "<NA>",
            "need_dfilling": 0, "need_pextract": 0, "need_dextract": 0,
            "gum": rnd.choice(["000000", "111111", "999999", "010000"]) if examined else "<NA>",
            "providertype": rnd.choice(["02", "06", "01"]) if examined else "<NA>",
        })
    return pd.DataFrame(rows)


def main() -> int:
    from core import profiles as pm, service

    tmp = tempfile.mkdtemp(prefix="dentaldx_smoke_")
    os.environ["DENTALDX_DATA"] = os.path.join(tmp, "data")
    os.environ["DENTALDX_PROFILES"] = os.path.join(ROOT, "profiles")
    os.environ["DENTALDX_REF"] = os.path.join(ROOT, "reference")

    profs = pm.discover()
    assert profs, "ไม่พบ profile ในโฟลเดอร์ profiles/"
    print("profiles:", list(profs))

    from core.engine import apply_scope

    ok = 0
    for pid, p in profs.items():
        os.makedirs(p.data_folder, exist_ok=True)

        # profile ที่สร้างคอลัมน์จากชื่อไฟล์ -> สร้างไฟล์ตามกฎเพื่อทดสอบจริง
        rules = [r for spec in p.filename_columns for r in spec.get("rules", [])]
        if rules:
            for i, rule in enumerate(rules):
                name = f"smoke {rule['contains']} .xlsx"
                fake_rows(seed=7 + i).to_excel(os.path.join(p.data_folder, name), index=False)
        else:
            fake_rows().to_excel(os.path.join(p.data_folder, "smoke.xlsx"), index=False)

        rep = service.report(p, refresh=True)

        for spec in p.filename_columns:
            col = spec["column"]
            df = service.get_dataset(p)
            assert col in df.columns, f"{pid}: ไม่ได้สร้างคอลัมน์ {col} จากชื่อไฟล์"
            got = set(df[col].dropna().unique())
            want = {r["value"] for r in spec.get("rules", [])}
            assert got == want, f"{pid}: {col} ได้ {got} แต่ควรเป็น {want}"
            assert df[col].isna().sum() == 0, f"{pid}: {col} มีค่าว่าง"
            print(f"  {pid}: {col} จากชื่อไฟล์ -> {sorted(got)} ✓")
        s = rep["summary"]
        assert s["target"] > 0, f"{pid}: ไม่มีข้อมูลเป้าหมาย"
        assert rep["tables"], f"{pid}: ไม่มีตาราง"
        for t in rep["tables"]:
            assert t["rows"], f"{pid}: ตารางที่ {t['no']} ว่าง"
            assert "insight" in t, f"{pid}: ตารางที่ {t['no']} ไม่มี insight"
        # หน้าสำรวจข้อมูล (EDA) ต้องคำนวณได้และเป็น JSON ที่ถูกต้อง
        e = service.eda(p)
        assert e["numeric"] and e["categorical"], f"{pid}: EDA ว่าง"
        import json
        txt = json.dumps(e, ensure_ascii=False, allow_nan=False)  # NaN -> ValueError
        assert "NaN" not in txt, f"{pid}: EDA มี NaN ที่เบราว์เซอร์ parse ไม่ได้"
        # กราฟขยายต้องมีคีย์ครบทุกตัวที่ bigChart() ใช้
        need = {"n", "mean", "sd", "min", "q1", "median", "q3", "max",
                "whisker_lo", "whisker_hi", "outliers_lo", "outliers_hi",
                "outlier_pct", "zero_pct", "hist"}
        for d in e["numeric"]:
            miss = need - set(d)
            assert not miss, f"{pid}/{d['column']}: กราฟขยายขาดคีย์ {miss}"
            assert d["hist"], f"{pid}/{d['column']}: histogram ว่าง"

        # ตัวเลขบนการ์ดต้องเท่ากับจำนวนรายชื่อที่เปิดดูได้จริง (คลิกการ์ด/แท่งกราฟ)
        d = max(e["numeric"], key=lambda x: x["outlier_n"])
        col = d["column"]
        for sel, want in (("all", d["n"]), ("outlier", d["outlier_n"]),
                          ("zero", d["zero_n"]), ("neg", d["neg_n"]),
                          ("extreme", d["extreme_n"]), ("iqr", d["iqr_n"])):
            got = len(service.value_list(p, col, sel))
            assert got == want, f"{pid}/{col}/{sel}: การ์ดบอก {want} แต่รายชื่อได้ {got}"
        # แท่งกราฟแต่ละแท่งต้องตรง และรวมกันได้เท่ากับจำนวนทั้งหมด (ไม่นับซ้ำที่ขอบ)
        total = 0
        for i, b in enumerate(d["hist"]):
            got = len(service.value_list(p, col, "range", b["from"], b["to"],
                                         hi_exclusive=(i < len(d["hist"]) - 1)))
            assert got == b["count"], \
                f"{pid}/{col}: แท่งที่ {i} กราฟบอก {b['count']} แต่รายชื่อได้ {got}"
            total += got
        assert total == d["n"], f"{pid}/{col}: ผลรวมแท่งกราฟ {total} ไม่เท่ากับ {d['n']}"
        print(f"  {pid}: คลิกดูรายบุคคลจาก {col} ตรงทุกการ์ดและทุกแท่งกราฟ ✓")
        print(f"  {pid}: EDA {len(e['numeric'])} ตัวแปรตัวเลข, "
              f"{len(e['anomalies']['rules'])} กฎตรวจ, "
              f"พบปัญหา {e['anomalies']['pct']}% ✓")

        # age_clamp: max -> อายุที่เกินช่วงต้องถูกดึงกลับมา ไม่ใช่ตัดทิ้ง
        scoped = apply_scope(service.get_dataset(p), p)
        ages = scoped["age"].dropna()
        assert ages.max() <= p.age_max and ages.min() >= p.age_min, \
            f"{pid}: อายุในรายงานหลุดช่วง {p.age_min}-{p.age_max}"
        if p.age_clamp:
            raw = pd.to_numeric(service.get_dataset(p)["age"], errors="coerce")
            over = int((raw > p.age_max).sum()) if p.age_clamp in ("max", "both") else 0
            under = int((raw < p.age_min).sum()) if p.age_clamp in ("min", "both") else 0
            # ปรับครบทั้งสองด้านเท่านั้นจึงจะไม่เหลือใครถูกตัดออก
            if p.age_clamp == "both":
                assert s["out_of_range"] == 0, \
                    f"{pid}: ตั้ง age_clamp: both แล้วแต่ยังมีเด็กถูกตัดออก {s['out_of_range']} คน"
            print(f"  {pid}: age_clamp={p.age_clamp} -> ปรับขึ้น {under} คน / "
                  f"ปรับลง {over} คน | เหลือถูกตัดออก {s['out_of_range']} คน ✓")

        # ช่วงอายุที่ตั้ง split: true ต้องมีแถวย่อยรายอายุครบ และผลรวมต้องเท่าแถวหลัก
        for b in [x for x in p.bands if x.split]:
            for t in rep["tables"]:
                rows = {str(r["row"]): r for r in t["rows"]}
                subs = [r for r in t["rows"] if r.get("_parent") == b.label]
                want = list(range(b.min, b.max + 1))
                assert [r["row"] for r in subs] == want, \
                    f"{pid}: ช่วง {b.label} ควรมีแถวย่อย {want} แต่ได้ {[r['row'] for r in subs]}"
                base_key = "ฐาน" if "ฐาน" in rows[b.label] else "จำนวนที่ตรวจ"
                got = sum(r[base_key] for r in subs)
                assert got == rows[b.label][base_key], (
                    f"{pid}: ตารางที่ {t['no']} ผลรวมแถวย่อย {got} "
                    f"ไม่เท่าแถว {b.label} ({rows[b.label][base_key]})")
            print(f"  {pid}: ช่วง {b.label} แตกเป็นรายอายุ {want} ครบและยอดตรง ✓")

        # ช่องที่คลิกได้ในตาราง -> จำนวนรายชื่อต้องตรงกับตัวเลขในตารางเป๊ะ
        n_cells = 0
        for t in rep["tables"]:
            assert "followup" in t, f"{pid}: ตารางที่ {t['no']} ไม่มีรายการช่องที่คลิกได้"
            if t["kind"] == "mean":
                continue          # ค่าเฉลี่ยเทียบกับจำนวนคนตรง ๆ ไม่ได้
            for met in t["followup"]:
                for r in t["rows"]:
                    key = f"{met}|จำนวน" if f"{met}|จำนวน" in r else met
                    want = r.get(key)
                    if not want:
                        continue
                    lst = service.metric_list(p, t["no"], met, r["row"])
                    assert len(lst) == want, (
                        f"{pid}: ตารางที่ {t['no']} '{met}' แถว {r['row']} "
                        f"ตารางบอก {want} แต่รายชื่อได้ {len(lst)}")
                    col = lst["ปัญหาที่พบ / สิ่งที่ต้องทำ"]
                    assert col.notna().all() and col.map(lambda v: isinstance(v, str)).all(), \
                        f"{pid}: คอลัมน์สรุปสิ่งที่ต้องทำมีค่าว่างหรือไม่ใช่ข้อความ"
                    n_cells += 1
        assert n_cells, f"{pid}: ไม่มีช่องไหนคลิกดูรายบุคคลได้เลย"
        print(f"  {pid}: ช่องที่คลิกดูรายชื่อได้ {n_cells} ช่อง ตรงกับตารางทุกช่อง ✓")

        # ส่งออกได้จริง
        from core import export
        assert export.xlsx_bytes(export.report_sheets(rep))[:2] == b"PK", "สร้าง xlsx ไม่ได้"
        # รายชื่อเด็ก — ต้องได้ครบและยอดต้องตรงกับสรุป
        pend = service.person_list(p, "pending")
        fail = service.person_list(p, "failed")
        assert len(pend) == s["pending"], f"{pid}: ยอดยังไม่ได้ตรวจไม่ตรงกับสรุป"
        assert len(fail) == s["examined"] - s["qualified"], f"{pid}: ยอดตกเกณฑ์ไม่ตรง"
        assert s["target"] == s["examined"] + s["pending"] + s["out_of_range"], \
            f"{pid}: ยอดรวมไม่ลงตัว"

        # ทุกแถวที่ตกเกณฑ์ต้องบอกได้ว่า "ฟิลด์ไหน" ผิด (หน้าเว็บเอาไประบายสีแดง)
        if len(fail):
            assert "_bad" in fail.columns, f"{pid}: รายชื่อตกเกณฑ์ไม่มีคอลัมน์ _bad"
            for i, cells in enumerate(fail["_bad"]):
                assert isinstance(cells, list) and cells, \
                    f"{pid}: แถวที่ {i} ตกเกณฑ์แต่ไม่ได้ระบุฟิลด์ที่ผิด"
                miss = [c for c in cells if c not in fail.columns]
                assert not miss, f"{pid}: ระบุฟิลด์ที่ไม่มีในตาราง {miss}"
            print(f"  {pid}: ระบุฟิลด์ที่ทำให้ตกเกณฑ์ครบทุกแถว "
                  f"({sorted({c for cs in fail['_bad'] for c in cs})}) ✓")

        # ตัวเลขบนปุ่มต้องเท่ากับจำนวนรายชื่อที่เปิดดูได้จริง
        rows = rep["units"] if rep.get("level") == "unit" else rep["districts"]
        assert sum(r["pending"] for r in rows) == len(pend), \
            f"{pid}: ปุ่ม 'ยังไม่ได้ตรวจ' ไม่ตรงกับรายชื่อ"
        assert sum(r["failed"] for r in rows) == len(fail), \
            f"{pid}: ปุ่ม 'ไม่ผ่านเกณฑ์' ไม่ตรงกับรายชื่อ"

        # apply_scope ต้องไม่แก้ข้อมูลต้นทาง
        # (เคยใช้ m = df["examined"] แล้ว m &= ... ซึ่งเขียนทับคอลัมน์จริง
        #  ทำให้ยอด "ยังไม่ได้ตรวจ" ผิดแบบเงียบ ๆ)
        base = service.get_dataset(p)
        before = int(base["examined"].sum())
        apply_scope(base, p)
        assert int(base["examined"].sum()) == before, \
            f"{pid}: apply_scope ไปแก้คอลัมน์ examined ของข้อมูลต้นทาง"

        # ไล่ทีละหน่วยบริการ: ครอบคลุมกรณีที่บางหน่วยตกเกณฑ์เพียงข้อเดียว
        # (เคยทำให้ fail_reasons พังเพราะ pandas เปลี่ยน None -> NaN)
        df = service.get_dataset(p)
        kinds = set()
        for hos in df["hoscode"].dropna().unique():
            sub = service.person_list(p, "failed", hos=hos)
            if len(sub):
                col = sub["สาเหตุที่ไม่ผ่านเกณฑ์"]
                assert col.notna().all(), f"{pid}/{hos}: สาเหตุที่ไม่ผ่านเกณฑ์มีค่าว่าง"
                assert col.map(lambda v: isinstance(v, str)).all(), \
                    f"{pid}/{hos}: สาเหตุที่ไม่ผ่านเกณฑ์ไม่ใช่ข้อความ"
                kinds |= set(col)
        if len(fail):
            print(f"  {pid}: สาเหตุที่พบ {sorted(kinds)} ✓")
        print(f"  {pid}: เป้าหมาย {s['target']} ตรวจ {s['examined']} "
              f"ผ่านเกณฑ์ {s['qualified']} ตาราง {len(rep['tables'])} ✓")
        ok += 1

    check_ask(profs)

    print(f"SMOKE TEST PASSED ({ok} profiles)")
    return 0


def check_ask(profs) -> None:
    """แท็บถาม-ตอบ: ตัวเลขต้องตรงกับตารางรายงานทุกช่อง และห้ามมีข้อมูลรายบุคคล
    หลุดออกไปกับ prompt ที่ส่งให้ AI
    """
    import json
    from core import ask, service

    # 1) ตัวเลขที่ ask คำนวณ ต้องเท่ากับตารางรายงานทุกช่อง
    n = 0
    for pid, p in profs.items():
        rep = service.report(p)
        tabs = {t["no"]: t for t in rep["tables"]}
        for t in p.tables:
            rt = tabs[t.no]
            names = (ask.QUALITY_METRICS if t.kind == "quality"
                     else [m.name for m in t.metrics])
            for row in rt["rows"]:
                label = str(row["row"])
                for name in names:
                    got = ask.run_spec({"profile": pid, "table": t.no, "metric": name,
                                        "rows": [label], "area": "",
                                        "group_by": None}, profs)["total"]
                    if t.kind == "quality":
                        want = (row["จำนวนที่ตรวจ"] if name == "จำนวนที่ตรวจ"
                                else row["จำนวนที่ผ่านเกณฑ์คุณภาพ"])
                        want_pct = None if name == "จำนวนที่ตรวจ" else row["ร้อยละ"]
                        assert got["count"] == want, \
                            f"{pid}/ตารางที่ {t.no}/{label}/{name}: {got['count']} != {want}"
                    elif t.kind == "mean":
                        want_pct = None
                        assert got["mean"] == row[name], \
                            f"{pid}/ตารางที่ {t.no}/{label}/{name}: ค่าเฉลี่ยไม่ตรง"
                    else:
                        want_pct = row[f"{name}|ร้อยละ"]
                        assert got["count"] == row[f"{name}|จำนวน"], \
                            f"{pid}/ตารางที่ {t.no}/{label}/{name}: จำนวนไม่ตรง"
                    assert want_pct is None or got.get("pct") == want_pct, \
                        f"{pid}/ตารางที่ {t.no}/{label}/{name}: ร้อยละไม่ตรง"
                    n += 1
    print(f"  ถาม-ตอบ: ตัวเลขตรงกับตารางรายงาน {n} ช่อง ✓")

    # 2) แคตตาล็อกที่ส่งให้ AI ต้องไม่มีข้อมูลรายบุคคล
    blob = json.dumps(ask.catalog(profs), ensure_ascii=False)
    for word in ("cid", "pid", "hoscode", "birth", "เลขบัตร", "นามสกุล"):
        assert word not in blob, f"แคตตาล็อกที่ส่งให้ AI มีคำต้องห้าม: {word}"
    print("  ถาม-ตอบ: prompt ที่ส่งให้ AI ไม่มีข้อมูลรายบุคคล ✓")

    # 3) ตัวแปลคำถามแบบคีย์เวิร์ด (ใช้เมื่อไม่มี API key) ต้องยังตอบได้
    pid0 = sorted(profs, key=lambda i: profs[i].age_min)[0]
    p0 = profs[pid0]
    age = p0.age_min + 1
    a = ask.answer(f"ปราศจากฟันผุ อายุ {age} ปี", profs)
    assert a["result"]["metric"] == "ปราศจากฟันผุ", "ตัวแปลคีย์เวิร์ดหาตัวชี้วัดไม่เจอ"
    assert a["result"]["rows"] == [str(age)], "ตัวแปลคีย์เวิร์ดอ่านอายุไม่ถูก"
    assert a["text"], "ไม่มีข้อความคำตอบ"
    print(f"  ถาม-ตอบ: ตัวแปลคีย์เวิร์ดตอบ 'ปราศจากฟันผุ อายุ {age} ปี' ได้ ✓")

    # 4) คำถามนอกเรื่องต้องตอบว่าไม่รู้ ไม่ใช่เดาตัวเลขมั่ว
    try:
        ask.answer("ราคาทองวันนี้เท่าไหร่", profs)
        raise AssertionError("คำถามนอกเรื่องควรตอบว่าไม่เข้าใจ")
    except ValueError:
        pass
    print("  ถาม-ตอบ: คำถามนอกเรื่องตอบว่าไม่เข้าใจ ✓")

    # 4.5) โหมดไม่ใช้ AI ต้องอ่านเลขไทยและชื่อพื้นที่ไม่เต็มได้
    pid0 = sorted(profs, key=lambda i: profs[i].age_min)[0]
    p0 = profs[pid0]
    words = {1: "หนึ่ง", 2: "สอง", 3: "สาม", 4: "สี่", 5: "ห้า"}
    age = min(p0.age_max, 3)
    if age in words:
        r = ask._find_rows(f"ปราศจากฟันผุ อายุ{words[age]}ขวบ", p0)
        assert r == [str(age)], f"อ่าน 'อายุ{words[age]}ขวบ' ไม่ออก ได้ {r}"
        assert ask._find_rows("สามารถดูได้ไหม", p0) == ["รวม"], \
            "'สามารถ' ไม่ควรถูกอ่านเป็นเลข 3"
        print(f"  ถาม-ตอบ: อ่านเลขไทย 'อายุ{words[age]}ขวบ' -> {age} ✓")

    tree = service.area_tree(service.get_dataset(p0))
    amps = sorted({a for pv in tree for a in tree[pv]})
    if amps:
        full = amps[0]
        short = full[:3]
        same = [a for a in amps if a.startswith(short)]
        try:
            got = ask.resolve_area(f"ปราศจากฟันผุ อ.{short}", tree)
            if len(same) == 1:
                assert got["amp"] == full, f"'อ.{short}' ควรได้ {full} แต่ได้ {got['amp']}"
                print(f"  ถาม-ตอบ: ชื่ออำเภอไม่เต็ม 'อ.{short}' -> {full} ✓")
            else:
                raise AssertionError(f"'อ.{short}' ตรงหลายอำเภอ ควรถามกลับ ไม่ใช่เดา")
        except ask.Ambiguous:
            assert len(same) > 1, "ไม่ควรบอกว่ากำกวมทั้งที่ตรงตัวเดียว"
            print(f"  ถาม-ตอบ: ชื่อกำกวม 'อ.{short}' ({len(same)} อำเภอ) -> ถามกลับ ✓")

    # 5) เตรียมคำขอแล้วต้อง "ยังไม่ส่ง" และกุญแจต้องไม่หลุดไปหน้าเว็บ
    KEY = "AIzaSyTESTKEY0123456789"
    saved_cfg, saved_http = ask._config_cache, ask._http_json
    sent = []
    ask._http_json = lambda *a, **k: sent.append(a[0]) or {}
    ask._config_cache = {**ask.DEFAULTS, "provider": "gemini",
                         "model": "gemini-2.0-flash", "api_key": KEY,
                         "phrase": True, "confirm": True}
    try:
        req = ask.plan_request("ปราศจากฟันผุ 3 ปี", profs)
        assert not sent, "plan_request ไม่ควรส่งอะไรออกไป"
        assert KEY in req["url"], "url จริงต้องมีกุญแจ"
        shown = json.dumps(req["display"], ensure_ascii=False)
        assert KEY not in shown, "กุญแจหลุดไปกับข้อมูลที่โชว์บนหน้าจอ!"
        assert req["display"]["body"] == json.dumps(req["payload"], ensure_ascii=False), \
            "สิ่งที่โชว์ไม่ตรงกับสิ่งที่จะส่งจริง"
        for word in ("cid", "เลขบัตร", "นามสกุล"):
            assert word not in shown, f"ข้อมูลที่โชว์มีคำต้องห้าม: {word}"
        print(f"  ถาม-ตอบ: เตรียมคำขอ {req['display']['bytes']:,} ไบต์ "
              "โดยยังไม่ส่ง และกุญแจถูกปิดบัง ✓")

        # phrase: false -> ต้องไม่มีคำขอก้อนที่มีตัวเลขเลย
        res = ask.run_spec({"profile": list(profs)[0], "table": profs[list(profs)[0]].tables[0].no,
                            "metric": ask.QUALITY_METRICS[0], "rows": ["รวม"],
                            "area": "", "group_by": None}, profs)
        assert ask.phrase_request("q", res) is not None, "phrase=true ควรมีก้อนที่ 2"
        ask._config_cache["phrase"] = False
        assert ask.phrase_request("q", res) is None, \
            "phrase=false แล้วยังเตรียมส่งตัวเลขออกไป!"
        assert not sent, "ยังไม่ควรมีอะไรถูกส่งออกไป"
        print("  ถาม-ตอบ: phrase=false แล้วตัวเลขไม่ถูกเตรียมส่งออก ✓")

        # 6) เลือก provider ไว้แต่ยังไม่ใส่กุญแจ = ต้องยังไม่เปิดใช้ AI
        ask._config_cache = {**ask.DEFAULTS, "provider": "gemini", "api_key": ""}
        assert not ask.ai_enabled(), "ไม่มีกุญแจแต่กลับเปิดใช้ AI"
        ask._config_cache = {**ask.DEFAULTS, "provider": "ollama", "api_key": ""}
        assert ask.ai_enabled(), "ollama ไม่ต้องใช้กุญแจ ควรเปิดใช้ได้"
        print("  ถาม-ตอบ: ไม่มีกุญแจ -> ยังไม่เปิด AI · ollama ไม่ต้องมีกุญแจ ✓")
    finally:
        ask._config_cache, ask._http_json = saved_cfg, saved_http

    # 7) หน้าตั้งค่าต้องไม่ส่งกุญแจกลับไปหน้าเว็บ (เขียนไฟล์ในที่ชั่วคราว)
    import tempfile
    KEY2 = "sk-ant-SECRET0123456789"
    old_env = os.environ.get("DENTALDX_AI_CONFIG")
    tmpdir = tempfile.mkdtemp()
    os.environ["DENTALDX_AI_CONFIG"] = os.path.join(tmpdir, "ai.yaml")
    saved_http_fn = ask._http
    try:
        # กันพลาด: เทสต์นี้รันบนเครื่องผู้ใช้ด้วย (release.bat เรียก)
        # ห้ามเขียนทับ ai.yaml ตัวจริงที่มี api_key ของเขาเด็ดขาด
        assert os.path.dirname(ask.config_path()) == tmpdir, \
            "เทสต์กำลังจะเขียนทับ ai.yaml ตัวจริง!"
        ask.save_config({"provider": "anthropic", "model": "claude-haiku-4-5",
                         "api_key": KEY2})
        pub = json.dumps(ask.public_config(), ensure_ascii=False)
        assert KEY2 not in pub, "กุญแจหลุดไปกับค่าตั้งที่ส่งให้หน้าเว็บ!"
        assert ask.config()["api_key"] == KEY2, "บันทึกกุญแจไม่สำเร็จ"
        ask.save_config({"phrase": False})          # ไม่ได้ส่ง api_key มา
        assert ask.config()["api_key"] == KEY2, "ไม่ส่งกุญแจมา ไม่ควรลบของเดิม"
        ask.save_config({"clear_key": "1"})
        assert not ask.config().get("api_key"), "สั่งลบกุญแจแล้วยังอยู่"
        # เลือก provider ไว้แต่ไม่มีกุญแจ -> ยังไม่เปิดใช้ AI แต่ต้องจำสิ่งที่เลือกไว้
        pub = ask.public_config()
        assert pub["provider"] == "anthropic" and not pub["enabled"], \
            "หน้าตั้งค่าควรจำ provider ที่เลือก แม้ยังใช้ไม่ได้เพราะไม่มีกุญแจ"
        print("  ถาม-ตอบ: บันทึก/ลบกุญแจได้ · กุญแจไม่ออกไปหน้าเว็บ · จำ provider ที่เลือก ✓")

        # 8) ปุ่ม "ทดสอบการเชื่อมต่อ" ต้องทดสอบค่าที่กรอกบนหน้าจอ ไม่ใช่ค่าที่บันทึกไว้
        #    (เคยเป็นบั๊ก: เลือก gemini + ใส่กุญแจแล้วยังไม่กดบันทึก กดทดสอบ
        #     กลับขึ้นว่า "โหมดไม่ใช้ AI" ทำให้ผู้ใช้งงว่าตั้งค่าไม่ติด)
        ask.save_config({"provider": "off"})
        assert ask.config()["provider"] == "off"
        eff = ask.effective_config({"provider": "gemini", "model": "gemini-2.0-flash",
                                    "api_key": "AIzaSyFORM123"})
        assert eff["provider"] == "gemini" and eff["api_key"] == "AIzaSyFORM123", \
            "ปุ่มทดสอบยังอ่านค่าที่บันทึกไว้ ไม่ใช่ค่าบนหน้าจอ"
        assert ask.config()["provider"] == "off", "การทดสอบต้องไม่บันทึกค่าให้เอง"
        r = ask.test_connection({"provider": "gemini", "model": "gemini-2.0-flash"})
        assert not r["ok"] and "API key" in r["text"], \
            "เลือก provider แต่ไม่มีกุญแจ ควรบอกว่ายังไม่ได้ใส่ API key"
        # ช่องกุญแจว่าง = ใช้กุญแจที่บันทึกไว้ ไม่ใช่ถือว่าไม่มีกุญแจ
        ask.save_config({"provider": "gemini", "model": "gemini-2.0-flash",
                         "api_key": "AIzaSySAVED123"})
        eff = ask.effective_config({"provider": "gemini", "model": "gemini-2.0-flash",
                                    "api_key": ""})
        assert eff["api_key"] == "AIzaSySAVED123", \
            "ช่องกุญแจว่างควรใช้กุญแจที่บันทึกไว้"
        print("  ถาม-ตอบ: ปุ่มทดสอบใช้ค่าบนหน้าจอ ไม่บันทึกให้เอง ✓")

        # 9) error จากปลายทางต้องแปลเป็นภาษาที่บอกทางแก้ได้
        #    (เคยขึ้นแค่ "HTTP Error 404: Not Found" ซึ่งเดาสาเหตุไม่ถูกเลย —
        #     ที่จริงคือชื่อโมเดลถูกปลดระวางไปแล้ว)
        import urllib.error as _ue
        import urllib.request as _ur

        ask._http_json = saved_http          # ต้องใช้ตัวจริง จะได้ผ่านชั้นแปล error
        saved_urlopen = _ur.urlopen
        try:
            for code, must in ((404, "↻"), (401, "กุญแจ"), (429, "โควตา")):
                def raiser(*a, _c=code, **k):
                    raise _ue.HTTPError(
                        "http://x", _c, "err", {},
                        io.BytesIO(json.dumps(
                            {"error": {"message": "detail from server"}}).encode()))
                _ur.urlopen = raiser
                r = ask.test_connection({"provider": "gemini", "model": "m",
                                         "api_key": "k"})
                assert not r["ok"], f"HTTP {code} ควรถือว่าไม่ผ่าน"
                assert str(code) in r["text"] and must in r["text"], \
                    f"ข้อความ HTTP {code} ไม่ได้บอกทางแก้: {r['text']}"
                assert "HTTPError" not in r["text"], "ยังโชว์ชื่อคลาส exception ดิบ"
                assert "detail from server" in r["text"], \
                    "ควรแนบคำอธิบายที่ปลายทางส่งมาด้วย"
        finally:
            _ur.urlopen = saved_urlopen
        print("  ถาม-ตอบ: แปล error 404/401/429 เป็นคำแนะนำที่ทำตามได้ ✓")

        # โมเดลที่ตอบคำถามไม่ได้ (embedding) ต้องไม่โผล่ในรายการให้เลือก
        ask._http = lambda *a, **k: {"models": [
            {"name": "models/gemini-2.5-flash",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004",
             "supportedGenerationMethods": ["embedContent"]}]}
        got = ask.list_models("gemini", api_key="k")
        assert got["live"] and got["models"] == ["gemini-2.5-flash"], \
            f"กรองรายชื่อโมเดลผิด: {got}"
        print("  ถาม-ตอบ: ดึงรายชื่อโมเดลจากปลายทางจริง (กรองรุ่นที่ใช้ไม่ได้ออก) ✓")
    finally:
        path = ask.config_path()
        if os.path.exists(path) and os.path.dirname(path) == tmpdir:
            os.remove(path)
        if old_env is None:
            os.environ.pop("DENTALDX_AI_CONFIG", None)
        else:
            os.environ["DENTALDX_AI_CONFIG"] = old_env
        ask._http = saved_http_fn          # คืนของที่ monkeypatch ไว้
        ask._config_cache = None


if __name__ == "__main__":
    sys.exit(main())

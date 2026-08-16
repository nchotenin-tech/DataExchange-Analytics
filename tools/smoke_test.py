"""ทดสอบเร็ว ๆ ว่า engine ยังคำนวณได้ถูก — ใช้ใน CI ก่อน build exe

สร้างข้อมูลจำลองขึ้นมาเอง ไม่ต้องใช้ข้อมูลจริง (ซึ่งห้าม commit)
"""
from __future__ import annotations

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

    print(f"SMOKE TEST PASSED ({ok} profiles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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

    ok = 0
    for pid, p in profs.items():
        os.makedirs(p.data_folder, exist_ok=True)
        fake_rows().to_excel(os.path.join(p.data_folder, "smoke.xlsx"), index=False)
        rep = service.report(p, refresh=True)
        s = rep["summary"]
        assert s["target"] > 0, f"{pid}: ไม่มีข้อมูลเป้าหมาย"
        assert rep["tables"], f"{pid}: ไม่มีตาราง"
        for t in rep["tables"]:
            assert t["rows"], f"{pid}: ตารางที่ {t['no']} ว่าง"
            assert "insight" in t, f"{pid}: ตารางที่ {t['no']} ไม่มี insight"
        # ส่งออกได้จริง
        from core import export
        assert export.xlsx_bytes(export.report_sheets(rep))[:2] == b"PK", "สร้าง xlsx ไม่ได้"
        assert len(service.person_list(p, "pending")) >= 0
        assert len(service.person_list(p, "failed")) >= 0
        print(f"  {pid}: เป้าหมาย {s['target']} ตรวจ {s['examined']} "
              f"ผ่านเกณฑ์ {s['qualified']} ตาราง {len(rep['tables'])} ✓")
        ok += 1

    print(f"SMOKE TEST PASSED ({ok} profiles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

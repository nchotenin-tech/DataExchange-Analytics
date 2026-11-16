#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""สร้างข้อมูลตัวอย่าง (สมมติทั้งหมด ไม่ใช่ข้อมูลคนจริง) สำหรับการทดสอบ

    python web/make_test_data.py <โฟลเดอร์ปลายทาง> [--rows 4000] [--big 100000]

สร้างโครงสร้างเดียวกับของจริง

    <ปลายทาง>/0-5y/sample 0-2.xlsx
    <ปลายทาง>/0-5y/sample 3-5.xlsx
    <ปลายทาง>/6-12y/sample 6-12.xlsx

แทรกค่าผิดรูปแบบที่พบจริงจาก HDC ไว้ด้วย: เลขไทย ช่องว่างหน้าหลัง
ตัวเลขปนข้อความ ค่าว่างแบบ <NA>/NULL วันที่คนละรูปแบบ และปี พ.ศ.
"""
from __future__ import annotations

import argparse
import os
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

COLS = ["hoscode", "hosname", "pid", "cid", "name", "lname", "sex", "birth", "addr",
        "check_typearea", "seq", "date_serv", "denttype", "servplace",
        "pteeth", "pcaries", "pfilling", "pextract",
        "dteeth", "dcaries", "dfilling", "dextract",
        "need_fluoride", "need_scaling", "need_sealant", "need_pfilling",
        "need_dfilling", "need_pextract", "need_dextract",
        "nprosthesis", "permanent_permanent", "permanent_prosthesis",
        "prosthesis_prosthesis", "gum", "schooltype", "class",
        "provider", "providertype", "result"]

# รหัสหน่วยบริการจริงในตารางอ้างอิง เพื่อให้ผูกอำเภอ/จังหวัดได้
HOSCODES = ["03929", "03930", "10972", "03933", "03940"]


def row(i: int, age: int, rnd: random.Random, permanent: bool) -> dict:
    exam = i % 3 != 0                       # 1 ใน 3 ยังไม่ได้ตรวจ
    serve_year = 2026
    birth_year = serve_year - age
    d = {c: "" for c in COLS}
    d.update({
        "hoscode": HOSCODES[i % len(HOSCODES)],
        "hosname": "หน่วยบริการทดสอบ",
        "pid": "%06d" % i,
        "cid": "1%012d" % i,
        "name": "ทดสอบ", "lname": "ระบบ",
        "sex": "1" if i % 2 else "2",
        "birth": "%04d-03-05" % birth_year,
        "addr": str(i % 200),
        "check_typearea": "1",
        "seq": str(i),
        "date_serv": "%04d-01-15" % serve_year if exam else "<NA>",
        "denttype": "1", "servplace": "1",
        "providertype": "02" if i % 7 else "06",
        "provider": "ผู้ตรวจทดสอบ",
        "gum": "000000",
        "need_fluoride": "1" if i % 4 == 0 else "2",
        "need_scaling": "2",
        "need_sealant": "0", "need_pfilling": "0", "need_dfilling": str(i % 3),
        "need_pextract": "0", "need_dextract": "0",
        "nprosthesis": "0", "permanent_permanent": "0",
        "permanent_prosthesis": "0", "prosthesis_prosthesis": "0",
        "schooltype": "1", "class": str(max(1, age - 6)), "result": "1",
    })
    if not exam:
        return d
    if permanent:
        d.update({"pteeth": str(rnd.randint(4, 28)), "pcaries": str(rnd.randint(0, 3)),
                  "pfilling": "0", "pextract": "0",
                  "dteeth": str(rnd.randint(0, 10)), "dcaries": "0",
                  "dfilling": "0", "dextract": "0"})
    else:
        teeth = 20 if age >= 3 else rnd.randint(1, 20)
        caries = rnd.randint(0, 4)
        d.update({"pteeth": "0", "pcaries": "0", "pfilling": "0", "pextract": "0",
                  "dteeth": str(teeth), "dcaries": str(caries),
                  "dfilling": "0", "dextract": "0"})
    return d


def add_edge_cases(rows: list) -> None:
    """แทรกค่าผิดรูปแบบที่พบจริงจากไฟล์ HDC"""
    if len(rows) < 40:
        return
    rows[4]["dcaries"] = "๒"                 # เลขไทย
    rows[4]["dteeth"] = "๒๐"
    rows[7]["dcaries"] = "  1  "             # ช่องว่างหน้าหลัง
    rows[10]["dteeth"] = "20 ซี่"            # ตัวเลขปนข้อความ
    rows[13]["dcaries"] = "<NA>"             # ค่าว่างแบบ HDC
    rows[16]["dteeth"] = "NULL"
    rows[19]["date_serv"] = "15/01/2026"     # วันที่อีกรูปแบบ
    rows[22]["birth"] = "2564-03-05"         # ปี พ.ศ.
    rows[25]["providertype"] = "02 "         # รหัสมีช่องว่างท้าย
    rows[28]["gum"] = "123"                  # GUM ไม่ครบ 6 หลัก


def write(path: str, rows: list) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(COLS)
    for r in rows:
        ws.append([r.get(c, "") for c in COLS])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    print("  %s (%d แถว)" % (path, len(rows)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--rows", type=int, default=4000)
    ap.add_argument("--big", type=int, default=0,
                    help="สร้างไฟล์ใหญ่กี่แถว (0 = ไม่สร้าง)")
    ap.add_argument("--clean", action="store_true",
                    help="ไม่ใส่ค่าผิดรูปแบบ — ใช้กับการเทียบผลกับ Python\n"
                         "(pandas แต่ละเวอร์ชันตีความค่าที่เป็นไปไม่ได้ไม่เหมือนกัน\n"
                         " เช่นปี พ.ศ. 2564 บางเวอร์ชันอ่านได้ บางเวอร์ชันเป็นค่าว่าง\n"
                         " ถ้าปนมาในข้อมูลเทียบผล จะล้มเพราะเวอร์ชันไลบรารี ไม่ใช่เพราะโค้ดผิด)")
    a = ap.parse_args()
    rnd = random.Random(7)

    print("สร้างข้อมูลตัวอย่าง (สมมติทั้งหมด):")
    g1 = [row(i, i % 3, rnd, False) for i in range(a.rows)]
    if not a.clean:
        add_edge_cases(g1)
    write(os.path.join(a.dest, "0-5y", "sample 0-2.xlsx"), g1)

    g2 = [row(i + a.rows, 3 + i % 3, rnd, False) for i in range(a.rows)]
    if not a.clean:
        add_edge_cases(g2)
    write(os.path.join(a.dest, "0-5y", "sample 3-5.xlsx"), g2)

    g3 = [row(i, 6 + i % 7, rnd, True) for i in range(a.rows)]
    if not a.clean:
        add_edge_cases(g3)
    write(os.path.join(a.dest, "6-12y", "sample 6-12.xlsx"), g3)

    if a.big:
        big = [row(i, 3 + i % 3, rnd, False) for i in range(a.big)]
        for i in range(0, a.big, 997):
            big[i]["dcaries"] = "๑"
        write(os.path.join(a.dest, "big", "sample big.xlsx"), big)
    return 0


if __name__ == "__main__":
    sys.exit(main())

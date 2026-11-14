#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""สร้าง zip สำหรับแจกจ่าย  Dashboard-Exam-vX.Y.Z.zip

    python web/make_package.py [dist/ไฟล์.html]

โครงสร้างในไฟล์ zip

    Dashboard-Exam\\
    ├─ DentalDX-Dashboard-vX.Y.Z.html   ดับเบิลคลิกเปิดด้วย Chrome หรือ Edge
    ├─ อ่านก่อนใช้งาน.txt
    ├─ profiles\\                        แก้เกณฑ์คำนวณเองได้ (ไม่บังคับ)
    └─ data\\
       ├─ 0-5y\\
       └─ 6-12y\\

ไฟล์ zip ที่ได้ "ไม่มีข้อมูลผู้ป่วย" — มีแต่โปรแกรมกับโฟลเดอร์เปล่า
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = "Dashboard-Exam"

README_TXT = """\
========================================================================
 DentalDX — Dashboard สภาวะทันตสุขภาพเด็ก (HDC Data Exchange)
 เวอร์ชัน {ver}
========================================================================

 วิธีใช้งาน
------------------------------------------------------------------------

 1. วางไฟล์ Excel ที่ส่งออกจาก HDC (แบบ Data Exchange การตรวจฟัน)
    ลงในโฟลเดอร์ตามกลุ่มอายุ

      data\\0-5y\\    ต้องมี 2 ไฟล์ และชื่อไฟล์ต้องมีคำว่า
                       "0-2"  = รายงาน 1.17.4 OHSP เด็ก 0-2 ปี
                       "3-5"  = รายงาน 1.17.8 OHSP เด็ก 3-5 ปี

      data\\6-12y\\   ใช้ไฟล์เดียว ตั้งชื่ออะไรก็ได้
                       รายงาน 1.17.11 OHSP เด็ก 6-12 ปี

    ** ถ้าชื่อไฟล์กลุ่ม 0-5 ปี ไม่มี "0-2" หรือ "3-5"
       โปรแกรมจะแยกช่วงอายุไม่ได้ **

 2. ดับเบิลคลิก {html}
    เปิดด้วย Google Chrome หรือ Microsoft Edge

 3. กดปุ่ม "เลือกโฟลเดอร์ข้อมูล" แล้วเลือกโฟลเดอร์ {pkg}
    (เบราว์เซอร์จะถามยืนยันการอ่านโฟลเดอร์ ให้กดอนุญาต)


 ข้อมูลของท่านปลอดภัย
------------------------------------------------------------------------

 โปรแกรมทำงานในเบราว์เซอร์บนเครื่องท่านทั้งหมด ไม่ต้องติดตั้ง
 และ **ถูกล็อกไม่ให้เชื่อมต่ออินเทอร์เน็ต** ด้วย Content-Security-Policy
 ใช้งานได้แม้ถอดสาย LAN

   ข้อมูลรายบุคคล (ชื่อ นามสกุล เลขบัตรประชาชน ที่อยู่ วันเกิด)
   อยู่ในหน่วยความจำชั่วคราวเท่านั้น ปิดแท็บแล้วหายทั้งหมด
   ไม่มีการบันทึกลงเครื่อง

   เบราว์เซอร์จำไว้เฉพาะ "ตัวเลขสรุปของรายงานล่าสุด"
   (จำนวนคน ร้อยละ ระดับอำเภอ/หน่วยบริการ) เพื่อแสดงตอนเปิดครั้งถัดไป
   ไม่มีข้อมูลรายบุคคล และกดล้างได้ทุกเมื่อ


 ไฟล์ไหนมีข้อมูลส่วนบุคคลบ้าง
------------------------------------------------------------------------

 มีข้อมูลส่วนบุคคล — เก็บและส่งต่ออย่างระมัดระวัง
   - ไฟล์ Excel ที่ท่านวางใน data\\        (มาจาก HDC)
   - ไฟล์ที่ส่งออกจากปุ่ม "รายชื่อเด็ก..."  (มีเลขบัตร ชื่อ ที่อยู่)

 ไม่มีข้อมูลส่วนบุคคล
   - {html}                 ตัวโปรแกรม
   - ไฟล์จากปุ่ม "บันทึกรายงาน (Excel)"  มีแต่ตัวเลขสรุป
   - สิ่งที่เบราว์เซอร์จำไว้


 แก้เกณฑ์การคำนวณเอง
------------------------------------------------------------------------

 แก้ไฟล์ในโฟลเดอร์ profiles\\ แล้วกดปุ่ม "โหลดข้อมูลใหม่" ในโปรแกรม
 มีผลทันที ไม่ต้องรอเวอร์ชันใหม่
 (ถ้าลบโฟลเดอร์ profiles\\ ทิ้ง โปรแกรมจะใช้เกณฑ์มาตรฐานที่ฝังมาในตัว)


 ปัญหาที่พบบ่อย
------------------------------------------------------------------------

 Q: กดเลือกโฟลเดอร์แล้วไม่มีอะไรเกิดขึ้น
 A: ต้องใช้ Chrome หรือ Edge  (Firefox ยังเลือกทั้งโฟลเดอร์ไม่ได้)

 Q: ขึ้นว่าไม่พบไฟล์ .xlsx ในโฟลเดอร์ data
 A: ต้องเลือกโฟลเดอร์ {pkg} ตัวนอกสุด ไม่ใช่เลือกโฟลเดอร์ data

 Q: ไฟล์ใหญ่มาก เปิดแล้วค้าง
 A: ไฟล์ขนาดแสนแถวใช้เวลาราว 5-10 วินาที กรุณารอจนขึ้นตาราง
"""


def version() -> str:
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as fh:
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
    return m.group(1) if m else "0.0.0"


def profile_folders() -> list:
    import yaml
    out = []
    pdir = os.path.join(ROOT, "profiles")
    for name in sorted(os.listdir(pdir)):
        if not name.endswith((".yaml", ".yml")):
            continue
        with open(os.path.join(pdir, name), encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        if spec and spec.get("id"):
            out.append((name, spec.get("data_folder") or spec["id"]))
    return out


def main() -> int:
    ver = version()
    html_src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "dist", "DentalDX-Dashboard-v%s.html" % ver)
    if not os.path.exists(html_src):
        raise SystemExit("ไม่พบ %s — รัน web/build_webapp.py ก่อน" % html_src)

    html_name = os.path.basename(html_src)
    zip_path = os.path.join(ROOT, "dist", "%s-v%s.zip" % (PKG, ver))
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)

    profs = profile_folders()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(html_src, "%s/%s" % (PKG, html_name))

        readme = README_TXT.format(ver=ver, html=html_name, pkg=PKG)
        # คู่มือเป็นไฟล์ .txt สำหรับ Notepad ของ Windows -> ต้องเป็น CRLF
        z.writestr("%s/อ่านก่อนใช้งาน.txt" % PKG,
                   readme.replace("\r\n", "\n").replace("\n", "\r\n"))

        for name, _folder in profs:
            z.write(os.path.join(ROOT, "profiles", name), "%s/profiles/%s" % (PKG, name))

        for _name, folder in profs:
            z.writestr("%s/data/%s/_วางไฟล์ที่นี่.txt" % (PKG, folder),
                       ("วางไฟล์ Excel ที่ส่งออกจาก HDC (Data Exchange การตรวจฟัน) "
                        "ของกลุ่ม %s ไว้ในโฟลเดอร์นี้\r\n"
                        "ดูรายละเอียดใน อ่านก่อนใช้งาน.txt\r\n" % folder))

    size = os.path.getsize(zip_path) / 1024
    print("เขียน %s (%.0f KB)" % (zip_path, size))
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            print("   ", n)
    print("\nไฟล์ zip นี้ไม่มีข้อมูลผู้ป่วย — มีแต่โปรแกรมกับโฟลเดอร์เปล่า")
    return 0


if __name__ == "__main__":
    sys.exit(main())

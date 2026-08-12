"""สร้างโฟลเดอร์ data/<กลุ่มอายุ>/ เปล่า ๆ ในชุดที่จะส่งมอบ

อ่านรายชื่อกลุ่มอายุจาก profiles/*.yaml จึงไม่ต้องแก้สคริปต์เมื่อเพิ่มกลุ่มใหม่
ใช้: python tools/make_data_dirs.py <โฟลเดอร์ปลายทาง>
"""
from __future__ import annotations

import glob
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTE = "วางไฟล์ .xlsx ของกลุ่มอายุนี้ในโฟลเดอร์นี้ แล้วเปิด DentalDX.exe\n"


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "package/DentalDX"
    made = []
    for path in sorted(glob.glob(os.path.join(ROOT, "profiles", "*.y*ml"))):
        with open(path, encoding="utf-8") as fh:
            spec = yaml.safe_load(fh) or {}
        pid = spec.get("id")
        if not pid:
            continue
        folder = os.path.join(out, "data", spec.get("data_folder", pid))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "_วางไฟล์ที่นี่.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"{spec.get('label', pid)}\n{NOTE}")
        made.append(folder)

    print("created:", *made, sep="\n  ")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())

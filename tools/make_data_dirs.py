"""สร้างโฟลเดอร์ data/<กลุ่มอายุ>/ พร้อมคำแนะนำการวางไฟล์

อ่านรายละเอียดจาก profiles/*.yaml จึงไม่ต้องแก้สคริปต์เมื่อเพิ่มกลุ่มอายุใหม่
ใช้: python tools/make_data_dirs.py <โฟลเดอร์ปลายทาง>
"""
from __future__ import annotations

import glob
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def help_text(spec: dict) -> str:
    """ข้อความในไฟล์ _วางไฟล์ที่นี่.txt ของแต่ละกลุ่มอายุ"""
    label = spec.get("label", spec.get("id", ""))
    helps = spec.get("data_help") or []
    lines = [
        "=" * 66,
        f" {label}",
        "=" * 66,
        "",
        "วางไฟล์ .xlsx ที่ดาวน์โหลดจาก HDC ในโฟลเดอร์นี้",
        "",
    ]
    if helps:
        lines.append(f"ต้องใช้ {len(helps)} ไฟล์:" if len(helps) > 1 else "ใช้ไฟล์เดียว:")
        lines.append("")
        for i, h in enumerate(helps, start=1):
            lines += [
                f" {i}. รายงาน HDC:",
                f"    {h.get('report', '-')}",
                "",
                f"    ชื่อไฟล์: {h.get('filename', 'ตั้งชื่อไฟล์อะไรก็ได้')}",
                "",
            ]
        if len(helps) > 1:
            lines += [
                "-" * 66,
                "สำคัญ: ไฟล์ที่โหลดจาก HDC มีชื่อคล้ายกันมากจนแยกไม่ออกว่าเป็นรายงานไหน",
                "ต้องเปลี่ยนชื่อไฟล์ให้มีคำที่ระบุไว้ข้างบน มิฉะนั้นโปรแกรมจะแยก",
                "ช่วงอายุไม่ได้",
                "-" * 66,
                "",
            ]
    lines += [
        "วางไฟล์แล้วเปิด DentalDX.exe (หรือกดปุ่ม \"โหลดข้อมูลใหม่\" ถ้าเปิดอยู่แล้ว)",
        "",
    ]
    return "\n".join(lines)


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
            fh.write(help_text(spec))
        made.append(folder)

    print("created:", *made, sep="\n  ")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())

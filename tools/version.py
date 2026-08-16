"""พิมพ์เลขเวอร์ชันที่อยู่ใน app.py — ใช้โดย release.bat และ GitHub Actions"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version() -> str:
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        raise SystemExit("ไม่พบตัวแปร VERSION ใน app.py")
    return m.group(1)


if __name__ == "__main__":
    sys.stdout.write(version())

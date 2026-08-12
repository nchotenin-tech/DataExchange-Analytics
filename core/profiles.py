"""ค้นหาและโหลด profile ของแต่ละกลุ่มอายุจากโฟลเดอร์ profiles/

เพิ่มกลุ่มอายุใหม่ = วางไฟล์ .yaml เพิ่ม ไม่ต้องแก้โค้ด
"""
from __future__ import annotations

import glob
import os
import sys

import yaml

from .engine import Profile


def app_root() -> str:
    """โฟลเดอร์ที่อยู่ข้าง exe (ไม่ใช่โฟลเดอร์ชั่วคราวของ PyInstaller)"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def profiles_dir() -> str:
    return os.environ.get("DENTALDX_PROFILES", os.path.join(app_root(), "profiles"))


def data_root() -> str:
    return os.environ.get("DENTALDX_DATA", os.path.join(app_root(), "data"))


def reference_dir() -> str:
    return os.environ.get("DENTALDX_REF", os.path.join(app_root(), "reference"))


def discover() -> dict[str, Profile]:
    out: dict[str, Profile] = {}
    for path in sorted(glob.glob(os.path.join(profiles_dir(), "*.yaml"))
                       + glob.glob(os.path.join(profiles_dir(), "*.yml"))):
        with open(path, encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        if not spec or not spec.get("id"):
            continue
        p = Profile.from_dict(spec)
        p.data_folder = os.path.join(data_root(), spec.get("data_folder", p.id))
        out[p.id] = p
    return out

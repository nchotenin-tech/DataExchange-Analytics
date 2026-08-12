"""คำนวณคอลัมน์ derived ที่ใช้ร่วมกันทุกกลุ่มอายุ"""
from __future__ import annotations

import numpy as np
import pandas as pd

GUM_CODES = ["0", "1", "2", "3", "9"]
GUM_LABELS = {
    "0": "ปกติ",
    "1": "เลือดออก",
    "2": "เหงือกอักเสบ/หินน้ำลาย",
    "3": "ปริทันต์อักเสบ",
    "9": "ตรวจไม่ได้",
}


def add_age(df: pd.DataFrame) -> pd.DataFrame:
    """อายุ (ปี) = date_serv - birth  (ปัดลง)"""
    df = df.copy()
    if "date_serv" not in df.columns or "birth" not in df.columns:
        df["age"] = pd.NA
        return df

    d, b = df["date_serv"], df["birth"]
    years = d.dt.year - b.dt.year
    # ยังไม่ถึงวันเกิดในปีนั้น -> ลบ 1
    before_bday = (d.dt.month < b.dt.month) | (
        (d.dt.month == b.dt.month) & (d.dt.day < b.dt.day)
    )
    age = years - before_bday.astype("float")
    age = age.where(d.notna() & b.notna())
    df["age"] = age.astype("Float64")
    df["age_month"] = (
        (years * 12 + (d.dt.month - b.dt.month) - (d.dt.day < b.dt.day).astype(int))
        .where(d.notna() & b.notna())
        .astype("Float64")
    )
    return df


def add_examined(df: pd.DataFrame) -> pd.DataFrame:
    """แถวที่มีการตรวจฟัน = date_serv ไม่เป็นค่าว่าง"""
    df = df.copy()
    df["examined"] = df["date_serv"].notna() if "date_serv" in df.columns else False
    return df


def _norm_gum(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    return s if len(s) == 6 else ("999999" if s else "")


def add_gum(df: pd.DataFrame) -> pd.DataFrame:
    """GUM = 6 sextant "XXXXXX" แต่ละ X in (0,1,2,3,9)

    gum_status = 9 ถ้า GUM=999999
                 มิฉะนั้น = ค่าสูงสุดของ sextant ที่ตรวจได้ (เทียบเฉพาะ 0,1,2,3)
    gum_sx_<code> = จำนวน sextant ที่มีค่านั้น
    """
    df = df.copy()
    if "gum" not in df.columns:
        df["gum_status"] = pd.NA
        for c in GUM_CODES:
            df[f"gum_sx_{c}"] = pd.NA
        return df

    g = df["gum"].map(_norm_gum)

    for c in GUM_CODES:
        df[f"gum_sx_{c}"] = g.map(lambda s, c=c: s.count(c) if s else np.nan)

    def status(s: str):
        if not s:
            return pd.NA
        valid = [ch for ch in s if ch in "0123"]
        return max(valid) if valid else "9"

    df["gum_status"] = g.map(status).astype("string")
    df["gum_label"] = df["gum_status"].map(GUM_LABELS).astype("string")
    return df


def add_indices(df: pd.DataFrame) -> pd.DataFrame:
    """DMFT (ฟันแท้) และ dmft (ฟันน้ำนม)"""
    df = df.copy()
    p = ["pcaries", "pfilling", "pextract"]
    d = ["dcaries", "dfilling", "dextract"]
    if all(c in df.columns for c in p):
        df["dmft_p"] = df[p].sum(axis=1, min_count=1)
    if all(c in df.columns for c in d):
        df["dmft_d"] = df[d].sum(axis=1, min_count=1)
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """pipeline มาตรฐาน"""
    return add_indices(add_gum(add_examined(add_age(df))))

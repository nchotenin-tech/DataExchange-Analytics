"""อ่านและทำความสะอาดข้อมูล Data Exchange (ใช้ร่วมทุกกลุ่มอายุ)"""
from __future__ import annotations

import glob
import os

import pandas as pd

# ค่าที่ถือว่า "ว่าง" ในไฟล์ export จาก HDC (เป็น string ไม่ใช่ NaN จริง)
NA_TOKENS = {"<NA>", "<null>", "<NULL>", "NULL", "null", "NaN", "nan", "", "-"}

# คอลัมน์ที่ต้องเป็นตัวเลข
NUMERIC_COLS = [
    "pteeth", "pcaries", "pfilling", "pextract",
    "dteeth", "dcaries", "dfilling", "dextract",
    "need_fluoride", "need_scaling", "need_sealant",
    "need_pfilling", "need_dfilling", "need_pextract", "need_dextract",
    "nprosthesis", "permanent_permanent", "permanent_prosthesis",
    "prosthesis_prosthesis",
]

# คอลัมน์ที่ต้องคงเป็น string (รหัสที่มีเลข 0 นำหน้า)
CODE_COLS = ["hoscode", "pid", "cid", "sex", "denttype", "servplace",
             "gum", "schooltype", "class", "provider", "providertype"]


def _clean_na(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().replace(list(NA_TOKENS), pd.NA)


def load_data(folder: str, pattern: str = "*.xlsx") -> pd.DataFrame:
    """อ่านทุกไฟล์ใน folder แล้วต่อกัน — ผู้ใช้วางไฟล์เพิ่มได้เอง"""
    files = sorted(
        f for f in glob.glob(os.path.join(folder, pattern))
        if not os.path.basename(f).startswith("~$")
    )
    if not files:
        raise FileNotFoundError(f"ไม่พบไฟล์ข้อมูลใน {folder}")

    frames = []
    for f in files:
        if f.lower().endswith((".csv", ".txt")):
            df = _read_csv_any(f)
        else:
            df = pd.read_excel(f, dtype=str)
        df["_source_file"] = os.path.basename(f)
        frames.append(df)

    df = pd.concat(frames, ignore_index=True)
    return normalize(df)


def _read_csv_any(path: str) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp874", "tis-620"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str, encoding="utf-8", errors="replace")


def apply_filename_rules(df: pd.DataFrame, specs: list[dict]) -> pd.DataFrame:
    """สร้างคอลัมน์จาก "ชื่อไฟล์" ตามกฎที่กำหนดใน profile

    ใช้กรณีที่ข้อมูลถูกแยกเป็นหลายไฟล์ตามกลุ่ม แต่ในไฟล์ไม่มีคอลัมน์บอกกลุ่ม
    เช่น "data_exchange ตรวจฟัน 0-2 ปี.xlsx" -> agegroup = "a0-2"

    specs = [{"column": "agegroup",
              "rules": [{"contains": "0-2", "value": "a0-2"}, ...],
              "default": None, "overwrite": False}]
    """
    if not specs or "_source_file" not in df.columns:
        return df

    df = df.copy()
    src = df["_source_file"].astype("string").fillna("")

    for spec in specs:
        col = spec.get("column")
        if not col:
            continue
        derived = pd.Series(spec.get("default"), index=df.index, dtype="object")
        for rule in spec.get("rules", []) or []:
            needle = str(rule.get("contains", ""))
            if not needle:
                continue
            hit = src.str.contains(needle, case=False, regex=False, na=False)
            derived = derived.mask(hit & derived.isna(), rule.get("value"))
        derived = derived.astype("string")

        if col in df.columns and not spec.get("overwrite", False):
            # ไฟล์ที่มีคอลัมน์นี้อยู่แล้วให้ใช้ค่าเดิม เติมเฉพาะช่องที่ว่าง
            df[col] = df[col].astype("string").fillna(derived)
        else:
            df[col] = derived
    return df


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """ทำให้ชื่อคอลัมน์และชนิดข้อมูลเป็นมาตรฐานเดียวกันทุกกลุ่มอายุ"""
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    for c in df.columns:
        if c.startswith("_"):
            continue
        df[c] = _clean_na(df[c])

    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ("date_serv", "birth", "d_update"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    for c in CODE_COLS:
        if c in df.columns:
            df[c] = df[c].astype("string")

    return df


def load_hospitals(path: str) -> pd.DataFrame:
    """hospitals.csv เป็น TIS-620 ไม่ใช่ UTF-8"""
    df = _read_csv_any(path)
    df.columns = [c.strip().lower() for c in df.columns]
    keep = [c for c in ["hoscode", "hosname", "hostype", "ampcode", "ampname",
                        "pvcode", "pvname", "tumcode", "tumbonname"] if c in df.columns]
    df = df[keep].drop_duplicates(subset="hoscode")
    # ตัดรหัสนำหน้าออกจากชื่อ เช่น "01-เมืองชัยภูมิ" -> "เมืองชัยภูมิ"
    for c in ("ampname", "pvname", "tumbonname"):
        if c in df.columns:
            df[c] = df[c].astype("string").str.replace(r"^\d+-", "", regex=True).str.strip()
    df["hoscode"] = df["hoscode"].astype("string").str.strip()
    return df


def load_dictionary(path: str) -> pd.DataFrame:
    """dentalfile.csv = metadata ของ field (label ไทย + ค่าที่เป็นไปได้)"""
    df = _read_csv_any(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["name"] = df["name"].astype("string").str.strip().str.lower()
    return df.set_index("name")


def attach_area(df: pd.DataFrame, hospitals: pd.DataFrame) -> pd.DataFrame:
    """ผูก hoscode -> จังหวัด/อำเภอ/ชื่อหน่วยบริการ"""
    df = df.copy()
    df["hoscode"] = df["hoscode"].astype("string").str.strip()
    out = df.merge(hospitals, on="hoscode", how="left", suffixes=("", "_ref"))
    if "hosname_ref" in out.columns:
        out["hosname"] = out["hosname"].fillna(out["hosname_ref"])
    for c in ("pvname", "ampname"):
        if c in out.columns:
            out[c] = out[c].fillna("ไม่ระบุ")
    return out

"""สำรวจข้อมูลเบื้องต้น (Exploratory Data Analysis)

คำนวณ 4 ส่วน จากข้อมูลชุดเดียวกับที่รายงานใช้:
  1. anomalies     ค่าที่ผิดปกติหรือขัดแย้งกันเอง
  2. numeric       การกระจายของค่าตัวเลข (histogram + สถิติแบบ boxplot)
  3. categorical   ความถี่ของตัวแปรหมวดหมู่ พร้อมคำอธิบายจาก dentalfile.csv
  4. heatmap       ตัวชี้วัดหลักเทียบข้ามพื้นที่

ทุกอย่างคำนวณในเครื่อง ไม่ต้องต่อเน็ต
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# คอลัมน์ที่นำมาสำรวจ
# ---------------------------------------------------------------------------

NUMERIC_CANDIDATES = [
    ("age", "อายุขณะตรวจ (ปี)"),
    ("pteeth", "ฟันแท้ที่มีอยู่ (ซี่)"),
    ("pcaries", "ฟันแท้ผุ (ซี่)"),
    ("pfilling", "ฟันแท้อุด (ซี่)"),
    ("pextract", "ฟันแท้ถอน/หลุด (ซี่)"),
    ("dmft_p", "ฟันแท้ผุถอนอุด DMFT (ซี่)"),
    ("dteeth", "ฟันน้ำนมที่มีอยู่ (ซี่)"),
    ("dcaries", "ฟันน้ำนมผุ (ซี่)"),
    ("dfilling", "ฟันน้ำนมอุด (ซี่)"),
    ("dextract", "ฟันน้ำนมถอน (ซี่)"),
    ("dmft_d", "ฟันน้ำนมผุถอนอุด dmft (ซี่)"),
    ("need_sealant", "ต้องเคลือบหลุมร่องฟัน (ซี่)"),
    ("need_pfilling", "ต้องอุดฟันแท้ (ซี่)"),
    ("need_dfilling", "ต้องอุดฟันน้ำนม (ซี่)"),
    ("need_pextract", "ต้องถอน/รักษารากฟันแท้ (ซี่)"),
    ("need_dextract", "ต้องถอนฟันน้ำนม (ซี่)"),
]

CATEGORICAL_CANDIDATES = [
    ("providertype", "ประเภทผู้ตรวจ"),
    ("denttype", "กลุ่มผู้รับบริการ"),
    ("servplace", "สถานที่ให้บริการ"),
    ("gum_status", "สภาวะปริทันต์ (สรุปจาก GUM)"),
    ("sex", "เพศ"),
    ("agegroup", "กลุ่มอายุในไฟล์"),
    ("class", "ระดับการศึกษา"),
    ("schooltype", "สังกัดสถานศึกษา"),
    ("check_typearea", "typearea"),
    ("nation", "สัญชาติ"),
    ("need_fluoride", "ความจำเป็นทาฟลูออไรด์"),
    ("need_scaling", "ความจำเป็นขูดหินน้ำลาย"),
    ("result", "ผลตามเกณฑ์ (จาก HDC)"),
]

SEX_LABEL = {"1": "ชาย", "2": "หญิง"}
GUM_STATUS_LABEL = {"0": "ปกติ", "1": "เลือดออก/เหงือกอักเสบ", "2": "มีหินน้ำลาย",
                    "3": "ปริทันต์อักเสบ", "9": "ตรวจไม่ได้"}

MAX_CATEGORIES = 12          # เกินนี้รวมเป็น "อื่น ๆ"
HIST_BINS = 12


# ---------------------------------------------------------------------------
# คำอธิบายรหัส จาก dentalfile.csv
# ---------------------------------------------------------------------------

def code_labels(dictionary: pd.DataFrame) -> dict[str, dict[str, str]]:
    """แปลง DESCRIPTION แบบ "1=ในหน่วยบริการ, 2=นอกหน่วยบริการ" เป็น dict"""
    out: dict[str, dict[str, str]] = {}
    if dictionary is None or dictionary.empty or "description" not in dictionary.columns:
        return out
    for name, row in dictionary.iterrows():
        desc = str(row.get("description") or "")
        pairs = re.findall(r"(\w+)\s*=\s*([^,;]+)", desc)
        if len(pairs) >= 2:
            out[str(name).lower()] = {k.strip(): v.strip() for k, v in pairs}
    out.setdefault("sex", SEX_LABEL)
    out["gum_status"] = GUM_STATUS_LABEL
    return out


# ---------------------------------------------------------------------------
# 1. ค่าผิดปกติ / ขัดแย้งกันเอง
# ---------------------------------------------------------------------------

def _rule_masks(df: pd.DataFrame, profile) -> list[tuple[str, str, pd.Series]]:
    """คืน [(ชื่อกฎ, คำอธิบาย, mask ของแถวที่ผิด), ...] — เฉพาะกฎที่ใช้ได้กับคอลัมน์ที่มี"""
    have = set(df.columns)
    num = lambda c: pd.to_numeric(df[c], errors="coerce")
    out = []

    def add(name, desc, mask):
        out.append((name, desc, mask.fillna(False).to_numpy(dtype=bool)))

    # จำนวนซี่ฟันติดลบเป็นไปไม่ได้ — ตรวจรวมทุกคอลัมน์ที่นับเป็นซี่
    tooth_cols = [c for c in ("pteeth", "pcaries", "pfilling", "pextract",
                              "dteeth", "dcaries", "dfilling", "dextract",
                              "need_sealant", "need_pfilling", "need_dfilling",
                              "need_pextract", "need_dextract") if c in have]
    if tooth_cols:
        neg = pd.Series(False, index=df.index)
        for c in tooth_cols:
            neg |= num(c) < 0
        add("จำนวนซี่ฟันติดลบ", "ค่าในช่องนับซี่ฟัน < 0 (เป็นไปไม่ได้)", neg)

    if "pteeth" in have:
        add("ฟันแท้เกิน 32 ซี่", "pteeth > 32", num("pteeth") > 32)
    if "dteeth" in have:
        add("ฟันน้ำนมเกิน 20 ซี่", "dteeth > 20", num("dteeth") > 20)
    if {"pcaries", "pfilling", "pteeth"} <= have:
        add("ฟันแท้ผุ+อุด มากกว่าฟันที่มีอยู่",
            "pcaries + pfilling > pteeth",
            num("pcaries").fillna(0) + num("pfilling").fillna(0) > num("pteeth"))
    if {"dcaries", "dfilling", "dteeth"} <= have:
        add("ฟันน้ำนมผุ+อุด มากกว่าฟันที่มีอยู่",
            "dcaries + dfilling > dteeth",
            num("dcaries").fillna(0) + num("dfilling").fillna(0) > num("dteeth"))
    if "gum" in have:
        g = df["gum"].astype("string")
        bad = g.notna() & ~g.str.fullmatch(r"[0-39]{6}", na=False)
        add("รหัส GUM ไม่ใช่ 6 หลัก", "ต้องเป็นตัวเลข 0-3 หรือ 9 จำนวน 6 ตัว", bad)
    if {"date_serv", "birth"} <= have:
        add("วันที่ตรวจก่อนวันเกิด", "date_serv < birth",
            df["date_serv"].notna() & df["birth"].notna()
            & (df["date_serv"] < df["birth"]))
        add("วันที่ตรวจอยู่ในอนาคต", "date_serv > วันนี้",
            df["date_serv"].notna() & (df["date_serv"] > pd.Timestamp.today()))
    if "age" in have and profile is not None:
        a = num("age")
        add(f"อายุขณะตรวจนอกช่วง {profile.age_min}-{profile.age_max} ปี",
            "คำนวณจาก date_serv - birth",
            df["examined"].fillna(False) & a.notna()
            & ((a < profile.age_min) | (a > profile.age_max)))
    if "providertype" in have:
        pt = df["providertype"].astype("string")
        add("ผู้ตรวจไม่ใช่ทันตแพทย์/ทันตาภิบาล", "providertype ไม่ใช่ 02 หรือ 06",
            df["examined"].fillna(False) & pt.notna() & ~pt.isin(["02", "06"]))
    if {"agegroup", "age"} <= have:
        ag = df["agegroup"].astype("string").str.extract(r"(\d+)\s*-\s*(\d+)")
        lo = pd.to_numeric(ag[0], errors="coerce")
        hi = pd.to_numeric(ag[1], errors="coerce")
        a = num("age")
        add("อายุไม่ตรงกับ agegroup ในไฟล์", "เช่น agegroup=a0-2 แต่คำนวณได้ 3 ปี",
            df["examined"].fillna(False) & a.notna() & lo.notna()
            & ((a < lo) | (a > hi)))
    # ตรวจคนซ้ำ: ใช้ CID ได้เฉพาะเมื่อไม่ได้ถูกปิดบัง (ไฟล์ HDC มักส่งมาเป็น 1369901xxxx****)
    if "cid" in have:
        c = df["cid"].astype("string")
        masked = c.notna() & c.str.contains(r"\*", na=False)
        if float(masked.mean()) < 0.5:
            add("เลขบัตรประชาชนซ้ำ", "อาจเป็นคนเดียวกันถูกบันทึกหลายครั้ง",
                c.notna() & c.duplicated(keep=False))
    if {"hoscode", "pid"} <= have:
        key = df["hoscode"].astype("string") + "|" + df["pid"].astype("string")
        add("PID ซ้ำในหน่วยบริการเดียวกัน",
            "hoscode + pid ซ้ำ — อาจเป็นคนเดียวกันถูกบันทึกหลายครั้ง",
            key.notna() & key.duplicated(keep=False))
    return out


def anomalies(df: pd.DataFrame, profile) -> dict:
    n = len(df)
    rules = []
    any_bad = np.zeros(n, dtype=bool)
    for name, desc, mask in _rule_masks(df, profile):
        cnt = int(mask.sum())
        any_bad |= mask
        rules.append({
            "name": name, "desc": desc, "count": cnt,
            "pct": round(100 * cnt / n, 2) if n else None,
        })
    rules.sort(key=lambda r: -r["count"])
    return {
        "rules": rules,
        "rows_with_issue": int(any_bad.sum()),
        "rows_total": n,
        "pct": round(100 * any_bad.sum() / n, 2) if n else None,
    }


# ---------------------------------------------------------------------------
# 2. การกระจายของค่าตัวเลข (histogram + boxplot)
# ---------------------------------------------------------------------------

def numeric_profile(df: pd.DataFrame) -> list[dict]:
    out = []
    for col, label in NUMERIC_CANDIDATES:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue

        q1, med, q3 = (float(s.quantile(q)) for q in (0.25, 0.5, 0.75))
        iqr = q3 - q1
        lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        inside = s[(s >= lo_f) & (s <= hi_f)]
        out_hi = s[s > hi_f]
        out_lo = s[s < lo_f]

        lo, hi = float(s.min()), float(s.max())
        if hi > lo:
            bins = min(HIST_BINS, int(hi - lo) + 1) if float(hi - lo).is_integer() else HIST_BINS
            counts, edges = np.histogram(s, bins=max(1, bins))
            hist = [{"from": round(float(edges[i]), 2),
                     "to": round(float(edges[i + 1]), 2),
                     "count": int(counts[i])} for i in range(len(counts))]
        else:
            hist = [{"from": lo, "to": hi, "count": int(len(s))}]

        out.append({
            "column": col, "label": label,
            "n": int(len(s)), "mean": round(float(s.mean()), 2),
            "sd": round(float(s.std(ddof=0)), 2) if len(s) > 1 else 0.0,
            "min": lo, "q1": round(q1, 2), "median": round(med, 2),
            "q3": round(q3, 2), "max": hi,
            "whisker_lo": float(inside.min()) if len(inside) else lo,
            "whisker_hi": float(inside.max()) if len(inside) else hi,
            "outliers_hi": int(len(out_hi)), "outliers_lo": int(len(out_lo)),
            "outlier_pct": round(100 * (len(out_hi) + len(out_lo)) / len(s), 2),
            "outlier_n": int(len(out_hi) + len(out_lo)),
            "zero_pct": round(100 * float((s == 0).sum()) / len(s), 1),
            "zero_n": int((s == 0).sum()),
            "neg_n": int((s < 0).sum()),          # ค่าติดลบ = เป็นไปไม่ได้ ต้องตามแก้
            "extreme_n": int(((s == lo) | (s == hi)).sum()),
            "iqr_n": int(((s >= q1) & (s <= q3)).sum()),
            "hist": hist,
        })
    return out


# ---------------------------------------------------------------------------
# 3. ความถี่ของตัวแปรหมวดหมู่
# ---------------------------------------------------------------------------

def categorical_profile(df: pd.DataFrame, labels: dict) -> list[dict]:
    n = len(df)
    out = []
    for col, label in CATEGORICAL_CANDIDATES:
        if col not in df.columns:
            continue
        s = df[col].astype("string")
        vc = s.value_counts(dropna=True)
        if vc.empty:
            continue
        lut = labels.get(col, {})
        items = []
        for val, cnt in vc.head(MAX_CATEGORIES).items():
            items.append({
                "value": str(val),
                "label": lut.get(str(val), ""),
                "count": int(cnt),
                "pct": round(100 * int(cnt) / n, 2) if n else None,
            })
        rest = int(vc.iloc[MAX_CATEGORIES:].sum())
        if rest:
            items.append({"value": f"อื่น ๆ ({len(vc) - MAX_CATEGORIES} ค่า)",
                          "label": "", "count": rest,
                          "pct": round(100 * rest / n, 2) if n else None})
        miss = int(s.isna().sum())
        out.append({
            "column": col, "label": label, "distinct": int(vc.nunique()),
            "missing": miss,
            "missing_pct": round(100 * miss / n, 2) if n else None,
            "items": items,
        })
    return out


# ---------------------------------------------------------------------------
# 4. heatmap เทียบพื้นที่
# ---------------------------------------------------------------------------

def heatmap(rows: list[dict], level: str, labels: dict) -> dict:
    """ใช้ผลสรุปรายพื้นที่ที่คำนวณไว้แล้ว มาทำตารางสีเทียบกัน"""
    cf = (labels or {}).get("caries_free_label", "ปราศจากฟันผุ")
    metrics = [
        {"key": "examined_pct", "label": "%ได้รับการตรวจ", "good": "high", "unit": "%"},
        {"key": "qualified_pct", "label": "%ผ่านเกณฑ์คุณภาพ", "good": "high", "unit": "%"},
        {"key": "caries_free_pct", "label": f"%{cf}", "good": "high", "unit": "%"},
        {"key": "dmft", "label": "ผุถอนอุดเฉลี่ย", "good": "low", "unit": ""},
    ]
    data = [r for r in rows if r.get("examined", 0) > 0]
    if not data:
        return {"metrics": [], "rows": []}

    # หา min/max ของแต่ละตัวชี้วัด เพื่อ normalize เป็นระดับสี 0-1
    for m in metrics:
        vals = [r.get(m["key"]) for r in data if isinstance(r.get(m["key"]), (int, float))]
        m["min"] = round(min(vals), 2) if vals else None
        m["max"] = round(max(vals), 2) if vals else None

    out_rows = []
    for r in data:
        cells = []
        for m in metrics:
            v = r.get(m["key"])
            lo, hi = m["min"], m["max"]
            if not isinstance(v, (int, float)) or lo is None or hi is None or hi == lo:
                score = None
            else:
                t = (v - lo) / (hi - lo)
                score = round(t if m["good"] == "high" else 1 - t, 3)
            cells.append({"value": v, "score": score})
        out_rows.append({"code": r.get("code", ""), "name": r.get("name", ""),
                         "target": r.get("target"), "cells": cells})
    return {"level": level, "metrics": metrics, "rows": out_rows}


# ---------------------------------------------------------------------------

def build(pop: pd.DataFrame, scoped: pd.DataFrame, profile,
          area_rows: list[dict], level: str,
          dictionary: pd.DataFrame, overview_labels: dict) -> dict:
    """pop = ทุกแถวในขอบเขต | scoped = เฉพาะที่ตรวจฟันและอยู่ในช่วงอายุ"""
    labels = code_labels(dictionary)
    return {
        "n_pop": len(pop),
        "n_scoped": len(scoped),
        "anomalies": anomalies(pop, profile),
        "numeric": numeric_profile(scoped),
        "categorical": categorical_profile(scoped, labels),
        "heatmap": heatmap(area_rows, level, overview_labels),
    }

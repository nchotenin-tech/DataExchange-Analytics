"""Engine กลาง: อ่าน spec จาก profile YAML แล้วคำนวณตารางรายงาน

ทุกกลุ่มอายุใช้ engine ตัวเดียวกัน — ต่างกันแค่ไฟล์ profile
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

TOTAL_LABEL = "รวม"


def evaluate(df: pd.DataFrame, expr: str) -> pd.Series:
    """ประเมิน expression บน DataFrame -> boolean/numeric Series

    รองรับไวยากรณ์ pandas.eval เช่น
        "pcaries + pfilling + pextract == 0"
        "providertype in ['02','06']"
        "need_sealant > 0"
    """
    if expr is None:
        return pd.Series(True, index=df.index)
    if isinstance(expr, bool):
        return pd.Series(expr, index=df.index)
    res = df.eval(expr, engine="python")
    if not isinstance(res, pd.Series):
        res = pd.Series(res, index=df.index)
    return res


def bool_mask(df: pd.DataFrame, expr: str) -> pd.Series:
    """เหมือน evaluate แต่บังคับเป็น boolean และ NA -> False"""
    s = evaluate(df, expr)
    if s.dtype == bool:
        return s
    return s.fillna(False).astype(bool)


@dataclass
class Metric:
    name: str
    expr: str
    kind: str = "count"          # count | mean | sum
    denominator: str | None = None
    note: str = ""


@dataclass
class TableSpec:
    no: str
    title: str
    kind: str                    # quality | count_pct | mean
    metrics: list[Metric] = field(default_factory=list)
    rows: str = "age"            # age | none
    denominator: str = "qualified"   # qualified | examined | all
    conditions: list[str] = field(default_factory=list)
    decimals: int = 2

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TableSpec":
        return cls(
            no=str(d.get("no", "")),
            title=d.get("title", ""),
            kind=d.get("kind", "count_pct"),
            rows=d.get("rows", "age"),
            denominator=d.get("denominator", "qualified"),
            conditions=d.get("conditions", []) or [],
            decimals=d.get("decimals", 2),
            metrics=[
                Metric(
                    name=m["name"],
                    expr=m.get("expr"),
                    kind=m.get("kind", "count"),
                    denominator=m.get("denominator"),
                    note=m.get("note", ""),
                )
                for m in d.get("metrics", [])
            ],
        )


@dataclass
class Band:
    """ช่วงอายุย่อยที่ใช้เป็นแถวของตาราง เช่น 0-2 ปี, 3-5 ปี"""
    label: str
    min: int
    max: int


@dataclass
class Profile:
    id: str
    label: str
    data_folder: str
    age_min: int
    age_max: int
    row_filter: str | None
    quality_filter: str
    quality_checks: list[dict]
    tables: list[TableSpec]
    bands: list[Band] = field(default_factory=list)
    quality_extra: dict[str, str] = field(default_factory=dict)
    overview: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        return cls(
            id=d["id"],
            label=d.get("label", d["id"]),
            data_folder=d.get("data_folder", d["id"]),
            age_min=int(d["age_range"][0]),
            age_max=int(d["age_range"][1]),
            row_filter=d.get("row_filter"),
            quality_filter=d["quality_filter"],
            quality_checks=d.get("quality_checks", []),
            bands=[Band(label=str(b["label"]), min=int(b["min"]), max=int(b["max"]))
                   for b in d.get("bands", []) or []],
            quality_extra=d.get("quality_extra", {}) or {},
            overview=d.get("overview", {}) or {},
            tables=[TableSpec.from_dict(t) for t in d.get("tables", [])],
        )

    def band_of(self, age) -> str | None:
        for b in self.bands:
            if b.min <= age <= b.max:
                return b.label
        return None


def quality_mask(df: pd.DataFrame, profile: Profile) -> pd.Series:
    """เกณฑ์คุณภาพ = เงื่อนไขหลัก + เงื่อนไขเพิ่มเติมเฉพาะบางช่วงอายุ (quality_extra)"""
    m = bool_mask(df, profile.quality_filter)
    if profile.quality_extra and "band" in df.columns:
        for label, expr in profile.quality_extra.items():
            in_band = df["band"] == label
            m &= (~in_band) | bool_mask(df, expr)
    return m


# --------------------------------------------------------------------------- #
# การคำนวณ
# --------------------------------------------------------------------------- #

def apply_scope(df: pd.DataFrame, profile: Profile) -> pd.DataFrame:
    """กรองให้เหลือเฉพาะแถวที่ตรวจฟันและอยู่ในช่วงอายุของ profile"""
    m = df["examined"]
    if profile.row_filter:
        m &= bool_mask(df, profile.row_filter)
    age = df["age"]
    m &= age.notna() & (age >= profile.age_min) & (age <= profile.age_max)
    out = df[m].copy()
    out["age"] = out["age"].astype("Int64")
    if profile.bands:
        out["band"] = out["age"].map(profile.band_of).astype("string")
    return out


def _age_index(profile: Profile) -> list:
    return list(range(profile.age_min, profile.age_max + 1))


def _groups(df: pd.DataFrame, spec: TableSpec, profile: Profile):
    """คืน [(label, sub_df), ...] โดยมีแถว 'รวม' ต่อท้ายเสมอ"""
    if spec.rows == "age":
        for a in _age_index(profile):
            yield a, df[df["age"] == a]
    elif spec.rows in ("bands", "band"):
        for b in profile.bands:
            yield b.label, df[df["band"] == b.label]
    yield TOTAL_LABEL, df


def _row_label(spec: TableSpec) -> str:
    return {"age": "อายุ (ปี)", "bands": "กลุ่มอายุ (ปี)",
            "band": "กลุ่มอายุ (ปี)"}.get(spec.rows, "รายการ")


def _pct(n, d, decimals=2):
    if d in (0, None) or pd.isna(d):
        return None
    return round(100.0 * n / d, decimals)


def build_quality_table(df: pd.DataFrame, spec: TableSpec, profile: Profile) -> dict:
    """ตารางคุณภาพข้อมูล: จำนวนที่ตรวจ / ผ่านเกณฑ์ / ร้อยละ + สาเหตุที่ไม่ผ่าน"""
    qual = quality_mask(df, profile)
    rows = []
    for label, sub in _groups(df, spec, profile):
        sub_q = qual.loc[sub.index]
        n = len(sub)
        n_pass = int(sub_q.sum())
        row = {
            "row": label,
            "จำนวนที่ตรวจ": n,
            "จำนวนที่ผ่านเกณฑ์คุณภาพ": n_pass,
            "ร้อยละ": _pct(n_pass, n, spec.decimals),
        }
        for chk in profile.quality_checks:
            # เกณฑ์บางข้อใช้เฉพาะบางช่วงอายุ -> นับเฉพาะแถวในช่วงนั้น
            only = chk.get("bands")
            applies = (sub["band"].isin(only) if only and "band" in sub.columns
                       else pd.Series(True, index=sub.index))
            fail = int((~bool_mask(sub, chk["expr"]) & applies).sum())
            base = int(applies.sum())
            row[f'ไม่ผ่าน: {chk["name"]}'] = fail
            row[f'ร้อยละไม่ผ่าน: {chk["name"]}'] = _pct(fail, base, spec.decimals)
        rows.append(row)

    cols = list(rows[0].keys()) if rows else ["row"]
    return {"no": spec.no, "title": spec.title, "kind": spec.kind,
            "row_label": _row_label(spec),
            "columns": cols, "rows": rows, "conditions": spec.conditions}


def build_count_pct_table(df: pd.DataFrame, spec: TableSpec, profile: Profile) -> dict:
    denom_mask = _denominator_mask(df, spec, profile)
    rows = []
    for label, sub in _groups(df, spec, profile):
        base = int(denom_mask.loc[sub.index].sum())
        row = {"row": label, "ฐาน": base}
        for m in spec.metrics:
            hit = int((bool_mask(sub, m.expr) & denom_mask.loc[sub.index]).sum())
            row[f"{m.name}|จำนวน"] = hit
            row[f"{m.name}|ร้อยละ"] = _pct(hit, base, spec.decimals)
        rows.append(row)

    cols = ["row", "ฐาน"] + [f"{m.name}|{k}" for m in spec.metrics
                             for k in ("จำนวน", "ร้อยละ")]
    return {"no": spec.no, "title": spec.title, "kind": spec.kind,
            "row_label": _row_label(spec),
            "columns": cols, "rows": rows, "conditions": spec.conditions,
            "metric_names": [m.name for m in spec.metrics]}


def build_mean_table(df: pd.DataFrame, spec: TableSpec, profile: Profile) -> dict:
    denom_mask = _denominator_mask(df, spec, profile)
    rows = []
    for label, sub in _groups(df, spec, profile):
        dm = denom_mask.loc[sub.index]
        base = int(dm.sum())
        row = {"row": label, "ฐาน": base}
        for m in spec.metrics:
            vals = pd.to_numeric(evaluate(sub, m.expr), errors="coerce")[dm]
            total = float(vals.sum())
            row[m.name] = round(total / base, spec.decimals) if base else None
            row[f"{m.name}|รวมซี่"] = total
        rows.append(row)

    cols = ["row", "ฐาน"] + [m.name for m in spec.metrics]
    return {"no": spec.no, "title": spec.title, "kind": spec.kind,
            "row_label": _row_label(spec),
            "columns": cols, "rows": rows, "conditions": spec.conditions,
            "metric_names": [m.name for m in spec.metrics]}


def _denominator_mask(df: pd.DataFrame, spec: TableSpec, profile: Profile) -> pd.Series:
    if spec.denominator == "qualified":
        return quality_mask(df, profile)
    if spec.denominator == "examined":
        return pd.Series(True, index=df.index)
    return bool_mask(df, spec.denominator)


BUILDERS = {
    "quality": build_quality_table,
    "count_pct": build_count_pct_table,
    "mean": build_mean_table,
}


def build_report(df: pd.DataFrame, profile: Profile) -> list[dict]:
    """คำนวณทุกตารางใน profile — df ต้องผ่าน apply_scope มาแล้ว"""
    out = []
    for spec in profile.tables:
        builder = BUILDERS.get(spec.kind)
        if builder is None:
            raise ValueError(f"ไม่รู้จัก table kind: {spec.kind}")
        out.append(builder(df, spec, profile))
    return out

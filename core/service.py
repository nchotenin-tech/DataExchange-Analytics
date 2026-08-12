"""ชั้นบริการ: โหลดข้อมูล + cache + กรองพื้นที่ + สร้างรายงาน"""
from __future__ import annotations

import os
import threading

import pandas as pd

from . import derive, insight, loader, profiles as prof_mod
from .engine import Profile, apply_scope, build_report, quality_mask

_cache: dict[str, pd.DataFrame] = {}
_lock = threading.Lock()
_hospitals: pd.DataFrame | None = None
_dictionary: pd.DataFrame | None = None


def hospitals() -> pd.DataFrame:
    global _hospitals
    if _hospitals is None:
        path = os.path.join(prof_mod.reference_dir(), "hospitals.csv")
        _hospitals = loader.load_hospitals(path)
    return _hospitals


def dictionary() -> pd.DataFrame:
    global _dictionary
    if _dictionary is None:
        path = os.path.join(prof_mod.reference_dir(), "dentalfile.csv")
        try:
            _dictionary = loader.load_dictionary(path)
        except Exception:
            _dictionary = pd.DataFrame()
    return _dictionary


def _fingerprint(folder: str) -> str:
    """ลายนิ้วมือของไฟล์ในโฟลเดอร์ — เปลี่ยนเมื่อผู้ใช้เพิ่ม/แก้ไฟล์ข้อมูล"""
    import hashlib
    parts = []
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if f.startswith("~$"):
            continue
        p = os.path.join(folder, f)
        if os.path.isfile(p):
            st = os.stat(p)
            parts.append(f"{f}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


CACHE_VERSION = "v2"

# pyarrow (parquet) เร็วกว่าและไฟล์เล็กกว่า แต่ทำให้ exe ใหญ่ขึ้นมาก
# ถ้าไม่มีก็ใช้ pickle ของ pandas แทน ผลลัพธ์เหมือนกัน
try:
    import pyarrow  # noqa: F401
    _CACHE_EXT = "parquet"
except ImportError:
    _CACHE_EXT = "pkl"


def _cache_read(path: str) -> pd.DataFrame:
    return pd.read_parquet(path) if path.endswith(".parquet") else pd.read_pickle(path)


def _cache_write(df: pd.DataFrame, path: str) -> None:
    if path.endswith(".parquet"):
        df.to_parquet(path, index=False)
    else:
        df.to_pickle(path)


def get_dataset(profile: Profile, refresh: bool = False) -> pd.DataFrame:
    """โหลด + เตรียมข้อมูลของ profile (ทุกแถวในไฟล์ ยังไม่กรองว่าตรวจฟันหรือไม่)

    เก็บแถวที่ยังไม่ได้ตรวจไว้ด้วย เพื่อใช้เป็นตัวหารของ "ร้อยละได้รับการตรวจฟัน"

    cache 2 ชั้น: หน่วยความจำ และไฟล์ .parquet (ทำให้เปิดครั้งถัดไปเร็วมาก)
    ถ้าผู้ใช้วางไฟล์ใหม่ในโฟลเดอร์ data/ ลายนิ้วมือจะเปลี่ยนและโหลดใหม่อัตโนมัติ
    """
    with _lock:
        fp = _fingerprint(profile.data_folder)
        key = f"{profile.id}:{fp}"
        if refresh:
            _cache.clear()
        elif key in _cache:
            return _cache[key]

        cache_dir = os.path.join(prof_mod.app_root(), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir,
                                  f"{profile.id}_{CACHE_VERSION}_{fp}.{_CACHE_EXT}")

        if not refresh and os.path.exists(cache_file):
            try:
                df = _cache_read(cache_file)
                _cache[key] = df
                return df
            except Exception:
                pass

        df = loader.load_data(profile.data_folder)
        df = loader.attach_area(df, hospitals())
        df = derive.prepare(df)
        if profile.bands:
            df["band"] = df["age"].map(
                lambda a: profile.band_of(a) if pd.notna(a) else None).astype("string")

        for old in os.listdir(cache_dir):
            if (old.startswith(f"{profile.id}_")
                    and old.endswith((".parquet", ".pkl"))
                    and old != os.path.basename(cache_file)):
                try:
                    os.remove(os.path.join(cache_dir, old))
                except OSError:
                    pass
        try:
            _cache_write(df, cache_file)
        except Exception:
            pass

        _cache[key] = df
        return df


def area_tree(df: pd.DataFrame) -> dict:
    """โครงพื้นที่สำหรับ drill-down: จังหวัด > อำเภอ > หน่วยบริการ"""
    cols = [c for c in ("pvname", "ampname", "hoscode", "hosname") if c in df.columns]
    sub = df[cols].drop_duplicates()
    def txt(v, default=""):
        return default if v is None or pd.isna(v) or str(v).strip() == "" else str(v).strip()

    tree: dict = {}
    for _, r in sub.iterrows():
        pv = txt(r.get("pvname"), "ไม่ระบุ")
        amp = txt(r.get("ampname"), "ไม่ระบุ")
        tree.setdefault(pv, {}).setdefault(amp, [])
        code = txt(r.get("hoscode"))
        name = txt(r.get("hosname"), code)
        if code and not any(h["code"] == code for h in tree[pv][amp]):
            tree[pv][amp].append({"code": code, "name": name})
    for pv in tree:
        for amp in tree[pv]:
            tree[pv][amp].sort(key=lambda h: h["name"])
    return tree


def filter_area(df: pd.DataFrame, pv=None, amp=None, hos=None) -> pd.DataFrame:
    out = df
    if pv:
        out = out[out["pvname"] == pv]
    if amp:
        out = out[out["ampname"] == amp]
    if hos:
        out = out[out["hoscode"].astype(str) == str(hos)]
    return out


def summary(df: pd.DataFrame, profile: Profile) -> dict:
    q = quality_mask(df, profile)
    n = len(df)
    return {
        "examined": n,
        "qualified": int(q.sum()),
        "qualified_pct": round(100 * q.sum() / n, 2) if n else 0,
        "hospitals": int(df["hoscode"].nunique()) if "hoscode" in df else 0,
        "districts": int(df["ampname"].nunique()) if "ampname" in df else 0,
        "date_min": str(df["date_serv"].min().date()) if n and df["date_serv"].notna().any() else "-",
        "date_max": str(df["date_serv"].max().date()) if n and df["date_serv"].notna().any() else "-",
    }


def overview_spec(profile: Profile) -> dict:
    """นิยามตัวชี้วัดของแถบสรุปรายอำเภอ (แต่ละกลุ่มอายุกำหนดเองได้ใน YAML)"""
    o = profile.overview or {}
    return {
        "caries_free": o.get("caries_free", "pcaries + pfilling + pextract == 0"),
        "dmft": o.get("dmft", "pcaries + pfilling + pextract"),
        "caries_free_label": o.get("caries_free_label", "ปราศจากฟันผุ"),
        "dmft_label": o.get("dmft_label", "DMFT เฉลี่ย"),
    }


def _breakdown(pop: pd.DataFrame, profile: Profile, by: str,
               code_col: str, name_col: str) -> list[dict]:
    """สรุปตามพื้นที่/หน่วยบริการ

    pop  = ประชากรเป้าหมายทั้งหมดในไฟล์ (ยังไม่กรองว่าตรวจฟันหรือไม่)
    ใช้เป็นตัวหารของ "ร้อยละได้รับการตรวจฟัน"
    """
    from .engine import bool_mask, evaluate
    spec = overview_spec(profile)

    # คำนวณ mask ทีเดียวทั้งชุด แล้วค่อยรวมยอดตามกลุ่ม (เร็วกว่าวนทีละกลุ่ม)
    scoped = apply_scope(pop, profile)
    sq = scoped[quality_mask(scoped, profile)] if len(scoped) else scoped
    cf_flag = bool_mask(sq, spec["caries_free"]) if len(sq) else pd.Series(dtype=bool)
    dmft_val = (pd.to_numeric(evaluate(sq, spec["dmft"]), errors="coerce")
                if len(sq) else pd.Series(dtype=float))

    target = pop.groupby(by, dropna=False).size()
    examined = scoped.groupby(by, dropna=False).size()
    qualified = sq.groupby(by, dropna=False).size()
    cf = cf_flag.groupby(sq[by], dropna=False).sum() if len(sq) else pd.Series(dtype=float)
    dm = dmft_val.groupby(sq[by], dropna=False).sum() if len(sq) else pd.Series(dtype=float)

    labels = (pop[[c for c in {by, code_col, name_col} if c in pop.columns]]
              .drop_duplicates(subset=by).set_index(by))

    rows = []
    for key in target.index:
        t = int(target.get(key, 0))
        e = int(examined.get(key, 0))
        b = int(qualified.get(key, 0))
        c = int(cf.get(key, 0) or 0)
        info = labels.loc[key] if key in labels.index else {}
        code = key if code_col == by else info.get(code_col)
        rows.append({
            "key": str(key) if pd.notna(key) else "ไม่ระบุ",
            "code": str(code) if code_col and pd.notna(code) else "",
            "name": str(info.get(name_col) or key or "ไม่ระบุ"),
            "target": t,
            "examined": e,
            "pending": t - e,
            "failed": e - b,
            "examined_pct": round(100 * e / t, 2) if t else None,
            "qualified": b,
            "qualified_pct": round(100 * b / e, 2) if e else None,
            "caries_free": c,
            "caries_free_pct": round(100 * c / b, 2) if b else None,
            "dmft": round(float(dm.get(key, 0) or 0) / b, 2) if b else None,
        })
    rows.sort(key=lambda r: (r["code"] or "￿", r["name"]))
    return rows


def by_district(pop: pd.DataFrame, profile: Profile) -> list[dict]:
    """สรุปรายอำเภอ เรียงตามรหัสอำเภอ"""
    return _breakdown(pop, profile, "ampname", "ampcode", "ampname")


def by_unit(pop: pd.DataFrame, profile: Profile) -> list[dict]:
    """สรุปรายหน่วยบริการ เรียงตามรหัสหน่วยบริการ"""
    return _breakdown(pop, profile, "hoscode", "hoscode", "hosname")


# --------------------------------------------------------------------------- #
# รายชื่อเด็กที่ยังไม่ได้ตรวจฟัน (สำหรับติดตามมาตรวจ)
# --------------------------------------------------------------------------- #

SEX_LABEL = {"1": "ชาย", "2": "หญิง"}

PENDING_COLS = [
    ("hoscode", "รหัสหน่วยบริการ"),
    ("hosname", "หน่วยบริการ"),
    ("ampname", "อำเภอ"),
    ("agegroup", "กลุ่มอายุ"),
    ("pid", "PID"),
    ("cid", "เลขบัตรประชาชน"),
    ("name", "ชื่อ"),
    ("lname", "นามสกุล"),
    ("sex_label", "เพศ"),
    ("birth_str", "วันเกิด"),
    ("age_today", "อายุปัจจุบัน (ปี)"),
    ("addr", "บ้านเลขที่"),
    ("check_typearea", "typearea"),
    ("tumbonname", "ตำบล"),
]


PROVIDER_LABEL = {"02": "ทันตแพทย์", "06": "ทันตาภิบาล"}

FAILED_COLS = [
    ("hoscode", "รหัสหน่วยบริการ"),
    ("hosname", "หน่วยบริการ"),
    ("ampname", "อำเภอ"),
    ("fail_reason", "สาเหตุที่ไม่ผ่านเกณฑ์"),
    ("pid", "PID"),
    ("cid", "เลขบัตรประชาชน"),
    ("name", "ชื่อ"),
    ("lname", "นามสกุล"),
    ("sex_label", "เพศ"),
    ("birth_str", "วันเกิด"),
    ("age", "อายุขณะตรวจ (ปี)"),
    ("date_str", "วันที่ตรวจ"),
    ("provider_label", "ผู้ตรวจ"),
    ("pteeth", "ฟันแท้ที่มี (ซี่)"),
    ("dteeth", "ฟันน้ำนมที่มี (ซี่)"),
    ("addr", "บ้านเลขที่"),
    ("tumbonname", "ตำบล"),
]

PERSON_KINDS = {
    "pending": "เด็กที่ยังไม่ได้ตรวจฟัน",
    "failed": "เด็กที่ตรวจแล้วไม่ผ่านเกณฑ์คุณภาพ",
}


def _add_person_fields(out: pd.DataFrame) -> pd.DataFrame:
    today = pd.Timestamp.today().normalize()
    b = out["birth"]
    yrs = today.year - b.dt.year
    before = (today.month < b.dt.month) | ((today.month == b.dt.month) & (today.day < b.dt.day))
    out["age_today"] = (yrs - before.astype(int)).where(b.notna()).astype("Int64")
    out["birth_str"] = b.dt.strftime("%Y-%m-%d")
    if "date_serv" in out.columns:
        out["date_str"] = out["date_serv"].dt.strftime("%Y-%m-%d")
    if "sex" in out.columns:
        out["sex_label"] = out["sex"].map(SEX_LABEL).fillna(out["sex"])
    if "providertype" in out.columns:
        out["provider_label"] = out["providertype"].map(
            lambda v: PROVIDER_LABEL.get(str(v), f"อื่น ๆ ({v})" if pd.notna(v) else "ไม่ระบุ"))
    return out


def _select(out: pd.DataFrame, spec, sort_keys) -> pd.DataFrame:
    cols = [(c, t) for c, t in spec if c in out.columns]
    res = out[[c for c, _ in cols]].rename(columns=dict(cols))
    order = [t for c, t in cols if c in sort_keys]
    if order:
        res = res.sort_values(order, na_position="last")
    return res.reset_index(drop=True)


def fail_reasons(df: pd.DataFrame, profile: Profile) -> pd.Series:
    """ข้อความบอกว่าตกเกณฑ์ข้อไหนบ้าง (คั่นด้วย ' + ')"""
    from .engine import bool_mask
    parts = []
    for chk in profile.quality_checks:
        only = chk.get("bands")
        applies = (df["band"].isin(only) if only and "band" in df.columns
                   else pd.Series(True, index=df.index))
        fail = (~bool_mask(df, chk["expr"])) & applies
        parts.append(fail.map(lambda x, n=chk["name"]: n if x else None))
    if not parts:
        return pd.Series("ไม่ผ่านเกณฑ์คุณภาพ", index=df.index)
    joined = pd.concat(parts, axis=1).apply(
        lambda r: " + ".join([v for v in r if v]) or "ไม่ผ่านเกณฑ์คุณภาพ", axis=1)
    return joined


def person_list(profile: Profile, kind: str = "pending",
                pv=None, amp=None, hos=None) -> pd.DataFrame:
    """รายชื่อเด็กสำหรับติดตาม

    kind='pending' = ยังไม่มี date_serv (ยังไม่ได้ตรวจ)
    kind='failed'  = ตรวจแล้วแต่ไม่ผ่านเกณฑ์คุณภาพ -> ควรตามมาตรวจใหม่
    """
    df = filter_area(get_dataset(profile), pv, amp, hos)

    if kind == "failed":
        scoped = apply_scope(df, profile)
        out = scoped[~quality_mask(scoped, profile)].copy()
        if len(out):
            out["fail_reason"] = fail_reasons(out, profile)
        else:
            out["fail_reason"] = pd.Series(dtype="object")
        out = _add_person_fields(out)
        return _select(out, FAILED_COLS, {"hoscode", "date_serv", "age"})

    out = _add_person_fields(df[~df["examined"].fillna(False)].copy())
    return _select(out, PENDING_COLS, {"hoscode", "age_today", "birth_str"})


def pending(profile: Profile, pv=None, amp=None, hos=None) -> pd.DataFrame:
    return person_list(profile, "pending", pv, amp, hos)


def report(profile: Profile, pv=None, amp=None, hos=None, refresh=False) -> dict:
    df = get_dataset(profile, refresh=refresh)
    pop = filter_area(df, pv, amp, hos)          # ประชากรเป้าหมายในขอบเขตที่เลือก
    scoped = apply_scope(pop, profile)           # เฉพาะที่ตรวจฟันและอยู่ในช่วงอายุ

    s = summary(scoped, profile)
    s["target"] = len(pop)
    s["examined_pct"] = round(100 * len(scoped) / len(pop), 2) if len(pop) else None

    tables = build_report(scoped, profile)
    for t in tables:
        try:
            t["insight"] = insight.build(t)
        except Exception:      # insight ห้ามทำให้รายงานพัง
            t["insight"] = {"summary": [], "rows": []}

    return {
        "profile": {"id": profile.id, "label": profile.label,
                    "age_min": profile.age_min, "age_max": profile.age_max},
        "scope": {"pvname": pv, "ampname": amp, "hoscode": hos},
        "overview_labels": {k: v for k, v in overview_spec(profile).items() if k.endswith("label")},
        "summary": s,
        # ยังไม่เลือกอำเภอ -> เทียบรายอำเภอ | เลือกอำเภอแล้ว -> ไล่ลงรายหน่วยบริการ
        "level": "unit" if (amp or hos) else "district",
        "districts": [] if (amp or hos) else by_district(pop, profile),
        "units": by_unit(pop, profile) if (amp and not hos) else [],
        "tables": tables,
    }

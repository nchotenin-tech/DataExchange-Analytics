"""ชั้นบริการ: โหลดข้อมูล + cache + กรองพื้นที่ + สร้างรายงาน"""
from __future__ import annotations

import os
import threading

import pandas as pd

from . import derive, eda as eda_mod, insight, loader, profiles as prof_mod
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


CACHE_VERSION = "v3"

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
    """เขียนแบบ atomic: เขียนไฟล์ชั่วคราวก่อนแล้วค่อยเปลี่ยนชื่อทับ

    ถ้าเปิดโปรแกรมพร้อมกันหลายหน้าต่าง จะได้ไม่อ่านไฟล์ที่เขียนค้างอยู่
    """
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        if path.endswith(".parquet"):
            df.to_parquet(tmp, index=False)
        else:
            df.to_pickle(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


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
        # สร้างคอลัมน์จากชื่อไฟล์ก่อน (เช่น agegroup) แล้วค่อยคำนวณตามปกติ
        df = loader.apply_filename_rules(df, profile.filename_columns)
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
    # "ยังไม่ได้ตรวจ" = ไม่มี date_serv จริง ๆ
    # (ไม่ใช่ เป้าหมาย - ตรวจแล้ว เพราะแถวที่ตรวจแล้วแต่อายุนอกช่วงจะถูกนับผิดฝั่ง)
    not_exam = pop[~pop["examined"].fillna(False)].groupby(by, dropna=False).size()
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
            "pending": int(not_exam.get(key, 0)),
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
    "value": "ข้อมูลรายบุคคลจากหน้าสำรวจข้อมูล",
    "metric": "รายชื่อเด็กที่ต้องติดตามจากตารางรายงาน",
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


# คอลัมน์ที่ระบบเติมเข้ามาเอง (ไม่ได้มาจากไฟล์ต้นฉบับ)
AREA_COLS = ["pvcode", "pvname", "ampcode", "ampname", "tumcode", "tumbonname",
             "hostype", "hosname_ref"]
CALC_COLS = ["age", "age_month", "band", "examined", "gum_status", "gum_label",
             "gum_sx_0", "gum_sx_1", "gum_sx_2", "gum_sx_3", "gum_sx_9",
             "dmft_p", "dmft_d"]
# คอลัมน์ชั่วคราวที่สร้างใน person_list เอง
TEMP_COLS = ["age_today", "birth_str", "date_str", "sex_label",
             "provider_label", "fail_reason"]


def raw_columns(df: pd.DataFrame) -> list[str]:
    """ฟิลด์ต้นฉบับที่มาจากไฟล์ข้อมูลจริง ๆ (ตามลำดับในไฟล์)"""
    skip = set(AREA_COLS) | set(CALC_COLS) | set(TEMP_COLS)
    return [c for c in df.columns if not c.startswith("_") and c not in skip]


def _select(out: pd.DataFrame, spec, sort_keys, raw: bool = False) -> pd.DataFrame:
    cols = [(c, t) for c, t in spec if c in out.columns]

    if raw:
        # ต่อท้ายด้วยฟิลด์ต้นฉบับทั้งหมด + ค่าที่ระบบคำนวณ เพื่อให้ตรวจสอบย้อนได้
        used = {c for c, _ in cols}
        cols += [(c, c) for c in raw_columns(out)]
        cols += [(c, c) for c in CALC_COLS if c in out.columns]
        if "_source_file" in out.columns:
            cols.append(("_source_file", "ไฟล์ต้นทาง"))
        # กันชื่อคอลัมน์ซ้ำ (ไม่ใช่กันแหล่งข้อมูลซ้ำ) — ฟิลด์ต้นฉบับต้องโผล่ครบทุกตัว
        # แม้ค่าจะซ้ำกับคอลัมน์สรุป เพราะจุดประสงค์คือตรวจสอบค่าดิบย้อนกลับ
        seen, uniq = set(), []
        for c, t in cols:
            if t not in seen:
                seen.add(t)
                uniq.append((c, t))
        cols = uniq

    res = out[[c for c, _ in cols]].copy()
    res.columns = [t for _, t in cols]
    order = [t for c, t in cols if c in sort_keys]
    if order:
        res = res.sort_values(order, na_position="last")

    # คอลัมน์วันที่ดิบต้องแปลงเป็นข้อความก่อน ไม่งั้น JSON พังเมื่อเจอค่าว่าง (NaT)
    for c in res.columns:
        if pd.api.types.is_datetime64_any_dtype(res[c]):
            fmt = "%Y-%m-%d %H:%M:%S" if c.lower() == "d_update" else "%Y-%m-%d"
            res[c] = res[c].dt.strftime(fmt)
    return res.reset_index(drop=True)


def fail_reasons(df: pd.DataFrame, profile: Profile) -> pd.Series:
    """ข้อความบอกว่าตกเกณฑ์ข้อไหนบ้าง (คั่นด้วย ' + ')

    ทำงานบน numpy array ตรง ๆ ไม่ผ่าน .map()/.apply()
    เพราะถ้าเกณฑ์ข้อไหนไม่มีใครตกเลย pandas จะเปลี่ยน dtype เป็น float
    ทำให้ค่า None กลายเป็น NaN (ซึ่งเป็น truthy) แล้ว join พัง
    """
    import numpy as np

    from .engine import bool_mask

    n = len(df)
    default = "ไม่ผ่านเกณฑ์คุณภาพ"
    if n == 0:
        return pd.Series([], index=df.index, dtype="string")

    checks = []
    for chk in profile.quality_checks:
        only = chk.get("bands")
        applies = (df["band"].isin(only).to_numpy(dtype=bool)
                   if only and "band" in df.columns else np.ones(n, dtype=bool))
        fail = (~bool_mask(df, chk["expr"]).to_numpy(dtype=bool)) & applies
        checks.append((str(chk["name"]), fail))

    if not checks:
        return pd.Series([default] * n, index=df.index, dtype="string")

    texts = [" + ".join(name for name, fail in checks if fail[i]) or default
             for i in range(n)]
    return pd.Series(texts, index=df.index, dtype="string")


_IDENT_RE = None


def _expr_columns(expr: str, df: pd.DataFrame) -> list[str]:
    """ดึงชื่อคอลัมน์ที่ expression อ้างถึง เช่น "dteeth + dextract == 20"
    -> ["dteeth", "dextract"] (กรองด้วยคอลัมน์จริงในข้อมูล คำอย่าง and/in จึงหลุดไป)
    """
    global _IDENT_RE
    if _IDENT_RE is None:
        import re
        _IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
    return [w for w in dict.fromkeys(_IDENT_RE.findall(str(expr or "")))
            if w in df.columns]


# ฟิลด์ดิบบางตัวถูกแปลงเป็นคอลัมน์อ่านง่ายก่อนแสดง ต้องระบายสีคู่กัน
_DISPLAY_ALIAS = {
    "providertype": ["provider_label"],
    "gum_status": ["gum_label"],
    "sex": ["sex_label"],
    "birth": ["birth_str"],
    "date_serv": ["date_str"],
    "need_fluoride": ["need_fluoride_label"],
    "need_scaling": ["need_scaling_label"],
}


def _headers_for(cols: list[str], spec) -> list[str]:
    """แปลงชื่อคอลัมน์ดิบ -> ชื่อหัวตารางที่หน้าเว็บใช้จริง (ทั้งชื่อดิบและชื่อสรุป)"""
    out = []
    for c in cols:
        out.append(c)                                   # คอลัมน์ฟิลด์ต้นฉบับ
        for src in [c] + _DISPLAY_ALIAS.get(c, []):
            out += [t for col, t in spec if col == src]  # คอลัมน์สรุปของฟิลด์เดียวกัน
    return list(dict.fromkeys(out))


def fail_fields(df: pd.DataFrame, profile: Profile, spec,
                checks=None) -> pd.Series:
    """คืน "ชื่อคอลัมน์ที่ทำให้ตกเกณฑ์" ของแต่ละแถว เพื่อให้หน้าเว็บระบายสีแดงได้

    ทำงานบน numpy array เหมือน fail_reasons — ถ้าเกณฑ์ข้อไหนไม่มีใครตก
    pandas จะเปลี่ยน dtype เป็น float แล้ว None กลายเป็น NaN ซึ่ง truthy
    """
    import numpy as np

    from .engine import bool_mask

    n = len(df)
    if n == 0:
        return pd.Series([[]] * 0, index=df.index, dtype=object)

    marks: list[tuple[np.ndarray, list[str]]] = []
    for chk in (checks if checks is not None else profile.quality_checks):
        only = chk.get("bands")
        applies = (df["band"].isin(only).to_numpy(dtype=bool)
                   if only and "band" in df.columns else np.ones(n, dtype=bool))
        fail = (~bool_mask(df, chk["expr"]).to_numpy(dtype=bool)) & applies
        marks.append((fail, _headers_for(_expr_columns(chk["expr"], df), spec)))

    out = [sorted({h for fail, hs in marks if fail[i] for h in hs}) for i in range(n)]
    return pd.Series(out, index=df.index, dtype=object)


def _bad_first(res: pd.DataFrame, after: int = 1) -> pd.DataFrame:
    """ย้ายคอลัมน์ที่ทำให้ตกเกณฑ์ขึ้นมาไว้ต้นตาราง

    ตารางกว้าง 80+ คอลัมน์ ถ้าไม่ย้ายขึ้นมา ผู้ใช้ต้องเลื่อนหาช่องสีแดงเอง
    """
    if "_bad" not in res.columns or res.empty:
        return res
    # ตัดชื่อคอลัมน์ที่ไม่ได้แสดงทิ้ง (เช่น ปิดฟิลด์ต้นฉบับ) ไม่งั้นหน้าเว็บหาไม่เจอ
    have = set(res.columns)
    res = res.copy()
    res["_bad"] = [[h for h in (lst or []) if h in have] for lst in res["_bad"]]
    bad = {h for lst in res["_bad"] for h in lst}
    if not bad:
        return res
    cols = list(res.columns)
    front = cols[:after] + [c for c in cols if c in bad]
    rest = [c for c in cols if c not in front]
    return res[front + rest]


def person_list(profile: Profile, kind: str = "pending",
                pv=None, amp=None, hos=None, raw: bool = False) -> pd.DataFrame:
    """รายชื่อเด็กสำหรับติดตาม

    kind='pending' = ยังไม่มี date_serv (ยังไม่ได้ตรวจ)
    kind='failed'  = ตรวจแล้วแต่ไม่ผ่านเกณฑ์คุณภาพ -> ควรตามมาตรวจใหม่
    raw=True       = ต่อท้ายด้วยฟิลด์ต้นฉบับทุกคอลัมน์ สำหรับตรวจสอบย้อนกลับ
    """
    df = filter_area(get_dataset(profile), pv, amp, hos)

    if kind == "failed":
        scoped = apply_scope(df, profile)
        out = scoped[~quality_mask(scoped, profile)].copy()
        if len(out):
            out["fail_reason"] = fail_reasons(out, profile)
            out["_bad"] = fail_fields(out, profile, FAILED_COLS)
        else:
            out["fail_reason"] = pd.Series(dtype="object")
            out["_bad"] = pd.Series(dtype="object")
        out = _add_person_fields(out)
        # คอลัมน์แรกคือ "สาเหตุที่ไม่ผ่านเกณฑ์" ... จึงย้ายช่องที่ผิดมาต่อจากนั้น
        res = _select(out, FAILED_COLS + [("_bad", "_bad")],
                      {"hoscode", "date_serv", "age"}, raw)
        return _bad_first(res, after=4)

    out = _add_person_fields(df[~df["examined"].fillna(False)].copy())
    return _select(out, PENDING_COLS, {"hoscode", "age_today", "birth_str"}, raw)


VALUE_COLS = [
    ("_value", "ค่าที่เลือก"),
    ("hoscode", "รหัสหน่วยบริการ"),
    ("hosname", "หน่วยบริการ"),
    ("ampname", "อำเภอ"),
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

# ตัวเลือกที่หน้าสำรวจข้อมูลส่งมา -> คำอธิบายที่แสดงบนหัวตาราง
VALUE_SELECTIONS = {
    "all": "ทุกแถวที่มีค่า",
    "outlier": "ค่าที่หลุดออกนอกหนวด (outlier)",
    "zero": "ค่าที่เป็นศูนย์",
    "neg": "ค่าที่ติดลบ (เป็นไปไม่ได้)",
    "extreme": "ค่าต่ำสุดและสูงสุด",
    "iqr": "ค่าที่อยู่ในกล่อง Q1–Q3",
    "range": "ค่าที่อยู่ในช่วงที่เลือกจากกราฟ",
}


def value_list(profile: Profile, col: str, sel: str = "outlier",
               lo=None, hi=None, pv=None, amp=None, hos=None,
               raw: bool = False, hi_exclusive: bool = False) -> pd.DataFrame:
    """รายบุคคลที่อยู่เบื้องหลังตัวเลขในหน้าสำรวจข้อมูล (คลิกจากการ์ดหรือแท่งกราฟ)

    ใช้ข้อมูลชุดเดียวกับที่ eda() ใช้ (scoped) และคำนวณ IQR ซ้ำด้วยวิธีเดียวกัน
    ตัวเลขบนการ์ดกับจำนวนรายชื่อที่เปิดได้จึงตรงกันเสมอ
    """
    scoped = apply_scope(filter_area(get_dataset(profile), pv, amp, hos), profile)
    if col not in scoped.columns:
        return pd.DataFrame()

    v = pd.to_numeric(scoped[col], errors="coerce")
    have = v.notna()

    if sel == "zero":
        m = have & (v == 0)
    elif sel == "neg":
        m = have & (v < 0)
    elif sel == "extreme":
        m = have & ((v == v.min()) | (v == v.max()))
    elif sel in ("outlier", "iqr"):
        q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
        iqr = q3 - q1
        inside = have & (v >= q1 - 1.5 * iqr) & (v <= q3 + 1.5 * iqr)
        m = (~inside & have) if sel == "outlier" else (have & (v >= q1) & (v <= q3))
    elif sel == "range":
        # แท่งกราฟใช้ขอบบนแบบไม่รวม (ยกเว้นแท่งสุดท้าย) ไม่งั้นค่าที่ตรงขอบ
        # จะถูกนับซ้ำในสองแท่ง แล้วยอดรวมจะเกินจำนวนจริง
        m = have
        if lo is not None:
            m &= v >= float(lo)
        if hi is not None:
            m &= (v < float(hi)) if hi_exclusive else (v <= float(hi))
    else:
        m = have

    out = scoped[m.fillna(False)].copy()
    out["_value"] = v[m.fillna(False)]
    out = _add_person_fields(out)
    res = _select(out, VALUE_COLS, set(), raw)
    # เรียงจากค่ามาก -> น้อย เพื่อให้ค่าที่ผิดปกติที่สุดอยู่บนสุด (ค่าติดลบเรียงกลับด้าน)
    label = VALUE_COLS[0][1]
    if label in res.columns:
        res = res.sort_values(label, ascending=(sel == "neg")).reset_index(drop=True)
    return res


TREATMENT_COLS = [
    ("_problem", "ปัญหาที่พบ / สิ่งที่ต้องทำ"),
    ("hoscode", "รหัสหน่วยบริการ"),
    ("hosname", "หน่วยบริการ"),
    ("ampname", "อำเภอ"),
    ("pid", "PID"),
    ("cid", "เลขบัตรประชาชน"),
    ("name", "ชื่อ"),
    ("lname", "นามสกุล"),
    ("sex_label", "เพศ"),
    ("birth_str", "วันเกิด"),
    ("age", "อายุขณะตรวจ (ปี)"),
    ("age_today", "อายุปัจจุบัน (ปี)"),
    ("date_str", "วันที่ตรวจ"),
    ("provider_label", "ผู้ตรวจ"),
    ("gum_label", "สภาวะปริทันต์"),
    ("pcaries", "ฟันแท้ผุ (ซี่)"),
    ("pextract", "ฟันแท้ถอน (ซี่)"),
    ("pfilling", "ฟันแท้อุด (ซี่)"),
    ("dcaries", "ฟันน้ำนมผุ (ซี่)"),
    ("dextract", "ฟันน้ำนมถอน (ซี่)"),
    ("dfilling", "ฟันน้ำนมอุด (ซี่)"),
    ("need_sealant", "ต้องเคลือบหลุมร่องฟัน (ซี่)"),
    ("need_pfilling", "ต้องอุดฟันแท้ (ซี่)"),
    ("need_dfilling", "ต้องอุดฟันน้ำนม (ซี่)"),
    ("need_pextract", "ต้องถอน/รักษารากฟันแท้ (ซี่)"),
    ("need_dextract", "ต้องถอนฟันน้ำนม (ซี่)"),
    ("need_fluoride_label", "ต้องทาฟลูออไรด์"),
    ("need_scaling_label", "ต้องขูดหินน้ำลาย"),
    ("addr", "บ้านเลขที่"),
    ("check_typearea", "typearea"),
    ("tumbonname", "ตำบล"),
]

# (คอลัมน์, ข้อความ) — ใส่จำนวนซี่ต่อท้ายให้อัตโนมัติ
_PROBLEM_RULES = [
    ("pcaries", "ฟันแท้ผุ"), ("dcaries", "ฟันน้ำนมผุ"),
    ("pextract", "ฟันแท้ถอน/หลุด"), ("dextract", "ฟันน้ำนมถอน"),
    ("need_sealant", "ต้องเคลือบหลุมร่องฟัน"),
    ("need_pfilling", "ต้องอุดฟันแท้"), ("need_dfilling", "ต้องอุดฟันน้ำนม"),
    ("need_pextract", "ต้องถอน/รักษารากฟันแท้"), ("need_dextract", "ต้องถอนฟันน้ำนม"),
]


def problem_summary(df: pd.DataFrame) -> pd.Series:
    """สรุปเป็นข้อความว่าเด็กคนนี้มีปัญหาอะไรและต้องทำอะไรบ้าง

    ทำงานบน numpy array เหมือน fail_reasons เพื่อเลี่ยงปัญหา NaN เป็น truthy
    """
    import numpy as np

    n = len(df)
    if n == 0:
        return pd.Series([], index=df.index, dtype="string")

    parts: list[tuple[np.ndarray, list[str]]] = []
    for col, text in _PROBLEM_RULES:
        if col not in df.columns:
            continue
        v = pd.to_numeric(df[col], errors="coerce").fillna(0)
        hit = (v > 0).fillna(False).to_numpy(dtype=bool)
        if hit.any():
            labels = [f"{text} {int(x)} ซี่" for x in v.to_numpy()]
            parts.append((hit, labels))

    for col, text, yes in (("need_fluoride", "ต้องทาฟลูออไรด์", 1),
                           ("need_scaling", "ต้องขูดหินน้ำลาย", 1)):
        if col not in df.columns:
            continue
        # ต้อง fillna ก่อน to_numpy(bool) — คอลัมน์ Int64 ที่มีค่าว่างจะ raise
        hit = ((pd.to_numeric(df[col], errors="coerce") == yes)
               .fillna(False).to_numpy(dtype=bool))
        if hit.any():
            parts.append((hit, [text] * n))

    if "gum_status" in df.columns:
        g = df["gum_status"].astype("string")
        for code, text in (("1", "เหงือกมีเลือดออก"), ("2", "เหงือกอักเสบ/มีหินน้ำลาย"),
                           ("3", "ปริทันต์อักเสบ"), ("9", "ตรวจสภาวะปริทันต์ไม่ได้")):
            hit = (g == code).fillna(False).to_numpy(dtype=bool)
            if hit.any():
                parts.append((hit, [text] * n))

    texts = [" + ".join(lbl[i] for hit, lbl in parts if hit[i]) or "ไม่พบปัญหาที่ต้องตามต่อ"
             for i in range(n)]
    return pd.Series(texts, index=df.index, dtype="string")


def _label_cols(out: pd.DataFrame) -> pd.DataFrame:
    """คอลัมน์ที่ต้องแปลรหัสเป็นคำอ่านก่อนแสดง"""
    yn = {1: "ต้องทำ", 2: "ไม่ต้อง", 0: "ไม่ต้อง"}
    for col, new in (("need_fluoride", "need_fluoride_label"),
                     ("need_scaling", "need_scaling_label")):
        if col in out.columns:
            out[new] = pd.to_numeric(out[col], errors="coerce").map(yn).fillna("ไม่ระบุ")
    return out


def metric_list(profile: Profile, table_no: str, metric: str, row=None,
                pv=None, amp=None, hos=None, raw: bool = False) -> pd.DataFrame:
    """รายชื่อเด็กที่อยู่เบื้องหลังตัวเลขในตารางรายงาน (คลิกจากช่องในตาราง)

    ใช้ spec เดียวกับตอนสร้างตาราง (ตัวหาร + expr ของตัวชี้วัด)
    ตัวเลขในตารางกับจำนวนรายชื่อจึงตรงกันเสมอ
    """
    from .engine import TOTAL_LABEL, _denominator_mask, bool_mask, evaluate

    spec = next((t for t in profile.tables if str(t.no) == str(table_no)), None)
    if spec is None:
        return pd.DataFrame()

    scoped = apply_scope(filter_area(get_dataset(profile), pv, amp, hos), profile)
    sub = scoped

    # กรองตามแถวของตาราง (อายุ หรือ กลุ่มอายุ) — "รวม" = ทุกแถว
    if row not in (None, "", TOTAL_LABEL):
        if spec.rows == "age":
            try:
                sub = sub[sub["age"] == int(float(row))]
            except (TypeError, ValueError):
                pass
        elif spec.rows in ("bands", "band"):
            # แถวย่อยรายอายุ (split: true ใน profile) ส่งมาเป็นตัวเลข เช่น "4"
            if str(row).strip().isdigit():
                sub = sub[sub["age"] == int(row)]
            else:
                sub = sub[sub["band"] == str(row)]

    value_col = None
    bad_check = None
    if spec.kind == "quality":
        # metric = "ไม่ผ่าน: <ชื่อเกณฑ์>"
        name = str(metric).split(":", 1)[-1].strip()
        chk = next((c for c in profile.quality_checks if c["name"] == name), None)
        if chk is None:
            return pd.DataFrame()
        only = chk.get("bands")
        applies = (sub["band"].isin(only) if only and "band" in sub.columns
                   else pd.Series(True, index=sub.index))
        sub = sub[~bool_mask(sub, chk["expr"]) & applies]
        bad_check = chk
    else:
        m = next((x for x in spec.metrics if x.name == metric), None)
        if m is None:
            return pd.DataFrame()
        sub = sub[_denominator_mask(sub, spec, profile)]
        if spec.kind == "mean":
            # ตารางค่าเฉลี่ย: คนที่ "มี" ค่ามากกว่า 0 คือคนที่ต้องตามต่อ
            v = pd.to_numeric(evaluate(sub, m.expr), errors="coerce")
            sub = sub[(v > 0).fillna(False)]
            value_col = v.loc[sub.index]
        else:
            sub = sub[bool_mask(sub, m.expr)]

    out = _label_cols(_add_person_fields(sub.copy()))
    out["_problem"] = problem_summary(out)
    cols = list(TREATMENT_COLS)
    if bad_check is not None:
        out["_bad"] = fail_fields(out, profile, TREATMENT_COLS, checks=[bad_check])
        cols = cols + [("_bad", "_bad")]
    if value_col is not None:
        out["_value"] = value_col
        cols = [("_value", f"{metric} (ซี่)")] + cols
    if value_col is not None:
        # ตารางค่าเฉลี่ย: เรียงจากรุนแรงมากไปน้อย ให้ตามเคสหนักก่อน
        res = _select(out, cols, set(), raw)
        res = res.sort_values(res.columns[0], ascending=False).reset_index(drop=True)
    else:
        # ตารางนับจำนวน: เรียงตามหน่วยบริการ เพื่อส่งรายชื่อให้แต่ละ รพ.สต. ตามต่อ
        res = _select(out, cols, {"hoscode", "pid"}, raw)
    return _bad_first(res, after=4)


def person_column_groups(profile: Profile, result: pd.DataFrame) -> dict:
    """แบ่งคอลัมน์ของผลลัพธ์เป็น 3 กลุ่ม ให้หน้าเว็บสลับซ่อน/แสดงได้"""
    rawset = set(raw_columns(get_dataset(profile)))
    calcset = set(CALC_COLS)
    cols = list(result.columns)
    return {
        "main": [c for c in cols if c not in rawset and c not in calcset],
        "raw": [c for c in cols if c in rawset],
        "calc": [c for c in cols if c in calcset],
    }


def pending(profile: Profile, pv=None, amp=None, hos=None) -> pd.DataFrame:
    return person_list(profile, "pending", pv, amp, hos)


def eda(profile: Profile, pv=None, amp=None, hos=None) -> dict:
    """สำรวจข้อมูลเบื้องต้นในขอบเขตที่เลือก"""
    df = get_dataset(profile)
    pop = filter_area(df, pv, amp, hos)
    scoped = apply_scope(pop, profile)
    level = "unit" if (amp or hos) else "district"
    rows = by_unit(pop, profile) if (amp and not hos) else by_district(pop, profile)
    return eda_mod.build(pop, scoped, profile, rows, level,
                         dictionary(), overview_spec(profile))


def report(profile: Profile, pv=None, amp=None, hos=None, refresh=False) -> dict:
    df = get_dataset(profile, refresh=refresh)
    pop = filter_area(df, pv, amp, hos)          # ประชากรเป้าหมายในขอบเขตที่เลือก
    scoped = apply_scope(pop, profile)           # เฉพาะที่ตรวจฟันและอยู่ในช่วงอายุ

    s = summary(scoped, profile)
    s["target"] = len(pop)
    s["examined_pct"] = round(100 * len(scoped) / len(pop), 2) if len(pop) else None
    s["pending"] = int((~pop["examined"].fillna(False)).sum())
    # แถวที่ตรวจแล้วแต่อายุอยู่นอกช่วงของ profile (ไม่นับเป็นทั้งตรวจแล้วและยังไม่ตรวจ)
    s["out_of_range"] = len(pop) - len(scoped) - s["pending"]

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

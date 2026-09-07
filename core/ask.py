"""ถาม-ตอบด้วยภาษาธรรมชาติ  ("caries free ของอายุ 3 ขวบ เท่าไหร่")

หลักการสำคัญ — **AI ไม่เคยเห็นข้อมูลเด็กรายคน**
    1. เราส่งให้ AI แค่ "แคตตาล็อก" (ชื่อกลุ่มอายุ ชื่อตาราง ชื่อตัวชี้วัด) + คำถาม
    2. AI ตอบกลับเป็น "สเปกคิวรี" (JSON) ว่าผู้ใช้อยากได้ตารางไหน ตัวชี้วัดไหน แถวไหน
    3. DentalDX คำนวณเองในเครื่องจาก DataFrame (โค้ดชุดเดียวกับที่สร้างตารางรายงาน)
    4. ส่งเฉพาะ "ตัวเลขสรุป" กลับไปให้ AI เรียบเรียงเป็นประโยคภาษาไทย

    ข้อมูลที่ออกจากเครื่องมีแค่: คำถามของผู้ใช้, ชื่อคอลัมน์/ตัวชี้วัด, และตัวเลขสรุป
    ไม่มีชื่อ ไม่มีเลขบัตร ไม่มีแถวรายบุคคล

ถ้าไม่ได้ตั้งค่า API key ก็ยังใช้งานได้ — จะถอยไปใช้ตัวแปลคำถามแบบคีย์เวิร์ด
(`_rule_plan`) ซึ่งครอบคลุมคำถามที่พบบ่อยและใช้ทดสอบแบบ offline ได้
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

import pandas as pd

from . import profiles as prof_mod
from . import service
from .engine import (Profile, TableSpec, TOTAL_LABEL, apply_scope, bool_mask,
                     evaluate, quality_mask)

# --------------------------------------------------------------------------- #
# ตั้งค่า AI  (ai.yaml ข้าง exe  หรือ environment variable)
# --------------------------------------------------------------------------- #

DEFAULTS = {
    "provider": "off",              # anthropic | openai | gemini | ollama | off
    "model": "claude-sonnet-4-5",
    "api_key": "",
    "base_url": "",
    "timeout": 60,
    "phrase": True,                 # ให้ AI เรียบเรียงประโยคตอบด้วยหรือไม่
    "confirm": True,                # โชว์สิ่งที่จะส่งออกแล้วรอผู้ใช้กดยืนยันก่อน
}

_config_cache: dict | None = None


def config(refresh: bool = False) -> dict:
    """อ่าน ai.yaml (ถ้ามี) แล้วทับด้วย environment variable"""
    global _config_cache
    if _config_cache is not None and not refresh:
        return _config_cache

    cfg = dict(DEFAULTS)
    path = config_path()          # ต้องเป็นไฟล์เดียวกับที่ save_config เขียน
    if os.path.exists(path):
        try:
            import yaml
            with open(path, encoding="utf-8") as fh:
                cfg.update({k: v for k, v in (yaml.safe_load(fh) or {}).items()
                            if v not in (None, "")})
        except Exception:
            pass

    env = {
        "provider": os.environ.get("DENTALDX_AI_PROVIDER"),
        "model": os.environ.get("DENTALDX_AI_MODEL"),
        "api_key": os.environ.get("DENTALDX_AI_KEY"),
        "base_url": os.environ.get("DENTALDX_AI_URL"),
    }
    cfg.update({k: v for k, v in env.items() if v})
    cfg["timeout"] = int(cfg.get("timeout") or 60)

    _config_cache = cfg
    return cfg


def needs_key(provider: str) -> bool:
    """ollama รันในเครื่อง ไม่ต้องมีกุญแจ"""
    return str(provider or "") not in ("off", "", "ollama")


def ai_enabled() -> bool:
    """ตั้ง provider ไว้แล้วแต่ยังไม่ได้ใส่กุญแจ = ยังใช้ AI ไม่ได้

    (ไม่ไปแก้ค่า provider ทิ้ง เพื่อให้หน้าตั้งค่ายังโชว์สิ่งที่ผู้ใช้เลือกไว้)
    """
    cfg = config()
    p = cfg.get("provider")
    if p in (None, "", "off"):
        return False
    return bool(cfg.get("api_key")) or not needs_key(p)


def config_path() -> str:
    return os.environ.get("DENTALDX_AI_CONFIG",
                          os.path.join(prof_mod.app_root(), "ai.yaml"))


# ค่าที่ให้แก้จากหน้าเว็บได้ (ตัวอื่นต้องแก้ไฟล์เอง เพื่อกันการตั้งค่าหลุด)
EDITABLE = ("provider", "model", "api_key", "base_url", "phrase", "confirm", "timeout")


def save_config(patch: dict) -> dict:
    """บันทึกลง ai.yaml — ค่าที่ไม่ได้ส่งมาจะคงของเดิมไว้

    api_key ที่เป็นสตริงว่างแปลว่า "ไม่เปลี่ยน" ไม่ใช่ "ลบ"
    (หน้าเว็บไม่เคยได้กุญแจตัวจริงกลับไป จึงส่งค่าว่างมาเวลาไม่ได้แก้)
    """
    import yaml
    path = config_path()
    cur = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cur = yaml.safe_load(fh) or {}
        except Exception:
            cur = {}

    for k in EDITABLE:
        if k not in patch:
            continue
        v = patch[k]
        if k == "api_key":
            if str(v or "").strip():
                cur[k] = str(v).strip()
            continue
        if k in ("phrase", "confirm"):
            cur[k] = bool(v)
        elif k == "timeout":
            cur[k] = max(5, min(600, int(v or 60)))
        else:
            cur[k] = str(v or "").strip()

    if str(patch.get("clear_key") or "") == "1":
        cur.pop("api_key", None)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# ตั้งค่า AI ของแท็บถาม-ตอบ — แก้ผ่านหน้าเว็บหรือแก้ไฟล์นี้ก็ได้\n")
        fh.write("# ห้าม commit ไฟล์นี้ (มี api_key) — .gitignore กันไว้แล้ว\n")
        yaml.safe_dump(cur, fh, allow_unicode=True, sort_keys=False)
    return config(refresh=True)


def public_config() -> dict:
    """ค่าตั้งสำหรับส่งให้หน้าเว็บ — ไม่มีกุญแจตัวจริง"""
    cfg = config(refresh=True)
    env_key = bool(os.environ.get("DENTALDX_AI_KEY"))
    return {
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "base_url": cfg.get("base_url") or "",
        "phrase": bool(cfg.get("phrase", True)),
        "confirm": bool(cfg.get("confirm", True)),
        "timeout": cfg.get("timeout", 60),
        "enabled": ai_enabled(),
        "needs_key": needs_key(cfg.get("provider")),
        "has_key": bool(cfg.get("api_key")),
        "key_hint": _mask(cfg.get("api_key")) if cfg.get("api_key") else "",
        "key_from_env": env_key,
        "config_file": config_path(),
        "config_exists": os.path.exists(config_path()),
    }


# --------------------------------------------------------------------------- #
# รายชื่อโมเดล
# --------------------------------------------------------------------------- #

PROVIDERS = [
    {"id": "off", "label": "ไม่ใช้ AI (คีย์เวิร์ดในเครื่อง)", "needs_key": False,
     "local": True,
     "note": "ไม่มีข้อมูลออกจากเครื่องเลย · ถามสั้น ๆ ตรง ๆ"},
    {"id": "anthropic", "label": "Anthropic (Claude)", "needs_key": True,
     "local": False, "note": "haiku ถูกและเร็วพอสำหรับงานนี้"},
    {"id": "openai", "label": "OpenAI", "needs_key": True, "local": False, "note": ""},
    {"id": "gemini", "label": "Google Gemini", "needs_key": True, "local": False,
     "note": "free tier: Google อาจนำ prompt ไปพัฒนาผลิตภัณฑ์และมีคนอ่าน"},
    {"id": "ollama", "label": "Ollama (โมเดลในเครื่อง)", "needs_key": False,
     "local": True, "note": "ไม่ต้องต่อเน็ต ไม่มีค่าใช้จ่าย · ต้องลง Ollama ก่อน"},
]

# รายชื่อสำรอง ใช้เฉพาะตอนดึงจากปลายทางไม่ได้ (ยังไม่ใส่กุญแจ / เน็ตล่ม)
#
# ⚠ รายชื่อนี้ล้าสมัยได้ตลอด — ผู้ให้บริการปลดระวางโมเดลเก่าเรื่อย ๆ
#   ถ้าเลือกโมเดลที่ถูกปลดระวางไปแล้วจะได้ HTTP 404 ตอนใช้งาน
#   ทางที่ถูกคือกดปุ่ม ↻ ให้ list_models() ไปถามปลายทางว่ามีอะไรให้ใช้จริง
KNOWN_MODELS = {
    "anthropic": ["claude-haiku-4-5", "claude-sonnet-4-5"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "ollama": ["llama3.1", "qwen2.5", "gemma2"],
}


def _remote_models(provider: str, cfg: dict) -> list[str]:
    """ถามปลายทางว่ากุญแจใบนี้ใช้โมเดลอะไรได้บ้าง

    สำคัญกว่าที่คิด — รายชื่อที่ hardcode ไว้ล้าสมัยได้ตลอด พอโมเดลถูกปลดระวาง
    จะได้ HTTP 404 ซึ่งผู้ใช้เดาสาเหตุไม่ถูกเลย
    """
    key = cfg.get("api_key") or ""
    timeout = min(int(cfg.get("timeout") or 60), 15)

    if provider == "gemini":
        base = (cfg.get("base_url")
                or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        data = _http(f"{base}/models?key={key}&pageSize=200", None, {}, timeout)
        out = []
        for m in data.get("models", []):
            name = str(m.get("name", "")).replace("models/", "")
            # เอาเฉพาะรุ่นที่ตอบคำถามได้ (บางรุ่นทำ embedding อย่างเดียว)
            if name and "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append(name)
        return out

    if provider == "openai":
        base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        data = _http(f"{base}/models", None, {"Authorization": f"Bearer {key}"}, timeout)
        return [m["id"] for m in data.get("data", []) if m.get("id")]

    if provider == "anthropic":
        base = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        data = _http(f"{base}/v1/models?limit=100", None,
                     {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
        return [m["id"] for m in data.get("data", []) if m.get("id")]

    if provider == "ollama":
        base = (cfg.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        data = _http(f"{base}/api/tags", None, {}, timeout)
        return [m["name"] for m in data.get("models", []) if m.get("name")]

    return []


def list_models(provider: str, base_url: str = "", api_key: str = "") -> dict:
    """รายชื่อโมเดลให้เลือก — ถามจากปลายทางจริงก่อน ถ้าไม่ได้ค่อยใช้รายชื่อสำรอง"""
    provider = str(provider or "").strip()
    out = {"models": list(KNOWN_MODELS.get(provider, [])), "live": False, "error": ""}
    if provider in ("", "off"):
        out["models"] = []
        return out

    cfg = effective_config({"provider": provider, "base_url": base_url,
                            "api_key": api_key})
    if needs_key(provider) and not cfg.get("api_key"):
        out["error"] = "ใส่ API key แล้วกด ↻ เพื่อดึงรายชื่อโมเดลที่ใช้ได้จริง"
        return out
    try:
        names = _remote_models(provider, cfg)
        if names:
            out["models"] = sorted(set(names))
            out["live"] = True
        else:
            out["error"] = "ปลายทางไม่ได้ส่งรายชื่อโมเดลมา — ใช้รายชื่อสำรองไปก่อน"
    except Exception as e:
        if provider == "ollama":
            base = cfg.get("base_url") or "http://127.0.0.1:11434"
            out["error"] = f"ต่อ Ollama ที่ {base} ไม่ได้ — เปิดโปรแกรม Ollama ไว้หรือยัง"
        else:
            detail = str(e) if isinstance(e, ApiError) else f"{type(e).__name__}: {e}"
            out["error"] = f"ดึงรายชื่อโมเดลไม่ได้ — {detail}"
    return out


def effective_config(patch: dict | None = None) -> dict:
    """ค่าตั้งที่บันทึกไว้ + ค่าที่ผู้ใช้กำลังกรอกอยู่บนหน้าจอ (ยังไม่บันทึก)

    ใช้กับปุ่ม "ทดสอบการเชื่อมต่อ" — ต้องทดสอบสิ่งที่เห็นตรงหน้า ไม่ใช่ของเก่า
    """
    cfg = dict(config())
    if not patch:
        return cfg
    for k in ("provider", "model", "base_url"):
        if str(patch.get(k) or "").strip():
            cfg[k] = str(patch[k]).strip()
    # ช่องกุญแจว่าง = ไม่ได้แก้ ให้ใช้ของที่บันทึกไว้
    if str(patch.get("api_key") or "").strip():
        cfg["api_key"] = str(patch["api_key"]).strip()
    return cfg


def test_connection(patch: dict | None = None) -> dict:
    """ยิงคำถามสั้น ๆ จริงเพื่อดูว่าตั้งค่าถูกไหม (ไม่บันทึกค่าใด ๆ)"""
    cfg = effective_config(patch)
    provider = cfg.get("provider")
    if provider in (None, "", "off"):
        return {"ok": True, "text": "โหมดไม่ใช้ AI — ไม่ต้องต่ออะไร"}
    if needs_key(provider) and not cfg.get("api_key"):
        return {"ok": False, "text": f"ยังไม่ได้ใส่ API key ของ {provider}"}
    if not cfg.get("model"):
        return {"ok": False, "text": "ยังไม่ได้เลือกโมเดล"}
    try:
        req = build_request("ตอบกลับด้วยคำว่า OK คำเดียว", "ping", cfg)
        txt = send_request(req, "ทดสอบการเชื่อมต่อ")
        return {"ok": True, "provider": provider, "model": cfg.get("model"),
                "text": (txt or "").strip()[:120] or "(ตอบกลับว่าง)"}
    except ApiError as e:
        # ข้อความอ่านรู้เรื่องอยู่แล้ว ไม่ต้องเอาชื่อคลาสไปรกหน้าจอ
        return {"ok": False, "provider": provider, "model": cfg.get("model"),
                "text": str(e)}
    except Exception as e:
        return {"ok": False, "provider": provider, "model": cfg.get("model"),
                "text": f"ต่อไม่ได้: {type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- #
# แคตตาล็อก — สิ่งเดียวที่ AI ได้เห็นเกี่ยวกับข้อมูล (ไม่มีข้อมูลรายบุคคล)
# --------------------------------------------------------------------------- #

QUALITY_METRICS = ["จำนวนที่ตรวจ", "จำนวนที่ผ่านเกณฑ์คุณภาพ"]


def _row_labels(p: Profile) -> list[str]:
    """ค่าที่ใส่ในช่อง rows ได้: ชื่อช่วงอายุ, อายุรายปี, และ 'รวม'"""
    out = [b.label for b in p.bands]
    out += [str(a) for a in range(p.age_min, p.age_max + 1)]
    return out + [TOTAL_LABEL]


def catalog(profiles: dict[str, Profile]) -> dict:
    """โครงสร้างที่ส่งให้ AI อ่าน — มีแต่ชื่อ ไม่มีตัวเลขและไม่มีข้อมูลเด็ก"""
    out = []
    for p in sorted(profiles.values(), key=lambda x: x.age_min):
        tables = []
        for t in p.tables:
            names = (QUALITY_METRICS if t.kind == "quality"
                     else [m.name for m in t.metrics])
            tables.append({"no": t.no, "title": t.title, "kind": t.kind,
                           "metrics": names})
        out.append({
            "profile": p.id,
            "label": p.label,
            "age_min": p.age_min,
            "age_max": p.age_max,
            "rows": _row_labels(p),
            "tables": tables,
        })
    return {"profiles": out}


# --------------------------------------------------------------------------- #
# ตัวช่วยจับคู่ข้อความ
# --------------------------------------------------------------------------- #

_STRIP = ("จังหวัด", "อำเภอ", "ตำบล", "โรงพยาบาลส่งเสริมสุขภาพตำบล",
          "โรงพยาบาล", "รพ.สต.", "รพ.สต", "รพสต", "รพ.", "อ.", "จ.", "ต.")


def _norm(s) -> str:
    s = str(s or "").strip().lower()
    for w in _STRIP:
        s = s.replace(w.lower(), "")
    return re.sub(r"[\s\-_.]", "", s)


def _best(text: str, choices: list[str]) -> str | None:
    """หาตัวเลือกที่ชื่อโผล่อยู่ในข้อความ — เอาตัวที่ยาวที่สุด (เจาะจงที่สุด)"""
    t = _norm(text)
    if not t:
        return None
    hits = [c for c in choices if _norm(c) and _norm(c) in t]
    return max(hits, key=lambda c: len(_norm(c))) if hits else None


# ข้อความที่ตามหลังคำบอกประเภทพื้นที่ = ชื่อพื้นที่ที่ผู้ใช้ตั้งใจพิมพ์
_AREA_TERM = re.compile(
    r"(?:จังหวัด|อำเภอ|ตำบล|จ\.|อ\.|ต\.|รพ\.สต\.?|รพสต|โรงพยาบาล|รพ\.)\s*([ก-๙A-Za-z]+)")


class Ambiguous(ValueError):
    """ชื่อที่พิมพ์มาตรงกับหลายพื้นที่ — ต้องให้ผู้ใช้เลือก ไม่ใช่เดาเอง"""


def _best_prefix(text: str, choices: list[str], kind: str) -> str | None:
    """เผื่อผู้ใช้พิมพ์ชื่อไม่เต็ม เช่น "อำเภอเมือง" -> "เมืองชัยภูมิ"

    ตรงหลายตัว = ไม่เดา แต่ถามกลับ (เงียบ ๆ แล้วตอบเป็นภาพรวมคืออันตรายกว่า)
    """
    for term in _AREA_TERM.findall(text):
        t = _norm(term)
        if len(t) < 3:
            continue
        # ผู้ใช้พิมพ์ยาวเกินชื่อจริง (ติดคำอื่นมาด้วย) -> เอาชื่อที่เป็นต้นของ term
        inside = [c for c in choices if _norm(c) and t.startswith(_norm(c))]
        if inside:
            return max(inside, key=lambda c: len(_norm(c)))
        hits = [c for c in choices if _norm(c).startswith(t)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise Ambiguous(
                f"มี{kind}ที่ขึ้นต้นด้วย “{term}” หลายแห่ง: "
                + " · ".join(sorted(hits)[:6])
                + (" …" if len(hits) > 6 else "") + " — ช่วยพิมพ์ชื่อให้ครบหน่อยครับ")
    return None


# ---------------------------------------------------------------------------
# เลขไทยที่เขียนเป็นตัวหนังสือ ("สามขวบ" -> "3 ขวบ")
# แทนเฉพาะที่ตามด้วย ขวบ/ปี เท่านั้น ไม่งั้น "สามารถ" จะกลายเป็น "3ารถ"
# ---------------------------------------------------------------------------
_THAI_NUM = {"หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6,
             "เจ็ด": 7, "แปด": 8, "เก้า": 9, "สิบ": 10, "สิบเอ็ด": 11, "สิบสอง": 12}
_THAI_AGE = re.compile("(" + "|".join(sorted(_THAI_NUM, key=len, reverse=True))
                       + r")\s*(ขวบ|ปี)")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def normalize_numbers(text: str) -> str:
    """แปลงเลขไทยและเลขที่เขียนเป็นตัวหนังสือให้เป็นตัวเลขอารบิก"""
    s = str(text or "").translate(_THAI_DIGITS)
    return _THAI_AGE.sub(lambda m: f"{_THAI_NUM[m.group(1)]} {m.group(2)}", s)


# คำที่บอกว่าผู้ใช้หมายถึง "หน่วยบริการ" ไม่ใช่ "อำเภอ"
_HOS_WORDS = ("รพ.สต", "รพสต", "โรงพยาบาล", "รพ.", "สถานีอนามัย", "หน่วยบริการ", "สอ.")
_AMP_WORDS = ("อำเภอ", "อ.")


def resolve_area(text: str, tree: dict) -> dict:
    """แปลงข้อความพื้นที่เป็น {pv, amp, hos, hos_name} เทียบกับพื้นที่ที่มีจริง

    ชื่ออำเภอกับชื่อโรงพยาบาลมักซ้ำกัน ("อำเภอเกษตรสมบูรณ์" กับ
    "โรงพยาบาลเกษตรสมบูรณ์") จึงต้องดูคำนำหน้าที่ผู้ใช้พิมพ์เป็นตัวตัดสิน
    """
    scope = {"pv": None, "amp": None, "hos": None, "hos_name": None}
    if not text:
        return scope
    amps = {a: p for p in tree for a in tree[p]}
    hoses = {h["name"]: (p, a, h["code"])
             for p in tree for a in tree[p] for h in tree[p][a]}
    said_hos = any(w in text for w in _HOS_WORDS)

    pv = _best(text, list(tree.keys()))
    amp = _best(text, list(amps.keys()))
    hos = _best(text, list(hoses.keys()))

    # พิมพ์ชื่อไม่เต็ม เช่น "อ.เมือง" -> เทียบแบบขึ้นต้น
    if not amp and not said_hos:
        amp = _best_prefix(text, list(amps.keys()), "อำเภอ")
    if not hos and said_hos:
        hos = _best_prefix(text, list(hoses.keys()), "หน่วยบริการ")
    if not pv:
        pv = _best_prefix(text, list(tree.keys()), "จังหวัด")

    if hos and amp:
        said_amp = any(w in text for w in _AMP_WORDS)
        # พิมพ์ "อำเภอ" มาแต่ไม่ได้พิมพ์คำที่แปลว่าโรงพยาบาล -> เอาอำเภอ
        if said_amp and not said_hos:
            hos = None
        elif not said_hos and len(_norm(hos)) <= len(_norm(amp)):
            hos = None

    if hos:
        p, a, code = hoses[hos]
        return {"pv": p, "amp": a, "hos": code, "hos_name": hos}
    if amp:
        return {"pv": amps[amp], "amp": amp, "hos": None, "hos_name": None}
    if pv:
        scope["pv"] = pv
    return scope


# --------------------------------------------------------------------------- #
# ตัวแปลคำถามแบบคีย์เวิร์ด (ใช้เมื่อไม่มี API key และใช้ทดสอบ offline)
# --------------------------------------------------------------------------- #

# คำที่ผู้ใช้มักพิมพ์ -> ชื่อตัวชี้วัดในตาราง
ALIASES = {
    "ปราศจากฟันผุ": ["caries free", "cariesfree", "ปราศจากฟันผุ", "ฟันไม่ผุ",
                     "ไม่มีฟันผุ", "ปลอดฟันผุ"],
    # "ฟันดี" เฉย ๆ กำกวมระหว่าง 2 ตัวชี้วัด — เลือกตัวที่ชื่อขึ้นต้นด้วยคำนี้
    # ถ้าหน่วยงานใช้คำนี้แทน "ปราศจากฟันผุ" ให้ย้ายบรรทัด "ฟันดี" ขึ้นไปข้างบน
    "ฟันดีไม่มีผุ": ["ฟันดีไม่มีผุ", "ฟันดี", "cavity free", "cavityfree"],
    "ฟันผุไม่ได้รักษา": ["ฟันผุไม่ได้รักษา", "ผุไม่ได้รักษา", "untreated"],
    "ฟันผุถอนอุด": ["ฟันผุถอนอุด", "dmft", "dmf"],
    "ฟันถอน": ["ฟันถอน", "ถอนฟัน"],
    "ฟันอุด": ["ฟันอุด", "อุดฟัน"],
    "จำนวนที่ผ่านเกณฑ์คุณภาพ": ["ผ่านเกณฑ์", "คุณภาพข้อมูล", "quality"],
    "จำนวนที่ตรวจ": ["ได้รับการตรวจ", "ตรวจฟัน", "ความครอบคลุม", "coverage"],
    "ทาฟลูออไรด์": ["ฟลูออไรด์", "fluoride"],
    "เคลือบหลุมร่องฟัน": ["เคลือบหลุมร่องฟัน", "sealant"],
}


MEAN_WORDS = ["เฉลี่ย", "ค่าเฉลี่ย", "average", "mean", "ซี่ต่อคน", "ต่อคน"]


def _find_metric(text: str, profiles: dict[str, Profile], pid: str):
    """คืน (table_no, metric_name) ที่ตรงกับคำถามมากที่สุด

    ชื่อตัวชี้วัดเดียวกันอยู่ได้หลายตาราง (เช่น "ฟันผุถอนอุด" มีทั้งตารางร้อยละ
    และตารางค่าเฉลี่ย) — ถ้าคำถามมีคำว่า "เฉลี่ย" ให้เลือกตารางค่าเฉลี่ยก่อน
    """
    p = profiles[pid]
    t = _norm(text)
    want_mean = any(_norm(w) in t for w in MEAN_WORDS)
    order = sorted(p.tables, key=lambda s: (s.kind != "mean") if want_mean
                   else (s.kind == "mean"))

    # 1) ชื่อตัวชี้วัดตรง ๆ ที่โผล่ในคำถาม
    best = None
    for spec in order:
        names = QUALITY_METRICS if spec.kind == "quality" else [m.name for m in spec.metrics]
        for name in names:
            if _norm(name) and _norm(name) in t:
                if best is None or len(_norm(name)) > len(_norm(best[1])):
                    best = (spec.no, name)
    if best:
        return best

    # 2) คำพ้อง
    for canonical, words in ALIASES.items():
        if any(_norm(w) in t for w in words):
            for spec in order:
                names = (QUALITY_METRICS if spec.kind == "quality"
                         else [m.name for m in spec.metrics])
                if canonical in names:
                    return spec.no, canonical
    return None, None


_AGE_PAT = re.compile(r"(\d+)\s*(?:-\s*(\d+))?\s*(?:ขวบ|ปี|y|yr|year)")


def _find_rows(text: str, p: Profile) -> list[str]:
    """หาแถวที่ถาม — ถ้าจับไม่ได้หรือช่วงที่ถามคือทั้ง profile ให้ใช้ 'รวม'"""
    labels = _row_labels(p)
    m = _AGE_PAT.search(normalize_numbers(text))
    if m:
        lo, hi = m.group(1), m.group(2)
        if hi:
            band = f"{lo}-{hi}"
            if band in labels:
                return [band]
            # "6-12 ปี" ในกลุ่ม 6-12 ปี = ทั้งกลุ่ม ไม่ใช่แถวย่อย
            if int(lo) <= p.age_min and int(hi) >= p.age_max:
                return [TOTAL_LABEL]
            return [str(a) for a in range(int(lo), int(hi) + 1) if str(a) in labels] \
                or [TOTAL_LABEL]
        return [lo] if lo in labels else [TOTAL_LABEL]
    return [TOTAL_LABEL]


def _find_profile(text: str, profiles: dict[str, Profile]) -> str:
    """เดากลุ่มอายุจากตัวเลขอายุในคำถาม ถ้าไม่มีก็เอากลุ่มแรก"""
    ids = sorted(profiles, key=lambda i: profiles[i].age_min)
    m = _AGE_PAT.search(normalize_numbers(text))
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        for pid in ids:
            p = profiles[pid]
            if p.age_min <= lo and hi <= p.age_max:
                return pid
    for pid in ids:
        if _norm(profiles[pid].label) in _norm(text) or pid in text:
            return pid
    return ids[0] if ids else ""


_GROUP_WORDS = {
    "district": ["รายอำเภอ", "แต่ละอำเภอ", "ทุกอำเภอ", "เทียบอำเภอ", "อำเภอไหน"],
    "unit": ["รายหน่วย", "รายรพ", "แต่ละหน่วย", "แต่ละรพ", "ทุกหน่วย",
             "หน่วยไหน", "รพ.สต.ไหน", "โรงพยาบาลไหน"],
}


def _rule_plan(question: str, profiles: dict[str, Profile]) -> dict:
    pid = _find_profile(question, profiles)
    if not pid:
        raise ValueError("ยังไม่มี profile กลุ่มอายุในระบบ")
    table, metric = _find_metric(question, profiles, pid)
    group_by = None
    t = _norm(question)
    for g, words in _GROUP_WORDS.items():
        if any(_norm(w) in t for w in words):
            group_by = g
            break
    return {
        "profile": pid,
        "area": question,          # ให้ resolve_area ไปหาชื่อพื้นที่เอง
        "table": table,
        "metric": metric,
        "rows": _find_rows(question, profiles[pid]),
        "group_by": group_by,
        "limit": 10,
        "sort": "asc" if any(w in t for w in (_norm("น้อยที่สุด"), _norm("ต่ำสุด"),
                                              _norm("แย่สุด"))) else "desc",
    }


# --------------------------------------------------------------------------- #
# เรียก LLM
# --------------------------------------------------------------------------- #

PLAN_SYSTEM = """คุณเป็นตัวแปลคำถามภาษาไทยให้เป็นสเปกคิวรีของโปรแกรม DentalDX
(รายงานสภาวะทันตสุขภาพเด็กจาก HDC)

ตอบกลับเป็น JSON อย่างเดียว ห้ามมีข้อความอื่น รูปแบบ:
{
  "profile": "<id ของกลุ่มอายุจากแคตตาล็อก>",
  "table": "<เลขตาราง>",
  "metric": "<ชื่อตัวชี้วัด ต้องตรงกับในแคตตาล็อกทุกตัวอักษร>",
  "rows": ["<ค่าจาก rows ของ profile นั้น เช่น \\"3\\" หรือ \\"3-5\\" หรือ \\"รวม\\">"],
  "area": "<ข้อความชื่อพื้นที่ที่ผู้ใช้พูดถึง ถ้าไม่ระบุให้เป็นสตริงว่าง>",
  "group_by": null | "district" | "unit",
  "sort": "desc" | "asc",
  "limit": 10
}

กติกา
- ห้ามคิดชื่อตัวชี้วัดหรือเลขตารางขึ้นเอง ต้องเลือกจากแคตตาล็อกเท่านั้น
- "caries free" = "ปราศจากฟันผุ"
- ถามอายุเป็นรายปี เช่น "3 ขวบ" -> rows = ["3"]
- ถามช่วง เช่น "3-5 ปี" -> rows = ["3-5"]
- ไม่ระบุอายุ -> rows = ["รวม"]
- ถามว่า "อำเภอไหน/รายอำเภอ" -> group_by = "district"
- ถามว่า "รพ.สต.ไหน/รายหน่วย" -> group_by = "unit"
- ถ้าคำถามไม่เกี่ยวกับข้อมูลในแคตตาล็อก ให้ตอบ {"error": "อธิบายสั้น ๆ"}"""

PHRASE_SYSTEM = """คุณเป็นผู้ช่วยสรุปผลรายงานทันตสุขภาพ
ผู้ใช้ถามคำถาม และระบบคำนวณตัวเลขมาให้แล้ว (JSON)
เขียนคำตอบภาษาไทย 1-3 ประโยค กระชับ อ้างตัวเลขให้ตรงกับ JSON เป๊ะ ๆ
ห้ามคิดตัวเลขเพิ่มเอง ห้ามคาดเดาสิ่งที่ไม่มีใน JSON
ถ้าฐาน (base) น้อยกว่า 30 ให้เตือนว่าจำนวนตัวอย่างน้อย ตีความอย่างระวัง"""


class ApiError(urllib.error.URLError):
    """ปลายทางตอบกลับมาว่าผิดพลาด — สืบทอดจาก URLError เพื่อให้ยังถอยไปใช้
    ตัวแปลคีย์เวิร์ดได้เหมือนกรณีเน็ตล่ม"""

    def __init__(self, msg: str):
        self.reason = msg
        super().__init__(msg)

    def __str__(self) -> str:
        return str(self.reason)


# คำแปลรหัส HTTP ที่เจอบ่อย — ให้ผู้ใช้รู้ว่าต้องไปแก้ตรงไหน
_HTTP_HINT = {
    400: "คำขอไม่ถูกต้อง — ชื่อโมเดลหรือค่าตั้งอาจผิด",
    401: "กุญแจไม่ถูกต้องหรือหมดอายุ — ตรวจ API key อีกครั้ง",
    403: "กุญแจนี้ไม่มีสิทธิ์ใช้บริการ/โมเดลนี้",
    404: "ไม่พบโมเดลนี้ที่ปลายทาง — กดปุ่ม ↻ ข้างช่องโมเดล "
         "เพื่อดึงรายชื่อโมเดลที่กุญแจของคุณใช้ได้จริง",
    429: "ใช้เกินโควตาที่กำหนด — รอสักครู่แล้วลองใหม่",
    500: "ฝั่งผู้ให้บริการขัดข้อง ลองใหม่อีกครั้ง",
    503: "ฝั่งผู้ให้บริการไม่ว่าง ลองใหม่อีกครั้ง",
}


def _http(url: str, payload: dict | None, headers: dict, timeout: int) -> dict:
    """เรียก HTTP แล้วแปลง error ให้อ่านรู้เรื่อง (ตัวปลายทางมักบอกสาเหตุมาใน body)"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
            elif err:
                detail = str(err)
        except Exception:
            pass
        hint = _HTTP_HINT.get(e.code, "")
        parts = [f"HTTP {e.code}"]
        if hint:
            parts.append(hint)
        if detail:
            parts.append(f"({detail[:200]})")
        raise ApiError(" · ".join(parts)) from None


def _http_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    return _http(url, payload, headers, timeout)


def _mask(key: str) -> str:
    """โชว์กุญแจแบบปิดบัง — ให้ผู้ใช้ยืนยันว่าใช้กุญแจถูกใบ แต่ไม่เห็นตัวจริง"""
    k = str(key or "")
    return f"{k[:6]}…{k[-4:]}" if len(k) > 12 else ("(ตั้งไว้แล้ว)" if k else "(ไม่มี)")


def build_request(system: str, user: str, cfg: dict | None = None) -> dict:
    """เตรียมคำขอ **โดยยังไม่ส่ง** — เอาไว้โชว์ให้ผู้ใช้ตรวจก่อนกดยืนยัน

    คืน dict ที่มี url/payload จริงที่จะถูกส่ง และ 'display' สำหรับโชว์บนหน้าจอ
    (กุญแจถูกปิดบังใน display แต่ตัวจริงอยู่ใน url/headers ที่ไม่ได้ส่งให้หน้าเว็บ)
    """
    cfg = cfg or config()
    provider = cfg["provider"]

    if provider == "anthropic":
        url = (cfg.get("base_url") or "https://api.anthropic.com") + "/v1/messages"
        payload = {"model": cfg["model"], "max_tokens": 1024, "system": system,
                   "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"}
        pick = lambda d: "".join(b.get("text", "") for b in d.get("content", []))
    elif provider == "openai":
        url = (cfg.get("base_url") or "https://api.openai.com/v1") + "/chat/completions"
        payload = {"model": cfg["model"],
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        headers = {"Authorization": f"Bearer {cfg['api_key']}"}
        pick = lambda d: d["choices"][0]["message"]["content"]
    elif provider == "gemini":
        base = cfg.get("base_url") or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base}/models/{cfg['model']}:generateContent?key={cfg['api_key']}"
        payload = {"system_instruction": {"parts": [{"text": system}]},
                   "contents": [{"parts": [{"text": user}]}],
                   "generationConfig": {"temperature": 0}}
        headers = {}
        pick = lambda d: "".join(p.get("text", "")
                                 for p in d["candidates"][0]["content"]["parts"])
    elif provider == "ollama":
        url = (cfg.get("base_url") or "http://127.0.0.1:11434") + "/api/chat"
        payload = {"model": cfg["model"], "stream": False,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        headers = {}
        pick = lambda d: d["message"]["content"]
    else:
        raise RuntimeError("ยังไม่ได้ตั้งค่า AI (ดู ai.yaml)")

    body = json.dumps(payload, ensure_ascii=False)
    # url ที่โชว์ต้องไม่มีกุญแจ (gemini แนบกุญแจมากับ query string)
    shown_url = re.sub(r"key=[^&]+", "key=" + _mask(cfg.get("api_key")), url)
    return {
        "url": url, "payload": payload, "headers": headers, "pick": pick,
        "timeout": cfg["timeout"],
        "display": {
            "provider": provider,
            "model": cfg.get("model"),
            "endpoint": shown_url,
            "local": provider == "ollama",   # ollama = ในเครื่อง ไม่ออกเน็ต
            "api_key": _mask(cfg.get("api_key")),
            "system": system,
            "user": user,
            "body": body,
            "bytes": len(body.encode("utf-8")),
        },
    }


# ประวัติสิ่งที่ "ส่งออกไปแล้วจริง ๆ" ในรอบการทำงานนี้ (เก็บในหน่วยความจำเท่านั้น)
OUTBOX: list[dict] = []
OUTBOX_MAX = 50


def send_request(req: dict, step: str) -> str:
    """ส่งจริง — เรียกเมื่อผู้ใช้กดยืนยันแล้วเท่านั้น"""
    import time
    started = time.time()
    entry = {"time": time.strftime("%H:%M:%S"), "step": step,
             **{k: req["display"][k] for k in
                ("provider", "model", "endpoint", "local", "bytes", "body")}}
    try:
        data = _http_json(req["url"], req["payload"], req["headers"], req["timeout"])
        out = req["pick"](data)
        entry["ok"] = True
    except Exception as e:
        entry["ok"] = False
        entry["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        entry["ms"] = int((time.time() - started) * 1000)
        OUTBOX.insert(0, entry)
        del OUTBOX[OUTBOX_MAX:]
    return out


def llm(system: str, user: str, cfg: dict | None = None, step: str = "-") -> str:
    """เตรียม + ส่งในขั้นตอนเดียว (ใช้เมื่อไม่ต้องให้ผู้ใช้ยืนยัน)"""
    return send_request(build_request(system, user, cfg), step)


def _json_from(text: str) -> dict:
    """โมเดลชอบห่อ JSON ด้วย ```json ... ``` หรือมีคำนำ — ดึงเฉพาะก้อน JSON"""
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"AI ไม่ได้ตอบเป็น JSON: {text[:200]}")
    return json.loads(m.group(0))


def plan_user_text(question: str, profiles: dict[str, Profile]) -> str:
    """ข้อความที่จะถูกส่งไปกับคำขอแปลคำถาม — ตรวจดูได้ก่อนส่ง

    เขียนแบบกระชับ (ไม่ใส่ indent) เพราะทุกตัวอักษรคือ token ที่ต้องจ่าย
    หน้าเว็บมีปุ่มจัดรูปแบบให้อ่านง่ายอยู่แล้ว
    """
    return json.dumps({"catalog": catalog(profiles), "question": question},
                      ensure_ascii=False)


def plan_request(question: str, profiles: dict[str, Profile]) -> dict | None:
    """คำขอ 'แปลคำถาม' ที่เตรียมไว้ (ยังไม่ส่ง) — None ถ้าไม่ได้ใช้ AI"""
    if not ai_enabled():
        return None
    return build_request(PLAN_SYSTEM, plan_user_text(question, profiles))


def plan(question: str, profiles: dict[str, Profile], req: dict | None = None) -> dict:
    """แปลคำถามเป็นสเปกคิวรี — ใช้ AI ถ้าตั้งค่าไว้ ไม่งั้นใช้คีย์เวิร์ด

    ส่ง req ที่ผู้ใช้ยืนยันแล้วเข้ามาได้ เพื่อให้สิ่งที่ส่งจริงเป็นก้อนเดียวกับ
    ที่โชว์บนหน้าจอเป๊ะ ๆ
    """
    if not ai_enabled():
        spec = _rule_plan(question, profiles)
        spec["_by"] = "rules"
        return spec
    try:
        req = req or plan_request(question, profiles)
        spec = _json_from(send_request(req, "แปลคำถาม"))
        if spec.get("error"):
            raise ValueError(spec["error"])
        spec["_by"] = "ai"
        return spec
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        # ต่อเน็ตไม่ได้/โมเดลตอบเพี้ยน -> ยังตอบคำถามง่าย ๆ ได้ด้วยคีย์เวิร์ด
        spec = _rule_plan(question, profiles)
        spec["_by"] = "rules"
        spec["_ai_error"] = f"{type(e).__name__}: {e}"
        return spec


# --------------------------------------------------------------------------- #
# คำนวณจริง — ใช้ engine ตัวเดียวกับตารางรายงาน ตัวเลขจึงตรงกันเสมอ
# --------------------------------------------------------------------------- #

def _table_of(p: Profile, no) -> TableSpec | None:
    for t in p.tables:
        if str(t.no) == str(no):
            return t
    return None


def _row_mask(scoped: pd.DataFrame, p: Profile, rows: list[str]) -> pd.Series:
    """แถวที่เลือก: 'รวม' = ทุกคน | '3-5' = ช่วงอายุ | '3' = อายุรายปี"""
    if not rows or TOTAL_LABEL in rows:
        return pd.Series(True, index=scoped.index)
    m = pd.Series(False, index=scoped.index)
    for r in rows:
        r = str(r).strip()
        if "band" in scoped.columns and (scoped["band"] == r).any():
            m |= (scoped["band"] == r).fillna(False)
        elif r.isdigit():
            m |= (scoped["age"] == int(r)).fillna(False)
    return m


def _denominator(scoped: pd.DataFrame, spec: TableSpec, p: Profile) -> pd.Series:
    # ตารางคุณภาพใช้ "จำนวนที่ตรวจ" เป็นตัวหาร ไม่ใช่จำนวนที่ผ่านเกณฑ์
    # (ไม่งั้น "ร้อยละผ่านเกณฑ์" จะเป็น 100% เสมอ)
    if spec.kind == "quality":
        return pd.Series(True, index=scoped.index)
    if spec.denominator == "qualified":
        return quality_mask(scoped, p)
    if spec.denominator == "examined":
        return pd.Series(True, index=scoped.index)
    return bool_mask(scoped, spec.denominator)


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _agg(scoped: pd.DataFrame, spec: TableSpec, p: Profile, metric: str,
         base: pd.Series) -> dict:
    """สรุปค่าตัวชี้วัดหนึ่งตัวบนกลุ่มแถวที่ให้มา"""
    n_base = int(base.sum())
    if spec.kind == "quality":
        if metric == "จำนวนที่ตรวจ":
            return {"kind": "count", "base": n_base, "count": n_base, "pct": None}
        q = quality_mask(scoped, p) & base
        n = int(q.sum())
        return {"kind": "count", "base": n_base, "count": n, "pct": _pct(n, n_base)}

    m = next((x for x in spec.metrics if x.name == metric), None)
    if m is None:
        raise ValueError(f"ไม่พบตัวชี้วัด '{metric}' ในตารางที่ {spec.no}")

    if spec.kind == "mean":
        vals = pd.to_numeric(evaluate(scoped, m.expr), errors="coerce")[base]
        total = float(vals.sum())
        return {"kind": "mean", "base": n_base, "sum": total,
                "mean": round(total / n_base, 2) if n_base else None}

    n = int((bool_mask(scoped, m.expr) & base).sum())
    return {"kind": "count", "base": n_base, "count": n, "pct": _pct(n, n_base)}


GROUP_COL = {"district": ("ampname", "อำเภอ"), "unit": ("hosname", "หน่วยบริการ")}


def run_spec(spec: dict, profiles: dict[str, Profile]) -> dict:
    """คำนวณตามสเปก — คืนเฉพาะตัวเลขสรุป ไม่มีข้อมูลรายบุคคล"""
    pid = spec.get("profile")
    p = profiles.get(pid)
    if p is None:
        raise ValueError(f"ไม่พบกลุ่มอายุ: {pid}")

    tspec = _table_of(p, spec.get("table"))
    if tspec is None:
        raise ValueError("ไม่รู้ว่าคำถามนี้ต้องดูตารางไหน "
                         "ลองระบุชื่อตัวชี้วัดให้ชัดขึ้น เช่น 'ปราศจากฟันผุ'")
    metric = spec.get("metric")
    names = (QUALITY_METRICS if tspec.kind == "quality"
             else [m.name for m in tspec.metrics])
    if metric not in names:
        metric = _best(str(metric or ""), names) or (names[0] if names else None)
    if metric is None:
        raise ValueError(f"ตารางที่ {tspec.no} ไม่มีตัวชี้วัดให้เลือก")

    df = service.get_dataset(p)
    scope = spec.get("scope") or resolve_area(str(spec.get("area") or ""),
                                              service.area_tree(df))
    pop = service.filter_area(df, scope.get("pv"), scope.get("amp"), scope.get("hos"))
    scoped = apply_scope(pop, p)

    rows = [str(r) for r in (spec.get("rows") or [TOTAL_LABEL])]
    rmask = _row_mask(scoped, p, rows)
    base = _denominator(scoped, tspec, p) & rmask

    result = {
        "profile": {"id": p.id, "label": p.label},
        "scope": scope,
        "table": {"no": tspec.no, "title": tspec.title, "kind": tspec.kind},
        "rows": rows,
        "metric": metric,
        "conditions": list(tspec.conditions or []),
        "total": _agg(scoped, tspec, p, metric, base),
        "groups": [],
    }

    gb = spec.get("group_by")
    if gb in GROUP_COL:
        col, label = GROUP_COL[gb]
        result["group_by"] = label
        if col in scoped.columns:
            out = []
            for name, idx in scoped.groupby(col, dropna=False).groups.items():
                sub_base = base.copy()
                sub_base[~base.index.isin(idx)] = False
                if not sub_base.any():
                    continue
                row = _agg(scoped, tspec, p, metric, sub_base)
                row["name"] = str(name) if pd.notna(name) else "ไม่ระบุ"
                out.append(row)
            key = "pct" if result["total"]["kind"] == "count" else "mean"
            out.sort(key=lambda r: (r.get(key) is None, r.get(key) or 0),
                     reverse=(spec.get("sort", "desc") != "asc"))
            result["groups"] = out[:int(spec.get("limit") or 10)]
    return result


# --------------------------------------------------------------------------- #
# เรียบเรียงคำตอบ
# --------------------------------------------------------------------------- #

def _scope_text(scope: dict) -> str:
    if scope.get("hos"):
        return scope.get("hos_name") or str(scope["hos"])
    for k, prefix in (("amp", "อำเภอ"), ("pv", "จังหวัด")):
        if scope.get(k):
            return f"{prefix}{scope[k]}"
    return "ทั้งหมด"


def _row_text(rows: list[str]) -> str:
    if not rows or rows == [TOTAL_LABEL]:
        return "ทุกอายุ"
    return "อายุ " + ", ".join(rows) + " ปี"


def template_answer(result: dict) -> str:
    """คำตอบแบบไม่ง้อ AI — ใช้เมื่อไม่มี API key หรือเรียบเรียงไม่สำเร็จ"""
    t = result["total"]
    head = (f'{result["metric"]} · {_row_text(result["rows"])} · '
            f'{_scope_text(result["scope"])} ({result["profile"]["label"]})')
    if t["kind"] == "mean":
        body = f'ค่าเฉลี่ย {t["mean"]} ซี่/คน จากฐาน {t["base"]:,} คน'
    else:
        pct = f' ({t["pct"]}%)' if t["pct"] is not None else ""
        body = f'{t["count"]:,} คน{pct} จากฐาน {t["base"]:,} คน'
    out = f"{head}\n{body}"
    if result.get("groups"):
        key = "mean" if t["kind"] == "mean" else "pct"
        unit = " ซี่/คน" if key == "mean" else "%"
        lines = [f'  {i+1}. {g["name"]} — {g.get(key)}{unit} (ฐาน {g["base"]:,})'
                 for i, g in enumerate(result["groups"])]
        out += f'\nเรียงตาม{result.get("group_by", "พื้นที่")}:\n' + "\n".join(lines)
    if t["base"] < 30:
        out += "\n⚠ ฐานน้อยกว่า 30 คน ตัวเลขร้อยละอาจแกว่งมาก"
    return out


def phrase_user_text(question: str, result: dict) -> str:
    return json.dumps({"question": question, "result": result}, ensure_ascii=False)


def phrase_request(question: str, result: dict) -> dict | None:
    """คำขอ 'เรียบเรียงคำตอบ' ที่เตรียมไว้ (ยังไม่ส่ง) — None ถ้าปิด phrase ไว้

    นี่คือก้อนเดียวที่มี "ตัวเลข" อยู่ข้างใน ตั้ง phrase: false แล้วจะไม่มีเลย
    """
    if not (ai_enabled() and config().get("phrase", True)):
        return None
    return build_request(PHRASE_SYSTEM, phrase_user_text(question, result))


def phrase(question: str, result: dict, req: dict | None = None) -> str:
    if not (ai_enabled() and config().get("phrase", True)):
        return template_answer(result)
    try:
        req = req or phrase_request(question, result)
        text = send_request(req, "เรียบเรียงคำตอบ").strip()
        return text or template_answer(result)
    except Exception:
        return template_answer(result)


def build_answer(question: str, spec: dict, profiles: dict[str, Profile]) -> dict:
    """คำนวณในเครื่องแล้วประกอบคำตอบ (ยังไม่เรียบเรียงด้วย AI)"""
    result = run_spec(spec, profiles)
    return {
        "question": question,
        "spec": spec,
        "result": result,
        "text": template_answer(result),
        "planner": spec.get("_by", "rules"),
        "ai": ai_enabled(),
        # ให้หน้าเว็บลิงก์ไปยังตาราง/รายชื่อเดิมได้ ผู้ใช้จะตรวจสอบตัวเลขเองได้
        "link": {"profile": result["profile"]["id"], "table": result["table"]["no"],
                 "metric": result["metric"],
                 "row": (result["rows"] or [TOTAL_LABEL])[0],
                 **result["scope"]},
    }


def answer(question: str, profiles: dict[str, Profile] | None = None) -> dict:
    """จุดเข้าหลัก แบบรวดเดียว (ไม่ถามยืนยัน) — ใช้ในเทสต์และเมื่อปิด confirm"""
    profiles = profiles if profiles is not None else prof_mod.discover()
    a = build_answer(question, plan(question, profiles), profiles)
    a["text"] = phrase(question, a["result"])
    return a

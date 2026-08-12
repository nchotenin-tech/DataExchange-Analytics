"""สร้างข้อสรุป (insight) จากตารางรายงานแบบอัตโนมัติ

ใช้กฎล้วน ๆ ไม่ต้องต่อเน็ต — ทำงานได้ในเครื่องผู้ใช้ตอน build เป็น exe
ทุกข้อความอ้างอิงตัวเลขจริงในตาราง ไม่มีการเดา
"""
from __future__ import annotations

# คำที่บ่งว่า "ค่ายิ่งสูงยิ่งดี" นอกนั้นถือว่ายิ่งต่ำยิ่งดี
GOOD_HIGH = ("ปราศจาก", "ฟันดี", "ปกติ", "ฟันที่มีในปาก")

SMALL_BASE = 30          # ฐานน้อยกว่านี้ถือว่าตีความยาก
MIN_GAP = 2.0            # ผลต่างที่ถือว่ามีนัย (จุด % หรือ ซี่)


def direction(metric: str, override: dict | None = None) -> str:
    if override and metric in override:
        return override[metric]
    return "high" if any(k in metric for k in GOOD_HIGH) else "low"


def _fmt(v, dec=2):
    return "-" if v is None else f"{v:,.{dec}f}"


def _rows(t: dict):
    data = [r for r in t["rows"] if str(r.get("row")) != "รวม"]
    total = next((r for r in t["rows"] if str(r.get("row")) == "รวม"), None)
    return data, total


def _value(t: dict, row: dict, metric: str):
    key = f"{metric}|ร้อยละ" if t["kind"] == "count_pct" else metric
    v = row.get(key)
    return v if isinstance(v, (int, float)) else None


def _unit(t: dict) -> str:
    return "%" if t["kind"] == "count_pct" else ""


def _label(t: dict, row: dict) -> str:
    r = row.get("row")
    return f"{r} ปี" if isinstance(r, (int, float)) else f"กลุ่ม {r} ปี"


def build(t: dict, row_word: str = "อายุ") -> dict:
    """คืน {'summary': [...], 'rows': [{'row','text','tone'}...]}"""
    if t["kind"] == "quality":
        return {"summary": _quality(t), "rows": _quality_rows(t)}
    if not t.get("metric_names"):
        return {"summary": [], "rows": []}
    return {"summary": _metrics_summary(t), "rows": _metrics_rows(t)}


# --------------------------------------------------------------------------- #
# ตารางคุณภาพข้อมูล
# --------------------------------------------------------------------------- #

def _quality(t: dict) -> list[dict]:
    data, total = _rows(t)
    out = []
    if not total:
        return out

    pct = total.get("ร้อยละ")
    n, ok = total.get("จำนวนที่ตรวจ"), total.get("จำนวนที่ผ่านเกณฑ์คุณภาพ")
    tone = "good" if (pct or 0) >= 90 else "warn" if (pct or 0) >= 75 else "bad"
    out.append({"tone": tone, "text":
                f"ภาพรวมผ่านเกณฑ์คุณภาพ {_fmt(pct)}% ({ok:,} จาก {n:,} คน) "
                f"— ข้อมูลที่ตกเกณฑ์ {n - ok:,} คนจะไม่ถูกนับในตารางถัดไป"})

    valid = [r for r in data if isinstance(r.get("ร้อยละ"), (int, float))]
    if valid:
        worst = min(valid, key=lambda r: r["ร้อยละ"])
        best = max(valid, key=lambda r: r["ร้อยละ"])
        if worst is not best and (best["ร้อยละ"] - worst["ร้อยละ"]) >= MIN_GAP:
            out.append({"tone": "warn", "text":
                        f"{_label(t, worst)} ผ่านเกณฑ์ต่ำสุด {_fmt(worst['ร้อยละ'])}% "
                        f"ขณะที่ {_label(t, best)} สูงสุด {_fmt(best['ร้อยละ'])}% "
                        f"— ต่างกัน {_fmt(best['ร้อยละ'] - worst['ร้อยละ'], 1)} จุด"})

    fails = [(k.replace("ไม่ผ่าน: ", ""), v) for k, v in total.items()
             if k.startswith("ไม่ผ่าน: ") and isinstance(v, (int, float)) and v > 0]
    if fails:
        top = max(fails, key=lambda x: x[1])
        share = 100 * top[1] / (n - ok) if n and ok is not None and n > ok else None
        out.append({"tone": "bad", "text":
                    f"สาเหตุที่ตกเกณฑ์มากที่สุดคือ “{top[0]}” {top[1]:,} รายการ"
                    + (f" (≈{_fmt(share, 0)}% ของที่ตกเกณฑ์)" if share else "")
                    + " — ใช้ปุ่ม “ไม่ผ่านเกณฑ์” ในตารางภาพรวมเพื่อดูรายชื่อ"})
    return out


def _quality_rows(t: dict) -> list[dict]:
    data, total = _rows(t)
    ref = (total or {}).get("ร้อยละ")
    out = []
    for r in data:
        p = r.get("ร้อยละ")
        if not isinstance(p, (int, float)):
            continue
        diff = p - ref if isinstance(ref, (int, float)) else None
        tone = "good" if p >= 90 else "warn" if p >= 75 else "bad"
        txt = f"ผ่านเกณฑ์ {_fmt(p)}%"
        if diff is not None and abs(diff) >= MIN_GAP:
            txt += f" ({'สูงกว่า' if diff > 0 else 'ต่ำกว่า'}ภาพรวม {_fmt(abs(diff), 1)} จุด)"
        n, ok = r.get("จำนวนที่ตรวจ"), r.get("จำนวนที่ผ่านเกณฑ์คุณภาพ")
        if isinstance(n, int) and isinstance(ok, int) and n > ok:
            txt += f" · ตกเกณฑ์ {n - ok:,} คน"
        out.append({"row": str(r["row"]), "text": txt, "tone": tone})
    return out


# --------------------------------------------------------------------------- #
# ตารางตัวชี้วัด (count_pct / mean)
# --------------------------------------------------------------------------- #

def _primary(t: dict) -> str:
    """ตัวชี้วัดหลักที่ใช้เล่าเรื่อง"""
    names = t["metric_names"]
    for n in names:
        if any(k in n for k in ("ปราศจาก", "ผุถอนอุด")):
            return n
    return names[0]


def _metrics_summary(t: dict) -> list[dict]:
    data, total = _rows(t)
    u = _unit(t)
    dec = 2
    out = []
    if not data:
        return out

    p = _primary(t)
    good = direction(p)
    series = [(r, _value(t, r, p)) for r in data]
    series = [(r, v) for r, v in series if v is not None]
    if not series:
        return out

    # 1) ภาพรวม + แนวโน้มจากอายุน้อยไปมาก
    tv = _value(t, total, p) if total else None
    if tv is not None:
        out.append({"tone": "info", "text": f"ภาพรวมทุกอายุ: {p} = {_fmt(tv, dec)}{u}"})

    first, last = series[0], series[-1]
    gap = last[1] - first[1]
    if abs(gap) >= MIN_GAP:
        worse = (gap < 0) if good == "high" else (gap > 0)
        out.append({"tone": "bad" if worse else "good", "text":
                    f"{p} เปลี่ยนจาก {_fmt(first[1], dec)}{u} ที่ {_label(t, first[0])} "
                    f"เป็น {_fmt(last[1], dec)}{u} ที่ {_label(t, last[0])} "
                    f"({'ลดลง' if gap < 0 else 'เพิ่มขึ้น'} {_fmt(abs(gap), 1)} "
                    f"{'จุด' if u else 'ซี่'}) — "
                    f"{'ยิ่งอายุมากยิ่งแย่ลง' if worse else 'ยิ่งอายุมากยิ่งดีขึ้น'}"})

    # 2) อายุที่ต้องให้ความสำคัญ
    worst = min(series, key=lambda x: x[1]) if good == "high" else max(series, key=lambda x: x[1])
    best = max(series, key=lambda x: x[1]) if good == "high" else min(series, key=lambda x: x[1])
    if worst[0] is not best[0]:
        word = "ต่ำสุด" if good == "high" else "สูงสุด"
        out.append({"tone": "warn", "text":
                    f"ควรเน้น {_label(t, worst[0])} — {p} {_fmt(worst[1], dec)}{u} "
                    f"({word}) เทียบกับ {_label(t, best[0])} ที่ {_fmt(best[1], dec)}{u}"})

    # 3) ช่วงอายุที่เปลี่ยนแปลงเร็วที่สุด = จุดที่ควรแทรกแซงก่อน
    steps = [(series[i], series[i + 1], series[i + 1][1] - series[i][1])
             for i in range(len(series) - 1)] if len(series) >= 3 else []
    if steps:
        key = (lambda s: s[2]) if good == "high" else (lambda s: -s[2])
        st = min(steps, key=key)
        worse_step = (st[2] < 0) if good == "high" else (st[2] > 0)
        if worse_step and abs(st[2]) >= MIN_GAP:
            out.append({"tone": "warn", "text":
                        f"เปลี่ยนแปลงเร็วที่สุดช่วง {_label(t, st[0][0])} → {_label(t, st[1][0])} "
                        f"({_fmt(abs(st[2]), 1)} {'จุด' if u else 'ซี่'}) "
                        f"— เป็นช่วงที่ควรแทรกแซงก่อนสาย"})

    # 4) ปัญหาเด่นในภาพรวม (เฉพาะตัวชี้วัดที่ยิ่งต่ำยิ่งดี)
    if total:
        bad_metrics = [(m, _value(t, total, m)) for m in t["metric_names"]
                       if direction(m) == "low"]
        bad_metrics = [(m, v) for m, v in bad_metrics if v is not None and v > 0]
        if bad_metrics:
            top = max(bad_metrics, key=lambda x: x[1])
            if top[0] != p:
                out.append({"tone": "info", "text":
                            f"รายการที่พบมากที่สุดคือ {top[0]} = {_fmt(top[1], dec)}{u}"})

    # 5) เตือนเรื่องฐานน้อย
    small = [r for r in data if isinstance(r.get("ฐาน"), int) and 0 < r["ฐาน"] < SMALL_BASE]
    if small:
        out.append({"tone": "warn", "text":
                    "ฐานข้อมูลน้อย ควรระวังการตีความ: "
                    + ", ".join(f"{_label(t, r)} ({r['ฐาน']:,} คน)" for r in small)})
    return out


def _metrics_rows(t: dict) -> list[dict]:
    """สรุปรายอายุ: เทียบกับภาพรวม + ชี้ตัวชี้วัดที่โดดที่สุดของอายุนั้น"""
    data, total = _rows(t)
    if not data or not total:
        return []
    u, dec = _unit(t), 2
    p = _primary(t)
    good = direction(p)
    out = []

    for r in data:
        v = _value(t, r, p)
        if v is None:
            continue
        tv = _value(t, total, p)
        diff = v - tv if tv is not None else None
        if diff is None or abs(diff) < MIN_GAP:
            tone = "info"
        else:
            better = (diff > 0) if good == "high" else (diff < 0)
            tone = "good" if better else "bad"

        txt = f"{p} {_fmt(v, dec)}{u}"
        if diff is not None and abs(diff) >= MIN_GAP:
            txt += f" ({'ดีกว่า' if tone == 'good' else 'แย่กว่า'}ภาพรวม " \
                   f"{_fmt(abs(diff), 1)} {'จุด' if u else 'ซี่'})"

        # ตัวชี้วัดที่เบี่ยงจากภาพรวมมากที่สุดของอายุนี้ (นอกเหนือจากตัวหลัก)
        devs = []
        for m in t["metric_names"]:
            if m == p or direction(m) != "low":
                continue          # ดูเฉพาะ "ปัญหา" ไม่รวมค่าที่สูงแล้วดี เช่น ฟันที่มีในปาก
            mv, mt = _value(t, r, m), _value(t, total, m)
            if mv is None or mt is None:
                continue
            d = mv - mt
            if d >= MIN_GAP:
                devs.append((m, mv, d))
        if devs:
            m, mv, d = max(devs, key=lambda x: abs(x[2]))
            txt += f" · เด่น: {m} {_fmt(mv, dec)}{u} (สูงกว่าภาพรวม {_fmt(abs(d), 1)} " \
                   f"{'จุด' if u else 'ซี่'})"

        base = r.get("ฐาน")
        if isinstance(base, int) and base < SMALL_BASE:
            txt += f" · ฐานเพียง {base:,} คน"
            tone = "warn"

        out.append({"row": str(r["row"]), "text": txt, "tone": tone})
    return out

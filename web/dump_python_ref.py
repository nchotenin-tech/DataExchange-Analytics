# -*- coding: utf-8 -*-
"""ดัมพ์ผลจากเวอร์ชัน Python เดิมไว้เป็นค่าอ้างอิงให้ parity test ฝั่งเว็บเทียบ

    python web/dump_python_ref.py out.json

ผลลัพธ์มีแต่ตัวเลขสรุปและจำนวนนับ ไม่มีข้อมูลรายบุคคล
"""
from __future__ import annotations

import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def clean(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if k not in ("_sub", "_parent")}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


def main() -> int:
    from core import profiles as prof, service

    out = {}
    for pid, p in prof.discover().items():
        rep = service.report(p)
        pend = service.person_list(p, "pending")
        fail = service.person_list(p, "failed")

        # ยอดคลิกดูรายชื่อ — สุ่มตรวจบางแถวพอ (ทุกแถวช้าเกินไปสำหรับ CI)
        clicks = {}
        for t in rep["tables"]:
            for met in (t.get("followup") or []):
                labels = [str(r["row"]) for r in t["rows"]]
                pick = labels[:2] + labels[-1:]
                for lab in dict.fromkeys(pick):
                    n = len(service.metric_list(p, t["no"], met, lab))
                    clicks["%s|%s|%s" % (t["no"], met, lab)] = n

        eda = service.eda(p)
        out[pid] = {
            "eda": clean(eda),
            "eda_clicks": {},
            "summary": clean(rep["summary"]),
            "districts": clean(rep["districts"]),
            "tables": [{"no": t["no"], "columns": t["columns"],
                        "rows": clean(t["rows"])} for t in rep["tables"]],
            "pending_n": len(pend),
            "failed_n": len(fail),
            "pending_cols": list(pend.columns),
            "failed_cols": [c for c in fail.columns if c != "_bad"],
            "clicks": clicks,
        }
        # ยอดคลิกจากการ์ด/แท่งกราฟในหน้าสำรวจข้อมูล
        for card in eda["numeric"][:6]:
            for sel in ("outlier", "zero", "neg", "extreme", "iqr"):
                n = len(service.value_list(p, card["column"], sel))
                out[pid]["eda_clicks"]["%s|%s" % (card["column"], sel)] = n
            for bi, h in enumerate(card["hist"][:2]):
                n = len(service.value_list(p, card["column"], "range",
                                           lo=h["from"], hi=h["to"], hi_exclusive=True))
                out[pid]["eda_clicks"]["%s|range|%d" % (card["column"], bi)] = n

        print("%s | ยังไม่ตรวจ %d | ไม่ผ่านเกณฑ์ %d | ช่องที่สุ่มตรวจ %d"
              % (pid, len(pend), len(fail), len(clicks)))

    dest = sys.argv[1] if len(sys.argv) > 1 else "python_ref.json"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("เขียน", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

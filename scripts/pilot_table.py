#!/usr/bin/env python3
"""Build runs/pilot/summary.jsonl and print a markdown table of all pilot runs.
Usage: pilot_table.py   (run from repo root after collect_spend.py)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from summarize import summarize  # noqa: E402

ROOT = Path("runs/pilot")
dirs = sorted(p.parent for p in ROOT.glob("proxy-*/*/*/meta.json"))
rows = [summarize(d) for d in dirs]
with open(ROOT / "summary.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

cols = ["model", "task", "arm", "slept", "wall_s", "agent_s", "correct", "requests", "in_tok", "out_tok",
        "proxy_spend", "hits", "misses", "wasted", "saved_ms", "eager_saved_ms",
        "tool_parts", "parts_args_streamed", "tool_errors", "http_429", "proxy_failures"]
print("| " + " | ".join(cols) + " |")
print("|" + "---|" * len(cols))
for r in rows:
    vals = []
    for c in cols:
        v = r.get(c)
        if c == "model":
            v = v.replace("proxy-", "")
        if c == "task":
            v = v[:2]
        if c == "proxy_spend" and v is not None:
            v = "%.4f" % v
        vals.append(str(v))
    print("| " + " | ".join(vals) + " |")
tot = sum(r["proxy_spend"] or 0 for r in rows)
print("\nTotal pilot proxy spend: $%.4f over %d runs" % (tot, len(rows)))

#!/usr/bin/env python3
"""Tables for the code-mode follow-up, computed only from runs/codemode/*/records.jsonl.

`python3 scripts/codemode_tables.py` prints every table as markdown (used in
docs/CODEMODE_FOLLOWUP.md); `data()` returns the same numbers as a dict for the HTML report.
"""
from __future__ import annotations

import collections
import json
import statistics as st
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs" / "codemode"
MODELS = ("codex-gpt-6.1-sol", "codex-gpt-6-luna")
ITERATIONS = [("main", "base1", "base"), ("it1", "new1", "new"), ("it2", "new2", "new"),
              ("it3", "new3", "new"), ("it4", "new4", "new"), ("it5", "new5", "new")]


def records(batch: str) -> list[dict]:
    return [json.loads(x) for x in (RUNS / batch / "records.jsonl").read_text().splitlines() if x.strip()]


def pick(recs: list[dict], model: str, variant: str, prefix: str = "") -> list[dict]:
    return [r for r in recs if r["model"] == model and r["variant"] == variant and r["task"].startswith(prefix)]


def _mean(xs: list[float], nd: int = 2) -> float:
    return round(st.mean(xs), nd) if xs else 0


def short_row(recs: list[dict]) -> dict:
    full = [r for r in recs if not r.get("no_transcript")] or recs
    nested = [n for r in full for n in r.get("nested", [])]
    return {
        "n": len(recs), "success": f"{sum(r['correct'] for r in recs)}/{len(recs)}",
        "wall_mean_s": _mean([r["wall_s"] for r in full], 1), "wall_median_s": round(st.median(r["wall_s"] for r in full), 1),
        "requests": _mean([r.get("requests", 0) for r in full]),
        "run_code": _mean([r.get("run_code", 0) for r in full]),
        "calls_per_run_code": _mean(nested), "pct_rc_le1": round(100 * sum(n <= 1 for n in nested) / len(nested)) if nested else 0,
        "rc_errors": _mean([r.get("rc_errors", 0) for r in full]),
        "timeouts": sum(bool(r.get("timed_out")) for r in recs),
        "in_tok_k": _mean([r.get("in_tok", 0) / 1000 for r in full], 1),
        "out_tok_k": _mean([r.get("out_tok", 0) / 1000 for r in full], 2),
    }


def long_row(recs: list[dict]) -> dict:
    full = [r for r in recs if not r.get("no_transcript")] or recs
    sub = lambda r, k: (r.get("sub") or {}).get(k, 0)  # noqa: E731
    nested = [n for r in full for n in r.get("nested", [])]
    fan = [n for r in full for n in r.get("invoke_per_rc", [])]
    return {
        "n": len(recs), "success": f"{sum(r['correct'] for r in recs)}/{len(recs)}",
        "part_acc": round(100 * st.mean((sum(r["fields_ok"]) / len(r["fields_ok"])) if r.get("fields_ok") else 0
                                        for r in recs)),
        "wall": _mean([r["wall_s"] for r in recs], 1),
        "wall_completed": _mean([r["wall_s"] for r in recs if not r.get("timed_out")], 1),
        "parent_req": _mean([r.get("requests", 0) for r in full], 1),
        "total_req": _mean([r.get("requests", 0) + sub(r, "requests") for r in full], 1),
        "calls_per_run_code": _mean(nested), "pct_rc_le1": round(100 * sum(n <= 1 for n in nested) / len(nested)) if nested else 0,
        "rc_errors": _mean([r.get("rc_errors", 0) + sub(r, "rc_errors") for r in full]),
        "max_fanout": max(fan) if fan else 0,
        "total_in_tok_k": _mean([(r.get("in_tok", 0) + sub(r, "in_tok")) / 1000 for r in full], 1),
        "total_out_tok_k": _mean([(r.get("out_tok", 0) + sub(r, "out_tok")) / 1000 for r in full], 2),
        "timeouts": sum(bool(r.get("timed_out")) for r in recs),
    }


def data() -> dict:
    conf = records("conf")
    short = {"off": records("off1"), "base": records("base1") + [r for r in conf if r["variant"] == "base"],
             "new": records("new5") + [r for r in conf if r["variant"] == "new"]}
    long_recs = records("long1") + records("fix1")
    out: dict = {"short": {}, "iterations": {}, "long": {"L_": {}, "D_": {}}, "subagents": {}, "fanout": {}}
    for m in MODELS:
        out["short"][m] = {v: short_row(pick(rs, m, v)) for v, rs in short.items()}
        out["iterations"][m] = [dict(label=lab, **short_row(pick(records(b), m, v))) for lab, b, v in ITERATIONS]
        for prefix in ("L_", "D_"):
            out["long"][prefix][m] = {v: long_row(pick(long_recs, m, v, prefix))
                                      for v in ("off", "base", "new", "fix") if pick(long_recs, m, v, prefix)}
        out["subagents"][m] = {}
        for v in ("off", "base", "new", "fix"):
            sess = [s for r in pick(long_recs, m, v, "D_") for s in (r.get("sub") or {}).get("per_session", [])]
            out["subagents"][m][v] = {"sessions": len(sess), "req": _mean([s["requests"] for s in sess], 1),
                                      "in_tok_k": _mean([s["in_tok"] / 1000 for s in sess], 1),
                                      "max_ret": max(s["max_return_chars"] for s in sess)}
        out["fanout"][m] = {
            "off_invokes_per_response": dict(collections.Counter(
                n for r in pick(long_recs, m, "off", "D_") for n in r.get("invoke_per_response", []))),
            "new_invokes_per_run_code": dict(collections.Counter(
                n for r in pick(long_recs, m, "new", "D_") for n in r.get("invoke_per_rc", []))),
        }
    out["n_runs"] = sum(len(records(p.name)) for p in RUNS.iterdir() if (p / "records.jsonl").exists())
    return out


# --- code mode off vs on (main today: #1013 + #1014) ---------------------------------------

WORKLOADS = [  # key, label, (task filter), off source, on source
    ("short_gather", "Short: read and answer", lambda r: not r["task"][:2] in ("L_", "D_") and r["family"] == "gather"),
    ("short_code", "Short: bug fix", lambda r: not r["task"][:2] in ("L_", "D_") and r["family"] == "code"),
    ("long_gather", "Long: read and answer", lambda r: r["task"].startswith("L_") and r["family"] == "gather"),
    ("long_code", "Long: multi-fix", lambda r: r["task"].startswith("L_") and r["family"] == "code"),
    ("deleg_gather", "Delegated: read and answer", lambda r: r["task"].startswith("D_") and r["family"] == "gather"),
    ("deleg_code", "Delegated: multi-fix", lambda r: r["task"].startswith("D_") and r["family"] == "code"),
]


def _pctile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1) if xs else 0


def work_calls(r: dict) -> int:
    """Real tool calls (run_code itself excluded), parent plus sub-agents."""
    sub = r.get("sub") or {}
    parent = r.get("top_calls", 0) - r.get("run_code", 0) + sum(r.get("nested", []))
    return parent + sub.get("top_calls", 0) - sub.get("run_code", 0) + sum(sub.get("nested", []))


def onoff_cell(recs: list[dict]) -> dict:
    full = [r for r in recs if not r.get("no_transcript")] or recs
    sub = lambda r, k: (r.get("sub") or {}).get(k, 0)  # noqa: E731
    req = [r.get("requests", 0) + sub(r, "requests") for r in full]
    intok = [r.get("in_tok", 0) + sub(r, "in_tok") for r in full]
    mix: dict[str, int] = {}
    for r in full:
        for t, n in list((r.get("top_by_tool") or {}).items()) + list((r.get("nested_by_tool") or {}).items()):
            if t != "run_code":
                mix[t] = mix.get(t, 0) + n
    nested = [n for r in full for n in r.get("nested", [])]
    return {
        "n": len(recs), "correct": sum(r["correct"] for r in recs),
        "success_pct": round(100 * sum(r["correct"] for r in recs) / len(recs)),
        "part_acc": round(100 * st.mean((sum(r["fields_ok"]) / len(r["fields_ok"])) if r.get("fields_ok") else 0
                                        for r in recs)),
        "walls": [r["wall_s"] for r in recs],
        "wall_mean": _mean([r["wall_s"] for r in recs], 1), "wall_median": round(st.median(r["wall_s"] for r in recs), 1),
        "wall_p90": _pctile([r["wall_s"] for r in recs], 0.9),
        "timeouts": sum(bool(r.get("timed_out")) for r in recs),
        "requests": _mean(req, 2), "parent_requests": _mean([r.get("requests", 0) for r in full], 2),
        "work_calls": _mean([work_calls(r) for r in full], 1),
        "calls_per_request": round(sum(work_calls(r) for r in full) / max(1, sum(req)), 2),
        "run_code": _mean([r.get("run_code", 0) for r in full], 2),
        "calls_per_run_code": _mean(nested), "rc_errors": _mean([r.get("rc_errors", 0) + sub(r, "rc_errors") for r in full]),
        "in_tok_k": _mean([x / 1000 for x in intok], 1),
        "out_tok_k": _mean([(r.get("out_tok", 0) + sub(r, "out_tok")) / 1000 for r in full], 2),
        "in_per_request_k": round(sum(intok) / max(1, sum(req)) / 1000, 2),
        "cache_read_k": _mean([r.get("cache_read", 0) / 1000 for r in full], 1),
        "subagents": _mean([sub(r, "sessions") for r in full], 1),
        "tool_mix": dict(sorted(((t, round(n / len(full), 2)) for t, n in mix.items()), key=lambda kv: -kv[1])),
    }


def onoff() -> dict:
    """Off vs on per model and workload. on = current main: new5+conf (short), new (long), fix (delegated)."""
    conf = records("conf")
    short_on = records("new5") + [r for r in conf if r["variant"] == "new"]
    long1, fix1 = records("long1"), records("fix1")
    src = {"off": records("off1") + [r for r in long1 if r["variant"] == "off"],
           "on": short_on + [r for r in long1 if r["variant"] == "new" and r["task"].startswith("L_")] + fix1,
           "on_1013": [r for r in long1 if r["variant"] == "new" and r["task"].startswith("D_")]}
    out: dict = {"workloads": [(k, label) for k, label, _ in WORKLOADS], "cells": {}, "tasks": {}}
    for m in MODELS:
        out["cells"][m] = {}
        for key, _, keep in WORKLOADS:
            out["cells"][m][key] = {side: onoff_cell([r for r in rs if r["model"] == m and keep(r)])
                                    for side, rs in src.items() if any(r["model"] == m and keep(r) for r in rs)}
        tasks: dict[str, dict] = {}
        for side in ("off", "on"):
            for r in src[side]:
                if r["model"] == m:
                    tasks.setdefault(r["task"], {}).setdefault(side, []).append(r)
        out["tasks"][m] = {t: {side: {"n": len(rs), "correct": sum(r["correct"] for r in rs),
                                      "wall": _mean([r["wall_s"] for r in rs], 1),
                                      "requests": _mean([r.get("requests", 0) + (r.get("sub") or {}).get("requests", 0)
                                                         for r in rs], 1),
                                      "in_tok_k": _mean([(r.get("in_tok", 0) + (r.get("sub") or {}).get("in_tok", 0)) / 1000
                                                         for r in rs], 1)}
                               for side, rs in v.items()} for t, v in sorted(tasks.items())}
        out["overall"] = out.get("overall", {})
        out["overall"][m] = overall(out["tasks"][m])
    return out


def overall(tasks: dict[str, dict]) -> dict:
    """Task-balanced comparison: each task counts once, whatever its run count per side."""
    both = {t: v for t, v in tasks.items() if "off" in v and "on" in v}
    res: dict = {"tasks": len(both)}
    for k in ("wall", "requests", "in_tok_k"):
        ratios = sorted(v["on"][k] / v["off"][k] for v in both.values() if v["off"][k])
        res[k] = {"off_mean": _mean([v["off"][k] for v in both.values()], 1),
                  "on_mean": _mean([v["on"][k] for v in both.values()], 1),
                  "median_change_pct": round(100 * (st.median(ratios) - 1)),
                  "tasks_better": sum(x < 1 for x in ratios)}
    res["success"] = {side: round(100 * st.mean(v[side]["correct"] / v[side]["n"] for v in both.values()))
                      for side in ("off", "on")}
    return res


def md(headers: list[str], rows: list[list[object]]) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
                     + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def onoff_md() -> str:
    """Markdown: code mode off vs on (current main), task-balanced overall plus every workload."""
    d = onoff()
    name = lambda m: m.replace("codex-", "")  # noqa: E731
    pc = lambda on, off: f"{(on - off) / off * 100:+.0f}%" if off else "-"  # noqa: E731
    out = ["## Code mode off vs on (current main)\n",
           "Across all 30 tasks, task-balanced (each task counts once; median of per-task changes):\n",
           md(["model", "model requests", "wall time", "input tokens", "success off → on"],
              [[name(m), *(f"{o[k]['median_change_pct']:+d}% (better on {o[k]['tasks_better']}/{o['tasks']})"
                           for k in ("requests", "wall", "in_tok_k")), f"{o['success']['off']}% → {o['success']['on']}%"]
               for m, o in d["overall"].items()])]
    for m in MODELS:
        out.append(f"\n### {name(m)}, per workload\n")
        rows = []
        for k, label in d["workloads"]:
            a, b = d["cells"][m][k]["off"], d["cells"][m][k]["on"]
            rows.append([label, f"{a['n']} / {b['n']}", f"{a['success_pct']}% → {b['success_pct']}%",
                         f"{a['part_acc']}% → {b['part_acc']}%",
                         *(f"{a[x]} → {b[x]} ({pc(b[x], a[x])})" for x in ("wall_mean", "requests", "work_calls",
                                                                             "calls_per_request", "in_tok_k", "out_tok_k"))])
        out.append(md(["workload", "runs off / on", "success", "parts right", "wall mean s", "model requests",
                       "tool calls", "tool calls / request", "input tok k", "output tok k"], rows))
    return "\n".join(out)


def main() -> None:
    d = data()
    name = lambda m: m.replace("codex-", "")  # noqa: E731
    print(onoff_md() + "\n")
    print("## Short tasks (pooled)\n")
    print(md(["model", "variant", "n", "success", "wall mean s", "wall median s", "requests/task", "calls/run_code",
              "% run_code <=1 call", "run_code errors/task", "in tok k", "out tok k"],
             [[name(m), v, x["n"], x["success"], x["wall_mean_s"], x["wall_median_s"], x["requests"],
               x["calls_per_run_code"], x["pct_rc_le1"], x["rc_errors"], x["in_tok_k"], x["out_tok_k"]]
              for m in MODELS for v, x in d["short"][m].items()]))
    print("\n## Prompt iterations\n")
    print(md(["model", "iteration", "success", "requests/task", "calls/run_code", "% run_code <=1 call",
              "run_code errors/task"],
             [[name(m), x["label"], x["success"], x["requests"], x["calls_per_run_code"], x["pct_rc_le1"],
               x["rc_errors"]] for m in MODELS for x in d["iterations"][m]]))
    for prefix, title in (("L_", "Long-horizon tasks"), ("D_", "Long-horizon tasks with delegation to sub-agents")):
        print(f"\n## {title}\n")
        print(md(["model", "variant", "success", "parts right %", "wall s", "wall s (completed runs)",
                  "parent requests", "total requests",
                  "calls/run_code", "max fan-out", "run_code errors", "total in tok k", "timeouts"],
                 [[name(m), v, x["success"], x["part_acc"], x["wall"], x["wall_completed"], x["parent_req"],
                   x["total_req"],
                   x["calls_per_run_code"], x["max_fanout"] or "-", x["rc_errors"], x["total_in_tok_k"], x["timeouts"]]
                  for m in MODELS for v, x in d["long"][prefix][m].items()]))
    print("\n## Sub-agent sessions (delegation tasks)\n")
    print(md(["model", "variant", "sessions", "requests/session", "in tok k/session", "largest return (chars)"],
             [[name(m), v, x["sessions"], x["req"], x["in_tok_k"], f"{x['max_ret']:,}"]
              for m in MODELS for v, x in d["subagents"][m].items()]))
    print("\n## Sub-agent fan-out\n")
    print(md(["model", "off: invoke_agent calls per model response", "new: invoke_agent calls per run_code"],
             [[name(m), json.dumps(d["fanout"][m]["off_invokes_per_response"], sort_keys=True),
               json.dumps(d["fanout"][m]["new_invokes_per_run_code"], sort_keys=True)] for m in MODELS]))


if __name__ == "__main__":
    main()

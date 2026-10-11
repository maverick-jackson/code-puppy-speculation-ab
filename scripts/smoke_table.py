#!/usr/bin/env python3
"""Tables and variance numbers for a batch (used for the Phase 2 smoke report).

Usage: smoke_table.py runs/<batch>/records.jsonl
Prints: per task x arm pass and wall (rep 1 and mean over reps), per family cost and wall,
and the variance components used for the main-run minimum detectable effect:
  sd_pair  = SD over blocks of the paired log-wall difference (arm X vs off), rep 1 only
  sd_within = pooled SD of log(wall) across reps within one (task, arm) cell
Uses only the latest VALID record per (task, arm, rep).
"""
import json
import math
import statistics as st
import sys
from collections import defaultdict


def latest_valid(path):
    cells = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("valid"):
            cells[(r["model"], r["task"], r["arm"], r["rep"])] = r
    return cells


def fmt(x, d=1):
    return "-" if x is None else f"{x:.{d}f}"


def main(path):
    cells = latest_valid(path)
    allrecs = [json.loads(line) for line in open(path)]
    arms = ["off", "on", "plain"]
    tasks = sorted({k[1] for k in cells})
    fam = {r["task"]: r["family"] for r in cells.values()}
    print("| task | family | pass off/on/plain (rep 1) | wall s off | wall s on | wall s plain | reps |")
    print("|---|---|---|---|---|---|---|")
    for t in tasks:
        ok, walls, reps = [], [], set()
        for a in arms:
            rs = [r for k, r in cells.items() if k[1] == t and k[2] == a]
            reps |= {r["rep"] for r in rs}
            r1 = [r for r in rs if r["rep"] == 1]
            ok.append("Y" if r1 and r1[0]["correct"] else ("n" if r1 else "-"))
            w1 = fmt(r1[0]["wall_s"]) if r1 else "-"
            wm = st.mean(r["wall_s"] for r in rs) if len(rs) > 1 else None
            walls.append(w1 + (f" (mean {fmt(wm)})" if wm else ""))
        print(f"| {t} | {fam[t]} | {'/'.join(ok)} | " + " | ".join(walls) + f" | {len(reps)} |")
    print()
    print("| family | arm | runs | pass rate | mean wall s | median wall s | mean agent s | mean $ / run | mean requests | mean input tok |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for f in ("gather", "code"):
        for a in arms + ["all"]:
            rs = [r for r in cells.values() if r["family"] == f and (a == "all" or r["arm"] == a)]
            if not rs:
                continue
            sp = [r["proxy_spend"] for r in rs if r.get("proxy_spend") is not None]
            print(f"| {f} | {a} | {len(rs)} | {sum(r['correct'] for r in rs) / len(rs):.2f} | "
                  f"{st.mean(r['wall_s'] for r in rs):.1f} | {st.median(r['wall_s'] for r in rs):.1f} | "
                  f"{st.mean(r['agent_s'] or 0 for r in rs):.1f} | {st.mean(sp):.4f} | "
                  f"{st.mean(r['requests'] or 0 for r in rs):.1f} | {st.mean(r['in_tok'] or 0 for r in rs):.0f} |")
    print()
    tot = sum(r.get("proxy_spend") or 0 for r in allrecs)
    inval = [r for r in allrecs if not r.get("valid")]
    print(f"attempts recorded: {len(allrecs)}, invalid attempts: {len(inval)} "
          f"{[(r['task'], r['arm'], r['invalid_reasons']) for r in inval]}")
    print(f"total proxy spend over all attempts: ${tot:.4f}; sum of valid wall_s: "
          f"{sum(r['wall_s'] for r in cells.values()):.0f} s")
    flags = [(r["task"], r["arm"], r["leak_suspect"]) for r in allrecs if r.get("leak_suspect")]
    print("leak_suspect:", flags or "none")
    print("touched_tests:", [(r["task"], r["arm"]) for r in allrecs if r["grader"].get("touched_tests")] or "none")
    print("repo_modified (gather):", [(r["task"], r["arm"]) for r in allrecs if r["grader"].get("repo_modified")] or "none")
    print("timed_out:", [(r["task"], r["arm"]) for r in allrecs if r.get("timed_out")] or "none")
    # variance components on the log scale
    for a in ("on", "plain"):
        d = []
        for t in tasks:
            x, y = cells.get((allrecs[0]["model"], t, a, 1)), cells.get((allrecs[0]["model"], t, "off", 1))
            if x and y:
                d.append(math.log(x["wall_s"]) - math.log(y["wall_s"]))
        if len(d) > 2:
            print(f"paired log(wall_{a}/wall_off), rep 1: n={len(d)} mean={st.mean(d):+.3f} "
                  f"(ratio {math.exp(st.mean(d)):.3f}) sd_pair={st.stdev(d):.3f}")
    groups = defaultdict(list)
    for (m, t, a, rep), r in cells.items():
        groups[(t, a)].append(math.log(r["wall_s"]))
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    if multi:
        num = sum((len(v) - 1) * st.variance(v) for v in multi.values())
        den = sum(len(v) - 1 for v in multi.values())
        print(f"sd_within (pooled over {len(multi)} cells with reps, df={den}): {math.sqrt(num / den):.3f}")
        for fam_name in ("gather", "code"):
            mv = {k: v for k, v in multi.items() if fam[k[0]] == fam_name}
            if mv:
                n2 = sum((len(v) - 1) * st.variance(v) for v in mv.values())
                d2 = sum(len(v) - 1 for v in mv.values())
                print(f"  sd_within {fam_name}: {math.sqrt(n2 / d2):.3f} (df={d2})")


if __name__ == "__main__":
    main(sys.argv[1])

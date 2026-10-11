#!/usr/bin/env python3
"""Pre-registered analysis of batch main1 (docs/PLAN.md, "Frozen design (2026-10-10 ...)").

Usage: .venv-analysis/bin/python scripts/analyze_main1.py [runs/main1/records.jsonl]
Needs numpy and matplotlib (see docs/RESULTS.md, "Reproduce"). Writes:
  docs/results/main1_tables.md, docs/results/main1_summary.json,
  docs/results/main1_forest.png, docs/results/main1_forest_family.png
Inputs: runs/main1/records.jsonl (one record per attempt), runs/main1/batch.json (one line per
launch of the runner) and runs/main1/run_extract.jsonl (per-attempt mechanism and error details
taken from the per-run dirs). The extract is rebuilt from the run dirs whenever they are present
(they are not committed, about 90 MB) and is read from the committed file otherwise; the list of
attempt dirs is kept the same way in runs/main1/attempt_dirs.txt.
Records are read with run_matrix.load_records (the runner's own reader: NUL bytes from a torn
write are stripped before parsing). Only valid records are used, the latest valid attempt per
(model, task, arm, rep). Every bootstrap uses a fresh numpy Generator seeded with SEED, so all
estimates share the same task resamples and every number reproduces exactly.
"""
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from run_matrix import load_records  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "results"
SEED = 20261011
B = 10_000
MODELS = ["proxy-deepseek-flash", "proxy-deepseek-v4-pro", "proxy-zai-g47"]
NAME = {"proxy-deepseek-flash": "DeepSeek flash", "proxy-deepseek-v4-pro": "DeepSeek V4 Pro",
        "proxy-zai-g47": "GLM-4.7 (Z.ai)", "pooled": "Pooled (3 models)"}
ARMS = ["off", "on", "plain"]
COMPARISONS = [("on", "off"), ("plain", "off"), ("on", "plain")]
CMP_LABEL = {("on", "off"): "on vs off (total effect)", ("plain", "off"): "plain vs off (code-mode interface)",
             ("on", "plain"): "on vs plain (speculation given code mode)"}
COST = [("in_tok", "proxy_prompt_tokens"), ("out_tok", "proxy_completion_tokens"),
        ("requests", "proxy_reqs"), ("usd", "proxy_spend")]
MAXRETRY = "exceeded max retries count"
# Tools that stay native in code mode (from the "Unknown tool name ... Available tools:" message of
# 0.0.896); every other tool call in arms on/plain is wrapped inside a run_code snippet.
CODE_MODE_NATIVE = {"create_file", "load_image_for_analysis", "replace_in_file", "run_code"}
SNIPPET_BINS = ["0", "1", "2", "3", "4+"]
PROJECT_PKGS = {"invkit", "click", "rich", "httpx"}


def pct(x):
    return 100.0 * (math.exp(x) - 1.0)


# ---------- data ----------

def load(path):
    raw = Path(path).read_bytes().split(b"\n")
    nul_lines = [i for i, ln in enumerate(raw) if b"\x00" in ln]
    recovered = set()
    for i in nul_lines:
        try:
            r = json.loads(raw[i].replace(b"\x00", b"").decode())
            recovered.add((r["model"], r["task"], r["arm"], r["rep"], r["attempt"]))
        except Exception:  # noqa: BLE001
            pass
    recs = load_records(Path(path))
    for r in recs:
        # docs/PLAN.md, frozen design, "Valid run": task failures, explicitly including "run_code max
        # retries", are valid runs and COUNT AS FAILURES. The grader only checks the answer / hidden
        # tests, so a run that fixed the bug and then exhausted run_code retries grades correct. Apply
        # the plan's rule here; the grader's verdict is kept as correct_raw.
        r["correct_raw"] = r["correct"]
        r["regraded_max_retry"] = bool(r.get("valid") and r["correct"] and MAXRETRY in (r["agent_error_text"] or ""))
        if r["regraded_max_retry"]:
            r["correct"] = False
    cells = {}
    for r in recs:
        if r.get("valid"):
            k = (r["model"], r["task"], r["arm"], r["rep"])
            if k not in cells or r["attempt"] > cells[k]["attempt"]:
                cells[k] = r
    batch = Path(path).parent / "batch.json"
    launches = [json.loads(ln)["started"] for ln in batch.read_text().splitlines() if ln.strip()] if batch.exists() else []
    data = {"n_lines": sum(1 for ln in raw if ln.strip()), "n_parsed": len(recs), "nul_lines": nul_lines,
            "recovered": sorted(recovered), "recs": recs, "cells": cells, "launches": launches,
            "batch_dir": Path(path).resolve().parent}
    data["extract"] = load_extract(data)
    return data


# ---------- per-run extract (mechanism and error details from the run dirs) ----------

def retry_category(content):
    """Category of a retry-prompt part (the error text the model is sent back)."""
    c = content if isinstance(content, str) else json.dumps(content)
    lines = [ln for ln in c.strip().splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    if "Unknown tool name" in c or "Unknown function" in c:
        return "native tool called by name inside code mode"
    if "extra_forbidden" in c:
        return "tool arguments rejected (extra field)"
    if c.startswith("Type error in code"):
        return "snippet rejected by the type check"
    if c.startswith("Syntax error in code"):
        return "snippet syntax error"
    if "'module' object has no attribute 'path'" in last:
        return "sandbox: sys.path unavailable"
    if "'PosixPath' object has no attribute" in last:
        return "sandbox: Path.glob / Path.rglob unavailable"
    if last.startswith("AttributeError: module '"):
        return "sandbox: os.walk / os.getcwd / asyncio.sleep unavailable"
    if last.startswith(("ModuleNotFoundError", "ImportError")):
        mod = last.split("'")[1].split(".")[0] if "'" in last else ""
        if mod in PROJECT_PKGS:
            return "sandbox: project package not importable"
        return "sandbox: stdlib module not importable (subprocess, ast, importlib, ...)"
    if ("str indices must be integers" in last or "'str' object has no attribute" in last
            or "'dict' object has no attribute" in last or "got 'dict'" in last
            or last.startswith("KeyError: content") or last.startswith("KeyError: slice")):
        return "tool result used as the wrong type (str / dict / object)"
    if last.startswith("FileNotFoundError"):
        return "file not found"
    if c.startswith("Runtime error"):
        return "other runtime error in the snippet"
    return "other"


def tool_error_category(tc):
    """Category of an error-like tool result as counted by the plugin (record field tool_errors)."""
    h = tc.get("result_head") or ""
    if "Unknown tool name" in h:
        return "native tool called by name inside code mode"
    if tc["tool"] == "run_code":
        return "run_code snippet raised or was rejected"
    if "extra_forbidden" in h or "validation error" in h:
        return "tool arguments rejected (extra field)"
    if tc["tool"] == "grep":
        return "grep given a file path, not a directory" if "is not a directory" in h else "grep: missing path or bad pattern"
    if tc["tool"] == "read_file":
        if "does not exist" in h:
            return "read_file: file does not exist"
        if "massive" in h:
            return "read_file: file over 10,000 tokens refused"
    if tc["tool"] == "shell" and h.startswith("success=False"):
        return "shell command failed (non-zero exit)"
    return "other"


def ts(x):
    return datetime.fromisoformat(x).timestamp()


def extract_run(d):
    """Per-attempt details from a run dir: proxy request timings, run_code snippet sizes, error kinds."""
    out = {}
    try:
        meta = json.loads((d / "meta.json").read_text())
    except Exception:  # noqa: BLE001
        meta = {}
    out["wall_epoch_s"] = meta.get("wall_epoch_s")
    out["req_s"] = [round(int(q["duration_ms"]) / 1000, 3) for q in meta.get("proxy_requests") or []]
    out["ttft_s"] = [round(ts(q["first_token"]) - ts(q["start"]), 3) for q in meta.get("proxy_requests") or []
                     if q.get("first_token") and q.get("start")]
    try:
        cap = json.loads((d / "capture.json").read_text())
    except Exception:  # noqa: BLE001
        cap = {}
    # Wrapped tool executions per run_code snippet: wrapped calls whose post hook fires after the
    # previous run_code completed and before this one completed (speculative launches in arm on
    # included; native calls and "Unknown tool name" rejections excluded).
    snippets, n = [], 0
    for e in sorted(cap.get("tool_calls") or [], key=lambda e: e["t_s"]):
        if e.get("phase") != "post":
            continue
        if e["tool"] == "run_code":
            snippets.append(n)
            n = 0
        elif e["tool"] not in CODE_MODE_NATIVE and "Unknown tool name" not in (e.get("result_head") or ""):
            n += 1
    out["wrapped_per_snippet"] = snippets
    out["tool_error_kinds"] = dict(Counter(tool_error_category(e) for e in cap.get("tool_calls") or []
                                           if e.get("phase") == "post" and e.get("error_like")))
    kinds = Counter()
    for f in sorted((d / "transcript").glob("*.json")):
        if f.name.endswith("_meta.json"):
            continue
        try:
            t = json.loads(f.read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        for m in t.get("messages", []):
            for part in m.get("parts", []):
                if part.get("part_kind") == "retry-prompt":
                    kinds[retry_category(part.get("content"))] += 1
    out["retry_prompt_kinds"] = dict(kinds)
    return out


def load_extract(data):
    """{run_dir: extract}; rebuilt from the run dirs when present, else read from run_extract.jsonl."""
    path = data["batch_dir"] / "run_extract.jsonl"
    have_dirs = all((ROOT / r["run_dir"]).is_dir() for r in data["cells"].values())
    if have_dirs:
        ex = {r["run_dir"]: extract_run(ROOT / r["run_dir"]) for r in data["recs"]}
        path.write_text("".join(json.dumps({"run_dir": k} | v) + "\n" for k, v in sorted(ex.items())))
    else:
        ex = {}
        for ln in path.read_text().splitlines():
            e = json.loads(ln)
            ex[e.pop("run_dir")] = e
    listing = data["batch_dir"] / "attempt_dirs.txt"
    if have_dirs:
        dirs = sorted(str(p.relative_to(ROOT)) for p in data["batch_dir"].glob("proxy-*/*/r*/*/a*") if p.is_dir())
        listing.write_text("".join(d + "\n" for d in dirs))
    data["attempt_dirs"] = listing.read_text().split()
    return ex


def recovered_cells(data):
    return {(m, t, a, rep) for m, t, a, rep, att in data["recovered"]
            if data["cells"].get((m, t, a, rep), {}).get("attempt") == att}


def pairs(cells, models, a, b, tasks, value=lambda r: r["wall_s"], keep=lambda ra, rb: True):
    """{task: [ln(value_a / value_b), ...]} over (model, rep) pairs where both cells exist."""
    out = defaultdict(list)
    for (m, t, arm, rep), ra in cells.items():
        if arm != a or m not in models or t not in tasks:
            continue
        rb = cells.get((m, t, b, rep))
        if rb is None or not keep(ra, rb):
            continue
        va, vb = value(ra), value(rb)
        if va and vb:
            out[t].append(math.log(va / vb))
    return out


def boot(by_task, stat="mean"):
    """Point estimate and 95% percentile CI, bootstrap clustered by task (B resamples)."""
    tasks = sorted(by_task)
    allv = np.concatenate([np.asarray(by_task[t]) for t in tasks])
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(tasks), size=(B, len(tasks)))
    if stat == "mean":
        sums = np.array([sum(by_task[t]) for t in tasks])
        cnts = np.array([len(by_task[t]) for t in tasks])
        dist = sums[idx].sum(1) / cnts[idx].sum(1)
        pt = allv.mean()
    else:
        arrs = [np.asarray(by_task[t]) for t in tasks]
        dist = np.array([np.median(np.concatenate([arrs[j] for j in row])) for row in idx])
        pt = float(np.median(allv))
    lo, hi = np.percentile(dist, [2.5, 97.5])
    return {"n_pairs": int(len(allv)), "n_tasks": len(tasks), "log": float(pt), "log_lo": float(lo),
            "log_hi": float(hi), "pct": pct(pt), "pct_lo": pct(lo), "pct_hi": pct(hi)}


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


# ---------- analysis ----------

def analyze(data):
    cells = data["cells"]
    tasks = sorted({k[1] for k in cells})
    fam = {r["task"]: r["family"] for r in cells.values()}
    fams = {"gather": {t for t in tasks if fam[t] == "gather"}, "code": {t for t in tasks if fam[t] == "code"}}
    groups = [(m, [m]) for m in MODELS] + [("pooled", MODELS)]
    S = {"seed": SEED, "bootstrap_resamples": B}

    # completeness and data handling
    expected = {(m, t, a, rep) for m in MODELS for t in tasks for a in ARMS for rep in (1, 2, 3)}
    S["data"] = {"record_lines": data["n_lines"], "records_parsed": data["n_parsed"],
                 "unparseable_lines": data["n_lines"] - data["n_parsed"],
                 "lines_with_nul_bytes": [i + 1 for i in data["nul_lines"]],
                 "records_recovered_from_nul_lines": [list(x) for x in data["recovered"]],
                 "valid_cells": len(cells), "expected_cells": len(expected),
                 "missing_cells": [list(k) for k in sorted(expected - set(cells))],
                 "hosts": dict(Counter(r["host"] for r in data["recs"])),
                 "cp_versions": dict(Counter(r["cp_version"] for r in data["recs"])),
                 "invalid_attempts": [{k: r[k] for k in ("model", "task", "arm", "rep", "attempt", "invalid_reasons")}
                                      for r in data["recs"] if not r.get("valid")]}

    # descriptive per model x arm
    desc = {}
    for g, ms in groups:
        for a in ARMS:
            rs = [r for k, r in cells.items() if k[0] in ms and k[2] == a]
            w = np.array([r["wall_s"] for r in rs])
            desc[f"{g}|{a}"] = {"runs": len(rs), "geo_mean_wall_s": float(np.exp(np.log(w).mean())),
                                "mean_wall_s": float(w.mean()), "median_wall_s": float(np.median(w)),
                                "min_wall_s": float(w.min()), "max_wall_s": float(w.max()),
                                "tool_parts": sum(r["tool_parts"] or 0 for r in rs),
                                "tool_parts_args_streamed": sum(r["parts_args_streamed"] or 0 for r in rs)}
    S["descriptive"] = desc

    # RQ1 / RQ5: wall clock
    wall = {}
    for a, b in COMPARISONS:
        for g, ms in groups:
            wall[f"{a}_vs_{b}|{g}|all"] = boot(pairs(cells, ms, a, b, set(tasks)))
            for f, ts in fams.items():
                wall[f"{a}_vs_{b}|{g}|{f}"] = boot(pairs(cells, ms, a, b, ts))
    S["wall"] = wall

    # sensitivity
    # run_matrix enumerates blocks from 0, so the first block of each worker is block_index 0.
    first_block = {(m, t, rep) for (m, t, a, rep), r in cells.items() if r["block_index"] == 0}
    rec = recovered_cells(data)
    split = outage_split_blocks(data)
    sens = {}
    for a, b in COMPARISONS:
        for g, ms in groups:
            key = f"{a}_vs_{b}|{g}"
            sens[key] = {
                "primary": wall[f"{key}|all"],
                "correct_only": boot(pairs(cells, ms, a, b, set(tasks), keep=lambda x, y: x["correct"] and y["correct"])),
                "excl_first_block": boot(pairs(cells, ms, a, b, set(tasks),
                                               keep=lambda x, y: (x["model"], x["task"], x["rep"]) not in first_block)),
                "median": boot(pairs(cells, ms, a, b, set(tasks)), stat="median"),
                "excl_outage_split_blocks": boot(pairs(cells, ms, a, b, set(tasks),
                                                       keep=lambda x, y: (x["model"], x["task"], x["rep"]) not in split)),
                "excl_recovered_record": boot(pairs(
                    cells, ms, a, b, set(tasks),
                    keep=lambda x, y: (x["model"], x["task"], x["arm"], x["rep"]) not in rec
                    and (y["model"], y["task"], y["arm"], y["rep"]) not in rec)),
                "agent_time_only": boot(pairs(cells, ms, a, b, set(tasks), value=lambda r: r["agent_s"])),
            }
    S["sensitivity"] = sens
    S["first_blocks"] = sorted(list(x) for x in first_block)
    S["outage_split_blocks"] = sorted(list(x) for x in split)
    S["run_history"] = run_history(data, split)

    # RQ2: success
    succ = {}
    for g, ms in groups:
        for a in ARMS:
            rs = [r for k, r in cells.items() if k[0] in ms and k[2] == a]
            k = sum(r["correct"] for r in rs)
            lo, hi = wilson(k, len(rs))
            succ[f"{g}|{a}"] = {"correct": k, "n": len(rs), "rate": k / len(rs), "lo": lo, "hi": hi,
                                "correct_raw_grader": sum(r["correct_raw"] for r in rs),
                                "regraded_max_retry": sum(r["regraded_max_retry"] for r in rs)}
        for a, b in COMPARISONS:
            bb = cc = n = 0
            for (m, t, arm, rep), ra in cells.items():
                rb = cells.get((m, t, b, rep))
                if arm != a or m not in ms or rb is None:
                    continue
                n += 1
                bb += ra["correct"] and not rb["correct"]
                cc += rb["correct"] and not ra["correct"]
            succ[f"{a}_vs_{b}|{g}|mcnemar"] = {"pairs": n, "a_only_correct": bb, "b_only_correct": cc,
                                              "p_exact": mcnemar_exact(bb, cc)}
    S["success"] = succ
    S["failures"] = [{k: r[k] for k in ("model", "task", "arm", "rep")} | {"error": (r["agent_error_text"] or "")[:90],
                     "answer": r["grader"].get("answer"), "regraded_max_retry": r["regraded_max_retry"],
                     "wall_s": r["wall_s"]} for r in cells.values() if not r["correct"]]

    # RQ3: cost (proxy-side fields: complete for every run and the basis of $)
    cost = {}
    for a, b in COMPARISONS:
        for g, ms in groups:
            for name, field in COST:
                cost[f"{a}_vs_{b}|{g}|{name}"] = boot(pairs(cells, ms, a, b, set(tasks), value=lambda r, f=field: r[f]))
    per_solved = {}
    for g, ms in groups:
        for a in ARMS:
            rs = [r for k, r in cells.items() if k[0] in ms and k[2] == a]
            by_t = defaultdict(lambda: [0.0, 0])
            for r in rs:
                by_t[r["task"]][0] += r["proxy_spend"]
                by_t[r["task"]][1] += int(r["correct"])
            ts = sorted(by_t)
            usd = np.array([by_t[t][0] for t in ts])
            ok = np.array([by_t[t][1] for t in ts])
            idx = np.random.default_rng(SEED).integers(0, len(ts), size=(B, len(ts)))
            dist = usd[idx].sum(1) / np.maximum(ok[idx].sum(1), 1)
            lo, hi = np.percentile(dist, [2.5, 97.5])
            per_solved[f"{g}|{a}"] = {"total_usd": float(usd.sum()), "solved": int(ok.sum()),
                                      "usd_per_solved": float(usd.sum() / ok.sum()), "lo": float(lo), "hi": float(hi),
                                      "usd_per_run": float(usd.sum() / len(rs))}
    S["cost"] = cost
    S["usd_per_solved"] = per_solved
    S["token_source_check"] = {
        "usage_matches_proxy": sum(1 for r in cells.values() if r["in_tok"] == r["proxy_prompt_tokens"]
                                   and r["out_tok"] == r["proxy_completion_tokens"] and r["requests"] == r["proxy_reqs"]),
        "usage_missing": [[r["model"], r["task"], r["arm"], r["rep"]] for r in cells.values() if r["in_tok"] is None],
        "usage_differs": [[r["model"], r["task"], r["arm"], r["rep"], r["requests"], r["proxy_reqs"]]
                          for r in cells.values() if r["in_tok"] is not None and r["requests"] != r["proxy_reqs"]]}

    # RQ4: mechanism (arm on)
    mech = {}
    for g, ms in groups:
        rs = [r for k, r in cells.items() if k[0] in ms and k[2] == "on"]
        share = np.array([(r["saved_ms"] or 0) / 1000 / r["wall_s"] for r in rs])
        saved = np.array([(r["saved_ms"] or 0) / 1000 for r in rs])
        d_plain, d_off = [], []
        for r in rs:
            p, o = cells.get((r["model"], r["task"], "plain", r["rep"])), cells.get((r["model"], r["task"], "off", r["rep"]))
            if p:
                d_plain.append(r["wall_s"] - p["wall_s"])
            if o:
                d_off.append(r["wall_s"] - o["wall_s"])
        mech[g] = {"runs": len(rs), "hits": sum(r["hits"] or 0 for r in rs), "misses": sum(r["misses"] or 0 for r in rs),
                   "wasted": sum(r["wasted"] or 0 for r in rs), "runs_with_hits": int(sum((r["hits"] or 0) > 0 for r in rs)),
                   "saved_s_total": float(saved.sum()), "saved_s_mean": float(saved.mean()),
                   "eager_saved_s_total": float(sum((r["eager_saved_ms"] or 0) for r in rs) / 1000),
                   "wall_s_total": float(sum(r["wall_s"] for r in rs)),
                   "share_mean": float(share.mean()), "share_median": float(np.median(share)), "share_max": float(share.max()),
                   "share_of_total": float(saved.sum() / sum(r["wall_s"] for r in rs)),
                   "mean_diff_on_minus_plain_s": float(np.mean(d_plain)), "mean_diff_on_minus_off_s": float(np.mean(d_off))}
    S["mechanism"] = mech

    # RQ6: reliability
    rel = {}
    for g, ms in groups:
        for a in ARMS:
            rs = [r for k, r in cells.items() if k[0] in ms and k[2] == a]
            att = [r for r in data["recs"] if r["model"] in ms and r["arm"] == a]
            rel[f"{g}|{a}"] = {
                "runs": len(rs), "tool_errors": sum(r["tool_errors"] or 0 for r in rs),
                "runs_with_tool_errors": sum(1 for r in rs if r["tool_errors"]),
                "retry_prompts": sum(r["retry_prompts"] or 0 for r in rs),
                "run_code_max_retry_failures": sum(1 for r in rs if MAXRETRY in (r["agent_error_text"] or "")),
                "http_429_all_attempts": sum(r["http_429"] or 0 for r in att),
                "timeouts": sum(1 for r in att if r["timed_out"]),
                "invalid_attempts": sum(1 for r in att if not r.get("valid")),
                # The record flag is called "slept" (the runner was written on a Mac, where it caught
                # system sleep). It fires when wall-clock epoch time advances more than 2 s beyond
                # perf_counter during a run. The bench host does not sleep, so here it marks a clock stall.
                "clock_stall_attempts": sum(1 for r in att if "slept" in r["invalid_reasons"])}
    S["reliability"] = rel
    ex = data["extract"]
    kinds = {}
    for a in ARMS:
        rs = [r for k, r in cells.items() if k[2] == a]
        te, rp = Counter(), Counter()
        for r in rs:
            te.update(ex[r["run_dir"]]["tool_error_kinds"])
            rp.update(ex[r["run_dir"]]["retry_prompt_kinds"])
        kinds[a] = {"tool_errors": dict(te.most_common()), "retry_prompts": dict(rp.most_common())}
    S["error_kinds"] = kinds
    reqs, snip = {}, {}
    for g, ms in groups:
        for a in ARMS:
            rs = [r for k, r in cells.items() if k[0] in ms and k[2] == a]
            dur = [x for r in rs for x in ex[r["run_dir"]]["req_s"]]
            ttft = [x for r in rs for x in ex[r["run_dir"]]["ttft_s"]]
            reqs[f"{g}|{a}"] = {"runs": len(rs), "requests_per_run": float(np.mean([r["proxy_reqs"] for r in rs])),
                                "request_s_mean": float(np.mean(dur)), "request_s_median": float(np.median(dur)),
                                "ttft_s_mean": float(np.mean(ttft)),
                                "prompt_tokens_per_request": float(sum(r["proxy_prompt_tokens"] for r in rs)
                                                                   / sum(r["proxy_reqs"] for r in rs)),
                                "model_time_per_run_s": float(sum(dur) / len(rs))}
            if a == "off":
                continue
            sn = [x for r in rs for x in ex[r["run_dir"]]["wrapped_per_snippet"]]
            c = Counter(min(x, 4) for x in sn)
            snip[f"{g}|{a}"] = {"runs": len(rs), "snippets": len(sn), "snippets_per_run": len(sn) / len(rs),
                                "mean_wrapped": float(np.mean(sn)),
                                "share": {b: c[i] / len(sn) for i, b in enumerate(SNIPPET_BINS)}}
    S["requests"] = reqs
    S["wrapped_per_snippet"] = snip
    S["anomalies"] = {"touched_tests_pycache_only": sum(
        1 for r in cells.values() if r["grader"].get("touched_tests")
        and all("__pycache__" in f for f in r["grader"]["touched_tests"])),
        "touched_tests_real": [[r["model"], r["task"], r["arm"], r["rep"]] for r in cells.values()
                               if any("__pycache__" not in f for f in r["grader"].get("touched_tests") or [])],
        "leak_suspect": sum(1 for r in data["recs"] if r.get("leak_suspect")),
        "repo_modified": sum(1 for r in cells.values() if r["grader"].get("repo_modified")),
        "subagent_runs": sum(1 for r in cells.values() if r["subagent_runs"])}
    return S, groups


def launch_of(data, r):
    """Index of the runner launch that started this attempt (batch.json lines are local time, records UTC)."""
    t0 = ts(data["launches"][0])
    first = min(ts(x["start_utc"]) for x in data["recs"])
    off = round((first - t0) / 3600) * 3600
    st = ts(r["start_utc"]) - off
    return max(i for i, x in enumerate(data["launches"]) if ts(x) <= st + 1)


def outage_split_blocks(data):
    """Blocks (model, task, rep) whose valid cells were started under different runner launches."""
    by_block = defaultdict(set)
    for (m, t, a, rep), r in data["cells"].items():
        by_block[(m, t, rep)].add(launch_of(data, r))
    return {k for k, v in by_block.items() if len(v) > 1}


def run_history(data, split):
    recs, cells = data["recs"], data["cells"]
    productive = sorted({launch_of(data, r) for r in recs})
    h = {"launches": len(data["launches"]), "launch_times_local": data["launches"],
         "launches_that_started_runs": len(productive),
         "launches_without_runs": len(data["launches"]) - len(productive),
         "records": len(recs), "attempt_dirs": len(data["attempt_dirs"]),
         "attempt_dirs_without_record": sorted(set(data["attempt_dirs"]) - {r["run_dir"] for r in recs}),
         "outage_split_blocks": len(split),
         "valid_cells_on_attempt_2_plus": sum(1 for r in cells.values() if r["attempt"] > 1),
         "clock_stall_attempts": [{k: r[k] for k in ("model", "task", "arm", "rep", "attempt", "start_utc")}
                                  | {"gap_s": round((data["extract"][r["run_dir"]]["wall_epoch_s"] or 0) - r["wall_s"], 2)
                                     if data["extract"][r["run_dir"]]["wall_epoch_s"] is not None else None}
                                  for r in recs if "slept" in r["invalid_reasons"]]}
    return h


# ---------- outputs ----------

def ci(e, d=1):
    return f"{e['pct']:+.{d}f}% [{e['pct_lo']:+.{d}f}, {e['pct_hi']:+.{d}f}]"


def tables(S, groups):
    L = ["# main1 tables", "", "Generated by `scripts/analyze_main1.py` (seed 20261011, 10,000 task-clustered bootstrap "
         "resamples). Wall-clock effects are the mean of per-(task, rep) log ratios, shown as % change with 95% CI. "
         "Negative = faster / cheaper than the comparison arm.", ""]
    L += ["## Data", "", f"- record lines {S['data']['record_lines']}, parsed {S['data']['records_parsed']}, "
          f"unparseable {S['data']['unparseable_lines']}; lines containing NUL bytes: {S['data']['lines_with_nul_bytes']}; "
          f"records recovered from them: {S['data']['records_recovered_from_nul_lines']}",
          f"- valid cells {S['data']['valid_cells']} of {S['data']['expected_cells']}; missing: {S['data']['missing_cells'] or 'none'}",
          f"- invalid attempts: {[(x['model'], x['task'], x['arm'], x['rep'], x['invalid_reasons']) for x in S['data']['invalid_attempts']]}",
          f"- hosts {S['data']['hosts']}, code-puppy {S['data']['cp_versions']}", ""]
    h = S["run_history"]
    L += ["## Run history", "",
          f"- runner launches (runs/main1/batch.json): {h['launches']}; launches that started runs: "
          f"{h['launches_that_started_runs']}; launches that started no run: {h['launches_without_runs']}",
          f"- launch times (local): {', '.join(x[11:19] for x in h['launch_times_local'])}",
          f"- attempt dirs {h['attempt_dirs']}, records {h['records']}; dirs without a record: {h['attempt_dirs_without_record']}",
          f"- valid cells whose kept attempt is 2 or later: {h['valid_cells_on_attempt_2_plus']}",
          f"- blocks whose arms were started under different launches (outage-split): {h['outage_split_blocks']} "
          f"{S['outage_split_blocks']}",
          f"- clock-stall attempts (record flag `slept`): {h['clock_stall_attempts']}", ""]
    L += ["## Mean wall-clock per arm (valid runs)", "", "| model | arm | runs | geometric mean s | mean s | median s | "
          "min s | max s | tool-call parts | parts with streamed argument deltas |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for g, _ in groups:
        for a in ARMS:
            d = S["descriptive"][f"{g}|{a}"]
            L.append(f"| {NAME[g]} | {a} | {d['runs']} | {d['geo_mean_wall_s']:.1f} | {d['mean_wall_s']:.1f} | {d['median_wall_s']:.1f} | "
                     f"{d['min_wall_s']:.1f} | {d['max_wall_s']:.1f} | {d['tool_parts']:,} | {d['tool_parts_args_streamed']:,} |")
    L += ["", "## RQ1 and RQ5: wall-clock change (paired)", "", "| comparison | model | all tasks | gathering | code |",
          "|---|---|---|---|---|"]
    for a, b in COMPARISONS:
        for g, _ in groups:
            w = [S["wall"][f"{a}_vs_{b}|{g}|{f}"] for f in ("all", "gather", "code")]
            L.append(f"| {a} vs {b} | {NAME[g]} | {ci(w[0])} (n={w[0]['n_pairs']}) | {ci(w[1])} | {ci(w[2])} |")
    L += ["", "## Sensitivity checks (all tasks)", "",
          "| comparison | model | primary | correct-only | excl. first block | median | excl. recovered record | "
          "excl. outage-split blocks | agent time only |",
          "|---|---|---|---|---|---|---|---|---|"]
    for a, b in COMPARISONS:
        for g, _ in groups:
            s = S["sensitivity"][f"{a}_vs_{b}|{g}"]
            L.append(f"| {a} vs {b} | {NAME[g]} | " + " | ".join(
                ci(s[k]) for k in ("primary", "correct_only", "excl_first_block", "median", "excl_recovered_record",
                                   "excl_outage_split_blocks", "agent_time_only")) + " |")
    L += ["", "## RQ2: success (Wilson 95% CI)", "",
          "run_code max-retry exhaustion counts as a failure (docs/PLAN.md, frozen design); the grader's own verdict "
          "is in parentheses where it differs.", "", "| model | off | on | plain |", "|---|---|---|---|"]
    for g, _ in groups:
        cs = [S["success"][f"{g}|{a}"] for a in ARMS]
        L.append(f"| {NAME[g]} | " + " | ".join(
            f"{c['correct']}/{c['n']} = {c['rate']:.3f} [{c['lo']:.3f}, {c['hi']:.3f}]"
            + (f" (grader {c['correct_raw_grader']}/{c['n']})" if c["regraded_max_retry"] else "") for c in cs) + " |")
    L += ["", "| comparison | model | pairs | only first arm correct | only second arm correct | exact McNemar p |",
          "|---|---|---|---|---|---|"]
    for a, b in COMPARISONS:
        for g, _ in groups:
            m = S["success"][f"{a}_vs_{b}|{g}|mcnemar"]
            L.append(f"| {a} vs {b} | {NAME[g]} | {m['pairs']} | {m['a_only_correct']} | {m['b_only_correct']} | {m['p_exact']:.3f} |")
    L += ["", "Failed runs:", ""] + [f"- {f['model']} {f['task']} {f['arm']} r{f['rep']}: "
                                      f"{f['error'] or 'wrong answer ' + str(f['answer'])}"
                                      + (" [regraded per plan: hidden tests passed]" if f["regraded_max_retry"] else "")
                                      + f" (wall {f['wall_s']:.1f} s)" for f in S["failures"]]
    L += ["", "## RQ3: cost (paired ratios from proxy rows)", "",
          "| comparison | model | input tokens | output tokens | requests | proxy $ |", "|---|---|---|---|---|---|"]
    for a, b in COMPARISONS:
        for g, _ in groups:
            L.append(f"| {a} vs {b} | {NAME[g]} | " + " | ".join(ci(S["cost"][f"{a}_vs_{b}|{g}|{n}"]) for n, _ in COST) + " |")
    L += ["", "| model | arm | total $ | solved | $ per run | $ per solved task [95% CI] |", "|---|---|---|---|---|---|"]
    for g, _ in groups:
        for a in ARMS:
            p = S["usd_per_solved"][f"{g}|{a}"]
            L.append(f"| {NAME[g]} | {a} | {p['total_usd']:.4f} | {p['solved']} | {p['usd_per_run']:.5f} | "
                     f"{p['usd_per_solved']:.5f} [{p['lo']:.5f}, {p['hi']:.5f}] |")
    L += ["", "## RQ4: mechanism (arm on)", "", "| model | runs | hits | misses | wasted | saved s total | eager saved s total | "
          "wall s total | saved share of total wall | (saved + eager) share of total wall | mean per-run share | "
          "median per-run share | max per-run share | mean on-minus-plain s | mean on-minus-off s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g, _ in groups:
        m = S["mechanism"][g]
        L.append(f"| {NAME[g]} | {m['runs']} | {m['hits']} | {m['misses']} | {m['wasted']} | {m['saved_s_total']:.1f} | "
                 f"{m['eager_saved_s_total']:.2f} | {m['wall_s_total']:.0f} | {100 * m['share_of_total']:.2f}% | "
                 f"{100 * (m['saved_s_total'] + m['eager_saved_s_total']) / m['wall_s_total']:.2f}% | {100 * m['share_mean']:.2f}% | "
                 f"{100 * m['share_median']:.2f}% | {100 * m['share_max']:.2f}% | {m['mean_diff_on_minus_plain_s']:+.1f} | "
                 f"{m['mean_diff_on_minus_off_s']:+.1f} |")
    L += ["", "## Mechanism: model requests per run and per-request latency (proxy rows)", "",
          "| model | arm | runs | requests per run | mean request s | median request s | mean time to first token s | "
          "prompt tokens per request | model time per run s |", "|---|---|---|---|---|---|---|---|---|"]
    for g, _ in groups:
        for a in ARMS:
            q = S["requests"][f"{g}|{a}"]
            L.append(f"| {NAME[g]} | {a} | {q['runs']} | {q['requests_per_run']:.1f} | {q['request_s_mean']:.2f} | "
                     f"{q['request_s_median']:.2f} | {q['ttft_s_mean']:.2f} | {q['prompt_tokens_per_request']:,.0f} | "
                     f"{q['model_time_per_run_s']:.1f} |")
    L += ["", "## Mechanism: wrapped tool calls per run_code snippet", "",
          "Wrapped tool executions seen by the post-tool hook between consecutive run_code completions "
          "(speculative launches included; native create_file / replace_in_file and rejected native calls excluded).", "",
          "| model | arm | runs | snippets | snippets per run | mean wrapped calls | 0 | 1 | 2 | 3 | 4+ |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g, _ in groups:
        for a in ("on", "plain"):
            w = S["wrapped_per_snippet"][f"{g}|{a}"]
            L.append(f"| {NAME[g]} | {a} | {w['runs']} | {w['snippets']} | {w['snippets_per_run']:.1f} | {w['mean_wrapped']:.2f} | "
                     + " | ".join(f"{100 * w['share'][b]:.0f}%" for b in SNIPPET_BINS) + " |")
    L += ["", "## RQ6: reliability", "", "| model | arm | runs | tool errors (runs with any) | retry prompts | run_code max-retry failures | "
          "429s | timeouts | invalid attempts (clock stalls) |", "|---|---|---|---|---|---|---|---|---|"]
    for g, _ in groups:
        for a in ARMS:
            r = S["reliability"][f"{g}|{a}"]
            L.append(f"| {NAME[g]} | {a} | {r['runs']} | {r['tool_errors']} ({r['runs_with_tool_errors']}) | {r['retry_prompts']} | "
                     f"{r['run_code_max_retry_failures']} | {r['http_429_all_attempts']} | {r['timeouts']} | "
                     f"{r['invalid_attempts']} ({r['clock_stall_attempts']}) |")
    for kind, title in (("tool_errors", "Error-like tool results by kind (all models)"),
                        ("retry_prompts", "Retry prompts by kind (all models)")):
        allk = sorted({k for a in ARMS for k in S["error_kinds"][a][kind]},
                      key=lambda k: -sum(S["error_kinds"][a][kind].get(k, 0) for a in ARMS))
        L += ["", f"### {title}", "", "| kind | off | on | plain |", "|---|---|---|---|"]
        for k in allk:
            L.append(f"| {k} | " + " | ".join(str(S["error_kinds"][a][kind].get(k, 0)) for a in ARMS) + " |")
        L.append("| total | " + " | ".join(str(sum(S["error_kinds"][a][kind].values())) for a in ARMS) + " |")
    L += ["", "## Checks", "", f"- token source: {S['token_source_check']}", f"- anomalies: {S['anomalies']}", ""]
    (OUT / "main1_tables.md").write_text("\n".join(L))


def forest(S, groups, by_family, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401
    color = {"proxy-deepseek-flash": "#2a78d6", "proxy-deepseek-v4-pro": "#eb6834", "proxy-zai-g47": "#1baf7a",
             "pooled": "#3d3d3a"}
    fams = [("gather", "gathering"), ("code", "code")] if by_family else [("all", "")]
    rows = [(g, f, fl) for g, _ in groups for f, fl in fams]
    vals = [S["wall"][f"{a}_vs_{b}|{g}|{f}"] for a, b in COMPARISONS for g, f, _ in rows]
    lo = min(v["pct_lo"] for v in vals)
    hi = max(v["pct_hi"] for v in vals)
    pad = (hi - lo) * 0.08
    h = 0.42 * len(rows) + 0.9
    fig, axes = plt.subplots(3, 1, figsize=(7, 3 * h), sharex=True)
    for ax, (a, b) in zip(axes, COMPARISONS):
        for i, (g, f, fl) in enumerate(rows):
            e = S["wall"][f"{a}_vs_{b}|{g}|{f}"]
            y = len(rows) - 1 - i
            ax.plot([e["pct_lo"], e["pct_hi"]], [y, y], color=color[g], lw=2, solid_capstyle="round")
            ax.plot(e["pct"], y, "o", ms=8 if g == "pooled" else 7, color=color[g])
            ax.text(1.02, y, f"{round(e['pct']):+d}%  [{round(e['pct_lo']):+d}, {round(e['pct_hi']):+d}]",
                    transform=ax.get_yaxis_transform(), va="center", fontsize=9.5, color="#333333")
        ax.axvline(0, color="#888888", lw=1)
        labels = [NAME[g] + (f", {fl}" if fl else "") for g, f, fl in rows]
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(labels[::-1], fontsize=10)
        ax.set_title(CMP_LABEL[(a, b)], loc="left", fontsize=11.5, fontweight="bold", color="#111111")
        ax.set_xlim(lo - pad, hi + pad)
        ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(25))
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", color="#e6e6e3", lw=0.8)
        ax.set_axisbelow(True)
    axes[-1].set_xlabel("Wall-clock change, %  (left of 0 = faster)\n"
                        "mean paired log ratio, 95% CI clustered by task", fontsize=10)
    fig.suptitle("main1: wall-clock effect" + (" by task family" if by_family else ""), x=0.02, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 0.87, 0.97))
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def main(path):
    OUT.mkdir(parents=True, exist_ok=True)
    data = load(path)
    S, groups = analyze(data)
    (OUT / "main1_summary.json").write_text(json.dumps(S, indent=1) + "\n")
    tables(S, groups)
    forest(S, groups, False, OUT / "main1_forest.png")
    forest(S, groups, True, OUT / "main1_forest_family.png")
    for a, b in COMPARISONS:
        for g, _ in groups:
            print(f"{a} vs {b:5s} {NAME[g]:18s} {ci(S['wall'][f'{a}_vs_{b}|{g}|all'])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "runs" / "main1" / "records.jsonl")

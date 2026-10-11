#!/usr/bin/env python3
"""Summarize run dirs into one JSON line each (and optional JSONL file).
Usage: summarize.py [--jsonl OUT] <run_dir> ...   Each run dir needs meta.json; capture/usage optional.
Expected answers are looked up as tasks/<task>.expected from meta.prompt_file.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from grade import grade  # noqa: E402


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:  # noqa: BLE001
        return {}


def summarize(d):
    m = load(Path(d, "meta.json"))
    g = grade(d, str(Path(m["prompt_file"]).with_suffix(".expected")))
    r = metrics(d)
    r.update(task=Path(m["prompt_file"]).stem, correct=g["correct"], answer=g["answer"])
    return r


def retry_prompts(d):
    """pydantic-ai RetryPromptPart count in the headless transcript (malformed/rejected tool calls)."""
    n = 0
    for f in Path(d, "transcript").glob("auto_session_*.json") if Path(d, "transcript").is_dir() else []:
        if not f.name.endswith("_meta.json"):
            n += f.read_text(errors="replace").count('"part_kind": "retry-prompt"')
    return n


def metrics(d):
    """Everything about a run except grading (timings, tokens, counters, reliability signals)."""
    m, c, u = load(Path(d, "meta.json")), load(Path(d, "capture.json")), load(Path(d, "usage.json"))
    runs = [r for r in c.get("runs", []) if r.get("agent")]
    main = runs[0] if runs else {}
    boot = None
    if c.get("t0_epoch") and m.get("start_epoch") and main.get("start_s") is not None:
        boot = round(c["t0_epoch"] - m["start_epoch"] + main["start_s"], 3)
    agent_s = round(main["end_s"] - main["start_s"], 3) if main.get("end_s") else None
    sf = c.get("spec_final") or {}
    parts = c.get("tool_parts", [])
    reqs = m.get("proxy_requests") or []
    ttft = [r for r in reqs if r.get("first_token")]
    import datetime as dt
    span = (dt.datetime.fromisoformat(m["end_utc"]) - dt.datetime.fromisoformat(m["start_utc"])).total_seconds()
    slept = m.get("slept", (span - m["wall_s"]) > 2.0)  # utc span vs perf_counter (stops in sleep)
    so = Path(d, "stdout.txt").read_text(errors="replace") if Path(d, "stdout.txt").exists() else ""
    return {
        "dir": str(d), "slept": slept,
        "http_retries": so.count("HTTP retry:"),
        "http_429": so.count("HTTP retry: 429"),
        "stream_retries": so.count("(attempt ") - so.count("HTTP retry:"),
        "proxy_failures": sum(1 for r in (m.get("proxy_requests") or []) if r.get("status") == "failure"),
        "agent_error": "Error executing prompt" in so, "model": m["model"], "arm": m["arm"],
        "wall_s": m["wall_s"], "boot_s": boot, "agent_s": agent_s,
        "teardown_s": round(m["wall_s"] - boot - agent_s, 3) if boot and agent_s else None,
        "exit": m["exit_code"], "timed_out": m["timed_out"],
        "run_success": main.get("success"), "run_error": main.get("error"),
        "response_text": main.get("response_text"), "usage_present": bool(u),
        "requests": u.get("requests"), "in_tok": u.get("input_tokens"), "out_tok": u.get("output_tokens"),
        "cache_read": u.get("cache_read_tokens"), "tool_calls": u.get("tool_calls"),
        "proxy_reqs": len(reqs), "proxy_spend": m.get("proxy_spend_usd"),
        "hits": sf.get("hits"), "misses": sf.get("misses"), "wasted": sf.get("wasted"),
        "saved_ms": sf.get("saved_ms"), "eager_saved_ms": sf.get("eager_saved_ms"),
        "spec_events": {k: v["n"] for k, v in c.get("spec_events", {}).items()},
        "tool_parts": len(parts), "run_code_parts": sum(p["tool"] == "run_code" for p in parts),
        "parts_args_streamed": sum(p["arg_deltas"] > 1 for p in parts),
        "max_arg_deltas": max([p["arg_deltas"] for p in parts], default=0),
        "tool_errors": sum(1 for t in c.get("tool_calls", []) if t.get("error_like")),
        "subagent_runs": len(runs) - 1 if runs else 0,
        "retry_prompts": retry_prompts(d),
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if args and args[0] == "--jsonl":
        out, args = args[1], args[2:]
    rows = [summarize(d) for d in args]
    for r in rows:
        print(json.dumps(r))
    if out:
        with open(out, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

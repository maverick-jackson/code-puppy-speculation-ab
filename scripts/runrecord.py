"""Execute one (model, task, arm, rep, attempt) run end to end and build its JSON record.

execute(): fresh HOME clone + fresh working copy, run_one.run() (the only timed part), grade,
  save the agent's diff, write partial.json (record minus proxy fields) into the run dir.
finalize(): attach this model's LiteLLM rows (written late by the proxy, so call it >= 60 s after
  the run), recompute metrics, decide validity, return the full record.
"""
import json
import platform
import sys
import shutil
import tempfile
import subprocess
import time
from argparse import Namespace
from pathlib import Path

import collect_spend
import run_one
import tasklib
from summarize import metrics

ROOT = Path(__file__).resolve().parent.parent
HOMES = ROOT / "runs" / "homes"
# Per-run HOMEs and working copies live OUTSIDE the project tree: in smoke1 an agent walked up
# from its cwd (runs/<batch>/_work/...) and read tasks/code/*/hidden/test_hidden.py and
# reference.patch. System temp is far from the repo and its path does not name the experiment.
SCRATCH = Path(tempfile.gettempdir()) / "pupbench"


def scratch_for(batch, model):
    return SCRATCH / batch.replace("/", "_") / model
# code-puppy model name -> LiteLLM_SpendLogs.model, and the budget provider it bills to.
PROXY_MODEL = {
    "proxy-deepseek-flash": ("deepseek/deepseek-chat", "deepseek"),
    "proxy-deepseek-v4-pro": ("deepseek/deepseek-v4-pro", "deepseek"),
    "proxy-zai-g47": ("zai/glm-4.7", "zai"),
}
LEAK_MARKERS = ("tasks/code", "tasks/gather", "test_hidden", "reference.patch", "bug.patch")
DETAIL_KEEP = ("answer", "expected", "fields_ok", "reason", "repo_modified", "pytest_rc", "pytest_summary",
               "diff_stat", "touched_tests")


def run_dir_for(batch_dir, model, task_id, rep, arm, attempt):
    return Path(batch_dir) / model / task_id / f"r{rep}" / arm / f"a{attempt}"


def power_state():
    if sys.platform != "darwin":
        return "AC"  # desktop bench box: mains only
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    return "AC" if "AC Power" in out.splitlines()[0] else "battery"


def lid_closed():
    """True when the MacBook lid is closed: macOS then sleeps (clamshell) regardless of caffeinate
    unless an external display is attached, so a timed run must not start."""
    if sys.platform != "darwin":
        return False
    out = subprocess.run(["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"],
                         capture_output=True, text=True).stdout
    return '"AppleClamshellState" = Yes' in out


def _leak(rd):
    text = ""
    for f in [rd / "stdout.txt", *sorted((rd / "transcript").glob("*.json"))] if (rd / "transcript").is_dir() else [rd / "stdout.txt"]:
        if f.exists():
            text += f.read_text(errors="replace")
    return sorted({m for m in LEAK_MARKERS if m in text})


def execute(batch_dir, task, model, arm, rep, attempt, ctx):
    """ctx: dict(batch, seed, block_seed, arm_order, order_pos, block_index, timeout, allow_battery)."""
    batch_dir = Path(batch_dir)
    rd = run_dir_for(batch_dir, model, task["id"], rep, arm, attempt)
    if rd.exists():
        shutil.rmtree(rd)
    rd.mkdir(parents=True)
    home = scratch_for(ctx["batch"], model) / "home"
    if home.exists():
        shutil.rmtree(home)
    home.parent.mkdir(parents=True, exist_ok=True)
    tmpl = HOMES / ("off" if arm == "off" else "on")
    subprocess.run(tasklib.clone_cmd(tmpl, home), check=True)
    work = tasklib.prepare_work(task, scratch_for(ctx["batch"], model) / "work")
    (rd / "prompt.txt").write_text(task["prompt"] + "\n")
    power = power_state()
    meta = run_one.run(Namespace(home=str(home), arm=arm, model=model, cwd=str(work),
                                 prompt_file=str(rd / "prompt.txt"), out_dir=str(rd),
                                 timeout=ctx["timeout"]))
    stdout = (rd / "stdout.txt").read_text(errors="replace")
    t0 = time.time()
    correct, detail = tasklib.grade(task, stdout, work)
    grade_s = round(time.time() - t0, 2)
    if task["family"] == "code":
        stat, full = tasklib.work_diff(work)
        (rd / "agent.diff").write_text(full)
        detail["diff_stat"] = stat.strip().splitlines()[-1:] if stat.strip() else []
        files = [ln.split(" b/")[-1] for ln in full.splitlines() if ln.startswith("diff --git ")]
        detail["touched_tests"] = [f for f in files if f.startswith("tests/") or "/test_" in f or f.startswith("test_")]
    (rd / "grade.json").write_text(json.dumps(dict(detail, correct=correct), indent=1))
    partial = {
        "batch": ctx["batch"], "model": model, "task": task["id"], "family": task["family"],
        "arm": arm, "rep": rep, "attempt": attempt, "order_pos": ctx["order_pos"],
        "block_index": ctx["block_index"], "arm_order": ctx["arm_order"], "seed": ctx["seed"],
        "block_seed": ctx["block_seed"], "cp_version": meta.get("cp_version"),
        "start_utc": meta["start_utc"], "end_utc": meta["end_utc"], "end_epoch": meta["end_epoch"],
        "power": power, "host": platform.node(), "allow_battery": ctx["allow_battery"], "correct": correct,
        "grader": {k: v for k, v in detail.items() if k in DETAIL_KEEP},
        "grade_s": grade_s, "leak_suspect": _leak(rd), "run_dir": str(rd.relative_to(ROOT)),
    }
    (rd / "partial.json").write_text(json.dumps(partial, indent=1))
    return partial


# Agent errors that are the AGENT failing the task (valid outcome, counted as a failure and a
# reliability event), as opposed to infrastructure errors (provider/proxy/network: invalid, retried).
TASK_FAILURE_ERRORS = ("exceeded max retries count", "UsageLimitExceeded", "request_limit")


def agent_error_text(rd):
    so = Path(rd, "stdout.txt").read_text(errors="replace") if Path(rd, "stdout.txt").exists() else ""
    i = so.rfind("Error executing prompt:")
    return so[i:i + 300].strip() if i >= 0 else None


def invalid_reasons(m, proxy_known=True, err=None):
    """Infra problems that make a run unusable as a TIMING sample (task failures are valid)."""
    r = []
    task_fail = bool(err) and any(k in err for k in TASK_FAILURE_ERRORS)
    if m.get("slept"):
        r.append("slept")
    if m.get("http_retries"):
        r.append("http_retry")
    if m.get("stream_retries", 0) > 0:
        r.append("stream_retry")
    if m.get("agent_error") and not task_fail:
        r.append("agent_error")
    if not m.get("usage_present") and not m.get("timed_out") and not task_fail:
        r.append("no_usage")
    if proxy_known and m.get("proxy_failures"):
        r.append("proxy_failure")
    if m.get("timed_out") and r:
        r.append("timeout_infra")
    return r


def quick_invalid(partial):
    """Validity from local signals only (before proxy rows exist)."""
    rd = ROOT / partial["run_dir"]
    return invalid_reasons(metrics(rd), proxy_known=False, err=agent_error_text(rd))


def finalize(partial, force=False):
    """Full record, or None while the proxy rows are not written yet (unless force)."""
    rd = ROOT / partial["run_dir"]
    proxy_model = PROXY_MODEL.get(partial["model"], (None, None))[0]
    collect_spend.attach(rd, proxy_model)
    m = metrics(rd)
    missing = bool(m.get("requests") and not m.get("proxy_reqs"))
    if missing and not force:
        return None
    tr = sorted((rd / "transcript").glob("auto_session_*[0-9].json")) if (rd / "transcript").is_dir() else []
    rec = dict(partial)
    rec.pop("end_epoch", None)
    for k in ("wall_s", "boot_s", "agent_s", "teardown_s", "slept", "timed_out", "requests",
              "in_tok", "out_tok", "cache_read", "tool_calls", "proxy_reqs", "proxy_spend", "hits",
              "misses", "wasted", "saved_ms", "eager_saved_ms", "tool_parts", "run_code_parts",
              "parts_args_streamed", "max_arg_deltas", "tool_errors", "retry_prompts", "http_429",
              "http_retries", "stream_retries", "proxy_failures", "agent_error", "run_success",
              "subagent_runs", "spec_events"):
        rec[k] = m.get(k)
    meta = json.loads((rd / "meta.json").read_text())
    rec["exit_code"] = meta.get("exit_code")
    rec["proxy_prompt_tokens"] = meta.get("proxy_prompt_tokens")
    rec["proxy_completion_tokens"] = meta.get("proxy_completion_tokens")
    rec["proxy_foreign_rows"] = meta.get("proxy_foreign_rows")
    rec["transcript"] = str(tr[0].relative_to(ROOT)) if tr else None
    rec["agent_error_text"] = agent_error_text(rd)
    rec["invalid_reasons"] = invalid_reasons(m, err=rec["agent_error_text"])
    if rec.get("leak_suspect"):
        rec["invalid_reasons"].append("leak")  # agent saw task-suite files: answer not independent
    # subagent_runs > 0 is kept as a flag, not an exclusion: capture only sees the main agent.
    rec["proxy_missing"] = missing  # spend unknown for this run (timing still usable)
    rec["valid"] = not rec["invalid_reasons"]
    return rec

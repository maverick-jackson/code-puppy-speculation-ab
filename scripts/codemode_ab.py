#!/usr/bin/env python3
"""Code-mode A/B runner for code-puppy builds: one headless run per (task, model, variant, rep).

Each variant is a code-puppy binary (--bin VARIANT=PATH, e.g. a venv per git checkout). Variants
listed in --off run with enable_speculative_code_mode = false; all others run with it on.

Isolation per run: fresh working copy (tasklib.prepare_work) and private XDG config / cache /
state / data dirs with a minimal puppy.cfg. From ~/.code_puppy only OAuth credentials and model
lists are shared. ChatGPT: symlinks (its token file is rewritten in place, so a refresh updates the
real file instead of forking the refresh token). Claude Code: a copy of the token file without the
refresh token (its store saves by atomic rename), with the real token refreshed by the runner
through the plugin when it would expire during a run. `model =` is pinned in the config so sub-agents
use the run's model. Grading uses the transcript's final text (rendered stdout wraps long lines);
the transcript, every sub-agent session and a record.json are kept per run, and one line per run
is appended to runs/codemode/<batch>/records.jsonl.

Usage:
  codemode_ab.py --batch NAME --bin off=/a/code-puppy --bin new=/b/code-puppy --off off \\
      --models codex-gpt-6.1-sol,codex-gpt-6-luna [--tasks id,..] [--reps N] [--jobs N]
Finished runs (record.json present) are skipped, so an interrupted batch can be resumed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import tasklib  # noqa: E402
from cm_transcripts import final_response_text, subagent_summary, transcript_metrics  # noqa: E402
from longtasks import grade as grade_task  # noqa: E402

OUT = ROOT / "runs" / "codemode"
REAL_DATA = Path.home() / ".code_puppy"
SHARED_DATA = ("chatgpt_oauth.json", "chatgpt_models.json")
# Claude Code OAuth saves tokens by atomic rename, which would replace a symlink, so Claude runs get
# a COPY of the token file with the refresh token removed: a run can use the access token but can
# never rotate the real refresh token. The real token is kept fresh by refresh_claude_token().
CLAUDE_TOKEN, CLAUDE_MODELS = "claude_code_oauth.json", "claude_models.json"
CLAUDE_LOCK = threading.Lock()
REFRESH = """
from code_puppy_core_plugins.claude_code_oauth import utils
print("refreshed" if utils.refresh_access_token(force=True) else "refresh failed")
"""
CFG = """[puppy]
model = {model}
puppy_name = Biscuit
owner_name = Mike
yolo_mode = true
auto_save_session = true
enable_speculative_code_mode = {code_mode}
kennel_enabled = false
skills_enabled = false
smart_grep = off
enable_dbos = false
enable_universal_constructor = false
enable_logfire_sessions = false
openai_reasoning_effort = low
openai_verbosity = low
lock_builtin_plugins = true
"""
LOCK = threading.Lock()


def claude_minutes_left() -> float:
    tokens = json.loads((REAL_DATA / CLAUDE_TOKEN).read_text())
    return (float(tokens.get("expires_at") or 0) - time.time()) / 60


def ensure_claude_token(python: str, need_minutes: float) -> None:
    """Refresh the REAL Claude token (plugin code, real data dir, its file lock) if it would expire mid-run."""
    with CLAUDE_LOCK:
        if claude_minutes_left() >= need_minutes:
            return
        env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "VIRTUAL_ENV", "CODE_PUPPY"))}
        out = subprocess.run([python, "-c", REFRESH], env=env, capture_output=True, text=True, timeout=120)
        left = claude_minutes_left()
        print(f"claude token: {out.stdout.strip() or out.stderr.strip()[-200:]}; {left:.0f} min left", flush=True)
        if left < need_minutes:
            raise RuntimeError(f"Claude token has {left:.0f} min left, run needs {need_minutes:.0f}")


def install_claude_credentials(datadir: Path) -> None:
    tokens = json.loads((REAL_DATA / CLAUDE_TOKEN).read_text())
    tokens.pop("refresh_token", None)
    (datadir / CLAUDE_TOKEN).write_text(json.dumps(tokens))
    (datadir / CLAUDE_TOKEN).chmod(0o600)
    shutil.copy2(REAL_DATA / CLAUDE_MODELS, datadir / CLAUDE_MODELS)


def run_one(task: dict, model: str, variant: str, rep: int, a: argparse.Namespace) -> dict:
    if model.startswith("claude-code-"):
        ensure_claude_token(str(Path(a.bins[variant]).parent / "python"), a.timeout / 60 + 10)
    tmp = Path(tempfile.mkdtemp(prefix=f"cmab_{variant}_"))
    xdg = {k: tmp / k.lower() for k in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME")}
    cfgdir, datadir = xdg["XDG_CONFIG_HOME"] / "code_puppy", xdg["XDG_DATA_HOME"] / "code_puppy"
    cfgdir.mkdir(parents=True)
    datadir.mkdir(parents=True)
    (cfgdir / "puppy.cfg").write_text(CFG.format(model=model, code_mode=str(variant not in a.off).lower()))
    for name in SHARED_DATA:
        (datadir / name).symlink_to(REAL_DATA / name)
    if model.startswith("claude-code-"):
        install_claude_credentials(datadir)
    work = tasklib.prepare_work(task, tmp / "work")
    rd = OUT / a.batch / model / task["id"] / variant / f"r{rep}"
    rd.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "VIRTUAL_ENV", "CODE_PUPPY"))}
    env.update({k: str(v) for k, v in xdg.items()})
    env.update(NO_VERSION_UPDATE="1", NO_COLOR="1",
               PATH=str(ROOT / ".venv" / "bin") + os.pathsep + os.environ.get("PATH", ""))
    cmd = [a.bins[variant], "-p", task["prompt"], "-m", model, "--yolo", "true",
           "--disable-ask-user-question", "--usage-file", str(rd / "usage.json")]
    t0, timed_out = time.time(), False
    with open(rd / "stdout.txt", "w") as fo, open(rd / "stderr.txt", "w") as fe:
        proc = subprocess.Popen(cmd, cwd=work, env=env, stdout=fo, stderr=fe,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            proc.wait(timeout=a.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, 9)
            proc.wait()
    wall = time.time() - t0
    autos = sorted((xdg["XDG_CACHE_HOME"] / "code_puppy" / "autosaves").glob("auto_session_*[0-9].json"))
    final = final_response_text(autos[-1]) if autos else ""
    stdout = (rd / "stdout.txt").read_text(errors="replace")
    correct, detail = grade_task(task, final or stdout, work)
    rec = dict(batch=a.batch, model=model, task=task["id"], family=task["family"], variant=variant, rep=rep,
               wall_s=round(wall, 1), exit=proc.returncode, timed_out=timed_out, correct=bool(correct),
               grade_reason=detail.get("reason") or detail.get("pytest_summary"),
               # gather: per answer field; long code: per hidden test file; short code: its one test file
               fields_ok=detail.get("fields_ok") or detail.get("parts_ok") or
               ([bool(correct)] if task["family"] == "code" else []))
    if autos:
        shutil.copy2(autos[-1], rd / "transcript.json")
        rec.update(transcript_metrics(autos[-1]))
    else:
        rec["no_transcript"] = True
    sub_dir = datadir / "subagent_sessions"
    subs = [s for s in sorted(sub_dir.glob("*.json")) if not s.name.endswith("_meta.json")] if sub_dir.exists() else []
    if subs:
        (rd / "subagents").mkdir(exist_ok=True)
        for s in subs:
            shutil.copy2(s, rd / "subagents" / s.name)
        rec["sub"] = subagent_summary(subs)
    (rd / "record.json").write_text(json.dumps(rec, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)
    with LOCK, open(OUT / a.batch / "records.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps({k: rec.get(k) for k in ("model", "task", "variant", "rep", "wall_s", "correct",
                                              "requests", "nested")}), flush=True)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--bin", action="append", required=True, metavar="VARIANT=PATH")
    ap.add_argument("--off", default="off", help="comma-separated variants run with code mode disabled")
    ap.add_argument("--models", required=True)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    a.bins = dict(b.split("=", 1) for b in a.bin)
    a.off = set(filter(None, a.off.split(",")))
    tasks = tasklib.load_tasks([t for t in a.tasks.split(",") if t] or None)
    (OUT / a.batch).mkdir(parents=True, exist_ok=True)
    jobs = [(t, m, v, r) for t in tasks.values() for m in a.models.split(",") for v in a.bins
            for r in range(a.reps) if not (OUT / a.batch / m / t["id"] / v / f"r{r}" / "record.json").exists()]
    print(f"{len(jobs)} runs to do", flush=True)
    random.Random(a.seed).shuffle(jobs)
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for f in cf.as_completed([ex.submit(run_one, t, m, v, r, a) for t, m, v, r in jobs]):
            if f.exception():
                print("RUN FAILED:", repr(f.exception()), flush=True)


if __name__ == "__main__":
    main()

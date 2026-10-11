#!/usr/bin/env python3
"""Run ONE headless code-puppy task in an isolated HOME and record everything.

Must be started with LITELLM_MASTER_KEY already in the environment (see run_batch.sh),
so that key decryption is NOT inside the timed window. Never prints the key.

Writes into --out-dir:
  meta.json      wall-clock, exit code, arm, model, cmd (no secrets); proxy rows are added
                 later by collect_spend.py (LiteLLM writes spend logs asynchronously, ~10s+)
  stdout.txt / stderr.txt   (key redacted)
  usage.json     code-puppy --usage-file output
  capture.json   spec_capture plugin output
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CP_BIN = os.path.expanduser("~/rig/tools/bin/code-puppy")
CP_SITE = Path(os.path.expanduser("~/rig/tools/uv/code-puppy/lib/python3.14/site-packages"))
AGENT_VENV_BIN = Path(__file__).resolve().parent.parent / ".venv" / "bin"


def installed_cp_version():
    """code-puppy version from the installed dist-info (no process start, no network)."""
    found = sorted(CP_SITE.glob("code_puppy-*.dist-info"))
    return found[0].name[len("code_puppy-"):-len(".dist-info")] if len(found) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--arm", required=True, choices=["off", "on", "plain", "eager"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    meta = run(ap.parse_args())
    print(json.dumps({k: meta.get(k) for k in ("arm", "model", "wall_s", "slept", "exit_code")}))


def run(a):
    """a: namespace with home, arm, model, cwd, prompt_file, out_dir, timeout. Returns meta dict."""
    key = os.environ.get("LITELLM_MASTER_KEY")
    if not key:
        sys.exit("LITELLM_MASTER_KEY not in env; launch via run_batch.sh")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prompt = Path(a.prompt_file).read_text().strip()

    env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
    env.update(
        HOME=os.path.abspath(a.home),
        NO_VERSION_UPDATE="1",
        CODE_PUPPY_NO_SPLASH="1",
        CODE_PUPPY_SKIP_TUTORIAL="1",
        CODE_PUPPY_NO_TUI="1",
        NO_COLOR="1",
        SPEC_CAPTURE_OUT=str(out.resolve() / "capture.json"),
        # Same python+pytest for the agent in every arm (system python3 has no pytest).
        PATH=str(AGENT_VENV_BIN) + os.pathsep + os.environ.get("PATH", ""),
    )
    if a.arm in ("plain", "eager"):  # need a home built with speculation on
        env["SPEC_ARM"] = "codemode_" + a.arm
    else:
        env.pop("SPEC_ARM", None)
    cmd = [CP_BIN, "-p", prompt, "-m", a.model, "--yolo", "true",
           "--usage-file", str(out.resolve() / "usage.json")]

    start_utc = dt.datetime.utcnow()
    start_epoch = time.time()
    t0 = time.perf_counter()
    timed_out = False
    # Output to files (not pipes) and kill the whole process group on timeout, so a sandbox
    # grandchild (monty) can never keep us blocked. Timeout is checked against the WALL clock:
    # on macOS perf_counter/monotonic stop while the machine sleeps.
    import signal
    with open(out / "stdout.raw", "w") as fo, open(out / "stderr.raw", "w") as fe:
        proc = subprocess.Popen(cmd, cwd=a.cwd, env=env, stdout=fo, stderr=fe,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        while proc.poll() is None:
            if time.time() - start_epoch > a.timeout:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                break
            time.sleep(0.05)
    rc = proc.returncode
    so = (out / "stdout.raw").read_text(errors="replace")
    se = (out / "stderr.raw").read_text(errors="replace")
    (out / "stdout.raw").unlink()
    (out / "stderr.raw").unlink()
    wall = time.perf_counter() - t0
    wall_epoch = time.time() - start_epoch
    end_utc = dt.datetime.utcnow()

    so, se = so.replace(key, "REDACTED"), se.replace(key, "REDACTED")
    # Headless always persists the session (even with auto_save_session=false): keep it as transcript.
    import shutil
    asd = Path(a.home, ".code_puppy", "autosaves")
    for f in sorted(asd.glob("auto_session_*.json")) if asd.is_dir() else []:
        if f.stat().st_mtime >= start_epoch:
            (out / "transcript").mkdir(exist_ok=True)
            shutil.copy2(f, out / "transcript" / f.name)
    (out / "stdout.txt").write_text(so)
    (out / "stderr.txt").write_text(se)
    meta = {
        "arm": a.arm, "model": a.model, "cwd": a.cwd, "prompt_file": a.prompt_file,
        "start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat(),
        "wall_s": round(wall, 3), "wall_epoch_s": round(wall_epoch, 3),
        # perf_counter excludes system sleep; a gap means the Mac slept mid-run: discard the run.
        "slept": (wall_epoch - wall) > 2.0, "exit_code": rc, "timed_out": timed_out,
        "cmd": [c if c != prompt else "<prompt>" for c in cmd],
        "start_epoch": start_epoch, "end_epoch": time.time(), "cp_version": installed_cp_version(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


if __name__ == "__main__":
    main()

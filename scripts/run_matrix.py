#!/usr/bin/env python3
"""Batch runner: models x tasks x arms x reps as paired, randomized blocks.

Launch via scripts/run_matrix.sh (decrypts the proxy key once, outside every timed window).
- Block = (model, task, rep): all arms back to back in a seeded random order (seed per block is
  derived from --seed, so a resumed batch replays the same orders). Block order is shuffled too.
- One worker thread per model; at most --parallel models run at once; never two runs of one model.
- Records: runs/<batch>/records.jsonl, one line per ATTEMPT (valid or not). Resumable: a cell
  (model, task, arm, rep) with a valid record, or with --max-attempts attempts, is skipped.
  Invalid (infra) attempts are retried: immediately when local signals show it, else after proxy
  rows arrive (single-arm retry at the end of that model's queue).
- Guards before every block: code-puppy version (abort batch on mismatch), AC power (poll every
  60 s unless --allow-battery, smoke only), per-provider spend cap (stop that model's worker).
  Before every run: lid open (a closed lid sleeps the Mac even under caffeinate) and power.
- The whole process runs under `caffeinate -dimsu -w <pid>`.
"""
import argparse
import datetime as dt
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import collect_spend  # noqa: E402
import run_one  # noqa: E402
import runrecord  # noqa: E402
import tasklib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS = ["proxy-deepseek-flash", "proxy-deepseek-v4-pro", "proxy-zai-g47"]
PRIOR_COST = {"proxy-deepseek-flash": 0.006, "proxy-deepseek-v4-pro": 0.03, "proxy-zai-g47": 0.04}
SPEND_LAG_S = 60

LOCK = threading.Lock()
ABORT = threading.Event()
PENDING_EST = {}  # provider -> estimated $ of runs whose proxy rows are not collected yet


def log(batch_dir, msg):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    with LOCK:
        print(line, flush=True)
        with open(batch_dir / "matrix.log", "a") as f:
            f.write(line + "\n")


def load_records(path):
    recs = []
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            line = line.replace("\x00", "").strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                # Torn tail from a hard power-off of the WSL VM; that cell is simply re-run.
                print(f"skipping torn record line in {path}", file=sys.stderr)
    return recs


def append_record(path, rec):
    with LOCK:
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())


class Worker(threading.Thread):
    def __init__(self, model, blocks, a, tasks, batch_dir, recs, sem):
        super().__init__(name=model, daemon=True)
        self.model, self.blocks, self.a, self.tasks = model, blocks, a, tasks
        self.batch_dir, self.sem = batch_dir, sem
        self.rec_path = batch_dir / "records.jsonl"
        self.provider = runrecord.PROXY_MODEL[model][1]
        self.cells = {}  # (task, arm, rep) -> list of finalized records
        for r in recs:
            if r["model"] == model:
                self.cells.setdefault((r["task"], r["arm"], r["rep"]), []).append(r)
        self.pending = []  # partial records awaiting proxy rows
        self.retry_queue = []
        self.stopped = None

    # --- bookkeeping -------------------------------------------------------------------
    def attempts(self, key):
        rd = runrecord.run_dir_for(self.batch_dir, self.model, key[0], key[2], key[1], 1).parent
        dirs = len(list(rd.glob("a*"))) if rd.exists() else 0
        return max(dirs, len(self.cells.get(key, [])))

    def done(self, key):
        recs = self.cells.get(key, [])
        return any(r["valid"] for r in recs) or self.attempts(key) >= self.a.max_attempts

    def est_cost(self):
        vals = [r["proxy_spend"] for rs in self.cells.values() for r in rs if r.get("proxy_spend")]
        return (sum(vals) / len(vals)) if len(vals) >= 3 else PRIOR_COST.get(self.model, 0.05)

    def finalize_pending(self, wait=False):
        keep = []
        for p in self.pending:
            age = time.time() - p["end_epoch"]
            if age < SPEND_LAG_S and not wait:
                keep.append(p)
                continue
            if age < SPEND_LAG_S:
                time.sleep(SPEND_LAG_S - age)
            rec = runrecord.finalize(p)
            if rec is None and wait:
                time.sleep(20)
                rec = runrecord.finalize(p)
            if rec is None and time.time() - p["end_epoch"] < 300:
                keep.append(p)
                continue
            if rec is None:  # proxy rows never appeared within 5 min: record it, spend unknown
                rec = runrecord.finalize(p, force=True)
            with LOCK:
                PENDING_EST[self.provider] = max(0.0, PENDING_EST.get(self.provider, 0) - p["_est"])
            rec.pop("_est", None)
            rec.pop("end_epoch", None)
            append_record(self.rec_path, rec)
            key = (rec["task"], rec["arm"], rec["rep"])
            self.cells.setdefault(key, []).append(rec)
            if not rec["valid"] and not self.done(key):
                self.retry_queue.append(key)
            log(self.batch_dir, f"{self.model} {rec['task']} r{rec['rep']} {rec['arm']} a{rec['attempt']}"
                f" wall={rec.get('wall_s')} correct={rec['correct']} ${rec.get('proxy_spend')}"
                f" valid={rec['valid']} {rec['invalid_reasons'] or ''}")
        self.pending = keep

    # --- guards ------------------------------------------------------------------------
    def guards(self, n_runs):
        v = run_one.installed_cp_version()
        if v != self.a.cp_version:
            log(self.batch_dir, f"ABORT: code-puppy version {v} != pinned {self.a.cp_version}")
            ABORT.set()
            return False
        self.wait_ready()
        cap = self.a.cap_deepseek if self.provider == "deepseek" else self.a.cap_zai
        spent = collect_spend.provider_spend(self.provider + "/%", self.a.since)
        with LOCK:
            pend = PENDING_EST.get(self.provider, 0)
        proj = spent + pend + n_runs * self.est_cost() * 1.25
        if proj > cap:
            log(self.batch_dir, f"BUDGET STOP {self.model}: spent {spent:.4f} + pending {pend:.4f} + "
                f"next {n_runs} runs -> {proj:.4f} > cap {cap:.2f} ({self.provider})")
            self.stopped = "budget"
            return False
        return not ABORT.is_set()

    def wait_ready(self):
        """Pause (poll 60 s) while on battery (unless --allow-battery) or while the lid is closed."""
        while not ABORT.is_set():
            why = []
            if runrecord.power_state() != "AC" and not self.a.allow_battery:
                why.append("on battery")
            if runrecord.lid_closed():
                why.append("lid closed")
            if not why:
                return
            log(self.batch_dir, f"{self.model}: {' and '.join(why)}, pausing (poll 60 s)")
            time.sleep(60)

    # --- running -----------------------------------------------------------------------
    def run_cell(self, task, arm, rep, ctx):
        key = (task["id"], arm, rep)
        while not self.done(key) and not ABORT.is_set():
            self.wait_ready()
            attempt = self.attempts(key) + 1
            p = runrecord.execute(self.batch_dir, task, self.model, arm, rep, attempt, ctx)
            p["_est"] = self.est_cost()
            with LOCK:
                PENDING_EST[self.provider] = PENDING_EST.get(self.provider, 0) + p["_est"]
            self.pending.append(p)
            q = runrecord.quick_invalid(p)
            if not q:
                return
            log(self.batch_dir, f"{self.model} {task['id']} {arm} a{attempt} invalid {q}, retrying now")
            self.finalize_pending(wait=True)  # record the failed attempt before retrying

    def run(self):
        with self.sem:
            self._run()

    def _run(self):
        for bi, (task_id, rep) in enumerate(self.blocks):
            if ABORT.is_set() or self.stopped:
                break
            task = self.tasks[task_id]
            bseed = f"{self.a.seed}|{self.model}|{task_id}|{rep}"
            order = list(self.a.arms)
            random.Random(bseed).shuffle(order)
            todo = [arm for arm in order if not self.done((task_id, arm, rep))]
            if not todo:
                continue
            self.finalize_pending()
            if not self.guards(len(todo)):
                break
            log(self.batch_dir, f"{self.model} block {bi + 1}/{len(self.blocks)} {task_id} r{rep} order={order}")
            for pos, arm in enumerate(order):
                if arm in todo and not ABORT.is_set():
                    ctx = dict(batch=self.a.batch, seed=self.a.seed, block_seed=bseed, arm_order=order,
                               order_pos=pos, block_index=bi, timeout=self.a.timeout,
                               allow_battery=self.a.allow_battery)
                    self.run_cell(task, arm, rep, ctx)
        self.finalize_pending(wait=True)
        while self.retry_queue and not ABORT.is_set() and not self.stopped:
            task_id, arm, rep = self.retry_queue.pop(0)
            if self.done((task_id, arm, rep)) or not self.guards(1):
                continue
            ctx = dict(batch=self.a.batch, seed=self.a.seed, block_seed=f"{self.a.seed}|{self.model}|{task_id}|{rep}",
                       arm_order=[arm], order_pos="retry", block_index=None, timeout=self.a.timeout,
                       allow_battery=self.a.allow_battery)
            self.run_cell(self.tasks[task_id], arm, rep, ctx)
            self.finalize_pending(wait=True)
        shutil.rmtree(runrecord.scratch_for(self.a.batch, self.model), ignore_errors=True)
        log(self.batch_dir, f"{self.model}: worker finished ({self.stopped or 'complete'})")


def finalize_orphans(batch_dir, recs, a):
    """Run dirs that have partial.json but no record (crash between run and record): finalize."""
    have = {r["run_dir"] for r in recs}
    for pj in sorted(batch_dir.glob("*/*/r*/*/a*/partial.json")):
        try:
            p = json.loads(pj.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            log(batch_dir, f"torn partial.json skipped (cell will re-run): {pj.parent}")
            continue
        if p["run_dir"] not in have:
            rec = runrecord.finalize(dict(p), force=True)
            if rec:
                rec.pop("end_epoch", None)
                append_record(batch_dir / "records.jsonl", rec)
                log(batch_dir, f"orphan finalized: {p['run_dir']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--batch", required=True)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, choices=sorted(runrecord.PROXY_MODEL))
    ap.add_argument("--tasks", nargs="*", default=None, help="task ids (default: all 20)")
    ap.add_argument("--arms", nargs="+", default=["off", "on", "plain"], choices=["off", "on", "plain"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--parallel", type=int, default=None, help="models running at once (default: all)")
    ap.add_argument("--cap-deepseek", type=float, default=4.00)
    ap.add_argument("--cap-zai", type=float, default=8.00)
    ap.add_argument("--since", default="2026-10-09 00:00:00", help="UTC start of project spend accounting")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--cp-version", default="0.0.896")
    ap.add_argument("--allow-battery", action="store_true", help="SMOKE ONLY: skip the AC power pause")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("LITELLM_MASTER_KEY") and not a.dry_run:
        sys.exit("LITELLM_MASTER_KEY not set: launch via scripts/run_matrix.sh")
    tasks = tasklib.load_tasks(a.tasks)
    batch_dir = ROOT / "runs" / a.batch
    batch_dir.mkdir(parents=True, exist_ok=True)
    blocks = [(m, t, r) for m in a.models for t in tasks for r in range(1, a.reps + 1)]
    random.Random(a.seed).shuffle(blocks)
    per_model = {m: [(t, r) for (mm, t, r) in blocks if mm == m] for m in a.models}
    if a.dry_run:
        for m, bl in per_model.items():
            print(m, len(bl), "blocks; first:", bl[:3])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    if run_one.installed_cp_version() != a.cp_version:
        sys.exit(f"code-puppy {run_one.installed_cp_version()} != pinned {a.cp_version}; aborting")
    with open(batch_dir / "batch.json", "a") as f:
        f.write(json.dumps({"started": dt.datetime.now().isoformat(), "args": vars(a),
                            "cp_version": run_one.installed_cp_version(), "n_tasks": len(tasks),
                            "planned_runs": len(blocks) * len(a.arms)}) + "\n")
    recs = load_records(batch_dir / "records.jsonl")
    finalize_orphans(batch_dir, recs, a)
    recs = load_records(batch_dir / "records.jsonl")
    log(batch_dir, f"batch {a.batch}: {len(blocks)} blocks x {len(a.arms)} arms, {len(recs)} records present,"
        f" seed {a.seed}, allow_battery={a.allow_battery}")
    sem = threading.Semaphore(a.parallel or len(a.models))
    workers = [Worker(m, per_model[m], a, tasks, batch_dir, recs, sem) for m in a.models]
    for w in workers:
        w.start()
    for w in workers:
        while w.is_alive():
            w.join(5)
    log(batch_dir, "batch done" + (" (ABORTED)" if ABORT.is_set() else ""))


if __name__ == "__main__":
    main()

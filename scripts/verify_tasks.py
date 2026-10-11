#!/usr/bin/env python3
"""Prove every task is gradable and solvable, without any model call.

code tasks: fresh working copy -> hidden tests must FAIL; apply reference.patch -> must PASS.
gather tasks: the expected answer (and formatting variants) must grade correct; a corrupted
  answer (one field wrong, or a field missing) must grade wrong.
Usage: .venv/bin/python scripts/verify_tasks.py [task_id ...]   exit 1 on any failure.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graders import grade_code, grade_gather  # noqa: E402
from tasklib import load_tasks, prepare_work  # noqa: E402


def variants(task):
    vals = [str(a["value"]) for a in task["answer"]]
    exact = "|".join(vals)
    fancy = " | ".join(f"`{v}`" if a["kind"] != "set" else ", ".join(reversed(v.split(",")))
                       for v, a in zip(vals, task["answer"]))
    wrong = []
    for i, a in enumerate(task["answer"]):
        w = list(vals)
        if a["kind"] in ("int", "num"):
            w[i] = str(float(vals[i]) + 1)
        else:
            w[i] = "Wrong" + vals[i][1:]
        if a["kind"] == "set":
            w[i] = ",".join(vals[i].split(",")[:-1]) or "x"
        wrong.append("|".join(w))
    return [f"blah\nANSWER: {exact}", f"**ANSWER:** {fancy}\n"], [f"ANSWER: {w}" for w in wrong] + [
        "ANSWER: " + "|".join(vals[:-1]), "no answer line"]


def main(ids):
    bad = 0
    for tid, t in load_tasks(ids or None).items():
        if t["family"] == "gather":
            good, wrong = variants(t)
            g = [grade_gather(t, s)[0] for s in good]
            w = [grade_gather(t, s)[0] for s in wrong]
            ok = all(g) and not any(w)
            print(f"{'OK ' if ok else 'BAD'} {tid}: good={g} wrong_accepted={sum(w)}")
            bad += not ok
            continue
        with tempfile.TemporaryDirectory() as tmp:
            work = prepare_work(t, Path(tmp) / "w")
            before, d1 = grade_code(t, t["dir"], work)
            subprocess.run(["git", "apply", str(Path(t["dir"]) / t["reference"])], cwd=work, check=True)
            after, d2 = grade_code(t, t["dir"], work)
        ok = (not before) and after
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} {tid}: before={d1['pytest_summary']!r} after={d2['pytest_summary']!r}")
        if not ok:
            print(d1["pytest_out"][-1500:], d2["pytest_out"][-1500:])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1:])

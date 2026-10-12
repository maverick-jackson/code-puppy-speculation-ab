#!/usr/bin/env python3
"""Long-horizon tasks composed from the validated reference tasks, plus their grader.

L_*: one task = all 4 questions (gather) or all 4 bugs/features (code) of one repo.
D_*: the same task with an explicit instruction to delegate the parts to sub-agents.
Ground truth is reused verbatim: gather answer specs are concatenated in order, code tasks
run every source task's hidden test file. Written into tasks/ so tasklib.load_tasks /
prepare_work pick them up unchanged.

Usage: scripts/longtasks.py build | scripts/longtasks.py validate
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF = HERE.parent
TASKS = REF / "tasks"
sys.path.insert(0, str(HERE))
import graders  # noqa: E402
import tasklib  # noqa: E402

GATHER = {"click": ["g1", "g2", "g3", "g4"], "httpx": ["h1", "h2", "h3", "h4"], "rich": ["r1", "r2", "r3", "r4"]}
CODE = {"click": ["c1", "c2", "c3", "c4"], "invkit": ["f1", "f2", "f3", "f4"]}
PARTS = "ABCD"
DELEGATE = (
    " This is a large task with independent parts. Delegate the parts to sub-agents with"
    " invoke_agent (agent_name \"code-puppy\"), giving each sub-agent everything it needs in its"
    " prompt, then check and combine their results yourself."
)


def _by_prefix(family: str) -> dict[str, dict]:
    return {t["id"].split("_")[0]: t for t in tasklib.load_tasks().values() if t["family"] == family}


def _questions(prompt: str) -> str:
    """The question body: 'answer: (1) ...' or 'answer about X: (1) ...', up to the no-edit rule."""
    m = re.search(r"\banswer( about [^:]+)?: (.+?) Do not modify any files\.", prompt)
    if m is None:
        raise ValueError(f"cannot parse questions from: {prompt[:120]}")
    return (f"About{m.group(1)[6:]}: " if m.group(1) else "") + m.group(2).strip()


def gather_task(repo: str, delegate: bool) -> dict:
    src = _by_prefix("gather")
    parts = [src[p] for p in GATHER[repo]]
    head = parts[0]["prompt"].split(" Using only", 1)[0]
    qs = [f"Part {PARTS[i]}: {_questions(t['prompt'])}" for i, t in enumerate(parts)]
    templ = [t["prompt"].rsplit("ANSWER: ", 1)[1].strip() for t in parts]
    prompt = (f"{head} Using only the files in this repository, answer all four parts below. "
              + " ".join(qs) + " Do not modify any files."
              + (DELEGATE if delegate else "")
              + " End your reply with one final line exactly in the form ANSWER: " + "|".join(templ))
    tid = f"{'D' if delegate else 'L'}_{repo}_gather"
    return {"id": tid, "family": "gather", "repo": repo, "prompt": prompt,
            "answer": [a for t in parts for a in t["answer"]], "sources": [t["id"] for t in parts]}


def code_task(base: str, delegate: bool) -> tuple[dict, list[Path], list[Path]]:
    src = _by_prefix("code")
    parts = [src[p] for p in CODE[base]]
    first = parts[0]["prompt"]
    head = first.split(" Bug report:")[0].split(" Feature request:")[0]
    reports = []
    for i, t in enumerate(parts):
        body = t["prompt"][len(head):].split(" Change only library source files", 1)[0].strip()
        reports.append(f"Part {PARTS[i]}: {body}")
    prompt = (f"{head} There are four open issues; resolve all of them. " + " ".join(reports)
              + (DELEGATE if delegate else "")
              + " Change only library source files; do not add, edit or delete any test files."
              + " When you are finished, end your reply with one final line exactly: DONE")
    tid = f"{'D' if delegate else 'L'}_{base}_code"
    task = {"id": tid, "family": "code", "base": parts[0]["base"], "pythonpath": parts[0]["pythonpath"],
            "prompt": prompt, "bug_patch": "bug.patch" if parts[0]["bug_patch"] else None,
            "hidden": "hidden/test_hidden_0.py",
            "hidden_files": [f"hidden/test_hidden_{i}.py" for i in range(len(parts))],
            "sources": [t["id"] for t in parts]}
    patches = [Path(t["dir"]) / t["bug_patch"] for t in parts if t["bug_patch"]]
    refs = [Path(t["dir"]) / t["reference"] for t in parts]
    for i, t in enumerate(parts):
        task.setdefault("_hidden_src", []).append(str(Path(t["dir"]) / t["hidden"]))
    return task, patches, refs


def _combined_patch(base: str, patches: list[Path]) -> str:
    """Apply the bug patches in sequence to a scratch copy and diff it: one stackable patch."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / base
        shutil.copytree(tasklib.REPOS / base, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        run = lambda *c: subprocess.run(c, cwd=dst, check=True, capture_output=True, text=True)  # noqa: E731
        run("git", "init", "-q")
        run("git", *tasklib.GIT_ID, "add", "-A")
        run("git", *tasklib.GIT_ID, "commit", "-qm", "base")
        for p in patches:
            run("git", "apply", str(p))
        return run("git", "diff").stdout


def build() -> list[str]:
    ids = []
    for delegate in (False, True):
        for repo in GATHER:
            t = gather_task(repo, delegate)
            (TASKS / "gather" / f"{t['id']}.json").write_text(json.dumps(t, indent=1))
            ids.append(t["id"])
        for base in CODE:
            t, patches, refs = code_task(base, delegate)
            d = TASKS / "code" / t["id"]
            (d / "hidden").mkdir(parents=True, exist_ok=True)
            for i, h in enumerate(t.pop("_hidden_src")):
                shutil.copy(h, d / "hidden" / f"test_hidden_{i}.py")
            if patches:
                (d / "bug.patch").write_text(_combined_patch(base, patches))
            (d / "reference.patch").write_text("".join(p.read_text() for p in refs))
            t["reference_parts"] = [str(p.relative_to(REF)) for p in refs]
            (d / "task.json").write_text(json.dumps(t, indent=1))
            ids.append(t["id"])
    return ids


def grade(task: dict, final_text: str, work: Path) -> tuple[bool, dict]:
    """Like tasklib.grade, but code tasks with hidden_files must pass every file."""
    if task["family"] != "code" or "hidden_files" not in task:
        return tasklib.grade(task, final_text, work)
    results = [graders.grade_code(dict(task, hidden=h), task["dir"], work) for h in task["hidden_files"]]
    passed = [ok for ok, _ in results]
    return all(passed), {"parts_ok": passed, "pytest_summary": " / ".join(d["pytest_summary"] for _, d in results)}


def validate() -> None:
    """Bugged copy fails every part; reference patches applied in turn make every part pass."""
    for tid, t in tasklib.load_tasks().items():
        if not tid.startswith(("L_", "D_")) or t["family"] != "code":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            work = tasklib.prepare_work(t, Path(tmp) / "w")
            bad = grade(t, "", work)[1]["parts_ok"]
            for ref in (str(REF / r) for r in t["reference_parts"]):
                # Independent reference fixes can overlap in context (f1 and f4 both touch
                # cli.py), so fall back from a strict apply to a 3-way merge, then fuzz.
                for cmd in (["git", "apply", ref], ["git", "apply", "--3way", ref],
                            ["patch", "-p1", "-F3", "-i", ref]):
                    if subprocess.run(cmd, cwd=work, capture_output=True).returncode == 0:
                        break
                else:
                    print(tid, "reference does not apply:", ref)
            good = grade(t, "", work)[1]["parts_ok"]
            print(tid, "bugged:", bad, "fixed:", good, "OK" if not any(bad) and all(good) else "BROKEN")
    for tid, t in tasklib.load_tasks().items():
        if tid.startswith(("L_", "D_")) and t["family"] == "gather":
            want = "|".join(str(a["value"]) for a in t["answer"])
            print(tid, "self-grade:", graders.grade_gather(t, f"ANSWER: {want}")[0], len(t["answer"]), "fields")


if __name__ == "__main__":
    os.chdir(REF)
    print(build() if sys.argv[1:] == ["build"] else validate())

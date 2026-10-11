"""Task suite loading, per-run working copies, and grading dispatch.

Tasks: tasks/gather/<id>.json (family gather) and tasks/code/<id>/task.json (family code).
Working copies (fresh per run, so runs cannot contaminate each other):
  gather: APFS clone (cp -c) of the pinned repo, .git included (read-only questions).
  code:   copy of the pinned repo (click) or fixture WITHOUT its history, the task's bug.patch
          applied, then a fresh one-commit git repo, so `git diff`/`git log` cannot reveal the
          injected bug or the original code. Hidden tests and reference patches stay in tasks/.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"
REPOS = ROOT / "runs" / "repos"
GIT_ID = ["-c", "user.name=bench", "-c", "user.email=bench@localhost", "-c", "commit.gpgsign=false"]


def clone_cmd(src, dst):
    """Copy-on-write tree copy: APFS clone on macOS, reflink when the Linux fs supports it."""
    if sys.platform == "darwin":
        return ["cp", "-cR", str(src), str(dst)]
    return ["cp", "-a", "--reflink=auto", str(src), str(dst)]


def load_tasks(ids=None):
    out = {}
    for p in sorted((TASKS / "gather").glob("*.json")):
        t = json.loads(p.read_text())
        t["dir"] = str(p.parent)
        out[t["id"]] = t
    for p in sorted((TASKS / "code").glob("*/task.json")):
        t = json.loads(p.read_text())
        t["dir"] = str(p.parent)
        out[t["id"]] = t
    if ids:
        missing = [i for i in ids if i not in out]
        if missing:
            raise SystemExit(f"unknown task ids: {missing}")
        out = {i: out[i] for i in ids}
    return out


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def prepare_work(task, work_root):
    """Create a fresh working copy for one run under work_root; return its path."""
    work_root = Path(work_root)
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)
    if task["family"] == "gather":
        dst = work_root / task["repo"]
        _run(clone_cmd(REPOS / task["repo"], dst), ROOT)
        return dst
    base = task["base"]
    if base.startswith("fixture:"):
        name = base.split(":", 1)[1]
        src = TASKS / "fixtures" / name
    else:
        name, src = base, REPOS / base
    dst = work_root / name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
                    copy_function=shutil.copy2)
    # init BEFORE applying: `git apply` inside a subdirectory of another repo silently skips
    # every path (that is how smoke1's click tasks ran without their bug).
    _run(["git", "init", "-q"], dst)
    if task.get("bug_patch"):
        bp = str(Path(task["dir"]) / task["bug_patch"])
        _run(["git", "apply", bp], dst)
        if subprocess.run(["git", "apply", "--check", "-R", bp], cwd=dst, capture_output=True).returncode:
            raise RuntimeError(f"bug patch for {task['id']} is not applied in {dst}")
    _run(["git", *GIT_ID, "add", "-A"], dst)
    _run(["git", *GIT_ID, "commit", "-qm", "snapshot"], dst)
    return dst


def work_diff(work):
    """The agent's change set (tracked edits plus new files), for the run record."""
    try:
        _run(["git", *GIT_ID, "add", "-A"], work)  # grader already removed _hidden_tests
        p = subprocess.run(["git", "diff", "--cached", "--stat"], cwd=work, capture_output=True, text=True)
        full = subprocess.run(["git", "diff", "--cached"], cwd=work, capture_output=True, text=True)
        return p.stdout, full.stdout
    except Exception as e:  # noqa: BLE001
        return f"diff failed: {e!r}", ""


def gather_dirty(work):
    p = subprocess.run(["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True)
    return p.stdout.strip()


def grade(task, final_text, work):
    """Return (correct, detail). For code tasks the hidden tests run inside `work`."""
    from graders import grade_code, grade_gather
    if task["family"] == "gather":
        ok, det = grade_gather(task, final_text)
        dirty = gather_dirty(work)
        if dirty:
            det["repo_modified"] = dirty[:500]
        return ok, det
    return grade_code(task, task["dir"], work)

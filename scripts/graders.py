"""Deterministic graders for the Phase 2 task suite.

gather: the LAST line starting with 'ANSWER:' in the agent's final output is split on '|' and
  each field is compared with the task's typed answer spec. Formatting is forgiven (case,
  whitespace, backticks, quotes, bold, a trailing period, qualified names like a.b.Name, '()' on
  function names, list order); substance is not (every field must match, lists must match exactly
  as sets, numbers must be equal).
code: hidden pytest file copied into the work copy only AFTER the agent exits, run with the
  grader venv (.venv) and an empty pytest config, so the repo's own pytest settings do not apply.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)?")


def _clean(s):
    s = ANSI.sub("", str(s)).strip()
    s = s.strip(" \t`'\"*")
    s = s.rstrip(".").strip(" \t`'\"*")
    return s


def _name(s):
    s = _clean(s)
    s = re.sub(r"\(\)$", "", s)
    return s.split(".")[-1].lower() if "/" not in s else s.lower()


def _num(s):
    """The single number in a field ('972', 'line 972', '65,536', '5.0s'), else None."""
    toks = [t.rstrip(",_") for t in re.findall(r"-?\d[\d,_]*(?:\.\d+)?", _clean(s))]
    if len(toks) != 1:
        return None
    return float(toks[0].replace(",", "").replace("_", ""))


def _items(s):
    parts = re.split(r",|;|\band\b", _clean(s))
    return {_name(p) for p in parts if _clean(p)}


def _path(s):
    s = _clean(s).lower()
    while s.startswith("./"):
        s = s[2:]
    return s.lstrip("/")


def field_ok(kind, got, want):
    if kind == "int":
        n = _num(got)
        return n is not None and n == int(want)
    if kind == "num":
        n = _num(got)
        return n is not None and abs(n - float(want)) < 1e-9
    if kind == "set":
        return _items(got) == _items(want)
    if kind == "path":
        return _path(got) == _path(want)
    if kind == "name":
        return _name(got) == _name(want)
    return _clean(got).lower() == _clean(want).lower()  # "str"


def extract_answer(text):
    text = ANSI.sub("", text or "")
    found = [m.strip() for m in re.findall(r"ANSWER:\s*(.+)", text)]
    found = [f for f in found if "<" not in f]  # skip echoes of the template
    return found[-1] if found else None


def grade_gather(task, final_text):
    ans = extract_answer(final_text)
    spec = task["answer"]
    detail = {"answer": ans, "expected": "|".join(str(a["value"]) for a in spec)}
    if not ans:
        return False, dict(detail, reason="no ANSWER line")
    fields = [f.strip() for f in ans.split("|")]
    if len(fields) == len(spec) + 1 and not _clean(fields[-1]):
        fields = fields[:-1]  # tolerate a trailing '|'
    if len(fields) != len(spec):
        return False, dict(detail, reason=f"{len(fields)} fields, expected {len(spec)}")
    per = [field_ok(a["kind"], f, a["value"]) for a, f in zip(spec, fields)]
    detail["fields_ok"] = per
    return all(per), detail


def grade_code(task, task_dir, work, timeout=180):
    """Copy the hidden test into the work copy, run it, return (passed, detail)."""
    hd = Path(work) / "_hidden_tests"
    if hd.exists():
        shutil.rmtree(hd)
    hd.mkdir()
    shutil.copy(Path(task_dir) / task["hidden"], hd / "test_hidden.py")
    (hd / "pytest.ini").write_text("[pytest]\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "LITELLM_MASTER_KEY")}
    env.update(PYTHONPATH=str(Path(work) / task["pythonpath"]), PYTHONDONTWRITEBYTECODE="1")
    cmd = [str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(hd / "pytest.ini"),
           "--rootdir", str(work), str(hd / "test_hidden.py")]
    try:
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "grader timeout", -9
    shutil.rmtree(hd, ignore_errors=True)
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or [""]
    passed = len(re.findall(r"(\d+) passed", tail[0])) and rc == 0
    return bool(passed), {"pytest_rc": rc, "pytest_summary": tail[0][:200], "pytest_out": out[-3000:]}

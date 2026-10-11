#!/usr/bin/env python3
"""Grade a gathering run: last 'ANSWER:' line in stdout vs tasks/<task>.expected (exact, normalized).
Usage: grade.py <run_dir> <expected_file>   prints JSON {answer, expected, correct}
"""
import json
import re
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)?")


def norm(s):
    s = ANSI.sub("", s).strip().strip("`*").strip()
    return "|".join(p.strip().strip("`*").strip().lower() for p in s.split("|"))


def grade(run_dir, expected_file):
    out = ANSI.sub("", Path(run_dir, "stdout.txt").read_text(errors="replace"))
    found = re.findall(r"ANSWER:\s*(.+)", out)
    found = [f for f in found if "<" not in f]
    ans = found[-1].strip() if found else None
    exp = Path(expected_file).read_text().strip()
    return {"answer": ans, "expected": exp, "correct": bool(ans) and norm(ans) == norm(exp)}


if __name__ == "__main__":
    print(json.dumps(grade(sys.argv[1], sys.argv[2])))

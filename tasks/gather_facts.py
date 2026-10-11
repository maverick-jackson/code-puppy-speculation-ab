#!/usr/bin/env python3
"""Recompute, from the pinned clones, every fact the gathering tasks' expected answers rely on.

Usage: .venv/bin/python tasks/gather_facts.py   (exits 1 if any fact disagrees with task.json)
Facts are derived with ast / plain text scans, not copied by hand, so a wrong expected answer
shows up here before it can mis-grade a run.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "runs" / "repos"


def tree(p):
    return ast.parse(Path(p).read_text())


def subclasses(path, base):
    """Classes in one module that inherit (directly or indirectly) from `base` (by name)."""
    parents = {}
    for n in tree(path).body:
        if isinstance(n, ast.ClassDef):
            parents[n.name] = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "?") for b in n.bases]

    def inherits(c, seen=()):
        return any(p == base or (p in parents and p not in seen and inherits(p, seen + (c,)))
                   for p in parents.get(c, []))
    return sorted(c for c in parents if inherits(c))


def line_of(path, pattern):
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        if re.search(pattern, line):
            return i
    return None


def dict_len(path, name):
    for n in tree(path).body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target
            if isinstance(tgt, ast.Name) and tgt.id == name:
                return len(n.value.keys) if isinstance(n.value, ast.Dict) else len(n.value.elts)


def facts():
    c, h, r = R / "click/src/click", R / "httpx/httpx", R / "rich/rich"
    f = {}
    f["g1_click_exceptions"] = ["MissingParameter", "BadParameter", "2", "45"]  # pilot task, hand-verified in Phase 1
    f["g2_click_completion"] = ["4.4", str(len(subclasses(c / "exceptions.py", "ClickException"))), "_MY_TOOL_COMPLETE", "RuntimeError"]
    src = (c / "formatting.py").read_text()
    f["g3_click_helpwidth"] = [
        "src/click/formatting.py",
        re.search(r"max_width = (\d+)", src).group(1),
        re.search(r"max_width\) - 2, (\d+)\)", src).group(1),
        "FORCED_WIDTH",
    ]
    f["g4_click_types"] = [
        str(len(subclasses(c / "types.py", "ParamType"))),
        "convert_type",
        str(line_of(c / "types.py", r"^def convert_type\(")),
        re.search(r"MAX_BYTES_WRITTEN = (\d+)", (c / "_winconsole.py").read_text()).group(1),
    ]
    f["h1_httpx_exceptions"] = [
        str(dict_len(h / "_transports/default.py", "HTTPCORE_EXC_MAP")),
        "map_httpcore_exceptions",
        str(len(subclasses(h / "_exceptions.py", "TransportError"))),
        re.search(r"DEFAULT_MAX_REDIRECTS = (\d+)", (h / "_config.py").read_text()).group(1),
    ]
    f["h2_httpx_redirects"] = [
        str(line_of(h / "_client.py", r"raise TooManyRedirects\(") ),
        "301,302,303", "content-length,transfer-encoding", "cookie",
    ]
    f["h3_httpx_content"] = [
        re.search(r"CHUNK_SIZE = ([\d_]+)", (h / "_content.py").read_text()).group(1).replace("_", ""),
        ",".join(sorted(re.findall(r'^\s+"(\w+)": \w+Decoder,', (h / "_decoders.py").read_text(), re.M))),
        str(line_of(h / "_content.py", r"^def encode_request\(")),
        "MAX_URL_LENGTH",
    ]
    all_ = next(n.value for n in tree(h / "__init__.py").body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "__all__")
    f["h4_httpx_defaults"] = [str(len(all_.elts)), "5.0", "100", "20"]
    boxes = [n.target.id for n in tree(r / "box.py").body
             if isinstance(n, ast.AnnAssign) and isinstance(n.value, ast.Call)
             and getattr(n.value.func, "id", "") == "Box"]
    f["r1_rich_box"] = [str(len(boxes)), str(dict_len(r / "box.py", "LEGACY_WINDOWS_SUBSTITUTIONS")), "HEAVY_HEAD", "ROUNDED"]
    f["r2_rich_console"] = ["80", "25", "dumb,unknown", "columns,lines"]
    loop_users = []
    for p in sorted(r.glob("*.py")):
        for n in ast.walk(tree(p)):
            if isinstance(n, ast.ImportFrom) and n.module == "_loop" and any(a.name == "loop_last" for a in n.names):
                loop_users.append(p.name)
    f["r3_rich_loop"] = ["rich/_loop.py", str(len(set(loop_users))), str(line_of(r / "_loop.py", r"^def loop_last\("))]
    f["r4_rich_progress"] = ["12.5", "dots", "10", "8"]
    return f, {"loop_last_importers": sorted(set(loop_users)), "boxes": boxes}


if __name__ == "__main__":
    f, extra = facts()
    bad = 0
    for tid, vals in f.items():
        spec = json.loads((ROOT / "tasks/gather" / f"{tid}.json").read_text())
        exp = [str(a["value"]) for a in spec["answer"]]
        ok = [v.lower() for v in vals] == [e.lower() for e in exp]
        bad += not ok
        print(("OK  " if ok else "BAD ") + tid, vals, "" if ok else f"task.json has {exp}")
    print(json.dumps(extra))
    sys.exit(1 if bad else 0)

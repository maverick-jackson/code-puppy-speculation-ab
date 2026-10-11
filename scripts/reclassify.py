#!/usr/bin/env python3
"""Recompute validity (invalid_reasons, valid, agent_error_text) of every record in a batch from
its run dir with the CURRENT rules in runrecord.py, keeping everything else. Idempotent.
Use after a rule fix, while the batch runner is stopped. Writes a .bak of the old file.
Usage: reclassify.py runs/<batch>/records.jsonl
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import runrecord  # noqa: E402
from summarize import metrics  # noqa: E402

path = Path(sys.argv[1])
shutil.copy(path, str(path) + ".bak")
out = []
for line in path.read_text().splitlines():
    r = json.loads(line)
    rd = runrecord.ROOT / r["run_dir"]
    err = runrecord.agent_error_text(rd)
    reasons = runrecord.invalid_reasons(metrics(rd), err=err)
    if r.get("leak_suspect"):
        reasons.append("leak")
    if reasons != r.get("invalid_reasons"):
        print(f"{r['task']} {r['arm']} a{r['attempt']}: {r.get('invalid_reasons')} -> {reasons}")
    r.update(agent_error_text=err, invalid_reasons=reasons, valid=not reasons)
    out.append(json.dumps(r))
path.write_text("\n".join(out) + "\n")

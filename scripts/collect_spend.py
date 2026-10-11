#!/usr/bin/env python3
"""Attach LiteLLM proxy rows (tokens, spend, per-request timings) to each run's meta.json.

Run AFTER a batch, at least ~30s after the last run (LiteLLM batches spend-log writes).
Window = [start_utc, end_utc + 1s]. run_matrix.py runs at most one run per model at a time and
passes the run's proxy model, so concurrent workers on OTHER models are filtered out (counted in
proxy_foreign_rows). The owner's own traffic on the SAME model would still be indistinguishable.
Usage: collect_spend.py <run_dir> [<run_dir> ...]   (each containing meta.json)
Also: collect_spend.py --total   prints total spend and row count.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

KEYS = ["request_id", "model", "prompt_tokens", "completion_tokens", "spend", "status",
        "start", "first_token", "end", "duration_ms", "cache_hit"]


def psql(sql):
    cmd = ("source ~/rig/env.sh && cd ~/rig/secrets && sops exec-env llm-keys.enc.yaml "
           "'psql \"$DATABASE_URL\" -F \"|\" -tAc \"$Q\"'")
    env = dict(os.environ, Q=sql)
    env.pop("LITELLM_MASTER_KEY", None)
    return subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True,
                          timeout=60, check=True).stdout


def provider_spend(model_like, since):
    """Total proxy spend for models matching `model_like` (SQL LIKE) since an ISO UTC time."""
    out = psql('select coalesce(sum(spend),0) from "LiteLLM_SpendLogs" where model like \'%s\' '
               'and "startTime" >= \'%s\'' % (model_like, since)).strip()
    return float(out or 0)


def attach(d, model=None):
    """Attach proxy rows in the run's UTC window to meta.json; only rows of `model` if given."""
    p = Path(d) / "meta.json"
    m = json.loads(p.read_text())
    end = dt.datetime.fromisoformat(m["end_utc"]) + dt.timedelta(seconds=1)
    rows = rows_between(m["start_utc"].replace("T", " "), end.isoformat(sep=" "))
    m["proxy_foreign_rows"] = sum(1 for r in rows if model and r["model"] != model)
    rows = [r for r in rows if not model or r["model"] == model]
    m["proxy_requests"] = rows
    m["proxy_spend_usd"] = round(sum(float(r["spend"] or 0) for r in rows), 6)
    m["proxy_prompt_tokens"] = sum(int(r["prompt_tokens"] or 0) for r in rows)
    m["proxy_completion_tokens"] = sum(int(r["completion_tokens"] or 0) for r in rows)
    m["proxy_models"] = sorted({r["model"] for r in rows})
    p.write_text(json.dumps(m, indent=1))
    return m


def rows_between(a, b):
    ts = 'to_char("%s", \'YYYY-MM-DD"T"HH24:MI:SS.MS\')'
    sql = ('select request_id, model, prompt_tokens, completion_tokens, spend, status, '
           + ", ".join(ts % c for c in ("startTime", "completionStartTime", "endTime"))
           + ', request_duration_ms, cache_hit from "LiteLLM_SpendLogs" '
           'where "startTime" >= \'%s\' and "startTime" <= \'%s\' order by "startTime"' % (a, b))
    out = []
    for line in psql(sql).strip().splitlines():
        parts = line.split("|")
        if len(parts) == len(KEYS):
            out.append(dict(zip(KEYS, parts)))
    return out


def main():
    if sys.argv[1:] == ["--total"]:
        print(psql('select round(sum(spend)::numeric,6), count(*) from "LiteLLM_SpendLogs"').strip())
        return
    for d in sys.argv[1:]:
        m = attach(d)
        print(d, len(m["proxy_requests"]), m["proxy_spend_usd"], m["proxy_models"])


if __name__ == "__main__":
    main()

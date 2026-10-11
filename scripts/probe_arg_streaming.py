#!/usr/bin/env python3
"""Probe: do tool-call ARGUMENTS stream through the LiteLLM proxy for a model group?

One small streaming chat completion with one tool; counts SSE chunks that carry
tool_calls[].function.arguments fragments. Needs LITELLM_MASTER_KEY in env
(run: bash -c 'source ~/rig/bin/_proxy-env; python3 scripts/probe_arg_streaming.py <group>...').
Prints JSON per model group; never prints the key.
"""
import json
import os
import sys
import time
import urllib.request

URL = "http://127.0.0.1:4000/v1/chat/completions"
TOOL = {"type": "function", "function": {
    "name": "run_code", "description": "Run a Python snippet.",
    "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                   "required": ["code"]}}}
MSG = ("Call run_code exactly once with a 6-line Python snippet that reads the files "
       "a.py, b.py and c.py with open() and prints their lengths. No prose.")


def probe(group):
    body = {"model": group, "stream": True, "tools": [TOOL], "tool_choice": "auto",
            "messages": [{"role": "user", "content": MSG}], "max_tokens": 2000}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"],
        "Content-Type": "application/json"})
    t0 = time.perf_counter()
    arg_chunks, arg_chars, first, last, chunks, tc_chunks = 0, 0, None, None, 0, 0
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            chunks += 1
            d = json.loads(line[5:])
            for ch in d.get("choices", []):
                for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                    tc_chunks += 1
                    a = (tc.get("function") or {}).get("arguments")
                    if a:
                        arg_chunks += 1
                        arg_chars += len(a)
                        now = time.perf_counter() - t0
                        first = first if first is not None else now
                        last = now
    return {"group": group, "sse_chunks": chunks, "tool_call_chunks": tc_chunks, "arg_chunks": arg_chunks, "arg_chars": arg_chars,
            "first_arg_s": round(first, 3) if first else None,
            "arg_span_s": round(last - first, 3) if first is not None else None,
            "total_s": round(time.perf_counter() - t0, 3)}


if __name__ == "__main__":
    for g in sys.argv[1:]:
        try:
            print(json.dumps(probe(g)))
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"group": g, "error": repr(e)[:300]}))

"""Metrics from code-puppy session files (autosave transcripts and sub-agent sessions).

Both use the same envelope: {"format", "code_puppy", "pydantic_ai", "encoding", "messages"} with
pydantic-ai messages. Nested tool calls made inside run_code are read from the run_code
tool-return metadata ("tool_calls"), so loops and asyncio.gather fan-outs are counted exactly.
"""
from __future__ import annotations

import json
from pathlib import Path


def _messages(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())["messages"]


def transcript_metrics(path: Path) -> dict:
    m = dict(requests=0, top_calls=0, run_code=0, native=0, nested=[], rc_errors=0, in_tok=0, out_tok=0,
             cache_read=0, nested_by_tool={}, invoke_per_rc=[], invoke_top=0, invoke_per_response=[])
    for msg in _messages(path):
        if msg.get("kind") == "response":
            m["requests"] += 1
            u = msg.get("usage") or {}
            m["in_tok"] += u.get("input_tokens", 0) or 0
            m["out_tok"] += u.get("output_tokens", 0) or 0
            m["cache_read"] += u.get("cache_read_tokens", 0) or 0
            inv = sum(p.get("part_kind") == "tool-call" and p.get("tool_name") == "invoke_agent"
                      for p in msg.get("parts", []))
            if inv:
                m["invoke_per_response"].append(inv)
        for p in msg.get("parts", []):
            kind, name = p.get("part_kind"), p.get("tool_name")
            if kind == "tool-call":
                m["top_calls"] += 1
                if name == "run_code":
                    m["run_code"] += 1
                else:
                    m["native"] += 1
                    m["invoke_top"] += name == "invoke_agent"
            elif kind == "tool-return" and name == "run_code":
                calls = ((p.get("metadata") or {}).get("tool_calls")) or {}
                m["nested"].append(len(calls))
                inv = sum(c.get("tool_name") == "invoke_agent" for c in calls.values())
                if inv:
                    m["invoke_per_rc"].append(inv)
                for c in calls.values():
                    t = c.get("tool_name", "?")
                    m["nested_by_tool"][t] = m["nested_by_tool"].get(t, 0) + 1
            elif kind == "retry-prompt" and name == "run_code":
                m["rc_errors"] += 1
    return m


def final_response_text(path: Path) -> str:
    """Text of the last model response. Graders use this: rendered stdout wraps long lines."""
    for msg in reversed(_messages(path)):
        if msg.get("kind") == "response":
            text = "".join(p.get("content", "") for p in msg["parts"] if p.get("part_kind") == "text")
            if text.strip():
                return text
    return ""


def subagent_summary(paths: list[Path]) -> dict:
    """Totals over every sub-agent session of one run, plus per-session context stats."""
    per = []
    for s in paths:
        msgs = _messages(s)
        rets = [len(json.dumps(p.get("content"))) for x in msgs for p in x.get("parts", [])
                if p.get("part_kind") == "tool-return"]
        per.append({"metrics": transcript_metrics(s), "max_return_chars": max(rets) if rets else 0})
    ms = [p["metrics"] for p in per]
    return {
        "sessions": len(per),
        **{k: sum(m[k] for m in ms) for k in ("requests", "top_calls", "run_code", "native", "rc_errors",
                                               "in_tok", "out_tok")},
        "nested": [n for m in ms for n in m["nested"]],
        "per_session": [{"requests": p["metrics"]["requests"], "in_tok": p["metrics"]["in_tok"],
                         "max_return_chars": p["max_return_chars"]} for p in per],
    }

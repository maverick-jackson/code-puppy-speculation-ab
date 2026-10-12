"""Metrics from code-puppy session files (autosave transcripts and sub-agent sessions).

Both use the same envelope: {"format", "code_puppy", "pydantic_ai", "encoding", "messages"} with
pydantic-ai messages. Nested tool calls made inside run_code are read from the run_code
tool-return metadata ("tool_calls"), so loops and asyncio.gather fan-outs are counted exactly.
"""
from __future__ import annotations

import json
from pathlib import Path

try:  # API list-price cost per request; optional so the runner works without it
    from genai_prices import Usage as _PriceUsage, calc_price as _calc_price
except ImportError:  # pragma: no cover
    _calc_price = None

GENAI_PRICES_PIN = "0.1.10"


COST_PARTS = ("uncached", "cache_read", "cache_write", "output")


def request_cost(model_name: str, usage: dict) -> dict[str, float] | None:
    """USD per cost component for one model response at API list prices, or None if unpriced.

    pydantic-ai usage: input_tokens includes cache reads and writes; cache_write_tokens includes
    1-hour writes (cache_write_1h_tokens), which Anthropic bills at 2x input vs 1.25x for 5-minute.
    Price tiers depend on the request's total input, so pricing is per request, and the split holds
    total input fixed (same tier) while isolating each category; the parts sum to the exact total.
    """
    if _calc_price is None or not model_name:
        return None
    provider = "anthropic" if model_name.startswith("claude") else "openai" if model_name.startswith("gpt") else None
    total = int(usage.get("input_tokens") or 0)
    cr, cw = int(usage.get("cache_read_tokens") or 0), int(usage.get("cache_write_tokens") or 0)
    cw1h, out = int(usage.get("cache_write_1h_tokens") or 0), int(usage.get("output_tokens") or 0)

    def price(**u: int):  # noqa: ANN202
        return _calc_price(_PriceUsage(input_tokens=total, **u), model_ref=model_name, provider_id=provider)

    try:
        full = price(cache_read_tokens=cr, cache_write_tokens=cw, cache_write_1h_tokens=cw1h, output_tokens=out)
        per_uncached = float(price().input_price) / total if total else 0.0
        reads = float(price(cache_read_tokens=cr).input_price) - (total - cr) * per_uncached
        writes = float(price(cache_write_tokens=cw, cache_write_1h_tokens=cw1h).input_price) - (total - cw) * per_uncached
    except LookupError:
        return None
    uncached = float(full.input_price) - reads - writes
    return {"uncached": uncached, "cache_read": reads, "cache_write": writes, "output": float(full.output_price)}


def _messages(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())["messages"]


def transcript_metrics(path: Path) -> dict:
    m = dict(requests=0, top_calls=0, run_code=0, native=0, nested=[], rc_errors=0, in_tok=0, out_tok=0,
             cache_read=0, nested_by_tool={}, top_by_tool={}, invoke_per_rc=[], invoke_top=0,
             invoke_per_response=[], cache_write=0, unpriced=0, **{f"cost_{k}": 0.0 for k in COST_PARTS})
    for msg in _messages(path):
        if msg.get("kind") == "response":
            m["requests"] += 1
            u = msg.get("usage") or {}
            m["in_tok"] += u.get("input_tokens", 0) or 0
            m["out_tok"] += u.get("output_tokens", 0) or 0
            m["cache_read"] += u.get("cache_read_tokens", 0) or 0
            m["cache_write"] += u.get("cache_write_tokens", 0) or 0
            cost = request_cost(msg.get("model_name") or "", u)
            if cost is None:
                m["unpriced"] += 1
            else:
                for k, v in cost.items():
                    m[f"cost_{k}"] += v
            inv = sum(p.get("part_kind") == "tool-call" and p.get("tool_name") == "invoke_agent"
                      for p in msg.get("parts", []))
            if inv:
                m["invoke_per_response"].append(inv)
        for p in msg.get("parts", []):
            kind, name = p.get("part_kind"), p.get("tool_name")
            if kind == "tool-call":
                m["top_calls"] += 1
                m["top_by_tool"][name] = m["top_by_tool"].get(name, 0) + 1
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
    for k in COST_PARTS:
        m[f"cost_{k}"] = round(m[f"cost_{k}"], 6)
    m["cost_in"] = round(m["cost_uncached"] + m["cost_cache_read"] + m["cost_cache_write"], 6)
    m["cost_out"] = m["cost_output"]
    m["cost_usd"] = round(m["cost_in"] + m["cost_out"], 6)
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
                                               "in_tok", "out_tok", "cache_read", "cache_write", "unpriced")},
        **{k: round(sum(m[k] for m in ms), 6) for k in ("cost_usd", "cost_in", "cost_out",
                                                         *(f"cost_{p}" for p in COST_PARTS))},
        "nested": [n for m in ms for n in m["nested"]],
        "per_session": [{"requests": p["metrics"]["requests"], "in_tok": p["metrics"]["in_tok"],
                         "max_return_chars": p["max_return_chars"]} for p in per],
    }

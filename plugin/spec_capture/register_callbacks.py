"""spec_capture: per-run telemetry for the speculation A/B (user plugin, read-only).

Installed into an ISOLATED code-puppy home (HOME=<sandbox>), never into the
owner's live ~/.code_puppy. Activated only when SPEC_CAPTURE_OUT is set.

Records, per process:
  - every speculation / eager event that reaches SpeculationStats.handle_event
    (counted by class, plus the final hits/misses/wasted/saved_ms/eager_saved_ms)
  - per tool-call part: name, number of streamed arg deltas, arg chars
    (evidence that tool-call ARGUMENTS stream through the proxy)
  - pre/post tool calls (name, duration, error-ish result)
  - agent_run_start/end (perf_counter + wall time, success, error, response)
Writes one JSON document to $SPEC_CAPTURE_OUT at agent_run_end and at exit.

Optional arm override: SPEC_ARM=codemode_plain keeps the run_code sandbox but
removes speculation and eager execution (CodeMode(speculate=None, eager=False)).
SPEC_ARM=codemode_eager keeps eager execution but removes speculation (splits the two clocks).
"""

from __future__ import annotations

import atexit
import dataclasses
import json
import os
import time

from code_puppy.callbacks import register_callback

OUT = os.environ.get("SPEC_CAPTURE_OUT")
ARM = os.environ.get("SPEC_ARM", "")
T0 = time.perf_counter()
T0_WALL = time.time()

REC: dict = {
    "pid": os.getpid(),
    "arm_override": ARM or None,
    "plugin_loaded_s": 0.0,
    "t0_epoch": T0_WALL,
    "spec_events": {},
    "spec_final": None,
    "tool_parts": [],
    "tool_calls": [],
    "runs": [],
    "stream_event_counts": {},
}
_parts: dict = {}


def _now() -> float:
    return round(time.perf_counter() - T0, 4)


def _error_like(result, text: str) -> bool:
    """Heuristic: tool result reports failure (success=False or a non-empty error field)."""
    if getattr(result, "success", True) is False:
        return True
    err = getattr(result, "error", None)
    if err:
        return True
    if isinstance(result, dict) and (result.get("error") or result.get("success") is False):
        return True
    return text.lower().startswith(("error", "traceback"))


def _dump() -> None:
    if not OUT:
        return
    try:
        from code_puppy.messaging.speculation_stats import get_speculation_stats

        s = get_speculation_stats()
        REC["spec_final"] = {
            "hits": s.hits,
            "misses": s.misses,
            "wasted": s.wasted,
            "saved_ms": round(s.saved_ms, 1),
            "eager_saved_ms": round(s.eager_saved_ms, 1),
        }
    except Exception as e:  # stats module missing would itself be a finding
        REC["spec_final"] = {"error": repr(e)}
    try:
        from code_puppy.config import get_speculative_code_mode_enabled

        REC["speculation_enabled_cfg"] = get_speculative_code_mode_enabled()
    except Exception:
        pass
    REC["dumped_at_s"] = _now()
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(REC, f, indent=1, default=str)
    os.replace(tmp, OUT)


if OUT:
    # 1) Tally every speculation event the stream handler routes to the stats.
    from code_puppy.messaging import speculation_stats as _ss

    _orig_handle = _ss.SpeculationStats.handle_event

    def _handle(self, event):  # type: ignore[no-untyped-def]
        consumed = _orig_handle(self, event)
        if consumed:
            name = type(event).__name__
            d = REC["spec_events"].setdefault(name, {"n": 0, "first_s": _now()})
            d["n"] += 1
            d["last_s"] = _now()
            if name == "SpeculativeCallClaimedEvent":
                REC.setdefault("claims", []).append(
                    {
                        "tool": getattr(event, "wrapped_tool_name", None),
                        "ready": getattr(event, "ready_at_claim", None),
                        "elapsed_ms": getattr(event, "elapsed_ms", None),
                    }
                )
        return consumed

    _ss.SpeculationStats.handle_event = _handle

    # 2) Optional third arm: code mode WITHOUT speculation or eager execution.
    if ARM in ("codemode_plain", "codemode_eager"):
        from code_puppy.agents import _builder, _code_mode

        _orig_build = _code_mode.build_speculative_code_mode

        def _plain(agent_tools):  # type: ignore[no-untyped-def]
            caps = _orig_build(agent_tools)
            out = []
            for c in caps:
                if type(c).__name__ == "CodeMode":
                    c = dataclasses.replace(c, speculate=None, eager=(ARM == "codemode_eager"))
                out.append(c)
            REC["codemode_override_applied"] = REC.get("codemode_override_applied", 0) + 1
            return out

        _code_mode.build_speculative_code_mode = _plain
        _builder.build_speculative_code_mode = _plain

    # 3) Stream events: tool-call parts and whether their args stream.
    async def _on_stream(event_type, data, session_id=None):  # type: ignore[no-untyped-def]
        c = REC["stream_event_counts"]
        c[event_type] = c.get(event_type, 0) + 1
        if not isinstance(data, dict):
            return
        idx = (session_id, data.get("index"))
        if event_type == "part_start" and data.get("part_type") in (
            "ToolCallPart",
            "BuiltinToolCallPart",
        ):
            part = data.get("part")
            args = getattr(part, "args", None)
            _parts[idx] = rec = {
                "tool": getattr(part, "tool_name", None),
                "start_s": _now(),
                "initial_arg_chars": len(args) if isinstance(args, str) else len(json.dumps(args or {})),
                "arg_deltas": 0,
                "arg_delta_chars": 0,
                "subagent_session": session_id,
            }
            REC["tool_parts"].append(rec)
        elif event_type == "part_delta" and data.get("delta_type") == "ToolCallPartDelta":
            rec = _parts.get(idx)
            delta = data.get("delta")
            ad = getattr(delta, "args_delta", None)
            if rec is not None and ad:
                rec["arg_deltas"] += 1
                rec["arg_delta_chars"] += len(ad) if isinstance(ad, str) else len(json.dumps(ad))
                if getattr(delta, "tool_name_delta", None) and not rec["tool"]:
                    rec["tool"] = delta.tool_name_delta
        elif event_type == "part_end":
            rec = _parts.pop(idx, None)
            if rec is not None:
                rec["end_s"] = _now()

    register_callback("stream_event", _on_stream)

    # 4) Tool calls (native ones; issue #982 says code-mode calls bypass these hooks).
    async def _pre(tool_name, tool_args, context=None):  # type: ignore[no-untyped-def]
        REC["tool_calls"].append({"tool": tool_name, "phase": "pre", "t_s": _now()})

    async def _post(tool_name, tool_args, result, duration_ms, context=None):  # type: ignore[no-untyped-def]
        text = str(result)[:300]
        REC["tool_calls"].append(
            {
                "tool": tool_name,
                "phase": "post",
                "t_s": _now(),
                "duration_ms": round(float(duration_ms or 0), 1),
                "error_like": _error_like(result, text),
                "result_head": text[:160],
            }
        )

    register_callback("pre_tool_call", _pre)
    register_callback("post_tool_call", _post)

    # 5) Agent runs.
    async def _run_start(agent_name, model_name, session_id=None):  # type: ignore[no-untyped-def]
        REC["runs"].append(
            {"agent": agent_name, "model": model_name, "session": session_id,
             "start_s": _now(), "start_wall": time.time()}
        )

    async def _run_end(agent_name, model_name, session_id=None, success=True,
                       error=None, response_text=None, metadata=None):  # type: ignore[no-untyped-def]
        for r in reversed(REC["runs"]):
            if r.get("session") == session_id and "end_s" not in r:
                r.update(
                    end_s=_now(), success=success,
                    error=repr(error) if error else None,
                    response_text=(response_text or "")[:4000],
                    metadata=metadata,
                )
                break
        _dump()

    register_callback("agent_run_start", _run_start)
    register_callback("agent_run_end", _run_end)

    REC["plugin_loaded_s"] = _now()
    atexit.register(_dump)

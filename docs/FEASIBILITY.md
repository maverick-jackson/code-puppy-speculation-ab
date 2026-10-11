# Phase 1 feasibility: speculative code mode A/B, headless, via LiteLLM

code-puppy 0.0.896 (core plugins 0.0.77), pydantic-ai-harness CodeMode, macOS arm64, 2026-10-09/10.
Source paths below are relative to
`~/rig/tools/uv/code-puppy/lib/python3.14/site-packages/` (installed package, read directly).
Raw pilot data: `runs/pilot/<model>/<task>/<arm>/` (meta.json, capture.json, usage.json,
stdout.txt, stderr.txt, transcript/). Aggregates: `runs/pilot/summary.jsonl`.

## Verdict

FEASIBLE, with one model caveat. Speculation can be switched per run headlessly (isolated
HOME per arm, one config key), counters are captured headlessly by a small user plugin, and a
third arm (code mode without speculation) works through the same plugin. Speculation engaged
(hits > 0) for all four models through LiteLLM. Tool-call arguments STREAM for deepseek-flash,
deepseek-v4-pro and kimi-k2.7-code; they do NOT stream for zai-glm-4.7 (whole arguments arrive in
one chunk), so GLM gets no streaming runway (see 2).

Recommended arms: A = off (native tools), B = on (speculation), C = code mode only
(`SPEC_ARM=codemode_plain`). The pilot already suggests why C matters: code mode alone changes
requests and input tokens a lot (e.g. flash g2: 5 requests/38k input tokens OFF vs 10/83k
plain vs 12/110k ON), so B vs A mixes an interface effect with a speculation effect; B vs C
isolates speculation. Optional D = eager only (`SPEC_ARM=codemode_eager`, built, not yet run).

Recommended task source: a local suite (option b), not Harbor/Terminal-Bench, for the main
experiment (reasons in 6). Kimi needs special handling: Moonshot returns HTTP 429 on this
account (12 and 16 429-retries in its two pilot runs), which makes its timing meaningless
unless concurrency/rate is throttled or the account tier is raised.

Pilot is n = 1 per cell. It proves the pipeline, not any effect size.

## 1. Turning speculation on/off, and a third arm

- The switch is the config key `enable_speculative_code_mode` (default False):
  `code_puppy/config.py:161-172` (`get_truthy_bool_value("enable_speculative_code_mode", False)`).
  There is no CLI flag and no env var for it. Ctrl+X Ctrl+S only flips the same key
  (`code_puppy/messaging/speculation_toggle.py:35-44`).
- It is read when an agent is BUILT: `build_speculative_code_mode()` returns `[]` when the key is
  off (`code_puppy/agents/_code_mode.py:203-204`); called for the main agent at
  `code_puppy/agents/_builder.py:706` and for sub-agents at
  `code_puppy/tools/subagent_invocation.py:501`. So per-process control via config is exact.
- Per run, headless: we never touch the owner's config. Every run gets `HOME=<sandbox>`
  (`scripts/run_one.py`), and code-puppy derives all its dirs from HOME unless XDG_* vars are set
  (`code_puppy/config.py:23-51`; user plugins dir `code_puppy/plugins/__init__.py:29` is also
  `Path.home()/.code_puppy/plugins`). `scripts/mkhome.sh <dir> on|off` builds a home whose
  puppy.cfg differs between arms ONLY in `enable_speculative_code_mode`
  (verified with `diff runs/homes/off/.code_puppy/puppy.cfg runs/homes/on/.code_puppy/puppy.cfg`).
  Alternatives considered: `--profile NAME` (core plugin `code_puppy_core_plugins/profiles/config.py`)
  redirects only puppy.cfg; sessions, catalogs and plugins stay shared, so it is weaker isolation.
- Third arm, code mode WITHOUT speculation: not exposed by config. CodeMode itself supports it
  (`pydantic_ai_harness/code_mode/_capability.py:127,135`: `eager: bool = False`,
  `speculate: ... = None`; code-puppy hard-codes `eager=True, speculate=DeclaredSpeculation(...)`
  at `_code_mode.py:211-218`). Our plugin (`plugin/spec_capture/register_callbacks.py`) wraps
  `build_speculative_code_mode` and `dataclasses.replace`s the CodeMode when `SPEC_ARM` is set:
  - `SPEC_ARM=codemode_plain`: same `run_code` tool surface and guidance, `speculate=None,
    eager=False` (arm C, used in the pilot).
  - `SPEC_ARM=codemode_eager`: `speculate=None, eager=True` (optional arm D, separates the eager
    clock from the speculative clock; added after the pilot, NOT yet run).
  Evidence arm C engaged: `capture.json` has `codemode_plain_applied: 2`, every tool part is
  `run_code`, and zero speculation events (e.g. `runs/tmp/smoke-plain`, all `plain` pilot runs).
  Caveat: this is a monkeypatch of a private function; re-verify on any code-puppy upgrade.
  Pilot runs used the plugin build before arm D was added (counter key `codemode_plain_applied`;
  the repo version renames it `codemode_override_applied`). The only other difference is the
  eager option itself (`diff` of the deployed copy vs `plugin/spec_capture/`). Rebuild homes
  with `scripts/mkhome.sh` before Phase 2 so every arm runs the same plugin build.

## 2. Does speculation engage per model, and do arguments stream?

Evidence 1, the full agent (`capture.json` per run; `parts_args_streamed` = tool-call parts that
received more than one argument delta; hits/saved from `SpeculationStats`), ON arm only:

| model (LiteLLM group) | task | hits | misses | wasted | saved ms | tool parts | parts with streamed args |
|---|---|---|---|---|---|---|---|
| deepseek-flash | g1 | 5 | 0 | 0 | 153 | 3 | 3 |
| deepseek-flash | g2 | 4 | 0 | 2 | 148 | 11 | 11 |
| deepseek-v4-pro | g1 | 7 | 0 | 0 | 245 | 7 | 7 |
| deepseek-v4-pro | g2 | 10 | 0 | 0 | 328 | 10 | 10 |
| kimi-k2.7-code | g1 | 7 | 0 | 0 | 240 | 16 | 16 |
| zai-glm-4.7 (alias zai-g47) | g1 | 7 | 0 | 0 | 0 | 8 | 0 |
| zai-glm-4.7 (alias zai-g47) | g2 | 15 | 0 | 0 | 348 | 10 | 0 |

Evidence 2, a raw streaming request through the proxy with one tool
(`scripts/probe_arg_streaming.py`, output `runs/pilot/arg_streaming_probe.jsonl`):
deepseek-flash 44 argument chunks over 0.19 s; deepseek-v4-pro 52 chunks over 0.23 s;
kimi-k2.7-code 57 chunks over 1.02 s; zai-glm-4.7 exactly 1 tool-call chunk carrying all
arguments (169 and 129 chars, span 0.0 s, two probes).

Reading:
- DeepSeek and Kimi: arguments stream, speculation launches during generation, hits are mostly
  `ready_at_claim=True`.
- GLM-4.7: arguments arrive whole. In g1 every claim was `ready_at_claim=False`, saved 0. In g2
  saved was 348 ms anyway: when a single snippet contains several literal read calls, they are
  all launched the moment the (whole) code arrives and later calls are already finished when the
  sequential snippet reaches them. So for GLM, "speculation" degrades to intra-snippet
  prefetch/parallelism, not overlap with generation. Whether the buffering happens in Z.ai's
  API or in LiteLLM's zai route is NOT verified (we have no direct Z.ai key on the rig; the
  owner could test with one).
- GLM needed two sandbox-only workarounds to run at all through LiteLLM (identical in every arm,
  in `scripts/mkhome.sh`): (1) LiteLLM rejects `max_completion_tokens` for zai with 400
  UnsupportedParamsError, fixed by sending `drop_params: true` via code-puppy custom params
  (`model_settings_<model>_custom`, `code_puppy/model_factory.py:628-637`); (2) code-puppy
  injects `extra_body.thinking` for any model name matching glm-4.5+
  (`model_factory.py:386-411`, `model_utils.py:457-485`), and LiteLLM's zai route then fails
  with 500 "unexpected keyword argument 'thinking'". Fixed by a sandbox alias name
  `proxy-zai-g47` (same LiteLLM group `zai-glm-4.7`). GLM-4.7 thinks by default server-side.
  Evidence of the failures: `runs/pilot/_failed/glm-max-completion-tokens-400/`, and a 110 s,
  5-attempt retry storm for the 500 (`runs/tmp`, not committed).

## 3. Capturing counters headlessly

- Why headless prints nothing: the stream handler feeds speculation events only to the
  module-global `SpeculationStats` and `continue`s (`code_puppy/agents/event_stream_handler.py:185,371`);
  the stats only render into the bottom bar. But the counters DO accumulate in headless mode
  (`spec_enabled` depends only on config and not-a-subagent, not on a TTY).
- Capture = user plugin `spec_capture` (copied into each sandbox home's
  `.code_puppy/plugins/`; user plugins load without a trust prompt,
  `code_puppy/plugins/__init__.py:276-375`). When `SPEC_CAPTURE_OUT` is set it:
  1. wraps `SpeculationStats.handle_event` to tally every event class (Launched, Settled,
     Claimed, Missed, Evicted, CodeUpdate, EagerExecutionCompleted) and per-claim
     `ready_at_claim`/`elapsed_ms`;
  2. reads final `hits/misses/wasted/saved_ms/eager_saved_ms` from `get_speculation_stats()`;
  3. registers `stream_event` (per tool-call part: name, number of streamed arg deltas, arg
     chars), `pre_tool_call`/`post_tool_call` (name, duration, error heuristic),
     `agent_run_start`/`agent_run_end` (timing, success, error, response text);
  4. dumps JSON at each `agent_run_end` and at process exit.
- Limitation: only the MAIN agent is counted (`not is_subagent()` gate at
  `event_stream_handler.py:185`), matching what the status row would show. Sub-agent
  speculation is invisible to this capture. Our tasks never invoked sub-agents
  (`subagent_runs: 0` in every pilot row); the harness must flag any run where it is non-zero.
- Example (deepseek-flash, g1, ON, `runs/tmp/smoke-on/capture.json`):
  `{'hits': 6, 'misses': 0, 'wasted': 0, 'saved_ms': 702.9, 'eager_saved_ms': 0.0}` with
  172 CodeUpdate, 6 Launched, 5 Settled, 6 Claimed events.
- Finding: pre/post_tool_call hooks DO fire for tools called inside `run_code` in this version
  (grep/list_files/read_file appear in `tool_calls` for ON runs), so issue #982's hook bypass
  is about the read-write workspace mount (direct pathlib access), not wrapped tool calls.
  Not verified beyond these read-only tools.

## 4. Timing and noise

- End-to-end wall-clock: `time.perf_counter()` around `subprocess.run` of the real binary
  (`scripts/run_one.py`). The proxy key is decrypted ONCE per batch by `scripts/run_batch.sh` /
  `scripts/pilot.sh` (sops, roughly 0.1 to 0.3 s), outside every timed window.
- Decomposition per run (`scripts/summarize.py`): `boot_s` = process start to agent run start
  (plugin records epoch at import), `agent_s` = agent_run_start to agent_run_end, `teardown_s` =
  remainder. Pilot: boot is a steady ~3.5 s (Python imports), teardown ~0.7 s. Report both
  wall and agent time; agent time is the cleaner speed metric, wall the user-facing one.
- Per request: LiteLLM_SpendLogs has `startTime`, `completionStartTime` (time to first token),
  `endTime`, `request_duration_ms` per call. `scripts/collect_spend.py` attaches the rows in the
  run's UTC window. Gotcha: LiteLLM writes these rows asynchronously and late (rows were missing
  3 s after a run, present ~1 min later), so collect after the batch. The window join is only
  valid while runs are sequential and nothing else uses the proxy; the collector records the
  row models so contamination is visible.
- Noise sources and how both arms neutralise them identically (env in `run_one.py`, cfg in
  `mkhome.sh`):
  - update check: `NO_VERSION_UPDATE=1` (`code_puppy/cli_runner.py:425-440`);
  - MCP servers: none in the sandbox, plus `disable_mcp = true`;
  - splash/tutorial/TUI: `CODE_PUPPY_NO_SPLASH=1`, `CODE_PUPPY_SKIP_TUTORIAL=1`,
    `CODE_PUPPY_NO_TUI=1`, `NO_COLOR=1`; smooth (typewriter) streaming off in cfg;
  - frontend emitter off, universal constructor off (identical tool surface in both arms;
    note this differs from the default install);
  - first run in a fresh home does a one-time "Flux commands installed" bootstrap: warm every
    home once before timed runs (done in the pilot);
  - autosave: headless ALWAYS persists the session (`cli_runner.py` `execute_single_prompt`
    finally-block) even with `auto_save_session = false`; cheap, identical in both arms, and it
    is our transcript (copied to `<run>/transcript/`);
  - `-m MODEL` is written back into the home's puppy.cfg (observed: `model =` changed after a
    run). Harmless here because every run passes `-m`, but it means homes are stateful;
  - stream retries: code-puppy retries failed streams with backoff (observed 5 attempts,
    ~110 s, on a GLM 400/500). Count them (stdout `(attempt N, streak`) and treat a run with
    retries as a reliability event, not a timing sample;
  - provider latency drift: the dominant noise. Interleave arms in shuffled order within each
    (task, model) block, as `scripts/pilot.sh` does.

## 5. Reliability signals per run

- Exit status is NOT a success signal: headless catches every agent error, prints it and exits 0
  (`cli_runner.py:1534`; observed: all six failed GLM runs in `runs/pilot/_failed/` exit 0).
  Harbor's adapter notes the same and fails a run when `--usage-file` was not written. Use:
  `usage.json` present, `capture.runs[0].success`, and an `Error executing prompt` scan.
- Final answer text: stdout and `capture.runs[0].response_text`; graded by
  `scripts/grade.py` (last `ANSWER:` line, normalised exact match).
- Tool errors: `post_tool_call` results with `success=False` or a non-empty `error`
  (`tool_errors` in summary), plus `run_code` errors visible in the transcript.
- Malformed / retried tool calls: pydantic-ai retry prompts are in the transcript
  (`transcript/auto_session_*.json`, `RetryPromptPart`); not yet parsed (Phase 2).
- Requests and tokens: `usage.json` (code-puppy) and proxy rows (LiteLLM); they agreed exactly on
  the smoke run (14,681 input tokens both).

## 6. Task source recommendation

Recommendation: (b) a local suite, Harbor/Terminal-Bench optional later as an external check.

- Harbor's merged adapter (`harbor-framework/harbor` PR #3199, merged 2026-09-14,
  `src/harbor/agents/installed/code_puppy.py`, read via `gh api`) writes puppy.cfg itself with a
  fixed key list (`_render_puppy_cfg`: required keys, `auto_save_session = false`, optional
  reasoning effort). There is NO kwarg for `enable_speculative_code_mode`, and no way to drop in
  our capture plugin. Both arms would need a custom agent subclass (Harbor supports agent import
  paths; not verified here).
- Proxy reachability from a container: the adapter has a `base_url` kwarg (OpenAI-compatible
  endpoint, key via `CODE_PUPPY_API_KEY`), but LiteLLM listens on 127.0.0.1:4000 only
  (`lsof -iTCP:4000`). Reaching it from colima requires the Lima host alias (host.lima.internal)
  forwarding to host loopback; NOT verified. Docker/colima are not installed and I did not
  install them.
- Terminal-Bench tasks are mostly shell/code-change work in task containers with image builds
  per trial; the creator's own hypothesis is that speculation helps GATHERING, and container
  build and test time would add large, arm-independent noise to the wall-clock signal we are
  trying to detect (a few seconds per task).
- The local suite is already working: pinned clone (`runs/repos/click`, pallets/click tag 8.1.7,
  commit 874ca2b, about 17.5k lines of Python), task prompt + `.expected` file, exact-match
  grader. Phase 2 should add more gathering tasks (several repos), plus small code-change
  tasks with hidden pytest graders run after the agent exits (create_file/replace_in_file stay
  native in every arm, so edits are comparable).

Measured cost and time per gathering task (pilot, per run, all arms pooled):

| model | wall s (range) | input tokens (range) | proxy $ (range) |
|---|---|---|---|
| deepseek-flash | 9 to 23 | 18k to 110k | 0.0015 to 0.0029 |
| deepseek-v4-pro | 14 to 31 | 23k to 104k | 0.006 to 0.016 |
| zai-glm-4.7 | 36 to 142 | 19k to 126k | 0.005 to 0.023 |
| kimi-k2.7-code | 163 to 248 (429-bound) | 37k to 129k | 0.016 to 0.045 |

Rough budget: 4 models x 3 arms x 15 tasks x 5 reps = 900 runs at the pilot mean of about
$0.012 per run is about $11 in total, inside the combined preloaded balances (DeepSeek $5,
Z.ai $10, Moonshot $5) but Kimi runs cost about 3x the mean and are 429-throttled, so size the
main run per provider and schedule Kimi last.

## 7. Pilot

Tasks: `tasks/g1_click_exceptions.txt` (expected `MissingParameter|BadParameter|2|45`),
`tasks/g2_click_completion.txt` (expected `4.4|7|_MY_TOOL_COMPLETE|RuntimeError`), cwd = the
pinned click clone. Arms in shuffled order per (model, task) where run by `scripts/pilot.sh`.
All 20 valid runs answered correctly. `wall_s` = process start to exit; `agent_s` = agent run
only; tokens from `--usage-file`; `proxy_spend` from LiteLLM_SpendLogs; `slept` = machine
sleep detected (all False here).

| model | task | arm | slept | wall_s | agent_s | correct | requests | in_tok | out_tok | proxy_spend | hits | misses | wasted | saved_ms | eager_saved_ms | tool_parts | parts_args_streamed | tool_errors | http_429 | proxy_failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| deepseek-flash | g1 | off | False | 8.781 | 4.544 | True | 3 | 17592 | 477 | 0.0015 | 0 | 0 | 0 | 0.0 | 0.0 | 5 | 5 | 1 | 0 | 0 |
| deepseek-flash | g1 | on | False | 9.936 | 5.717 | True | 4 | 30504 | 565 | 0.0016 | 5 | 0 | 0 | 153.3 | 0.0 | 3 | 3 | 0 | 0 | 0 |
| deepseek-flash | g1 | plain | False | 10.808 | 6.582 | True | 4 | 37133 | 641 | 0.0021 | 0 | 0 | 0 | 0.0 | 0.0 | 6 | 6 | 0 | 0 | 0 |
| deepseek-flash | g2 | off | False | 12.158 | 7.907 | True | 5 | 37755 | 902 | 0.0021 | 0 | 0 | 0 | 0.0 | 0.0 | 7 | 7 | 1 | 0 | 0 |
| deepseek-flash | g2 | on | False | 23.161 | 18.924 | True | 12 | 110224 | 1616 | 0.0029 | 4 | 0 | 2 | 147.6 | 0.0 | 11 | 11 | 4 | 0 | 0 |
| deepseek-flash | g2 | plain | False | 18.639 | 14.388 | True | 10 | 82713 | 1351 | 0.0025 | 0 | 0 | 0 | 0.0 | 0.0 | 9 | 9 | 2 | 0 | 0 |
| deepseek-v4-pro | g1 | off | False | 13.958 | 9.934 | True | 4 | 23271 | 676 | 0.0063 | 0 | 0 | 0 | 0.0 | 0.0 | 4 | 4 | 0 | 0 | 0 |
| deepseek-v4-pro | g1 | on | False | 24.493 | 20.425 | True | 8 | 72795 | 1219 | 0.0111 | 7 | 0 | 0 | 244.5 | 0.0 | 7 | 7 | 2 | 0 | 0 |
| deepseek-v4-pro | g1 | plain | False | 30.672 | 26.621 | True | 8 | 77734 | 1705 | 0.0126 | 0 | 0 | 0 | 0.0 | 0.0 | 10 | 10 | 1 | 0 | 0 |
| deepseek-v4-pro | g2 | off | False | 30.425 | 26.377 | True | 8 | 103954 | 1672 | 0.0162 | 0 | 0 | 0 | 0.0 | 0.0 | 11 | 11 | 1 | 0 | 0 |
| deepseek-v4-pro | g2 | on | False | 22.845 | 18.819 | True | 7 | 69954 | 1222 | 0.0119 | 10 | 0 | 0 | 328.1 | 0.0 | 10 | 10 | 0 | 0 | 0 |
| deepseek-v4-pro | g2 | plain | False | 22.251 | 18.22 | True | 6 | 71826 | 1206 | 0.0138 | 0 | 0 | 0 | 0.0 | 0.0 | 10 | 10 | 2 | 0 | 0 |
| kimi-k2.7-code | g1 | off | False | 163.109 | 159.088 | True | 7 | 36802 | 715 | 0.0156 | 0 | 0 | 0 | 0.0 | 0.0 | 6 | 6 | 0 | 12 | 12 |
| kimi-k2.7-code | g1 | on | False | 248.222 | 243.501 | True | 15 | 129417 | 2353 | 0.0446 | 7 | 0 | 0 | 240.4 | 0.0 | 16 | 16 | 6 | 16 | 16 |
| zai-g47 | g1 | off | False | 35.794 | 31.509 | True | 4 | 19224 | 524 | 0.0052 | 0 | 0 | 0 | 0.0 | 0.0 | 5 | 0 | 1 | 0 | 0 |
| zai-g47 | g1 | on | False | 74.295 | 70.013 | True | 9 | 79061 | 1240 | 0.0170 | 7 | 0 | 0 | 0.0 | 0.5 | 8 | 0 | 1 | 0 | 0 |
| zai-g47 | g1 | plain | False | 78.891 | 74.649 | True | 10 | 69644 | 1247 | 0.0129 | 0 | 0 | 0 | 0.0 | 0.0 | 9 | 0 | 3 | 0 | 0 |
| zai-g47 | g2 | off | False | 87.854 | 83.792 | True | 8 | 72404 | 1827 | 0.0184 | 0 | 0 | 0 | 0.0 | 0.0 | 12 | 0 | 2 | 0 | 0 |
| zai-g47 | g2 | on | False | 105.664 | 101.58 | True | 11 | 107397 | 1921 | 0.0221 | 15 | 0 | 0 | 348.3 | 0.5 | 10 | 0 | 5 | 0 | 0 |
| zai-g47 | g2 | plain | False | 141.733 | 137.692 | True | 16 | 125685 | 2638 | 0.0230 | 0 | 0 | 0 | 0.0 | 0.0 | 15 | 0 | 1 | 0 | 0 |

Total pilot proxy spend: $0.2435 over 20 runs

Notes on the table:
- flash `off` rows were recorded with an earlier plugin build (no boot timestamp, and a cruder
  tool-error heuristic that flagged `error=''`); their counters and timings are otherwise valid.
- Kimi g1 and V4-Pro g1 on/off, and all g2 runs except flash, were run individually (not via the
  shuffled loop) after the first loop was stopped; Kimi g1 has no `plain` run.
- n = 1 per cell. ON was slower than OFF in 6 of 7 pairs, and `plain` was about as slow as ON,
  which points at the code-mode interface (more turns, more input tokens) rather than at
  speculation. That is a hypothesis for Phase 3, not a result.
- `tool_errors` in code-mode arms are mostly sandbox runtime errors inside `run_code`
  (Python exceptions in model-written snippets); native arms show tool-level errors (grep on a
  file path, read_file on a >10k token file). This is the RQ6 signal.

Invalidated pilot attempts (kept as evidence, excluded above):
- `runs/pilot/_failed/glm-max-completion-tokens-400/`: all 6 GLM runs failed with LiteLLM 400,
  each still exit 0.
- `runs/pilot/_failed/glm-g2-machine-asleep/`: the MacBook lid was closed on battery during the
  first loop; pmset log shows "DarkWake from Deep Idle ... lid", one GLM request took 15 min,
  and the run recorded `wall_s` 89 s for a process that lived 31 min, because perf_counter and
  monotonic stop during macOS sleep. Runner fixed: wall-clock timeout + process-group kill +
  `slept` flag. Kimi and V4-Pro were run after the lid was opened.

Spend (LiteLLM_SpendLogs, all models): before this phase $0.040480 (44 rows); after
$0.336723 (303 rows). Phase 1 total $0.2962, of which the 20 pilot runs in the table are
$0.2435 and the rest is smoke tests, home warm-ups, the failed GLM attempts and the probes.

## Not verified

- Statistical effect of speculation on wall-clock, success or cost: n = 1, nothing concluded.
- Whether GLM argument buffering is Z.ai or LiteLLM (no direct Z.ai key).
- Harbor custom-agent subclass with speculation on, container to proxy networking via colima.
  Nothing was installed (no Homebrew, no Docker, no colima).
- Sub-agent speculation counters (main agent only; no pilot run used sub-agents).
- `codemode_eager` arm D: implemented in the plugin and runner, never run.
- Code-change tasks: none piloted; only gathering tasks.
- Kimi rate limits: the 429s are observed; the Moonshot tier and its RPM/TPM limits are not
  checked. Kimi `plain` arm not run.
- The proxy-row join is by time window; valid only with nothing else using the proxy. No foreign
  model rows appeared in any pilot window (checked via `proxy_models`), but the owner's own
  sessions on the same model would be indistinguishable.
- The `-m` flag persists the model into the sandbox puppy.cfg; harmless here, not investigated
  for other side effects.
- Owner config: `~/.code_puppy` was only READ (extra_models.json copied into sandboxes); no
  backup/restore was needed because nothing in it was written.

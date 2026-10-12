# Follow-up: making code mode actually batch

_2026-10-11. A follow-up to the main A/B in this repo, by Mike Pfaffenberger (Code Puppy maintainer)._

The main A/B found that code mode made code-puppy slower on short tasks: about 61% of `run_code` snippets
wrapped exactly one tool call, so every snippet cost a full model round trip, and models kept hitting
sandbox gaps (`sys.path`, `Path.glob`, `subprocess`). It also asked for a workload where code mode should
win. This follow-up does both: it fixes what the A/B pointed at, re-measures on the same 20 tasks, and adds
10 long-horizon tasks, including ones that delegate to sub-agents.

The report with charts, `docs/results/codemode_followup.html` (a single self-contained file), compares code mode off vs on across every workload, metric and task.

## Short answer

- **Code mode on vs off across all 30 tasks, five models** (task-balanced: median of per-task changes).
  Every model makes fewer model requests with code mode (-12% to -40%). Wall time and tokens depend on
  the model:

  | model | model requests | wall time | input tokens | success off → on |
  |---|---|---|---|---|
  | gpt-6.1-sol | -40% | -6% | -3% | 90% → 92% |
  | gpt-6-luna | -12% | +16% | +34% | 77% → 72% |
  | claude-opus-5.5 | -16% | -1% | +20% | 100% → 97% |
  | claude-sonnet-5.5 | -19% | -3% | +12% | 100% → 100% |
  | claude-haiku-5.5 | -25% | -8% | -5% | 98% → 95% |

  Clear wins: gpt-6.1-sol and claude-haiku-5.5. Opus and Sonnet are about even on time and pay 12 to 20%
  more input tokens; luna is slower and pays more. The Claude models already batch well without code mode
  (1.2 to 1.3 tool calls per response, and they usually start all four sub-agents in one response), so
  code mode has less to fix for them.
- **Snippets now carry real work.** Tool calls per `run_code` went 1.60 → 3.19 (gpt-6-luna) and
  2.03 → 2.74 (gpt-6.1-sol). Sandbox errors per task fell 0.42 → 0.04 (sol) and 0.44 → 0.17 (luna).
- **Short tasks are still roughly a wash on wall time** against plain tool calling. sol makes 37% fewer
  model requests than with code mode off; luna makes 10% fewer but still pays more input tokens, because
  code mode adds about 2.8k tokens of sandbox stubs to every request.
- **Long tasks:** same success as plain tool calling with fewer model requests (sol 7.5 vs 11.4, luna 7.0
  vs 9.5) at the same wall time; luna uses 30% fewer input tokens.
- **Sub-agents are where code mode wins clearly.** One `run_code` launches all four sub-agents at once.
  sol finishes delegation tasks in 89s vs 217s with code mode off (285s if its one 900s timeout is
  counted), with 19.5 vs 43.1 total requests and 99% vs 91% of answer parts right.
- The benchmark found **two real Code Puppy bugs**, both fixed and merged (below).

## What changed in Code Puppy

- [code_puppy#1013](https://github.com/mpfaffenberger/code_puppy/pull/1013), merged:
  - Code-mode guidance rewritten around "write programs, not single calls" (batch, chain, loop, filter in
    code, absorb errors) with two type-clean multi-call examples. The old "never compute arguments"
    speculation rule, which discouraged loops, became a footnote.
  - The sandbox gaps from the A/B are stated up front: no `Path.glob` / `rglob`, `os.walk`, `sys.path`,
    `subprocess`; `next(genexpr)` raises (generator expressions are lists in Monty); `str | None` result
    fields must be narrowed for the type checker.
  - A batching note on the `run_code` tool description itself.
  - Bug fix: nested tool results over 10k chars came back to the snippet as a spill-handle string
    instead of a dict. Now only what reaches the model is bounded.
  - Bug fix: `read_file` refused files over 10k tokens with `content=None`, which snippet code read as
    an empty file and silently undercounted. In code mode the sandbox now gets the whole file.
- [code_puppy#1014](https://github.com/mpfaffenberger/code_puppy/pull/1014), merged: sub-agents were
  built without the main agent's tool-output limits. Once the sandbox could read whole files, single
  sub-agent returns reached 294,877 chars. Sub-agents now get the same bounds.

## Setup

- **Variants** (`--bin VARIANT=PATH`): `off` = code-puppy main with code mode disabled; `base` = code mode
  before #1013 (main at f2f2e462); `new` = after #1013; `fix` = after #1014.
- **Models:** `codex-gpt-6.1-sol` and `codex-gpt-6-luna` through Code Puppy's ChatGPT OAuth, and
  `claude-code-claude-{opus,sonnet,haiku}-5-5` through its Claude Code OAuth (no LiteLLM). Claude runs get a
  copy of the OAuth token without its refresh token; the runner refreshes the real token through the
  plugin when needed, so benchmark runs can never rotate it.
  GLM 5.3 served by vLLM was tried and dropped: at about 20 tokens/s it timed out on most long code-mode runs.
- **Tasks:** the original 20 tasks and graders, unchanged, plus 10 long-horizon tasks built from them by
  `scripts/longtasks.py`:
  - `L_<repo>_gather`: all four question sets for one repo in one task (15 to 16 answer fields).
  - `L_click_code` (four click bugs stacked in one patch) and `L_invkit_code` (two bugs, two features),
    graded by all four hidden test files.
  - `D_*`: the same five tasks, told to delegate the parts to sub-agents with `invoke_agent`.
  - `longtasks.py validate` checks that every long code task fails each part when bugged and passes each
    part with the reference fixes applied, and that each gather answer key grades itself correct.
- **Runner:** `scripts/codemode_ab.py`. One headless `code-puppy -p` per run, a fresh working copy, and
  private config / cache / state / data dirs; only the ChatGPT OAuth token and model list are shared.
  The run's model is pinned in the config so sub-agents use it too, and every sub-agent session is kept.
- **Grading:** as in the main A/B, except gather answers are read from the transcript's final text.
  Rendered stdout wraps long lines at terminal width, which split the 16-field ANSWER lines; regrading
  the short tasks this way changes none of their grades.
- **Metrics:** nested tool calls are read from the `run_code` return metadata, so loops and
  `asyncio.gather` fan-outs are counted exactly. Long-task totals include every sub-agent's requests
  and tokens. "Parts right" is the share of answer fields (gather) or hidden test files (code) passed.
- **Size:** 1,220 runs, records in `runs/codemode/<batch>/records.jsonl`. Claude models: 360 in `claude1`
  (30 tasks x off/on x 2 reps x 3 models, off and on from the same current-main build). Short tasks: 80 runs per
  iteration batch, 160 in the interleaved `conf` batch, 80 in `off1`. Long tasks: 120 in `long1`, 20 in
  `fix1`. Full transcripts (212 MB) are not committed; `scripts/cm_transcripts.py` is the code that
  turned them into the records.

Reproduce every table below with `python3 scripts/codemode_tables.py`, and the HTML report with
`python3 scripts/codemode_report.py`.

## Results

Short-task rows pool `base1` + `conf` (base) and `new5` + `conf` (new); `off` is its own batch (`off1`),
so that comparison is not controlled for time of day. In `long1` the off / base / new variants were
shuffled together; `fix1` is a separate batch. The Claude models ran in one batch, `claude1`, with off and on shuffled together.

### Code mode off vs on (current main)

Across all 30 tasks, task-balanced (each task counts once; median of per-task changes):

| model | model requests | wall time | input tokens | success off → on |
|---|---|---|---|---|
| gpt-6.1-sol | -40% (better on 29/30) | -6% (better on 18/30) | -3% (better on 15/30) | 90% → 92% |
| gpt-6-luna | -12% (better on 23/30) | +16% (better on 9/30) | +34% (better on 8/30) | 77% → 72% |
| claude-opus-5.5 | -16% (better on 22/30) | -1% (better on 15/30) | +20% (better on 7/30) | 100% → 97% |
| claude-sonnet-5.5 | -19% (better on 20/30) | -3% (better on 21/30) | +12% (better on 8/30) | 100% → 100% |
| claude-haiku-5.5 | -25% (better on 24/30) | -8% (better on 20/30) | -5% (better on 16/30) | 98% → 95% |

#### gpt-6.1-sol, per workload

| workload | runs off / on | success | parts right | wall mean s | model requests | tool calls | tool calls / request | input tok k | output tok k |
|---|---|---|---|---|---|---|---|---|---|
| Short: read and answer | 24 / 48 | 96% → 92% | 99% → 98% | 22.5 → 20.6 (-8%) | 5.83 → 3.04 (-48%) | 5.8 → 5.3 (-9%) | 0.99 → 1.75 (+77%) | 29.1 → 22.5 (-23%) | 0.34 → 0.46 (+35%) |
| Short: bug fix | 16 / 32 | 100% → 100% | 100% → 100% | 42.2 → 46.8 (+11%) | 8.56 → 6.38 (-25%) | 9.8 → 12.7 (+30%) | 1.15 → 1.99 (+73%) | 42.9 → 57.3 (+34%) | 0.92 → 1.36 (+48%) |
| Long: read and answer | 6 / 6 | 67% → 67% | 98% → 98% | 57.4 → 47.0 (-18%) | 10.67 → 5 (-53%) | 15.3 → 11.2 (-27%) | 1.44 → 2.23 (+55%) | 82.2 → 43.8 (-47%) | 1.38 → 1.55 (+12%) |
| Long: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 84.4 → 96.0 (+14%) | 12.5 → 11.25 (-10%) | 15.2 → 23.2 (+53%) | 1.22 → 2.07 (+70%) | 100.9 → 132.6 (+31%) | 2.25 → 3.12 (+39%) |
| Delegated: read and answer | 6 / 6 | 67% → 83% | 98% → 99% | 193.1 → 82.9 (-57%) | 40.5 → 18 (-56%) | 44.5 → 34 (-24%) | 1.1 → 1.89 (+72%) | 219.4 → 139.2 (-37%) | 5.12 → 5.53 (+8%) |
| Delegated: multi-fix | 4 / 4 | 75% → 100% | 81% → 100% | 423.2 → 120.7 (-71%) | 48.33 → 26.75 (-45%) | 51.3 → 55.5 (+8%) | 1.06 → 2.07 (+95%) | 252.5 → 242.4 (-4%) | 6.51 → 7.29 (+12%) |

#### gpt-6-luna, per workload

| workload | runs off / on | success | parts right | wall mean s | model requests | tool calls | tool calls / request | input tok k | output tok k |
|---|---|---|---|---|---|---|---|---|---|
| Short: read and answer | 24 / 48 | 75% → 75% | 93% → 94% | 17.8 → 20.8 (+17%) | 4.54 → 4.21 (-7%) | 5.3 → 11.5 (+117%) | 1.17 → 2.74 (+134%) | 25.5 → 32.8 (+29%) | 0.25 → 0.53 (+112%) |
| Short: bug fix | 16 / 32 | 100% → 100% | 100% → 100% | 28.8 → 29.7 (+3%) | 7.38 → 6.38 (-14%) | 7.6 → 11.1 (+46%) | 1.03 → 1.75 (+70%) | 36.6 → 53.5 (+46%) | 0.63 → 0.81 (+29%) |
| Long: read and answer | 6 / 6 | 17% → 17% | 92% → 90% | 41.5 → 41.2 (-1%) | 8.33 → 5.5 (-34%) | 15.7 → 26.2 (+67%) | 1.88 → 4.76 (+153%) | 108.1 → 52.3 (-52%) | 0.95 → 1.43 (+51%) |
| Long: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 50.5 → 49.3 (-2%) | 11.25 → 9.25 (-18%) | 15 → 22.5 (+50%) | 1.33 → 2.43 (+83%) | 89.5 → 98.2 (+10%) | 1.32 → 1.31 (-1%) |
| Delegated: read and answer | 6 / 6 | 50% → 17% | 96% → 90% | 78.3 → 81.1 (+4%) | 29.17 → 25 (-14%) | 34.7 → 68 (+96%) | 1.19 → 2.72 (+129%) | 207.5 → 194.4 (-6%) | 2.6 → 4.42 (+70%) |
| Delegated: multi-fix | 4 / 4 | 100% → 75% | 100% → 94% | 100.5 → 81.3 (-19%) | 34.25 → 28.75 (-16%) | 39.5 → 65.5 (+66%) | 1.15 → 2.28 (+98%) | 176.4 → 244.8 (+39%) | 3.34 → 4.23 (+27%) |

#### claude-opus-5.5, per workload

| workload | runs off / on | success | parts right | wall mean s | model requests | tool calls | tool calls / request | input tok k | output tok k |
|---|---|---|---|---|---|---|---|---|---|
| Short: read and answer | 24 / 24 | 100% → 100% | 100% → 100% | 17.1 → 15.7 (-8%) | 3.79 → 3.08 (-19%) | 4 → 3.1 (-22%) | 1.05 → 1.0 (-5%) | 33.8 → 38.6 (+14%) | 1.06 → 1.05 (-1%) |
| Short: bug fix | 16 / 16 | 100% → 100% | 100% → 100% | 24.3 → 26.2 (+8%) | 5.88 → 5.25 (-11%) | 6.2 → 7.6 (+23%) | 1.05 → 1.45 (+38%) | 56.4 → 72.1 (+28%) | 1.63 → 1.86 (+14%) |
| Long: read and answer | 6 / 6 | 100% → 83% | 100% → 99% | 27.9 → 31.6 (+13%) | 4 → 4.33 (+8%) | 4.3 → 7.8 (+81%) | 1.08 → 1.81 (+68%) | 47.8 → 64.8 (+36%) | 2.28 → 2.67 (+17%) |
| Long: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 49.3 → 43.4 (-12%) | 7.5 → 6.25 (-17%) | 10.2 → 7.5 (-26%) | 1.37 → 1.2 (-12%) | 104.1 → 102.0 (-2%) | 4.37 → 3.58 (-18%) |
| Delegated: read and answer | 6 / 6 | 100% → 83% | 100% → 99% | 52.4 → 44.3 (-15%) | 17.83 → 14 (-21%) | 21 → 21.3 (+1%) | 1.18 → 1.52 (+29%) | 158.5 → 169.3 (+7%) | 8.49 → 7.0 (-18%) |
| Delegated: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 118.8 → 89.8 (-24%) | 30.5 → 24 (-21%) | 34.8 → 39 (+12%) | 1.14 → 1.62 (+42%) | 344.6 → 334.0 (-3%) | 17.83 → 13.86 (-22%) |

#### claude-sonnet-5.5, per workload

| workload | runs off / on | success | parts right | wall mean s | model requests | tool calls | tool calls / request | input tok k | output tok k |
|---|---|---|---|---|---|---|---|---|---|
| Short: read and answer | 24 / 24 | 100% → 100% | 100% → 100% | 14.0 → 12.9 (-8%) | 3.75 → 2.96 (-21%) | 4.2 → 3.1 (-26%) | 1.13 → 1.04 (-8%) | 33.4 → 37.2 (+11%) | 0.82 → 0.85 (+4%) |
| Short: bug fix | 16 / 16 | 100% → 100% | 100% → 100% | 19.5 → 19.3 (-1%) | 6.06 → 4.81 (-21%) | 6.8 → 6.6 (-3%) | 1.12 → 1.38 (+23%) | 56.3 → 64.9 (+15%) | 1.25 → 1.56 (+25%) |
| Long: read and answer | 6 / 6 | 100% → 100% | 100% → 100% | 23.8 → 23.3 (-2%) | 4.33 → 3.67 (-15%) | 5.7 → 8 (+40%) | 1.31 → 2.18 (+66%) | 53.9 → 56.7 (+5%) | 1.98 → 2.25 (+14%) |
| Long: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 32.0 → 28.5 (-11%) | 7.75 → 5.5 (-29%) | 12.8 → 5.5 (-57%) | 1.65 → 1.0 (-39%) | 97.8 → 85.4 (-13%) | 3.07 → 2.77 (-10%) |
| Delegated: read and answer | 6 / 6 | 100% → 100% | 100% → 100% | 37.9 → 41.0 (+8%) | 15.67 → 17.17 (+10%) | 18.8 → 22 (+17%) | 1.2 → 1.28 (+7%) | 139.6 → 212.6 (+52%) | 6.43 → 7.3 (+14%) |
| Delegated: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 78.2 → 69.9 (-11%) | 29.5 → 30.5 (+3%) | 35.8 → 43 (+20%) | 1.21 → 1.41 (+17%) | 304.1 → 407.3 (+34%) | 10.95 → 11.85 (+8%) |

#### claude-haiku-5.5, per workload

| workload | runs off / on | success | parts right | wall mean s | model requests | tool calls | tool calls / request | input tok k | output tok k |
|---|---|---|---|---|---|---|---|---|---|
| Short: read and answer | 24 / 24 | 100% → 96% | 100% → 99% | 12.8 → 11.6 (-9%) | 4.33 → 3.08 (-29%) | 5.4 → 4.4 (-19%) | 1.24 → 1.42 (+15%) | 44.7 → 39.5 (-12%) | 1.47 → 1.37 (-7%) |
| Short: bug fix | 16 / 16 | 100% → 100% | 100% → 100% | 21.2 → 20.6 (-3%) | 7.12 → 5.75 (-19%) | 8.8 → 12.4 (+41%) | 1.24 → 2.15 (+73%) | 78.4 → 86.1 (+10%) | 2.79 → 2.92 (+5%) |
| Long: read and answer | 6 / 6 | 83% → 83% | 99% → 99% | 26.3 → 27.4 (+4%) | 6.5 → 5.5 (-15%) | 9.2 → 23 (+150%) | 1.41 → 4.18 (+196%) | 110.9 → 89.0 (-20%) | 4.59 → 5.19 (+13%) |
| Long: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 50.7 → 34.6 (-32%) | 12.5 → 8 (-36%) | 21.8 → 22.8 (+5%) | 1.74 → 2.84 (+63%) | 242.0 → 163.4 (-32%) | 8.13 → 6.58 (-19%) |
| Delegated: read and answer | 6 / 6 | 100% → 83% | 100% → 99% | 38.9 → 35.6 (-8%) | 24.33 → 16.5 (-32%) | 31.8 → 23.3 (-27%) | 1.31 → 1.41 (+8%) | 268.8 → 221.9 (-17%) | 12.2 → 10.23 (-16%) |
| Delegated: multi-fix | 4 / 4 | 100% → 100% | 100% → 100% | 76.6 → 75.1 (-2%) | 32 → 31.75 (-1%) | 42.2 → 59.2 (+40%) | 1.32 → 1.87 (+42%) | 392.3 → 502.7 (+28%) | 19.69 → 22.02 (+12%) |

### Short tasks (pooled)

| model | variant | n | success | wall mean s | wall median s | requests/task | calls/run_code | % run_code <=1 call | run_code errors/task | in tok k | out tok k |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6.1-sol | off | 40 | 39/40 | 30.4 | 27.4 | 6.92 | 0 | 0 | 0 | 34.6 | 0.57 |
| gpt-6.1-sol | base | 80 | 76/80 | 32.7 | 25.1 | 5.06 | 2.03 | 43 | 0.42 | 39.9 | 0.78 |
| gpt-6.1-sol | new | 80 | 76/80 | 31.1 | 24.4 | 4.38 | 2.74 | 31 | 0.04 | 36.4 | 0.82 |
| gpt-6-luna | off | 40 | 34/40 | 22.2 | 17.9 | 5.67 | 0 | 0 | 0 | 29.9 | 0.41 |
| gpt-6-luna | base | 80 | 65/80 | 22.8 | 21.1 | 6.13 | 1.6 | 58 | 0.44 | 48.8 | 0.49 |
| gpt-6-luna | new | 80 | 68/80 | 24.3 | 22.6 | 5.08 | 3.19 | 36 | 0.17 | 41.1 | 0.64 |

### Prompt iterations

| model | iteration | success | requests/task | calls/run_code | % run_code <=1 call | run_code errors/task |
|---|---|---|---|---|---|---|
| gpt-6.1-sol | main | 38/40 | 5.05 | 2.02 | 41 | 0.45 |
| gpt-6.1-sol | it1 | 39/40 | 4.6 | 2.58 | 21 | 0.25 |
| gpt-6.1-sol | it2 | 36/40 | 5.1 | 3.11 | 22 | 0.57 |
| gpt-6.1-sol | it3 | 36/40 | 4.7 | 2.82 | 29 | 0.03 |
| gpt-6.1-sol | it4 | 36/40 | 4.5 | 2.82 | 27 | 0.03 |
| gpt-6.1-sol | it5 | 38/40 | 4.33 | 2.77 | 30 | 0.05 |
| gpt-6-luna | main | 31/40 | 6.15 | 1.61 | 59 | 0.54 |
| gpt-6-luna | it1 | 31/40 | 5.62 | 1.88 | 60 | 0.38 |
| gpt-6-luna | it2 | 33/40 | 5.95 | 2.99 | 39 | 0.97 |
| gpt-6-luna | it3 | 34/40 | 5.42 | 3.13 | 42 | 0.25 |
| gpt-6-luna | it4 | 34/40 | 5.7 | 2.86 | 42 | 0.2 |
| gpt-6-luna | it5 | 33/40 | 5.1 | 3.06 | 39 | 0.17 |

### Long-horizon tasks

| model | variant | success | parts right % | wall s | wall s (completed runs) | parent requests | total requests | calls/run_code | max fan-out | run_code errors | total in tok k | timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6.1-sol | off | 8/10 | 99 | 68.2 | 68.2 | 11.4 | 11.4 | 0 | - | 0 | 89.6 | 0 |
| gpt-6.1-sol | base | 8/10 | 99 | 65.1 | 65.1 | 8.6 | 8.6 | 2.72 | - | 0.9 | 87.2 | 0 |
| gpt-6.1-sol | new | 8/10 | 99 | 66.6 | 66.6 | 7.5 | 7.5 | 2.94 | - | 0.2 | 79.3 | 0 |
| gpt-6-luna | off | 5/10 | 95 | 45.1 | 45.1 | 9.5 | 9.5 | 0 | - | 0 | 100.6 | 0 |
| gpt-6-luna | base | 4/10 | 72 | 48.9 | 48.9 | 9.9 | 9.9 | 3.19 | - | 2 | 95.1 | 0 |
| gpt-6-luna | new | 5/10 | 94 | 44.5 | 44.5 | 7 | 7 | 5.2 | - | 0.1 | 70.6 | 0 |

### Long-horizon tasks with delegation to sub-agents

| model | variant | success | parts right % | wall s | wall s (completed runs) | parent requests | total requests | calls/run_code | max fan-out | run_code errors | total in tok k | timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6.1-sol | off | 7/10 | 91 | 285.1 | 216.8 | 11.8 | 43.1 | 0 | - | 0 | 230.5 | 1 |
| gpt-6.1-sol | base | 8/10 | 94 | 193.8 | 115.4 | 6.4 | 27 | 3.88 | 4 | 1.22 | 230.6 | 1 |
| gpt-6.1-sol | new | 8/10 | 99 | 88.9 | 88.9 | 4.9 | 19.5 | 4.63 | 4 | 0.3 | 177.7 | 0 |
| gpt-6.1-sol | fix | 9/10 | 99 | 98.0 | 98.0 | 4.8 | 21.5 | 4.49 | 4 | 0.4 | 180.5 | 0 |
| gpt-6-luna | off | 7/10 | 97 | 87.2 | 87.2 | 7.5 | 31.2 | 0 | - | 0 | 195.0 | 0 |
| gpt-6-luna | base | 7/10 | 95 | 107.3 | 107.3 | 6.1 | 25.9 | 2.25 | 4 | 1.7 | 240.1 | 0 |
| gpt-6-luna | new | 6/10 | 96 | 73.3 | 73.3 | 5.7 | 20.8 | 3.43 | 4 | 0.3 | 402.6 | 0 |
| gpt-6-luna | fix | 4/10 | 92 | 81.2 | 81.2 | 6.9 | 26.5 | 3.93 | 4 | 1.2 | 214.6 | 0 |

### Sub-agent sessions (delegation tasks)

| model | variant | sessions | requests/session | in tok k/session | largest return (chars) |
|---|---|---|---|---|---|
| gpt-6.1-sol | off | 37 | 7.9 | 38.1 | 12,891 |
| gpt-6.1-sol | base | 39 | 5.2 | 40.1 | 26,588 |
| gpt-6.1-sol | new | 40 | 3.6 | 32.3 | 71,762 |
| gpt-6.1-sol | fix | 39 | 4.3 | 33.2 | 9,836 |
| gpt-6-luna | off | 40 | 5.9 | 36.5 | 38,004 |
| gpt-6-luna | base | 39 | 5.1 | 48.2 | 88,614 |
| gpt-6-luna | new | 39 | 3.9 | 89.0 | 294,877 |
| gpt-6-luna | fix | 42 | 4.7 | 34.7 | 9,845 |

### Sub-agent fan-out

| model | off: invoke_agent calls per model response | new: invoke_agent calls per run_code |
|---|---|---|
| gpt-6.1-sol | {"1": 40, "4": 10} | {"4": 10} |
| gpt-6-luna | {"1": 12, "4": 7} | {"3": 1, "4": 9} |

## How the prompt changes went (short tasks)

| iteration | change | effect |
|---|---|---|
| it1 | batching guidance, `run_code` description note, whole nested values | sol single-call snippets 41% → 21% |
| it2 | named the three commonest single-call habits; heredoc quoting tip | calls per snippet up, but errors doubled: our own example used `sorted({m["file_path"] ...})`, which the sandbox type checker rejects (`str \| None`) |
| it3 | type-clean examples, `str \| None` and `next(genexpr)` facts | sol errors 0.57 → 0.03 per task |
| it4 | "return matched lines next to computed counts" | did not fix a consistent r3 miss (8 vs 9) |
| it5 | root cause of r3: `read_file` returned `content=None` for big files; code mode now reads whole files | r3 fixed; final prompt |

## Caveats

- 10 runs per long-task cell. luna's delegation success moves between 4 and 7 of 10 across variants
  while its part accuracy stays at 92 to 97%; read one- or two-run differences as noise.
- Five models from two providers, on one machine (macOS). Model settings are Code Puppy defaults, except
  reasoning effort low for the GPT models.
- The `off` short-task batch and the `fix1` batch were not interleaved with the others.
- The sub-agent fix (`fix`) is 8 to 9 seconds slower than `new` on delegation tasks. Sub-agents got
  bounded returns but called `read_tool_result` once in 81 sessions, so this is not extra round trips;
  it is most likely batch-to-batch noise.

## How this was run

An AI coding agent (Code Puppy) did the hands-on work: harness, task composition, runs, analysis, and
the Code Puppy PRs. Mike chose the questions, reviewed results between iterations, and merged the PRs.

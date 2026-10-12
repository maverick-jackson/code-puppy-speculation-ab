# Does code-puppy's speculative code mode make it faster?

Short answer from my testing: not on short tasks. It made all three models I tried slower, and the slowdown comes from code mode itself, not from speculation.

_Glitch asked for people to test `enable_speculative_code_mode` before it becomes the default, so I set up a proper A/B. I ran it with Claude Code doing the heavy lifting (details at the bottom).

## Follow-up (2026-10-11): code mode that actually batches

The finding above (one tool call per snippet, sandbox gaps) was fixed in Code Puppy
([#1013](https://github.com/mpfaffenberger/code_puppy/pull/1013), [#1014](https://github.com/mpfaffenberger/code_puppy/pull/1014))
and re-measured on the same 20 tasks plus 10 new long-horizon and sub-agent tasks: for the GPT models, snippets now carry 2.7 to 3.2
tool calls instead of 1.6 to 2.0, and delegating to sub-agents is 2.4x faster with code mode than without it. Across all 30 tasks and five models
(gpt-6.1-sol, gpt-6-luna, Claude Opus / Sonnet / Haiku 5.5) every model makes 12 to 40% fewer model requests;
it is a clear win for gpt-6.1-sol and claude-haiku-5.5, about even on time for Opus and Sonnet, and slower for luna.
Write-up: `docs/CODEMODE_FOLLOWUP.md`; charts: `docs/results/codemode_followup.html`.

## What I ran

- code-puppy 0.0.896, headless, through a local LiteLLM proxy
- 3 models: DeepSeek flash, DeepSeek V4 Pro, GLM-4.7
- 20 tasks:
  - 12 "go read the repo and answer" questions on pinned versions of click, httpx and rich, graded against known answers
  - 8 small bug fixes, graded by hidden tests the agent never sees
- 3 setups for every task:
  - **off**: normal tool calling (the default)
  - **on**: speculative code mode
  - **plain**: code mode with speculation turned off, to separate the two effects
- 3 repeats of everything, run order shuffled, so 540 runs in total. All 540 were valid.
- Total API spend for the main run: $5.65

I wrote the plan and the stats method down before the main run and didn't change them afterwards (`docs/PLAN.md`).

## Results

Change in wall clock time with speculative code mode on, compared with off. A positive number means slower. The range in brackets is a 95% confidence interval.

| model | on vs off | code mode only (plain vs off) | speculation only (on vs plain) |
|---|---|---|---|
| DeepSeek flash | +20% (+10 to +31) | +20% (+10 to +33) | 0% (-8 to +8) |
| DeepSeek V4 Pro | +29% (+14 to +45) | +35% (+25 to +46) | -5% (-12 to +3) |
| GLM-4.7 | +54% (+37 to +73) | +60% (+43 to +80) | -4% (-12 to +4) |
| all three | +33% (+25 to +43) | +38% (+29 to +47) | -3% (-6 to 0) |

![wall clock change per model](docs/results/main1_forest.png)

- **Success rate:** basically the same. 531 of 540 runs were correct, and no setup was clearly better or worse.
- **Cost:** about 44% more per task with it on (89% more input tokens).
- **Task type:** the read-and-answer tasks were hit hardest (+38%), the bug fixes less (+27%).

## Why it's slower

Each request isn't slower. There are just more of them. With code mode on, the models made 30 to 60% more requests per task, and each one resent a bigger context.

The code mode prompt tells the model to "Go BIG" and pack 10 to 30 tool calls into one `run_code` snippet. None of the models did that. About 61% of snippets wrapped exactly one tool call, and about a quarter wrapped none. So every snippet became a full model round trip, and speculation had almost nothing to run ahead on. Speculation's own counter (`saved_ms`) added up to about 0.2% of total run time.

A lot of the extra retries came from things the `run_code` sandbox doesn't allow, which the models kept trying:

- `sys.path`
- `Path.glob` / `Path.rglob`
- importing `subprocess`, `ast`, `importlib`

These might be cheap wins, either supporting them or telling the model up front they're not available.

## Caveats

- These are short tasks, about 10 to 90 seconds each. _Glitch said the big gains show up with long blocking tool calls, and this doesn't test that. I'm happy to run that next if someone points me at a workload it should win on.
- Only 3 models, all through LiteLLM, all on one machine (a Windows desktop running WSL2).
- GLM-4.7 thinks before every response (6 to 7 seconds before its first token), so any extra request costs it a lot. That's why its number is the biggest.
- Runs were headless with yolo mode on and MCP off.
- Tested on 0.0.896. The code mode and speculation source files had not changed as of 0.0.912 (2026-10-11), so the result should still apply.
- The machine got restarted a couple of times during the run (including two hard power-offs). The runner resumed each time, and leaving out the affected blocks doesn't change the result. Details are in the full write-up.

## How this was run

I ran this with Claude Code doing most of the hands-on work, and I steered. I chose the question and the models, signed off on the plan before the main run, and reviewed the results. Claude built the task suite, graders and runner, ran it in phases, and checked its own work between them.

The process, roughly:

1. **Feasibility check:** confirmed the three setups could be switched cleanly and measured, with a small pilot.
2. **Building and smoke-testing the harness:** a smoke test caught three harness bugs before any real data. One task could read its own answer key. The bug fix tasks were running without the injected bug. Some agent failures were being retried as if they were infrastructure errors. All three were fixed and the smoke test was re-run.
3. **Locking the plan:** the design and stats method were written down and frozen in `docs/PLAN.md` before the main run started.
4. **The main run:** 540 runs on my desktop (WSL2), about 5 hours, $5.65 in API spend.
5. **Analysis:** done exactly as the frozen plan said.
6. **Audit:** a separate Claude model was told to try to break the result before I posted it. The headline held, and it found 11 things to fix: a bug in one sensitivity check, run history I hadn't disclosed, and wording that overstated things. All are fixed, and the audit is in `docs/audit/`.

Everything is in the repo, so you don't have to take Claude's or my word for any number.

## More detail

- `docs/RESULTS.md`: the full write-up, with every table
- `docs/results/main1_tables.md`: all the numbers
- `docs/audit/AUDIT_main1.md`: a separate Claude model trying to break the analysis, done before I posted
- `runs/main1/records.jsonl`: one line per run, the raw data
- To rebuild every number: `python scripts/analyze_main1.py` (needs numpy and matplotlib)

# Adversarial audit of batch main1 (before anything is shown to the creator)

Auditor: a separate Claude model (Claude Code subagent) told to break the result, 2026-10-11. Scope: try to break the conclusion in `docs/RESULTS.md`.
Inputs: everything under `docs/`, `scripts/`, `plugin/spec_capture/`, `runs/main1/` (records,
per-run dirs, matrix.log, batch.json) and the installed code-puppy 0.0.896 source on this Mac.
No new benchmark runs were made. All numbers below were recomputed from `runs/main1` with
throwaway scripts (kept out of the repo); where a number is quoted from RESULTS.md it was checked
against `docs/results/main1_summary.json`.

## Verdict

**The headline holds.** Turning `enable_speculative_code_mode` on made every model slower on
this suite, the effect is large relative to its CI, and the cause is the code-mode interface,
not speculation. Nothing I found reverses it or moves it outside its CI.

Solid, publishable as stated:
- Per-model on vs off slowdowns (+19.8% / +28.5% / +54.1%) and plain vs off. An independent
  bootstrap implementation (different RNG, different code) reproduces every point estimate to
  0.1 point and every CI bound to within 0.5 point. A plain t-interval over the 20 task means
  gives +33.4% [+24.1, +43.3] pooled, same answer. 19 of 20 tasks are slower on vs off (the
  one exception, r3_rich_loop, is -3%).
- Arm validity: every `off` run used native tools only (0 `run_code` parts in 180 runs); every
  `on` run used `run_code` with the config flag true and speculation events present (179 of
  180 had at least one speculative launch); every `plain` run used `run_code` with the plugin
  override applied, zero speculation events, zero eager savings.
- No startup confound: process boot (3.4 to 3.8 s) and teardown (1.4 to 1.7 s) are the same
  in every arm; per-request latency is the same in every arm. The slowdown is more model
  round-trips per task (requests +30% to +60%) with larger prompts, period.
- Cost and token increases (proxy-side rows, cache discounts applied by LiteLLM).
- Success at ceiling, McNemar underpowered.

Must be softened, corrected, or disclosed before publishing (details in the checks):
1. The two `run_code` max-retry runs are counted as correct; the frozen plan says they count as
   failures. One of them (V4 Pro, c3, on, rep 2) aborted early at 40.9 s against 89.8 s off and
   is the single most on-favourable pair in the data set. Disclose the deviation or regrade per
   plan (nothing significant changes either way).
2. The "excluding first block per worker" sensitivity excludes the SECOND block
   (`block_index == 1`; blocks are 0-indexed). Fix the script; the corrected number is
   +33.1% [+24.1, +42.4] pooled, so the conclusion is unchanged but the row is mislabelled.
3. The run was interrupted by two hard VM power-offs and a 13-launch crash loop (28 minutes
   down). RESULTS.md mentions only the NUL-prefixed record. 550 run dirs exist, 544 records;
   6 attempts were killed in flight and re-run; 3 blocks had their arms split across the
   outage. Excluding those 3 blocks: +33.2% [+24.3, +42.4] pooled. Say so.
4. "slept" is the wrong word on a Linux desktop. The flag is a >2 s gap between wall-epoch
   and perf_counter (a VM clock stall), and the 3 flagged attempts were not near the power-offs.
5. "Code mode doubles tool errors" needs the actual content: the extra errors are the model's
   own sandbox snippets failing (`sys.path` missing, `PosixPath.rglob/glob` missing,
   `import subprocess/ast` missing, indexing tool results as dicts) plus the model calling
   native `grep`/`read_file` in code mode. These are Monty sandbox limits and model habits,
   not harness crashes. "Tool errors" in the off arm are mostly grep-no-match results counted
   by the same heuristic. Report it as what it is or the creator will (rightly) object.
6. The "-3% speculation saving" must not be presented as a finding. For GLM no argument
   streaming happens at all (0 of 1,173 tool-call parts streamed), so its -3.9% on vs plain
   cannot be a speculation effect; it is the noise floor of this design (about plus or minus
   4% per model). Treat the DeepSeek numbers the same way.
7. The raw data (`runs/main1`) is not committed. The "every number traceable" claim is only
   true once `records.jsonl` and the per-run dirs (or at least records.jsonl) are in the repo.

## Check 1: arm validity

Evidence per valid run from `capture.json` (plugin) and the record fields derived from it.

| arm | runs | runs with any `run_code` part | runs with speculative launch (hits > 0) | `speculation_enabled_cfg` | `codemode_override_applied` | eager_saved_ms > 0 |
|---|---|---|---|---|---|---|
| off | 180 | 0 | 0 | False in 180 | absent in 180 | 0 |
| on | 180 | 180 | 179 | True in 180 | absent in 180 | 65 |
| plain | 180 | 180 | 0 | True in 180 | 2 in 180 (main build + rebuild) | 0 |

- Native tools seen in off (`capture.tool_calls`): read_file, grep, shell, list_files,
  replace_in_file, read_tool_result. No run_code anywhere.
- In on/plain, `run_code` plus the same tools wrapped inside it (the pre/post tool hooks DO
  fire for wrapped calls in 0.0.896; the plugin docstring's note about issue #982 is stale
  but harmless).
- The one `on` run with zero launches: V4 Pro, r1_rich_box, rep 1 (7 run_code parts, 1,026
  SpeculativeCodeUpdateEvents, no SpeculativeCallLaunchedEvent). Code mode and the flag were
  active; the model simply never wrote a literal-argument read line. It is still a valid `on`
  run. Mention it so "179 of 180" is not read as a failed arm.
- `plain` is implemented by monkeypatching `build_speculative_code_mode` in both
  `code_puppy.agents._code_mode` and `code_puppy.agents._builder` (the builder imports the
  name, so the second patch is the one that matters). `CodeMode(speculate=None, eager=False)`
  keeps `SilenceToolOutput`, `EagerTiming`, `StreamedToolNameNormalizer` and the
  `CodeModeGuidance` system prompt text (which still says "Speculation is on"). So plain is
  "code mode + the speculation guidance prompt, with early execution removed". That is the
  right control for isolating the mechanism, but it is not a shipped option and the prompt
  text is identical to on. State both facts (RESULTS already states the first).
- Template homes: `runs/homes/off` and `runs/homes/on` differ only in the
  `enable_speculative_code_mode` line of `puppy.cfg` (verified on this Mac's copy; the bench
  copies were built by the same `prep_homes.sh`, which diffs them). Both warmed once.
- GLM arg streaming: 0 of 432 / 551 / 622 tool-call parts (off/on/plain) streamed argument
  deltas; DeepSeek flash and V4 Pro streamed 100%. Matches FEASIBILITY.md.

Verdict: no run where the arm did not take effect.

## Check 2: measurement confounds (startup, plugin, templates)

Mean seconds per run, valid runs, from `boot_s` / `agent_s` / `teardown_s` and the proxy rows:

| model | arm | wall | boot | agent | teardown | sum of request durations | agent time outside requests | requests | TTFT |
|---|---|---|---|---|---|---|---|---|---|
| flash | off | 16.0 | 3.69 | 10.8 | 1.51 | 9.2 | 1.6 | 6.1 | 0.50 |
| flash | on | 19.7 | 3.67 | 14.5 | 1.51 | 12.6 | 1.9 | 8.0 | 0.54 |
| flash | plain | 19.6 | 3.63 | 14.4 | 1.55 | 12.1 | 2.2 | 8.0 | 0.53 |
| V4 Pro | off | 31.4 | 3.56 | 26.3 | 1.56 | 23.6 | 2.7 | 6.7 | 0.56 |
| V4 Pro | on | 38.7 | 3.79 | 33.6 | 1.36 | 30.6 | 3.1 | 9.0 | 0.55 |
| V4 Pro | plain | 41.7 | 3.39 | 36.5 | 1.72 | 33.0 | 3.5 | 9.9 | 0.58 |
| GLM-4.7 | off | 63.5 | 3.60 | 58.4 | 1.56 | 53.8 | 4.6 | 6.2 | 6.09 |
| GLM-4.7 | on | 98.8 | 3.35 | 93.7 | 1.73 | 87.1 | 6.7 | 10.1 | 6.96 |
| GLM-4.7 | plain | 104.4 | 3.50 | 99.3 | 1.63 | 91.7 | 7.6 | 11.2 | 6.76 |

- Boot (process start to `agent_run_start`, includes plugin load, Flux commands, config) is
  flat across arms. Teardown is flat. The spec_capture plugin is loaded in every arm with the
  same hooks; the only arm-asymmetric work it does is a dict increment per speculation event
  (on only), microseconds per event.
- Time outside model requests (tool execution + harness overhead) is 1.6 to 7.6 s per run and
  grows with the number of turns, not with the arm per se. It is a small share of the delta.
- Wrapped tool execution is fast everywhere: median 18 ms (off) / 10 ms (on) / 3 ms (plain),
  p90 about 125 ms, max 2.3 s (a shell call in off). Mean tool time per run 0.6 to 0.7 s.

Verdict: no startup, plugin or template confound. The time goes into extra model requests.

## Check 3: more turns vs slower turns; caching

Per-request latency is unchanged by the arm (mean request duration flash 1.51 / 1.58 / 1.52 s,
V4 Pro 3.53 / 3.38 / 3.35 s, GLM 8.68 / 8.59 / 8.20 s for off / on / plain). Requests per run
go from 6.1 to 8.0 (flash), 6.7 to 9.0 (V4 Pro), 6.2 to 10.1 (GLM). Prompt tokens per request
go from about 6.9k to 9.4k (flash) and 6.5k to 8.5k (GLM). So the slowdown is
(extra requests) x (per-request latency) plus a little extra tool overhead.

Why GLM shows the largest percentage: each GLM request costs about 8.6 s, of which about 6 s is
time to first token (Z.ai GLM-4.7 is a forced-thinking model; the `proxy-zai-g47` alias skips
code-puppy's `extra_body.thinking` injection, but per `model_utils.supports_glm_thinking`
GLM-4.7 does not honour "disabled" anyway, so this is also what a normal user gets). Four extra
turns at 8.6 s is 35 s, which is the observed mean on-minus-off (+35.2 s). The post should
say this: the code-mode cost is a per-turn tax, so it scales with the model's per-turn latency.

The mechanism, in one number the creator will care about: across all on and plain
`run_code` snippets, 24% wrap zero tool calls, 62% wrap exactly one, 8% two, 4% three, 3% four
or more. Wrapped calls per snippet average 1.0 to 1.1 for every model. The guidance text tells
the model to "go BIG in one run_code call" with "ten, twenty, thirty tool calls in a single
snippet"; the three models did not do that. Speculation therefore had almost no runway, which
is exactly why `saved_ms` is 0.18% of wall. This is a finding about model behaviour under the
0.0.896 guidance, and it is the most useful thing in the data set for the creator.

Caching: `cache_read` tokens are 80% to 90% of prompt tokens in every arm (flash off 34k of
42k, on 66k of 76k). The proxy spend reflects provider cache pricing: DeepSeek first request
about $0.15 per M prompt tokens vs about $0.02 for later requests in the same run; Z.ai $0.23
vs $0.17. Both arms benefit equally; the $ ratios are fair as long as LiteLLM's price table for
these models is right, which this repo cannot verify. Say "proxy-computed $" rather than "$".

Eager execution: `eager_saved_ms` totals 7.2 s (flash) + 3.9 s (V4 Pro) + 0.07 s (GLM) =
11.2 s across 180 on runs, on top of the 16.7 s `saved_ms`. It is in `main1_summary.json` but
not in the RESULTS mechanism table. Add it; combined it is still under 0.3% of wall.

## Check 4: order, drift, restarts, outliers, the recovered record

Order within blocks (mean ln wall minus block mean): position 0 -0.0%, position 1 +1.7%,
position 2 -1.7% (180 runs each). Arm-by-position counts are reasonably balanced (off at
position 0 in 70 blocks, on in 59, plain in 51; on at position 2 in 69). No position effect
worth modelling.

Time drift: residual ln wall vs the (model, arm, task) mean by UTC hour: 01h -1.0%, 02h +5.3%,
03h -2.9%, 04h +0.5%, 05h +1.6%. Rep residuals -0.9% / -0.6% / +1.5%. Arms are interleaved
within minutes inside a block, so drift cancels in the pairs.

Restarts, reconstructed from `runs/main1/batch.json` (16 launches) and `matrix.log`
(timestamps local, UTC = local + 4 h):
- Launch 1 at 21:12 local. Hard VM power-off at about 21:55. Relaunch at 21:56:22 finalized
  12 orphan run dirs and resumed with 263 records.
- Second hard power-off at about 22:11. Relaunches at 22:13, 22:15, 22:17, 22:19, 22:21,
  22:23, 22:24, 22:26, 22:28, 22:30, 22:32, 22:34, 22:37 each died at startup with
  `JSONDecodeError` on a zero-byte `partial.json` (V4 Pro r4_rich_progress r1 plain a1; the
  run itself had completed and has a full meta.json, 29 s, but the record was never written).
  Commit 979fdb7 made resume skip torn partials; the 22:39:26 launch finalized 8 more orphans
  (including the NUL-prefixed record), skipped that torn partial so the cell re-ran, and
  resumed with 322 records. The bench was idle for about 28 minutes.
- Run dirs: 550; records: 544. The 6 dirs without a record are 5 runs killed in flight (only
  `stdout.raw` / `stderr.raw` present: flash f1 r2 on, V4 Pro f4 r1 off, V4 Pro g4 r1 off,
  GLM c1 r3 on, GLM f1 r3 plain) plus the torn-partial run above. All six cells were re-run
  as attempt 2 and are valid. `attempt == 2` in 10 valid cells = these 6 + the 4 invalid
  retries RESULTS lists.
- Blocks whose arms were split by an outage (3 of 180): GLM c1 r3 (plain at 01:50 UTC, on and
  off after the 01:56 relaunch), V4 Pro r4 r1 (off and on at 02:10, plain at 02:39), GLM f1
  r3 (off at 02:09, plain and on at 02:39). Excluding them: on vs off +33.2% [+24.3, +42.4],
  plain vs off +36.8% [+28.5, +45.5], on vs plain -2.6% [-6.0, +0.8] pooled. No change.
- First run of each worker after a relaunch: wall ratios to the model-arm geometric mean are
  0.63 to 1.80, i.e. ordinary scatter, no cold-start spike.
- The three `slept` attempts (V4 Pro r1 off r2 at 02:52 UTC, GLM h3 off r3 at 02:52 UTC, GLM
  f2 on r2 at 05:31 UTC) have a 2.6 to 2.7 s gap between wall-epoch and perf_counter and are
  not adjacent to any power-off. On WSL2 that is a VM clock stall, not sleep. Retrying them
  was right; the label is wrong.
- The NUL-prefixed record (V4 Pro h4 r2 off a1, 17.3 s, started 02:09:40 UTC) is a run that
  completed normally just before the second power-off; its block mates ran at 02:09:57 and
  02:10:11, before the outage. Nothing wrong with it; the sensitivity row is fine.
- Outliers: the eight longest runs are all GLM (293, 250, 241, 221, 203 s ...), six of them on
  or plain, all correct. Largest on-favourable pair: V4 Pro c3 r2, on 40.9 s vs off 89.8 s,
  and that on run is one of the two max-retry aborts (see check 6). Largest off-favourable:
  V4 Pro h3 r1, on 65.1 vs off 14.3 s. Log-ratio pairing and the median sensitivity already
  bound the influence of these.

## Check 5: statistics

- Clustering: `boot()` resamples the 20 tasks with replacement and carries every (model, rep)
  pair of a task along (sum and count arrays indexed by task). That is a correct cluster
  bootstrap with task as the cluster. For the pooled estimate the cluster still is the task
  (all three models' pairs travel together), which is the conservative choice.
- Pairing: `ln(wall_a / wall_b)` per (model, task, rep), mean, then `exp - 1`. Correct. The
  point estimate is the mean of all pairs (each model contributes 60), so "pooled" is an
  equal-weight average of the three per-model effects. Fine, and RESULTS reports it alongside.
- Independent re-derivation (4,000 resamples, Python `random`, seed 7): every point estimate
  matches to 0.1 point and every CI bound to within 0.5 point. A t-interval on the 20 task
  means (df 19) gives on vs off +33.4% [+24.1, +43.3], plain vs off +37.5% [+28.3, +47.3], on
  vs plain -3.0% [-6.6, +0.8].
- McNemar: exact two-sided binomial on discordant pairs, `min(1, 2 * tail)`. Correct.
  Recomputed p(0,3) = 0.250, p(3,4) = 1.000, p(2,0) = 0.500.
- Wilson intervals: standard formula, spot-checked (59/60 gives [0.911, 0.997]).
- BUG: `first_block` is defined as `block_index == 1`; `run_matrix.py` enumerates blocks
  from 0, so the row labelled "excluding first block per worker" excludes the second block.
  Correct row (block_index == 0 excluded): on vs off +33.1% [+24.1, +42.4], plain vs off
  +37.0% [+28.1, +46.3], on vs plain -2.8% [-6.3, +0.5] pooled. Fix the script and
  regenerate; also note that each of the 3 productive relaunches creates a new "first block"
  for each worker, which this sensitivity does not cover (the restart-split check above does).
- Multiple comparisons: 3 comparisons x 4 groups x 3 families plus 5 sensitivity variants is
  about 100 intervals. The headline is the pre-registered primary (per-model on vs off, 3
  intervals) and survives any correction. The "median CI just excludes zero" remark on the
  speculation effect should be dropped or explicitly flagged as one of many looks.
- Every number I checked in RESULTS.md prose matches `main1_summary.json` (0.18% median share,
  1.30% max, 0.09 s saved per run, 2.4x tool errors, 1.2 retry prompts per run, $1.42 / $2.05 /
  $2.14 totals, 1,324 / 19 / 9 counters, 7 failures, max wall 293 s). The "Pooled" descriptive
  line and the per-model geometric means match the tables file.

## Check 6: grader fairness

- Frozen plan (PLAN.md, "Valid run"): "Task failures (wrong answer, hidden tests fail,
  run_code max retries, agent timeout) are valid runs and count as failures." RESULTS.md
  counts the two `run_code exceeded max retries` runs (V4 Pro c3 on r2, GLM c3 on r2) as
  correct because the hidden tests pass. That is a deviation from the pre-registration, in
  the direction that favours arm on. Under the plan: on = 174/180, on vs off pooled discordant
  3 vs 6 (p = 0.51), V4 Pro 0 vs 4 (p = 0.125), GLM 2 vs 1. Still nothing significant, but the
  text "all valid, 533 of 540 correct" changes to 531 of 540, and the dollars-per-solved for on
  rises slightly. Either regrade per plan or state the deviation and show both.
- Those two runs also ended early (the agent aborted after 3 retries). The V4 Pro one at
  40.9 s vs 89.8 s off is the most on-favourable pair in the data. Timing-wise they are valid
  runs under the plan and should stay in; just say that keeping them is conservative for the
  headline.
- The missing `ANSWER:` prefix failure (V4 Pro g1 on r2) printed the right four values on the
  last line with no prefix. Strict under the frozen grader, which is the same in every arm.
  Disclosed already; keep it.
- The grader is arm-blind (same stdout regex, same hidden pytest). `extract_answer` takes the
  LAST `ANSWER:` line, which is right for both arms. No gather run modified its repo; no
  real test file was touched (the 90 `__pycache__` entries are pytest bytecode).
- The "tool errors" metric is a heuristic over tool results (`success=False`, non-empty
  `error`, text starting with "error"/"traceback"). In off it is dominated by grep calls that
  found nothing (`matches=[] error="..."`), which are not failures in any meaningful sense. In
  on/plain the extra 230 are `run_code` snippets raising. Content of the 432 retry prompts
  across on + plain: 160 AttributeError (68 `'module' object has no attribute 'path'` from
  `sys.path.insert`, 40 `PosixPath` has no `rglob`/`glob`, 12 `os.walk` missing), 108 other
  runtime errors (54 `str indices must be integers`: treating a tool result string as a dict),
  32 native tool call in code mode ("Unknown tool name: 'grep'"), 28 `import subprocess`,
  13 `import ast`, 21 type-check rejections (missing `await`), 20 file not found, 19 syntax
  errors in the snippet, 10 NameError. These are Monty sandbox gaps plus models reaching for
  stdlib habits. They are a real cost of the interface, but call them that.

## Check 7: generalization limits the post must state

- Short tasks: 8 to 293 s wall, tool calls median 18 ms, p90 125 ms, max 2.3 s. No build,
  test-suite, or network call anywhere. The creator's "5% to 50%" claim was explicitly about
  hiding tool latency, which this suite does not have. The result says nothing about that
  regime except that the interface tax exists before any gain can start.
- Three models, all through one local LiteLLM proxy on one host, one code-puppy version
  (0.0.896, pydantic-ai-harness CodeMode as pinned there), Python repos only (click, httpx,
  rich, a fixture). No Anthropic/OpenAI/Gemini model; no model that follows the "go big"
  guidance was observed, and a model that did could change both the cost and the gain.
- GLM-4.7 via Z.ai: no argument streaming through LiteLLM, forced thinking with about 6 s
  TTFT per request. Its on vs plain number is pure noise by construction, and its on vs off
  percentage is inflated by the per-turn latency. State that the GLM result is "per-turn tax
  times an expensive turn".
- Arm plain is the author's reconstruction (plugin monkeypatch), carries the speculation
  guidance prompt, and is not something a user can switch on.
- Headless `-p` mode, `--yolo`, MCP disabled, universal constructor disabled, frontend emitter
  off. Interactive sessions with a TUI, MCP servers (which code mode also folds), or longer
  multi-step work were not measured.
- Pooled estimates weight the three models equally; the GLM effect pulls the pool up.
- The experiment was run by someone outside the project and the run was interrupted twice by
  hardware failures; the data survived because of resume logic, and the sensitivity checks
  show no effect, but the post should say it rather than let the creator find it in the
  logs.

## Check 8: things that would embarrass the author

- Not disclosing the max-retry grading deviation from the frozen plan (check 6).
- The mislabelled sensitivity row (check 5). Trivial, but "pre-registered analysis, every
  number reproducible" invites a reader to run the script and read the code.
- Describing the reliability result as "code mode doubles tool errors" without the content.
  The creator knows what Monty does not support; if the post does not, it looks like the
  author did not read the transcripts.
- Framing "-3% speculation" as a saving at all. GLM's -3.9% with zero streamed arguments
  proves the number is noise-sized.
- Publishing "all 540 valid, 4 invalid attempts" when the run dirs show 550 attempts and the
  logs show two power-offs and a crash loop. All handled correctly, but it reads as hidden if
  the creator looks.
- Claiming reproducibility while `runs/main1` is untracked.
- "slept" on a desktop.
- Stale comment in the plugin about hooks being bypassed in code mode (they fire). Harmless,
  but it is the file the creator will read first.
- The plugin's `plain` arm keeps `CodeModeGuidance` telling the model "Speculation is on".
  Fine as a control, but say it.

## REQUIRED changes to docs/RESULTS.md before publishing

1. RQ2 paragraph: either regrade the two `run_code` max-retry runs as failures per PLAN.md
   (update the success table, McNemar rows, failure count, $ per solved) or add one sentence:
   "The frozen plan counts run_code max-retry exhaustion as a task failure; we report these
   two runs as correct because the hidden tests pass, which is a deviation that favours arm
   on; under the plan's rule on is 174/180 and no test changes verdict." Also note that one of
   them is the most on-favourable timing pair and was kept.
2. Fix `first_block` in `scripts/analyze_main1.py` to `block_index == 0`, regenerate tables,
   JSON, figures, and the sensitivity row in RESULTS.md (+33.1% / +37.0% / -2.8% pooled).
3. Data section: replace the single NUL-record note with the run history: 16 launches, two
   hard VM power-offs (about 21:55 and 22:11 local), 13 failed relaunches on a zero-byte
   partial.json until commit 979fdb7, about 28 minutes idle; 550 attempt dirs, 544 records,
   6 in-flight attempts re-run; 3 blocks split across an outage; sensitivity excluding those
   blocks unchanged (give the numbers).
4. Rename "slept" in RESULTS.md to "clock stall (>2 s gap between wall-epoch and
   perf_counter; the bench does not sleep)".
5. RQ6: state what the errors are. Suggested wording: "Error-like tool results (heuristic:
   success=False, error field, or text starting with error/traceback; in off mostly grep calls
   with no match) rise from 167 to 397. The extra ones are run_code snippets raising inside the
   Monty sandbox (sys.path, PosixPath.rglob, os.walk, import subprocess/ast unavailable;
   tool results indexed as dicts) and models calling native grep/read_file in code mode. Each
   costs a model round-trip." Keep the retry-prompt counts.
6. Headline bullets: drop "the speculation gain is real in sign"; replace with "speculation
   given code mode is within noise: -3.0% [-6.3, +0.3] pooled, and GLM-4.7 shows -3.9% with
   zero streamed arguments, so a difference of that size can arise with no speculation at
   all." Drop the "median CI just excludes zero" remark or label it one of about 100 looks.
7. RQ3 and RQ4: add the request-count and per-request-latency table (check 3) and the
   wrapped-calls-per-snippet distribution (24% / 62% / 15%). These two tables are the
   mechanism, and they pre-empt "your proxy was slow" and "speculation never had a chance".
8. RQ4: add `eager_saved_ms` (11.2 s pooled) next to `saved_ms` (16.7 s); combined share still
   under 0.3% of wall.
9. Limitations: add GLM forced thinking / about 6 s TTFT per request and that the GLM
   percentage is a per-turn tax on an expensive turn; add "headless, yolo, MCP off"; add that
   no model followed the "go big" guidance; add that plain carries the "Speculation is on"
   guidance prompt.
10. Cost: write "proxy-computed $ (LiteLLM price table, cache discounts applied)" the first
    time dollars appear.
11. Commit `runs/main1/records.jsonl` (and ideally the per-run dirs, minus `stdout.raw`) before
    claiming reproducibility; the Reproduce section currently points at an untracked file.

## OPTIONAL improvements

- Add "wrapped tool calls per run_code snippet" and "requests per run" as paired ratios with
  CIs; they are better mechanism outcomes than `saved_ms`.
- Show per-task effects (19 of 20 tasks slower; r3_rich_loop -3%) as a small table or strip.
- Report on vs off in seconds per model as well as percent (flash +3.7 s, V4 Pro +7.3 s,
  GLM +35.2 s) so the per-turn-tax reading is obvious.
- Update the plugin docstring (hooks do fire for wrapped tools) and name the pydantic-ai-harness
  version in RESULTS.md, since the creator will ask which CodeMode this was.
- A follow-up with one deliberately slow tool (a 5 to 10 s shell call per task) would test the
  maintainer's actual claim at a cost of a few dollars; say it is planned or invite him to
  suggest tasks rather than letting the conversation become "wrong workload".
- Rename the `slept` flag in `run_one.py`/`summarize.py` to `clock_stall` for the next batch.

## Safest headline

"On 20 short read-and-edit tasks across three models, enabling code-puppy 0.0.896's speculative
code mode made runs 20% to 54% slower (95% CIs all above zero); the cost is the run_code
interface adding model round-trips, and speculation itself recovered at most a few percent
because the models wrote one tool call per snippet."

# Phase 2 report: harness, task suite, smoke batch

code-puppy 0.0.896 (checked from the installed dist-info before every block), macOS arm64,
2026-10-09/10. Smoke model: proxy-deepseek-flash. Raw data: `runs/smoke2/records.jsonl` (one line
per attempt) and `runs/smoke2/<model>/<task>/r<rep>/<arm>/a<attempt>/` (prompt, stdout, stderr,
capture, usage, transcript, grade.json, agent.diff, meta with proxy rows).

## 1. What was built

- Task suite (`tasks/README.md`): 12 gathering tasks on click 8.1.7, httpx 0.27.0 and rich
  13.7.1 (pinned SHAs, `scripts/setup_repos.sh`), 8 code-change tasks (4 bugs injected into
  click, 4 bugs/features on a fixture library `tasks/fixtures/invkit`). Gathering answers are
  anchored to the pinned commit (line numbers, counts, constants) and recomputed from the clones
  by `tasks/gather_facts.py`. Code tasks are graded by hidden pytest files copied in only after
  the agent exits; `scripts/verify_tasks.py` proves each fails before and passes after its
  `reference.patch` (20/20 OK). Prompts are identical across arms and never mention speculation
  or code mode.
- Graders (`scripts/graders.py`): typed per-field comparison of the last `ANSWER:` line (case,
  whitespace, backticks, bold, qualified names, list order forgiven; every field must match);
  hidden pytest with an empty config.
- Batch runner (`scripts/run_matrix.py`, launched by `scripts/run_matrix.sh`; per-run logic in
  `scripts/runrecord.py`, working copies in `scripts/tasklib.py`):
  - paired blocks (model, task, rep), all 3 arms back to back in a seeded random order (block
    seed recorded), block order shuffled; one thread per model, `--parallel` caps how many
    models run at once, never two runs of one model;
  - fresh APFS clone of a warmed template HOME and a fresh working copy per run, both in
    `$TMPDIR/pupbench/` (outside the project tree, see 4B);
  - one JSON record per attempt with every field the brief lists plus agent_error_text,
    retry_prompts, leak_suspect, power state, grader detail and diff stats;
  - resumable (cells with a valid record or 3 attempts are skipped; orphaned run dirs are
    finalized); infra-invalid runs (slept, HTTP/stream retries, proxy failures, provider
    errors, infra timeouts) retried immediately or at the end of the queue, max 3 attempts;
  - guards: version before every block (abort batch on mismatch), per-provider budget before
    every block (`--cap-deepseek 4.00`, `--cap-zai 8.00`, project spend since 2026-10-09 UTC plus
    pending estimates plus next block), AC power and lid open before every run (poll 60 s;
    `--allow-battery` exists for smoke only), whole process under `caffeinate -dimsu -w <pid>`;
  - 600 s wall-clock timeout per run (wall clock, not perf_counter, so sleep cannot hide it).
- Reused from Phase 1 with small changes: run_one.py (now a function, records the installed
  version, puts `.venv/bin` with pytest first on PATH in every arm), summarize.py (metrics split
  from grading, counts transcript retry prompts), collect_spend.py (filters proxy rows by model so
  concurrent workers do not mix), mkhome.sh via `scripts/prep_homes.sh` (rebuilt and warmed).
  `scripts/reclassify.py` re-applies validity rules to a batch; `scripts/smoke_table.py` makes
  the tables below.

## 2. Smoke results (smoke2, flash, rep 1, valid attempts)

| task | family | pass off/on/plain | wall s off | wall s on | wall s plain |
|---|---|---|---|---|---|
| c1_click_intrange_clamp | code | Y/Y/Y | 22.7 | 25.4 | 21.9 |
| c2_click_longopt_equals | code | Y/Y/Y | 18.5 | 31.2 | 40.6 |
| c3_click_short_help | code | Y/Y/Y | 28.8 | 33.7 | 52.7 |
| c4_click_bool_case | code | Y/Y/Y | 15.5 | 19.1 | 23.5 |
| f1_invkit_total_value | code | Y/Y/Y | 15.5 | 18.8 | 19.8 |
| f2_invkit_thousands | code | Y/Y/Y | 34.2 | 21.5 | 23.9 |
| f3_invkit_bulk_discount | code | Y/Y/Y | 14.9 | 13.1 | 13.5 |
| f4_invkit_report_desc | code | Y/Y/Y | 18.4 | 15.9 | 25.1 |
| g1_click_exceptions | gather | Y/Y/Y | 13.0 | 9.4 | 9.4 |
| g2_click_completion | gather | Y/Y/Y | 15.3 | 13.1 | 12.5 |
| g3_click_helpwidth | gather | Y/Y/Y | 9.7 | 9.1 | 10.0 |
| g4_click_types | gather | Y/Y/Y | 13.2 | 18.2 | 26.2 |
| h1_httpx_exceptions | gather | Y/n/Y | 14.8 | 11.8 | 19.1 |
| h2_httpx_redirects | gather | Y/Y/Y | 9.2 | 13.3 | 14.0 |
| h3_httpx_content | gather | Y/Y/Y | 12.3 | 14.4 | 15.7 |
| h4_httpx_defaults | gather | Y/Y/Y | 8.8 | 14.2 | 10.7 |
| r1_rich_box | gather | n/n/Y | 14.7 | 12.2 | 17.7 |
| r2_rich_console | gather | Y/Y/Y | 9.9 | 9.1 | 13.5 |
| r3_rich_loop | gather | Y/Y/Y | 9.9 | 14.7 | 11.1 |
| r4_rich_progress | gather | Y/Y/Y | 11.9 | 13.6 | 13.5 |

| family | arm | runs | pass | mean wall s | mean agent s | mean $/run | mean requests | mean input tok |
|---|---|---|---|---|---|---|---|---|
| gather | off | 12 | 0.92 | 11.9 | 7.5 | 0.0018 | 4.8 | 33,031 |
| gather | on | 12 | 0.83 | 12.7 | 8.4 | 0.0021 | 4.6 | 39,966 |
| gather | plain | 12 | 1.00 | 14.5 | 10.1 | 0.0022 | 6.4 | 57,243 |
| code | off | 8 | 1.00 | 21.1 | 16.7 | 0.0025 | 8.2 | 59,974 |
| code | on | 8 | 1.00 | 22.3 | 18.0 | 0.0028 | 10.0 | 94,943 |
| code | plain | 8 | 1.00 | 27.6 | 23.1 | 0.0033 | 11.8 | 116,832 |

The three failures are genuine: r1/off answered 18 Box styles (it missed `ASCII2`, a name
with a digit; the ast count is 19), and h1/on and r1/on ended with `Tool 'run_code' exceeded
max retries count of 3` (code-mode reliability, RQ6). No task fails in all arms for infra
reasons; no timeouts, leaks, test-file edits or repo modifications in smoke2. One attempt
(g2/plain) slept with the lid closed and was retried automatically. n = 1 per cell: the
per-arm differences above are not results.

Measured cost per run (flash): gathering $0.0020, code $0.0029, all $0.00236 (60 valid runs).
Wall: gathering 13.0 s, code 23.7 s, all 17.3 s.

## 3. Grader audit

`docs/GRADER_AUDIT.md`: 14 items (40+ graded runs) checked by hand against the source or the
diff; the graders' verdicts were right every time, and 71/71 synthetic wrong answers were
rejected. The audit found three defects OUTSIDE the graders, all fixed:
A) in smoke1 the click bug patches were silently not applied (`git apply` inside a subdirectory
of the project repo), B) in smoke1 an agent walked up from its working copy and read the hidden
test and reference patch, C) code-mode tool-retry exhaustion was classified as infra and would
have been retried away. smoke1 (`runs/smoke1`) is kept as evidence and is not used.

## 4. Deviations and things the manager should know

- A. Scratch location. The brief says work only in the project directory. Per-run HOMEs and
  working copies now live in `$TMPDIR/pupbench/` and are deleted when the worker ends: inside
  the project tree an agent read the answers (finding B). Everything durable (records, raw
  outputs, scripts) stays in the project. This is the closest sound option I found.
- B. Ceiling effect. Flash solved all 8 code tasks in every arm and 33/36 gathering runs.
  v4-pro will likely be at ceiling too, so RQ2 (success rate) will have little power except via
  rare code-mode failures. If RQ2 matters, Phase 3 should add harder tasks before freezing.
- C. Lid. The Mac clamshell-sleeps when the lid closes (on battery always, on AC unless an
  external display is attached), whatever caffeinate asserts. The lid guard prevents STARTING
  runs; a lid closed mid-run still yields a slept run (detected and retried). The main run
  needs AC and the lid open (or an external display) for its whole 6 to 8 hours.
- D. Per-run overhead outside the timed window is about 10 s (template clone, working copy,
  grading, and a sops+psql call for spend per run and per block): measured 720 s elapsed for 25
  runs with 392 s of run wall time. It does not affect timing data, only the schedule.
- E. Variance reps. Reps 2 and 3 of 6 tasks (g1, h2, r1, c2, f1, f3), all 3 arms, were run in
  smoke2 (36 more valid runs; one more slept attempt retried) to measure within-cell noise.

## 5. Proposed main-run size

Per-run figures. Flash is measured (smoke2). v4-pro and GLM are scaled from flash by the Phase
1 pilot ratios on gathering (pilot means; v4-pro: wall 1.73x, cost 5.65x; GLM: wall 6.3x, cost
7.75x) because no code task has been run on them yet. Overhead 10 s per run (4D).

| model | wall s/run | + overhead | $/run | runs per rep (20 tasks x 3 arms) | time per rep | $ per rep |
|---|---|---|---|---|---|---|
| flash | 17.3 | 27.3 | 0.00236 | 60 | 1,638 s (0.46 h) | 0.14 |
| v4-pro | 17.3 x 1.73 = 29.9 | 39.9 | 0.00236 x 5.65 = 0.0133 | 60 | 2,394 s (0.67 h) | 0.80 |
| GLM (zai-g47) | 17.3 x 6.3 = 109 | 119 | 0.00236 x 7.75 = 0.0183 | 60 | 7,140 s (1.98 h) | 1.10 |

- DeepSeek budget: cap $4.00, already spent $0.48 (project, LiteLLM, as of 05:25 EDT), left
  $3.52. Per rep flash + v4-pro = $0.94; with a 25 % margin for retries and estimate error,
  $1.18 per rep: 3.52 / 1.18 = 2.98, so 3 reps fits with slightly under 25 % margin
  (projected total $0.48 + 3 x $0.94 = $3.30, $0.70 headroom). The guard stops a DeepSeek
  worker before the cap if v4-pro code tasks run more expensive than projected.
- Z.ai budget: cap $8.00, spent $0.14, left $7.86; $1.10 x 1.25 = $1.37 per rep: 5.7 reps.
- Time (models in parallel, GLM is the long pole): 3 reps = 3 x 1.98 h = 5.9 h; 4 reps = 7.9 h
  (no margin for retries or slower GLM code tasks).
- Proposal: 3 reps for every model: 3 models x 20 tasks x 3 arms x 3 reps = 540 runs.
  Projected spend: DeepSeek 3 x $0.94 = $2.82 (project total about $3.30 of $4.00), Z.ai
  3 x $1.10 = $3.30 (total about $3.44 of $8.00). Wall about 6 h (GLM), with v4-pro and flash
  done in about 2 h and 1.4 h. The budget guard stops a provider before its cap if GLM or v4-pro
  code tasks cost more than projected.
- Command: `scripts/run_matrix.sh --batch main1 --reps 3` (defaults: the 3 models, 20 tasks,
  3 arms, caps $4/$8, 600 s timeout; never `--allow-battery`).

## 6. Minimum detectable paired wall-clock difference

Method: per block, d = ln(wall_arm) - ln(wall_off) (paired, same task and rep, arms run back to
back). Two-sided alpha 0.05, power 0.8: MDE = (1.96 + 0.84) x SD(d) / sqrt(n), read as a ratio
exp(MDE).

Variance inputs (smoke2, flash, `scripts/smoke_table.py`):
- SD(d) over the 20 rep-1 blocks: 0.278 (on vs off), 0.308 (plain vs off). This mixes run noise
  with task-to-task differences in the true effect.
- Within-cell SD of ln(wall) across reps (18 task x arm cells, 3 reps, df 36): 0.266 (gather
  0.273, code 0.259). Two INDEPENDENT runs would give a difference SD of 0.266 x sqrt(2) = 0.38;
  the observed paired SD (0.28) is smaller, so back-to-back pairing removes shared drift and
  there is no sign of large between-task effect heterogeneity. I therefore treat SD(d) = 0.28
  (on) and 0.31 (plain) as mostly noise that more reps do average down.

| analysis | n per model (3 reps) | MDE on vs off | MDE plain vs off |
|---|---|---|---|
| per model, pairs (task-clustered bootstrap has about the same n when heterogeneity is small) | 60 | 2.8 x 0.278 / 7.75 = 0.100, ratio about 1.11 | 0.111, about 1.12 |
| per model, worst case: all of SD(d) is between-task (n = 20 task means) | 20 | 0.174, about 1.19 | 0.193, about 1.21 |
| pooled over 3 models, common effect | 180 | 0.058, about 1.06 | 0.064, about 1.07 |

Conclusion: at 3 reps the design detects about a 10 % wall-clock change per model and about
6 % pooled; the pre-registered 10 % target is met per model only if GLM and v4-pro are not much
noisier than flash. GLM was far noisier in the pilot (36 to 142 s per gathering run), so expect
its per-model MDE to be worse. These estimates come from one model and one smoke batch.

## 7. Spend

Phase 2 LiteLLM spend (rows from 2026-10-10 01:50 UTC to 09:23 UTC): $0.382, all DeepSeek
flash (template warm-ups, 2-task test batch, smoke1 23 attempts, smoke2 98 attempts incl. the
variance reps; smoke2 alone $0.238). Project totals: DeepSeek $0.477, Z.ai $0.139.

## 8. Open issues

- No code task has been run on v4-pro or GLM: their cost and time per code run are projected,
  not measured. A 1-rep GLM code-only check (8 tasks x 3 arms, about 24 x 119 s = 48 min,
  about $0.45) before the main run would de-risk the 6 h estimate.
- Proxy-row attribution is by time window and model; the owner using the same model on the
  proxy during a batch would contaminate cost rows (not timing).
- Ceiling effect on success rate (4B).

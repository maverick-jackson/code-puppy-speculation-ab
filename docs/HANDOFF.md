# Handoff

## Phase 4 (analysis of main1), in progress

### Done
- `scripts/analyze_main1.py` implements the frozen analysis plan (docs/PLAN.md) and writes
  `docs/results/main1_tables.md`, `main1_summary.json`, `main1_forest.png`,
  `main1_forest_family.png`. Run it with `.venv-analysis/bin/python` (separate venv with numpy
  and matplotlib, gitignored; the agents' `.venv` is left untouched). Seed 20261011, 10,000
  task-clustered resamples; about 10 s.
- main1 is complete: 540 of 540 cells valid, 4 invalid attempts (3 clock stalls, flagged by the
  record field `slept`, and 1 proxy failure), all retried. All 544 records on host bench, code-puppy 0.0.896.
- `docs/RESULTS.md`: write-up of RQ1 to RQ6, sensitivity, limitations, reproduce steps. Headline:
  on vs off is SLOWER for every model (pooled +33.4% [+24.8, +42.5]); the cost is the code-mode
  interface (plain vs off pooled +37.5%); speculation given code mode is pooled -3.0% [-6.3, +0.3],
  within noise.

- Independent audit done: docs/audit/AUDIT_main1.md (headline holds; 11 required changes).
- Audit fixes, step 1 (raw data): committed `runs/main1/records.jsonl` (544 attempt records),
  `runs/main1/batch.json` (16 launch lines), `runs/main1/matrix.log` (runner log, line 430 is
  the NUL tail of the second power-off) and `runs/main1.log` (console output incl. the 13
  JSONDecodeError crash-loop launches). The per-run dirs `runs/main1/proxy-*/` (about 90 MB)
  are gitignored and stay on the Mac (copied from the bench host); available on request.

- Audit fixes, step 2 (analysis script, outputs regenerated): run_code max-retry runs regraded
  as failures per PLAN.md (raw grader verdict kept as `correct_raw`; on is now 174/180, 531 of
  540 correct); first-block sensitivity fixed to `block_index == 0`; new sensitivity excluding
  the 3 outage-split blocks; run-history section; `slept` reported as clock stall; new tables for
  requests per run / per-request latency / TTFT, wrapped calls per run_code snippet, tool-error
  and retry-prompt kinds per arm; eager_saved_ms next to saved_ms. Mechanism and error details
  come from `runs/main1/run_extract.jsonl` (+ `attempt_dirs.txt`), rebuilt from the run dirs when
  present and committed so the script reproduces everything from the repo alone (verified:
  identical summary JSON with a run dir moved away). Wall-clock numbers and forest PNGs unchanged.

- Audit fixes, step 3: `docs/RESULTS.md` rewritten with all 11 required changes: audit's safest
  headline as the lead sentence (numbers unchanged by the regenerated output); RQ2 regraded per
  the frozen rule (on 174/180, on vs off pooled McNemar 3 vs 6, p = 0.508); new Mechanism section
  (requests / latency / TTFT table, wrapped calls per snippet: about 1 per snippet); on vs plain
  framed as within noise with the GLM 0-of-1,173 streamed-args noise floor; median CI flagged as
  one of about 100 intervals; RQ4 with eager_saved_ms (11.2 s) next to saved_ms (16.7 s); RQ6
  error and retry-prompt kinds per arm; clock-stall wording; Run integrity section; outage-split
  sensitivity row; proxy-computed $ label; Data note on where run dirs live; Limitations
  additions. Script fix in the same commit: relative records path now resolves (the Reproduce
  command crashed in `relative_to`), and wall min/max plus arg-streaming counts are tabulated.
- New in the regraded data, worth knowing before the creator reads it: on vs plain success
  McNemar (not pre-registered) is 0 vs 6, p = 0.031. RESULTS reports it as a hint, not a finding.
- Audit correction: off-arm tool errors are mostly `grep` given a file path where it expects a
  directory (103 of 167), not "grep calls with no match"; RESULTS says so. The torn attempt dir
  (V4 Pro r4 r1 plain a1) has a zero-byte meta.json on the Mac copy, not a full one.

### Next
- Owner review of RESULTS.md. Discord drafts only after owner approval.

### Gotchas
- records.jsonl line 315 starts with 1,147 NUL bytes (the torn tail of the VM power-off) followed
  WITHOUT a newline by the valid orphan-finalized record of v4-pro h4_httpx_defaults r2 off. A
  plain json.loads per line drops that cell; `run_matrix.load_records` strips NULs and recovers
  it (that is why the runner never re-ran the cell). The analysis uses `load_records` and reports
  a sensitivity check with that record excluded.
- `grader.touched_tests` lists `tests/__pycache__/*.pyc` in 90 code runs: pytest bytecode picked
  up by `git add -A` in work_diff, not an agent edit. No run touched a real test file.
- Cost metrics use proxy-side fields (complete for all 540 runs); usage.json is missing for the
  2 run_code max-retry runs and differs by one request in 6 runs (time-window attribution).

## Phase 2 (harness + task suite + smoke), in progress

### Done
- Task suite: 12 gathering (click, httpx, rich at pinned SHAs) + 8 code-change (4 click bug
  injections, 4 on the invkit fixture). `tasks/README.md`. `scripts/setup_repos.sh` clones pins
  and builds `.venv` (pytest). `scripts/verify_tasks.py`: all 20 OK (code: hidden tests fail
  before, pass after reference.patch; gather: grader accepts variants, rejects corruptions).
  `tasks/gather_facts.py` recomputes every gather fact from the clones: 12/12 OK.
- `scripts/graders.py` (typed field grader + hidden pytest runner), `scripts/tasklib.py`
  (fresh per-run working copies, grade dispatch).

- Harness: `scripts/run_matrix.py` (+ `run_matrix.sh` key wrapper) with `runrecord.py`
  (execute/finalize one run). Paired blocks with seeded per-block arm order, shuffled block
  order, one thread per model (`--parallel` caps models at once), JSONL record per attempt,
  resume (tested), in-block and end-of-queue retries for infra-invalid runs (max 3 attempts),
  guards per block: code-puppy version (abort), AC power (60 s poll, `--allow-battery` for
  smoke only), per-provider budget (`--cap-deepseek 4`, `--cap-zai 8`, since 2026-10-09 UTC).
  Runs under `caffeinate -dimsu -w <pid>`.
- Homes: `scripts/prep_homes.sh` rebuilt + warmed templates `runs/homes/{off,on}` with the
  current plugin; every run gets a fresh APFS clone of a template (plain = on + SPEC_ARM).
- run_one.py refactored to `run()` (CLI unchanged), records the installed version, puts
  `.venv/bin` first on the agent PATH. summarize.py split into `metrics()` + grading, counts
  transcript `retry-prompt` parts. collect_spend.py filters rows by proxy model.
- 2-task test batch `runs/tmp/t0` (flash, 6 runs): all valid and correct, resume skips all.

- Smoke batch `runs/smoke1` started 22:01 on battery (`--allow-battery`). At 22:17 the lid was
  closed: pmset log "Clamshell Sleep ... Using Batt". One run was flagged slept (detector worked)
  and retried. Batch stopped, LID GUARD added (run_matrix pauses before every run while
  `ioreg AppleClamshellState = Yes`), batch relaunched; it resumes when the lid opens.

- LEAK found in smoke1: c3_click_short_help/on (flash) walked up from its cwd inside the repo
  (`find /Users/tinyr/rig/work/cp-spec-ab -maxdepth 3`), then `cat` the task's
  reference.patch and hidden test (329 s, $0.048). Fix: per-run HOME + working copy now live in
  `$TMPDIR/pupbench/<batch>/<model>/` (outside the project, path does not name the experiment),
  and any run whose transcript/stdout mentions task-suite files is invalid (`leak`) and retried.
  smoke1 (23 records, kept as evidence) is superseded by smoke2 (fresh, same seed).
- SECOND smoke1 defect, found in the grader audit: all 4 click code tasks ran WITHOUT their
  injected bug (empty agent.diff, agents reported "already fixed"). `git apply` was run in a
  copy inside the project repo before `git init`, and git silently skips every path when run
  in a subdirectory of another repo. Fixed: init first, then apply, then assert with
  `git apply --check -R`. verify_tasks 20/20 OK again. smoke1 is therefore invalid for c1..c4.
- smoke2 restarted 01:55 with both fixes (lid now open).
- Validity rule fix: "Error executing prompt: Tool 'run_code' exceeded max retries count of 3"
  (h1 on, smoke2) is the AGENT failing (code-mode reliability, RQ6), not infra; it was being
  retried as agent_error. Now TASK_FAILURE_ERRORS stay valid failures; only provider/proxy errors
  are infra. `scripts/reclassify.py` re-applies the rules to a batch (run with the runner
  stopped); applied to smoke1 and smoke2 (.bak kept). smoke2 resumed under the lid guard.

- smoke2 rep 1 complete: 60 valid runs (+1 slept retry), 57/60 correct (3 genuine failures),
  $0.00236/run. docs/GRADER_AUDIT.md (14 items, graders right every time) and
  docs/PHASE2_REPORT.md (tables, sizing: 3 reps = 540 runs, about 6 h, DeepSeek about $3.21 and
  Z.ai about $3.44 projected project totals; MDE about 10 to 19 % per model, 6 to 12 % pooled).

### Next
- Variance reps done (sd_within 0.266 on ln wall, df 36); report section 6 updated.
- Recommended before freezing: 1-rep GLM code-only check (report section 8).
- Main run (Phase 3, after freeze): `scripts/run_matrix.sh --batch main1 --reps 3` on AC, lid open.

### Gotchas
- Grader pytest runs with an empty `-c` config: click's setup.cfg sets filterwarnings=error.
- Code working copies drop the original .git and get a fresh one-commit repo (bug invisible).
- Closed lid = clamshell sleep even under caffeinate (on battery always; on AC unless an
  external display is attached). The lid guard only prevents STARTING runs; a lid closed mid-run
  still produces a slept run (flagged, retried).
- `git add -A -- . ':!dir'` fails (128) when dir does not exist; work_diff uses plain add -A.
- Proxy spend rows lag: records are appended only after >= 60 s (finalize_pending); a run whose
  rows never appear within 5 min is recorded with proxy_missing=true.

# Phase 1 handoff (feasibility spike), kept for reference

## Done
- Isolation: experiments run with `HOME=runs/homes/<arm>` (built by `scripts/mkhome.sh`), so the
  owner's live `~/.code_puppy` is never read or written. Live puppy.cfg was NOT modified.
- `plugin/spec_capture/` user plugin (copied into each sandbox home) captures speculation
  counters, per-event tallies, per-tool-call arg streaming, tool calls, agent run timings.
  Optional `SPEC_ARM=codemode_plain` = code mode without speculation/eager (arm C).
- `scripts/run_one.py` (via `scripts/run_batch.sh`, which decrypts the proxy key once outside the
  timed window) runs one headless task and writes meta/stdout/stderr/usage/capture.
- `scripts/collect_spend.py` attaches LiteLLM_SpendLogs rows to meta.json AFTER a batch.
- Smoke runs (runs/tmp, gitignored): deepseek-flash OFF 9.6s, ON 11.3s, both correct;
  ON had 6 hits / 0 misses / 0 wasted, saved >= 0.70s.

- GLM-4.7 via LiteLLM needed two sandbox-only fixes (alias `proxy-zai-g47`, `drop_params`), see
  mkhome.sh comments. Failed first attempt kept in runs/pilot/_failed/.
- Plugin gained `SPEC_ARM=codemode_eager` (arm D, eager without speculation) and run_one.py
  copies the headless transcript; both added mid-pilot, not yet exercised.
- docs/FEASIBILITY.md drafted (sections 1, 3, 4, 5); pilot-dependent sections are placeholders.

- Pilot done for flash (g1+g2, 3 arms) and GLM (g1, 3 arms). GLM g2 and the Kimi/V4-Pro
  pilots were invalidated: the MacBook lid was closed on battery, the machine slept (pmset log
  DarkWake "lid"), one request took 15 min. Moved to runs/pilot/_failed/glm-g2-machine-asleep.
- runner now: files not pipes, wall-clock timeout with process-group kill, `slept` flag
  (perf_counter stops during macOS sleep; utc span does not).
- scripts/probe_arg_streaming.py: arg deltas stream for deepseek-flash/kimi/v4-pro, NOT for
  GLM-4.7 (1 tool-call chunk with whole args). runs/pilot/arg_streaming_probe.jsonl.

- Kimi g1 on/off, V4-Pro g1 x3 and g2 x3, GLM g2 x3 run with lid open (no sleep). 20 valid
  pilot runs, all correct. FEASIBILITY.md complete. Phase 1 spend $0.2962.

## Next (Phase 2)
- Rebuild homes (deployed plugin predates arm D). Template-home + per-run reset recommended.
- Harness: JSONL records, shuffled interleaving, retries/429/slept as exclusion flags, transcript
  parse for RetryPromptPart. More gathering tasks across repos + code-change tasks with hidden
  pytest graders. Throttle Kimi. Run on AC power, lid open, under caffeinate.

## Gotchas
- Mac must be on AC with lid open for any timed batch; a closed lid on battery sleeps the
  machine regardless of caffeinate -i. Discard any run with `slept: true`.
- LiteLLM writes spend logs asynchronously and late (rows appeared >10s after the run). Collect
  spend after the batch, not inside the run.
- First run in a fresh sandbox home installs "Flux commands" (one-time startup noise): warm each
  home with one throwaway run before timing.
- Headless exits 0 even when the agent run errors (errors are emitted, not raised).
- zsh: never use `===` as an echo separator in Bash tool commands (zsh `=` expansion).

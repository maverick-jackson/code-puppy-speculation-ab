# Experiment 1: does code-puppy's speculative code mode make agents faster, and at what cost?

Owner: maverick-jackson. Manager: Claude (orchestrator). Status: design, pre-registration draft.
Nothing in this repo is published or posted until the owner approves the exact package.

## Why this, why now

- In late September 2026 code-puppy's creator shipped `enable_speculative_code_mode`
  (Ctrl+X Ctrl+S) as experimental, said he had seen speed gains that varied a lot by workflow,
  expected the biggest gains on gathering and on long blocking tool calls, and asked the
  community to test it before possibly making it the default.
- No controlled measurement existed. `docs/SPECULATION_STATUS.md` in code_puppy says the
  `saved ≥` counter is a LOWER BOUND on hidden tool latency, explicitly NOT wall-clock speedup,
  and that no live stats are printed to headless transcripts.
- Turning speculation on also folds every tool except create_file/replace_in_file into a
  `run_code` sandbox (code mode). So the switch changes the model's tool interface, which can
  change success rate, tokens and tool-call errors, not just latency. That side effect is the
  most decision-relevant thing to measure.
- Related: code_puppy issue #982 (code-mode workspace mount) and llxprt-code issue #3759
  (speculative execution for programmatic tool calls), so the result is relevant beyond
  code-puppy.
- Design goal: a paired, repeated, randomized A/B with confidence intervals, rather than single
  runs.

## Research questions (pre-registered)

- RQ1 (speed): end-to-end wall-clock per task, speculation ON vs OFF, same model, same task.
- RQ2 (quality): task success rate ON vs OFF. Does code mode hurt or help weaker / cheaper models?
- RQ3 (cost): input/output tokens, requests, $ per task and $ per SOLVED task.
- RQ4 (mechanism): speculation hits / misses / wasted and `saved ≥` per run, and how much of the
  measured wall-clock delta that lower bound explains.
- RQ5 (by workload): gathering-heavy (read/search/answer) vs code-change tasks, testing the
  creator's own hypothesis.
- RQ6 (reliability): malformed tool calls, tool errors, retries, timeouts, aborted runs per arm.

## Design (to be finalised after the feasibility phase, then frozen before the main run)

- Unit: (task, model, arm, repetition). Paired by task and model. Arms randomized in order within
  each pair, interleaved in time so provider latency drift hits both arms equally.
- Arms: A = native tools (speculation off). B = speculation on. If code mode can be enabled
  WITHOUT speculation, add arm C so we can separate "code mode effect" from "speculation effect".
- Models (via local LiteLLM, paid per token, owner budget = preloaded balances only, no refills):
  deepseek-flash, deepseek-v4-pro, zai-glm-4.7, kimi-k2.7-code. Groq free tier only if its rate
  limits do not contaminate timing. No subscription-billed models in any cost table.
- Tasks: two families, each with an automatic, deterministic grader:
  1. Gathering: questions about a pinned real repo with exact verifiable answers.
  2. Code change: small bug-fix / feature tasks graded by hidden tests (Terminal-Bench-style; use
     Harbor + Terminal-Bench tasks if Docker is workable on this Mac, else a local suite).
- Version pinned: code-puppy exact version recorded per run (installed: 0.0.896 at design time).
- Statistics: paired differences per (task, model); report median and mean speedup with
  bootstrap 95% CIs clustered by task; success rates with Wilson 95% CIs and a paired test
  (McNemar or exact sign test) on per-pair outcomes; tokens and cost as paired ratios with CIs.
  Sample size from pilot variance: target enough reps to detect a 10% wall-clock change.
- Every number in the write-up must be traceable to a raw run record (JSONL) and reproducible by
  a script in this repo. Graders are spot-checked by hand on a random sample.

## Phases (each run by a single-pass agent; manager verifies between phases)

1. Feasibility spike: toggle headless, confirm speculation engages with our models, capture
   counters, measure timing, pick task source, 1 pilot pair per model. Output FEASIBILITY.md.
2. Harness + task suite + graders, with tests. Pilot (~2 reps) to estimate variance and cost.
3. Freeze design (this file, section "Frozen design"), then main run.
4. Analysis + charts + independent audit agent re-derives every number from raw data.
5. Package: README, report, charts, raw data, Discord message drafts. Owner approval gate.

## Budget guard

Preloaded balances: Z.ai $10, DeepSeek $5 (+ grant), Moonshot $5, Groq free. Spent before this
project: $0.04. Harness must read LiteLLM spend before and after each batch and stop if any
provider would drop below $0.50 remaining.

## Frozen design (2026-10-10, before batch main1; no changes after the run starts)

- Batch `main1`: models proxy-deepseek-flash, proxy-deepseek-v4-pro, proxy-zai-g47; all 20 tasks
  (12 gathering, 8 code); arms off / on / plain; 3 reps; seed 20261010; one worker per model,
  paired randomized blocks; code-puppy 0.0.896; timeout 600 s; caps DeepSeek $4.00, Z.ai $8.00.
- Valid run: not slept, no infra failure (proxy error, timeout_infra, harness crash). Invalid runs
  are retried up to the runner's attempt limit; a cell still invalid after that is reported as
  missing, never imputed. Task failures (wrong answer, hidden tests fail, run_code max retries,
  agent timeout) are valid runs and count as failures.
- Primary outcome: per-model paired log wall-clock ratio, on vs off. Point estimate = mean of
  per-(task, rep) log ratios, reported as % change; 95% CI by bootstrap (10,000 resamples)
  clustered by task. Pooled estimate across models reported alongside, never instead.
- Secondary: plain vs off (code-mode interface effect), on vs plain (speculation effect given code
  mode); same method. Split by family (gathering vs code) as RQ5.
- Success: per arm Wilson 95% CI; paired on vs off and plain vs off with exact McNemar on
  discordant pairs. Expect low power (ceiling); report as such.
- Cost: paired ratios of input tokens, output tokens, requests, proxy $; $ per solved task.
- Mechanism: sum of `saved_ms` as a share of measured wall-clock per run in arm on.
- Reliability: counts per arm of tool_errors, run_code max-retry failures, 429s, timeouts.
- Sensitivity checks (reported, not used to pick headlines): correct-only runs; excluding the
  first block per worker (warm-up); medians instead of means.
- Known limitation stated up front: workloads are short tasks (about 10 to 90 s); long blocking
  tool calls, where the creator expects the biggest gains, are under-represented.

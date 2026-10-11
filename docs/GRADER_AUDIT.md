# Grader audit (Phase 2 smoke)

Method: for each graded run listed below I read the agent's final output (stdout tail) or its
diff (`agent.diff`), compared it with the source at the pinned commit (gather) or with the task
spec and reference patch (code), and recorded whether the automatic grade was right. Model:
proxy-deepseek-flash. Paths are under `runs/<batch>/proxy-deepseek-flash/<task>/r1/<arm>/a1/`.

## Runs checked by hand

| # | batch | task / arm | automatic grade | what I checked | grade right? |
|---|---|---|---|---|---|
| 1 | smoke2 | g4_click_types / on | correct | `ANSWER: 17\|convert_type\|999\|32767`; 17 = ast count of ParamType descendants in types.py, `def convert_type` is line 999, `MAX_BYTES_WRITTEN = 32767` in _winconsole.py | yes |
| 2 | smoke2 | r2_rich_console / plain | correct | `80\|25\|dumb, unknown\|COLUMNS, LINES` (spaces after commas, normalised as sets); console.py 1004 returns (80, 25), 976 `("dumb", "unknown")`, 1023-1028 COLUMNS/LINES | yes |
| 3 | smoke2 | h1_httpx_exceptions / on | wrong | no ANSWER line; run ended with `Tool 'run_code' exceeded max retries count of 3` | yes (and see finding C) |
| 4 | smoke2 | h1_httpx_exceptions / off | correct | `14\|map_httpcore_exceptions\|15\|20`: default.py 89-104 has 14 entries; 15 TransportError descendants (ast); DEFAULT_MAX_REDIRECTS = 20 | yes |
| 5 | smoke2 | g3_click_helpwidth / all 3 arms | correct | `src/click/formatting.py\|80\|50\|FORCED_WIDTH`, formatting.py 123-128 | yes |
| 6 | smoke2 | c1_click_intrange_clamp / on | correct (4 passed) | diff restores `return bound + dir`, identical to reference.patch | yes |
| 7 | smoke2 | c3_click_short_help / off | correct (4 passed) | diff restores `if word[-1] == ".":`, identical to reference.patch | yes |
| 8 | smoke2 | c4_click_bool_case / off | correct (17 passed) | diff restores `.lower()`, identical to reference.patch | yes |
| 9 | smoke2 | f2_invkit_thousands / off | correct (3 passed) | different fix from reference (regex that strips only well-formed comma groups); accepts "1,200" and "1,299.50", still rejects garbage and negatives as the spec says | yes |
| 10 | smoke2 | f1_invkit_total_value / on | correct (6 passed) | `total_value` reuses `by_category`, rounds to 2 places; CLI `--total` prints `Total value: {:.2f}` last | yes |
| 11 | smoke2 | f4_invkit_report_desc / plain | correct (4 passed) | `sorted(..., reverse=descending)` plus `--desc` wired into `format_report` | yes |
| 12 | smoke2 + pilot | g1_click_exceptions, all arms (3 smoke + 11 pilot runs, re-graded with the new grader) | correct | every answer `MissingParameter\|BadParameter\|2\|45`, same verdict as the Phase 1 grader | yes |
| 13 | smoke1 | c1..c4 click tasks, all arms | correct | agents reported the bug "already fixed", `agent.diff` empty | grade right on its own terms, TASK broken (finding A) |
| 14 | smoke1 | c3_click_short_help / on | correct | agent ran `find` above its cwd and `cat` the task's reference.patch and hidden test | grade not meaningful (finding B) |

Automated checks in addition to the hand audit (`scripts/verify_tasks.py`, all 20 OK):
- gather: for each of the 12 tasks the exact answer and a reformatted one (backticks, bold
  `**ANSWER:**`, spaces around `|`, reversed list order) grade correct; each single-field
  corruption, a missing field and a missing ANSWER line grade wrong (0 false accepts out of 71).
- code: hidden tests fail on the fresh working copy and pass after `reference.patch`.
- `tasks/gather_facts.py` recomputes every expected count, line number and constant from the
  clones (ast/regex): 12/12 agree with the task files.

## Findings

A. Broken task setup (fixed, commit 15b9a92). In smoke1 the click working copies were made
inside the project repo and `git apply bug.patch` ran before `git init`; git silently skips all
paths when run in a subdirectory of another repo, so the bug was never injected. The grader
passed the untouched code correctly, but those runs measured nothing. Fix: init first, apply,
then assert with `git apply --check -R`. Would have been invisible without reading diffs.

B. Hidden-test leak (fixed, commit 3583a7e). Working copies lived under the project tree, so an
agent could walk up into `tasks/`. Fix: per-run HOME and working copy in `$TMPDIR/pupbench/`,
plus a leak detector (task-suite paths in stdout/transcript) that makes the run invalid.

C. Validity rule (fixed, commit dedf477). The code-mode tool-retry exhaustion in #3 was being
classified as infra (`agent_error`) and would have been retried, hiding exactly the reliability
signal RQ6 measures. Now only provider/proxy/network errors are infra.

Verdict: on 14 hand-checked items (40+ graded runs) the graders' verdicts were right every time;
the three defects found were in task setup, isolation and the validity rule, all fixed, and
smoke1 is superseded by smoke2.

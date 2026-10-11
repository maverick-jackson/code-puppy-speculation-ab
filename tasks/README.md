# Task suite (Phase 2)

20 tasks, two families, all graded automatically and deterministically. Prompts are identical in
every arm and never mention speculation or code mode. Setup: `scripts/setup_repos.sh` clones the
pinned repos into `runs/repos/` (gitignored) and builds `.venv` (pytest 8.3.3, used by the grader
and put first on the agent's PATH in every arm). Self-check: `.venv/bin/python scripts/verify_tasks.py`
and `.venv/bin/python tasks/gather_facts.py`.

Pinned repos:

| repo | tag | commit |
|---|---|---|
| pallets/click | 8.1.7 | 874ca2bc1c30d93a4ac6e36a15ed685eafe89097 |
| encode/httpx | 0.27.0 | 326b9431c761e1ef1e00b9f760d1f654c8db48c6 |
| Textualize/rich | v13.7.1 | 7f580bdcf07a3b269a0e786b6a3aa9c804f393cf |

## Gathering (12): `tasks/gather/<id>.json`

Each prompt asks 3 or 4 questions that need reading or searching several places, and ends with
`ANSWER: a|b|c|d`. Each field has a type (`int`, `num`, `name`, `path`, `set`, `str`); see
`scripts/graders.py` for the exact normalisation. Anchors that memory alone cannot answer: line
numbers, counts and constants at the pinned commit. Every count, line number and constant is
recomputed from the clones by `tasks/gather_facts.py` (ast and regex, not by hand).

| id | repo | what it needs |
|---|---|---|
| g1_click_exceptions | click | exception raised for a missing option, its parent, exit_code via inheritance, a default arg (Phase 1 pilot task) |
| g2_click_completion | click | min Bash version, ClickException subclass count, completion env var, Exit base class (Phase 1 pilot task) |
| g3_click_helpwidth | click | file defining HelpFormatter, default max width, minimum width, override variable |
| g4_click_types | click | ParamType subclass count (17), convert_type and its def line (999), MAX_BYTES_WRITTEN in the Windows module |
| h1_httpx_exceptions | httpx | size of the httpcore to httpx exception map (14), the context manager using it, TransportError subclass count (15), default max redirects |
| h2_httpx_redirects | httpx | line raising TooManyRedirects (972), status codes that switch to GET, headers dropped on switch, header always dropped |
| h3_httpx_content | httpx | file read chunk size, decoder mapping keys (including br), encode_request def line (182), URL length constant |
| h4_httpx_defaults | httpx | number of names in `__all__` (69), default timeout and pool limits |
| r1_rich_box | rich | number of Box styles (19), legacy Windows substitution entries (6), Table and Panel default boxes |
| r2_rich_console | rich | dumb terminal size, TERM values that count as dumb, env vars overriding size |
| r3_rich_loop | rich | file defining loop_last, how many modules import it (9), its def line (18) |
| r4_rich_progress | rich | Status refresh rate and spinner, Progress refresh rate, number of decimal size suffixes |

## Code change (8): `tasks/code/<id>/`

`task.json` (prompt, base, PYTHONPATH), `hidden/test_hidden.py` (never inside the agent's working
copy; copied in only after the agent exits), `reference.patch` (a known-good fix), and for click
tasks `bug.patch` (applied to the fresh working copy before the run; the copy gets a fresh
one-commit git history so the injected change is not visible in `git log` or `git diff`).
`scripts/verify_tasks.py` proves for each task: hidden tests FAIL on the fresh copy and PASS
after `reference.patch`.

| id | base | kind | change |
|---|---|---|---|
| c1_click_intrange_clamp | click 8.1.7 + bug | bug fix | IntRange clamp ignores open bounds |
| c2_click_longopt_equals | click 8.1.7 + bug | bug fix | `--name=a=b=c` loses everything after the second `=` |
| c3_click_short_help | click 8.1.7 + bug | bug fix | short help no longer stops at the first sentence |
| c4_click_bool_case | click 8.1.7 + bug | bug fix | bool options reject capitalised spellings |
| f1_invkit_total_value | fixture invkit | feature | `Inventory.total_value(category=None)` plus a `--total` CLI flag |
| f2_invkit_thousands | fixture invkit | bug fix | CSV numbers with thousands separators fail to parse |
| f3_invkit_bulk_discount | fixture invkit | bug fix | off-by-one in bulk discount threshold |
| f4_invkit_report_desc | fixture invkit | feature | `descending` keyword for `format_report` plus `--desc` CLI flag |

`tasks/fixtures/invkit/` is a small inventory library written for this suite (5 modules, a CLI,
4 visible tests). Click tasks use the pinned click source (its own test suite is visible to the
agent, as in real work).

## Old pilot files

`tasks/g1_click_exceptions.{txt,expected}` and `tasks/g2_click_completion.{txt,expected}` are the
Phase 1 pilot inputs, kept so `runs/pilot/` stays reproducible with `scripts/summarize.py`.

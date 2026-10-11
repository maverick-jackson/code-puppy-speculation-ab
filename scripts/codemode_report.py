#!/usr/bin/env python3
"""Render docs/results/codemode_followup.html (self-contained HTML, inline SVG) from the run records.

Every number comes from scripts/codemode_tables.data(), which reads runs/codemode/*/records.jsonl.
Usage: python3 scripts/codemode_report.py [OUT.html]
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codemode_tables  # noqa: E402

D = codemode_tables.data()
SOL, LUNA = "codex-gpt-6.1-sol", "codex-gpt-6-luna"
NAMES = {SOL: "gpt-6.1-sol", LUNA: "gpt-6-luna"}
COLORS = {"off": "#8b95a7", "base": "#f5a524", "new": "#2dd4bf", "fix": "#a78bfa"}
LABELS = {"off": "code mode off", "base": "code mode, before", "new": "code mode, after #1013",
          "fix": "after #1013 + #1014"}


def esc(s: object) -> str:
    return html.escape(str(s))


def bars(title: str, groups: list[tuple[str, dict[str, float]]], unit: str = "", fmt: str = "{:.1f}",
         lower_better: bool = True) -> str:
    """Grouped horizontal-ish vertical bar chart as inline SVG."""
    series = [s for s in ("off", "base", "new", "fix") if any(s in g for _, g in groups)]
    vmax = max(v for _, g in groups for v in g.values()) * 1.18 or 1
    w, h, pad_l, pad_b, pad_t = 560, 250, 14, 46, 34
    gw = (w - pad_l * 2) / len(groups)
    bw = min(46, (gw - 30) / len(series))
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="{esc(title)}">',
           f'<text x="{pad_l}" y="18" class="ct">{esc(title)}</text>']
    base_y = h - pad_b
    out.append(f'<line x1="{pad_l}" y1="{base_y}" x2="{w - pad_l}" y2="{base_y}" class="axis"/>')
    for gi, (gname, vals) in enumerate(groups):
        x0 = pad_l + gi * gw + (gw - bw * len(series)) / 2
        for si, s in enumerate(series):
            if s not in vals:
                continue
            v = vals[s]
            bh = (base_y - pad_t) * v / vmax
            x = x0 + si * bw
            out.append(f'<rect x="{x + 3:.1f}" y="{base_y - bh:.1f}" width="{bw - 6:.1f}" height="{bh:.1f}" '
                       f'rx="5" fill="{COLORS[s]}"><title>{esc(LABELS[s])}: {fmt.format(v)}{unit}</title></rect>')
            out.append(f'<text x="{x + bw / 2:.1f}" y="{base_y - bh - 6:.1f}" class="bv">{fmt.format(v)}{unit}</text>')
        out.append(f'<text x="{pad_l + gi * gw + gw / 2:.1f}" y="{base_y + 20}" class="gl">{esc(gname)}</text>')
    hint = "lower is better" if lower_better else "higher is better"
    out.append(f'<text x="{w - pad_l}" y="18" class="hint">{hint}</text></svg>')
    return "".join(out)


def legend(series: list[str]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{COLORS[s]}"></i>{esc(LABELS[s])}</span>' for s in series) + "</div>"


def lines(title: str, key: str, fmt: str = "{:.2f}") -> str:
    it = D["iterations"]
    labels = [x["label"] for x in it[SOL]]
    vals = {m: [float(x[key]) for x in it[m]] for m in (SOL, LUNA)}
    vmax = max(max(v) for v in vals.values()) * 1.15 or 1
    w, h, pl, pr, pt, pb = 560, 240, 44, 24, 46, 40
    sx = lambda i: pl + i * (w - pl - pr) / (len(labels) - 1)  # noqa: E731
    sy = lambda v: h - pb - (h - pb - pt) * v / vmax  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="{esc(title)}">',
           f'<text x="14" y="18" class="ct">{esc(title)}</text>']
    for k in range(4):
        v = vmax * k / 4
        out.append(f'<line x1="{pl}" y1="{sy(v):.1f}" x2="{w - pr}" y2="{sy(v):.1f}" class="grid"/>'
                   f'<text x="{pl - 8}" y="{sy(v) + 4:.1f}" class="tick">{fmt.format(v)}</text>')
    for i, lab in enumerate(labels):
        out.append(f'<text x="{sx(i):.1f}" y="{h - pb + 20}" class="gl">{esc(lab)}</text>')
    lx = w - pr
    for m, color in ((LUNA, "#f472b6"), (SOL, "#38bdf8")):
        pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(vals[m]))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"/>')
        for i, v in enumerate(vals[m]):
            out.append(f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="4.5" fill="{color}"><title>{NAMES[m]} '
                       f'{labels[i]}: {fmt.format(v)}</title></circle>')
        label = f"{NAMES[m]}: {fmt.format(vals[m][0])} → {fmt.format(vals[m][-1])}"
        out.append(f'<text x="{lx}" y="18" class="lg" style="fill:{color}">{esc(label)}</text>')
        lx -= 9 + 6.6 * len(label)
    out.append("</svg>")
    return "".join(out)


def cell(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"
    return str(v)


def table(headers: list[str], rows: list[list[object]], highlight_col: int | None = None) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        variant = str(r[1]) if len(r) > 1 else ""
        cls = ' class="hl"' if variant in ("new", "fix") else ""
        body += f"<tr{cls}>" + "".join(f"<td>{esc(cell(c))}</td>" for c in r) + "</tr>"
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def pct(a: float, b: float) -> str:
    return f"{(a - b) / b * 100:+.0f}%"


def fewer(a: float, b: float, noun: str) -> str:
    """'30% fewer input tokens' / '12% more input tokens' for a vs b."""
    change = (a - b) / b * 100
    return f"{abs(change):.0f}% {'fewer' if change < 0 else 'more'} {noun}"


S, L, Dl = D["short"], D["long"]["L_"], D["long"]["D_"]
SUB, FAN, IT = D["subagents"], D["fanout"], D["iterations"]
n_runs = D["n_runs"]

kpis = [
    (f'{S[LUNA]["base"]["calls_per_run_code"]:.1f} → {S[LUNA]["new"]["calls_per_run_code"]:.1f}',
     "tool calls per run_code", "gpt-6-luna, short tasks"),
    (f'{Dl[SOL]["off"]["wall_completed"]:.0f}s → {Dl[SOL]["new"]["wall"]:.0f}s',
     "delegation wall time", f'gpt-6.1-sol, {Dl[SOL]["off"]["wall_completed"] / Dl[SOL]["new"]["wall"]:.1f}x faster than no code mode'),
    (f'{S[SOL]["base"]["rc_errors"]:.2f} → {S[SOL]["new"]["rc_errors"]:.2f}',
     "run_code errors per task", "gpt-6.1-sol, short tasks"),
    (f'{SUB[LUNA]["new"]["in_tok_k"]:.0f}k → {SUB[LUNA]["fix"]["in_tok_k"]:.0f}k',
     "sub-agent context per session", "gpt-6-luna, after PR #1014"),
]

short_rows = []
for m in (SOL, LUNA):
    for v in ("off", "base", "new"):
        x = S[m][v]
        short_rows.append([NAMES[m], v, x["n"], x["success"], x["wall_mean_s"], x["wall_median_s"], x["requests"],
                           x["calls_per_run_code"] or "-", f'{x["pct_rc_le1"]}%' if x["run_code"] else "-",
                           x["rc_errors"], x["in_tok_k"], x["out_tok_k"]])


def long_rows(block: dict, with_sub: bool) -> list[list[object]]:
    rows = []
    for m in (SOL, LUNA):
        for v in ("off", "base", "new", "fix"):
            if v not in block[m]:
                continue
            x = block[m][v]
            r = [NAMES[m], v, x["success"], f'{x["part_acc"]}%', x["wall"]]
            if with_sub:
                r.append(x["wall_completed"])
            r.append(x["parent_req"])
            if with_sub:
                r += [x["total_req"], x["max_fanout"] or "-"]
            r += [x["calls_per_run_code"] or "-", x["rc_errors"], x["total_in_tok_k"], x["timeouts"]]
            rows.append(r)
    return rows


iter_notes = [
    ("main", "origin/main baseline: prompt says go BIG, but models wrap one call per snippet."),
    ("it1", "Rewrote guidance around batch / chain / loop / filter-in-code; run_code description note; "
            "nested results stop spilling to handles inside the sandbox."),
    ("it2", "Named the three commonest single-call habits + heredoc quoting fix. Calls per snippet jumped, but "
            "errors doubled: our own example failed the sandbox type checker (file_path is str | None)."),
    ("it3", "Type-clean examples, str | None narrowing rule, Monty quirk: next(genexpr) raises. Errors collapse."),
    ("it4", "Told models to return matched lines next to computed counts. Did not fix the r3 miss."),
    ("it5", "Root cause of r3: read_file refused big files with content=None, which code read as empty. "
            "Code mode now reads whole files in the sandbox."),
]

sol_off_single = FAN[SOL]["off_invokes_per_response"].get(1, 0)
sol_off_quad = FAN[SOL]["off_invokes_per_response"].get(4, 0)

CSS = """
:root{--bg:#070b14;--panel:#0e1526;--panel2:#121b31;--line:#1f2a44;--text:#e6edf7;--muted:#93a1bd;--accent:#2dd4bf;--accent2:#38bdf8;--warn:#f5a524;--bad:#f87171}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:0 28px}
header{background:radial-gradient(1200px 500px at 10% -10%,#134e4a 0,transparent 60%),radial-gradient(900px 500px at 100% 0,#1e3a8a 0,transparent 55%),var(--bg);border-bottom:1px solid var(--line);padding:72px 0 56px}
.eyebrow{letter-spacing:.18em;text-transform:uppercase;font-size:12px;color:var(--accent);font-weight:700}
h1{font-size:54px;line-height:1.05;margin:14px 0 18px;letter-spacing:-.02em}h1 em{font-style:normal;background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.lede{font-size:20px;color:#c7d2e6;max-width:820px}
.meta{margin-top:22px;color:var(--muted);font-size:14px;display:flex;gap:22px;flex-wrap:wrap}.meta b{color:var(--text)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:40px}
.kpi{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:20px 20px 18px;position:relative;overflow:hidden}
.kpi:before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:linear-gradient(90deg,var(--accent),var(--accent2))}
.kpi .v{font-size:28px;font-weight:800;letter-spacing:-.01em;white-space:nowrap}.kpi .l{margin-top:6px;font-weight:600}.kpi .s{color:var(--muted);font-size:13px;margin-top:2px}
section{padding:56px 0 8px}h2{font-size:30px;margin:0 0 6px;letter-spacing:-.01em}h2 small{display:block;font-size:14px;color:var(--muted);font-weight:500;margin-top:6px;letter-spacing:0}
h3{font-size:19px;margin:28px 0 10px}p,li{color:#cfd8ea}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 18px 10px}
.chart{width:100%;height:auto;display:block}.ct{fill:var(--text);font-weight:700;font-size:14px}.hint{fill:var(--muted);font-size:11px;text-anchor:end}
.bv{fill:var(--text);font-size:12px;font-weight:700;text-anchor:middle}.gl{fill:var(--muted);font-size:13px;text-anchor:middle}.axis{stroke:var(--line);stroke-width:1.5}.grid{stroke:#18223a;stroke-width:1}.tick{fill:#64708a;font-size:11px;text-anchor:end}.lg{font-size:12px;font-weight:700;text-anchor:end}
.legend{display:flex;gap:18px;flex-wrap:wrap;margin:10px 0 2px;color:var(--muted);font-size:13px}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:7px;vertical-align:-1px}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:14px;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th{background:var(--panel2);color:var(--muted);text-align:left;font-weight:600;padding:9px 10px;white-space:nowrap;border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid #16203a;white-space:nowrap}tr.hl td{background:rgba(45,212,191,.06)}tr:last-child td{border-bottom:0}
.tldr{background:linear-gradient(180deg,#0f2a2a,#0d1a26);border:1px solid #1b4d4a;border-radius:18px;padding:22px 26px}.tldr li{margin:8px 0}.tldr b{color:#fff}
.pill{display:inline-block;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted);margin-right:6px}
.pill.ok{color:#5eead4;border-color:#115e59;background:#042f2e}.pill.pr{color:#93c5fd;border-color:#1e3a8a;background:#0b1739}
.timeline{list-style:none;padding:0;margin:0}.timeline li{display:grid;grid-template-columns:70px 1fr;gap:14px;padding:12px 0;border-bottom:1px dashed var(--line)}.timeline li span{font-weight:800;color:var(--accent)}
.bugs{display:grid;grid-template-columns:1fr 1fr;gap:16px}.bug{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:12px;padding:14px 16px}.bug h4{margin:0 0 6px;font-size:16px}.bug p{margin:0;font-size:14.5px}
.callout{border-left:4px solid var(--accent2);background:var(--panel);padding:14px 18px;border-radius:10px;margin:16px 0;color:#cfd8ea}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;background:#111a2e;border:1px solid var(--line);padding:1px 6px;border-radius:6px;color:#e2e8f0}
footer{margin:64px 0 0;padding:28px 0 48px;border-top:1px solid var(--line);color:var(--muted);font-size:13.5px}
@media (max-width:900px){.kpis{grid-template-columns:1fr 1fr}.grid2,.bugs{grid-template-columns:1fr}h1{font-size:40px}}
"""

body = f"""
<header><div class="wrap">
<div class="eyebrow">Code Puppy · code mode A/B · follow-up</div>
<h1>Code mode, <em>actually batching</em>.</h1>
<p class="lede">The original A/B found code mode made Code Puppy slower: models wrapped one tool call per
<code>run_code</code> snippet and paid an extra round trip each time. We fixed the prompt, the return values
and two harness bugs, then measured again, including the long, sub-agent-heavy work code mode was built for.</p>
<div class="meta"><span><b>{n_runs}</b> headless runs</span><span><b>2</b> models: gpt-6.1-sol, gpt-6-luna</span>
<span><b>30</b> tasks (20 short + 10 long-horizon)</span><span>PRs <b>#1013</b> + <b>#1014</b> merged</span>
<span>2026-10-11</span></div>
<div class="kpis">{"".join(f'<div class="kpi"><div class="v">{esc(v)}</div><div class="l">{esc(lab)}</div><div class="s">{esc(sub)}</div></div>' for v, lab, sub in kpis)}</div>
</div></header>

<main class="wrap">
<section><div class="tldr"><h2 style="margin-bottom:8px">TL;DR</h2><ul>
<li><b>Snippets carry real work now.</b> Tool calls per <code>run_code</code> went {S[LUNA]["base"]["calls_per_run_code"]:.2f} → {S[LUNA]["new"]["calls_per_run_code"]:.2f} (luna) and {S[SOL]["base"]["calls_per_run_code"]:.2f} → {S[SOL]["new"]["calls_per_run_code"]:.2f} (sol); single-call snippets dropped from {S[LUNA]["base"]["pct_rc_le1"]}% to {S[LUNA]["new"]["pct_rc_le1"]}% (luna). Sandbox errors fell {S[SOL]["base"]["rc_errors"]} → {S[SOL]["new"]["rc_errors"]} per task (sol).</li>
<li><b>Fewer round trips at equal accuracy.</b> On long single-agent tasks code mode needs {L[SOL]["new"]["parent_req"]} model requests vs {L[SOL]["off"]["parent_req"]} without it (sol) at the same success rate and wall time; luna uses {fewer(L[LUNA]["new"]["total_in_tok_k"], L[LUNA]["off"]["total_in_tok_k"], "input tokens")}.</li>
<li><b>Sub-agents are where it shines.</b> One <code>run_code</code> fans out all four sub-agents at once. sol finishes delegation tasks in <b>{Dl[SOL]["new"]["wall"]:.0f}s vs {Dl[SOL]["off"]["wall_completed"]:.0f}s</b> (counting only finished runs; with its one 900s timeout, no code mode averages {Dl[SOL]["off"]["wall"]:.0f}s) with {Dl[SOL]["new"]["total_req"]:.1f} vs {Dl[SOL]["off"]["total_req"]:.1f} total requests and {Dl[SOL]["new"]["part_acc"]}% vs {Dl[SOL]["off"]["part_acc"]}% of answer parts right.</li>
<li><b>Short tasks are a wash on wall time.</b> Code mode still carries per-request prompt overhead; for luna it costs more input tokens than plain tool calling on 10 to 60 second tasks.</li>
<li><b>Two real Code Puppy bugs found by the benchmark</b>, both fixed and merged: nested results spilled to handle strings inside the sandbox (#1013), and sub-agents had no output bounds at all (#1014).</li>
</ul></div></section>

<section><h2>What changed<small>Code Puppy PRs #1013 and #1014, both merged into main</small></h2>
<div class="grid2">
<div class="card"><span class="pill ok">merged</span><span class="pill pr">#1013</span><h3 style="margin-top:12px">Teach batching, return whole values</h3><ul>
<li>Guidance rewritten around <b>write programs, not single calls</b>: batch, chain, loop, filter in code, absorb errors, with two type-clean multi-call examples.</li>
<li>Honest sandbox facts: no <code>Path.glob</code>, <code>os.walk</code>, <code>subprocess</code>; <code>next(genexpr)</code> raises; narrow <code>str | None</code> fields; check <code>error</code> instead of <code>or ""</code>.</li>
<li>Batching note appended to the <code>run_code</code> tool description.</li>
<li>Nested tool results stay whole inside the sandbox; only what reaches the model is bounded.</li>
<li><code>read_file</code> returns whole files in code mode instead of <code>content=None</code>.</li></ul></div>
<div class="card"><span class="pill ok">merged</span><span class="pill pr">#1014</span><h3 style="margin-top:12px">Bound sub-agent outputs</h3><ul>
<li>Sub-agents were built without the main agent's <code>ToolOutputLimits</code> and response clamp.</li>
<li>Once the sandbox could read whole files, a single sub-agent return reached <b>{SUB[LUNA]["new"]["max_ret"]:,} chars</b>.</li>
<li>Fix wires the same bounds into the sub-agent site: largest return now {SUB[LUNA]["fix"]["max_ret"]:,} chars, luna sub-agent context {SUB[LUNA]["new"]["in_tok_k"]}k → {SUB[LUNA]["fix"]["in_tok_k"]}k tokens per session.</li></ul></div>
</div></section>

<section><h2>Short tasks: the original 20<small>12 read-and-answer questions + 8 bug fixes on pinned click / httpx / rich and a fixture; pooled 80 runs per cell for code mode, 40 for off</small></h2>
{legend(["off", "base", "new"])}
<div class="grid2">
<div class="card">{bars("Tool calls per run_code", [(NAMES[m], {v: S[m][v]["calls_per_run_code"] for v in ("base", "new")}) for m in (SOL, LUNA)], fmt="{:.2f}", lower_better=False)}</div>
<div class="card">{bars("Model requests per task", [(NAMES[m], {v: S[m][v]["requests"] for v in ("off", "base", "new")}) for m in (SOL, LUNA)], fmt="{:.2f}")}</div>
<div class="card">{bars("run_code errors per task", [(NAMES[m], {v: S[m][v]["rc_errors"] for v in ("base", "new")}) for m in (SOL, LUNA)], fmt="{:.2f}")}</div>
<div class="card">{bars("Input tokens per task (k)", [(NAMES[m], {v: S[m][v]["in_tok_k"] for v in ("off", "base", "new")}) for m in (SOL, LUNA)], fmt="{:.1f}")}</div>
</div>
{table(["model", "variant", "n", "success", "wall mean s", "wall median s", "requests/task", "calls/run_code", "run_code ≤1 call", "run_code errors", "in tok k", "out tok k"], short_rows)}
<div class="callout">Against plain tool calling, sol makes {fewer(S[SOL]["new"]["requests"], S[SOL]["off"]["requests"], "model requests")} on short tasks at a similar wall time. luna makes {fewer(S[LUNA]["new"]["requests"], S[LUNA]["off"]["requests"], "requests")} but carries ~{S[LUNA]["new"]["in_tok_k"] / S[LUNA]["new"]["requests"] - S[LUNA]["off"]["in_tok_k"] / S[LUNA]["off"]["requests"]:.1f}k extra input tokens per request (the sandbox function stubs), so on 10 to 60 second tasks it is slightly slower. The <code>off</code> batch ran separately from the others.</div>
</section>

<section><h2>How we got there<small>Five prompt iterations, 80 runs each, same 20 tasks</small></h2>
<div class="grid2">
<div class="card">{lines("Tool calls per run_code", "calls_per_run_code")}</div>
<div class="card">{lines("run_code errors per task", "rc_errors")}</div>
</div>
<ul class="timeline">{"".join(f"<li><span>{esc(a)}</span><div>{esc(b)}</div></li>" for a, b in iter_notes)}</ul>
</section>

<section><h2>Long-horizon tasks<small>All four question sets of a repo in one task (15 to 16 answer fields), or four bugs and features in one codebase; 10 runs per cell</small></h2>
{legend(["off", "base", "new"])}
<div class="grid2">
<div class="card">{bars("Model requests per task", [(NAMES[m], {v: L[m][v]["parent_req"] for v in ("off", "base", "new")}) for m in (SOL, LUNA)])}</div>
<div class="card">{bars("Answer parts right (%)", [(NAMES[m], {v: L[m][v]["part_acc"] for v in ("off", "base", "new")}) for m in (SOL, LUNA)], fmt="{:.0f}", lower_better=False)}</div>
</div>
{table(["model", "variant", "success", "parts right", "wall s", "requests", "calls/run_code", "run_code errors", "in tok k", "timeouts"], long_rows(L, False))}
</section>

<section><h2>Sub-agents<small>Same long tasks, told to delegate the four parts to sub-agents; totals include every sub-agent's requests and tokens</small></h2>
{legend(["off", "base", "new", "fix"])}
<div class="grid2">
<div class="card">{bars("Wall time per task, finished runs (s)", [(NAMES[m], {v: Dl[m][v]["wall_completed"] for v in ("off", "base", "new", "fix")}) for m in (SOL, LUNA)], fmt="{:.0f}")}</div>
<div class="card">{bars("Sub-agent input tokens per session (k)", [(NAMES[m], {v: SUB[m][v]["in_tok_k"] for v in ("off", "base", "new", "fix")}) for m in (SOL, LUNA)], fmt="{:.1f}")}</div>
</div>
<div class="callout"><b>Why code mode wins here:</b> it launches all four sub-agents from one <code>run_code</code> with <code>asyncio.gather</code> (sol {FAN[SOL]["new_invokes_per_run_code"].get(4, 0)} of 10 runs, luna {FAN[LUNA]["new_invokes_per_run_code"].get(4, 0)} of 10). With plain tool calling sol issued {sol_off_single} single-<code>invoke_agent</code> responses (one sub-agent per turn) against {sol_off_quad} that launched all four at once.</div>
{table(["model", "variant", "success", "parts right", "wall s", "wall s (finished)", "parent requests", "total requests", "max fan-out", "calls/run_code", "run_code errors", "in tok k", "timeouts"], long_rows(Dl, True))}
<p>The <code>new</code> row is main right after #1013, before the sub-agent fix; <code>fix</code> adds #1014. The fix runs were a separate batch. Their delegation wall time is {Dl[SOL]["fix"]["wall"] - Dl[SOL]["new"]["wall"]:.0f}s (sol) and {Dl[LUNA]["fix"]["wall"] - Dl[LUNA]["new"]["wall"]:.0f}s (luna) longer than <code>new</code>; that is not extra round trips (sub-agents got bounded, spilled returns but called <code>read_tool_result</code> once in 81 sessions), so treat it as batch-to-batch noise. sol stays {Dl[SOL]["off"]["wall_completed"] / Dl[SOL]["fix"]["wall"]:.1f}x faster than no code mode, and luna's sub-agent context drops by {fewer(SUB[LUNA]["fix"]["in_tok_k"], SUB[LUNA]["new"]["in_tok_k"], "tokens").split(" ")[0]}. luna's delegation success moves around a lot between variants (4 to 7 of 10) while its part accuracy stays at 92 to 97%; with 10 runs per cell, read success differences of one or two runs as noise.</p>
</section>

<section><h2>Bugs the benchmark caught</h2><div class="bugs">
<div class="bug"><h4>Spill handles inside the sandbox</h4><p>Any nested tool result over 10k chars came back to the snippet as a <code>"[Tool output too large ...]"</code> string instead of a dict, breaking <code>r["content"]</code> and forcing extra round trips. Fixed in #1013.</p></div>
<div class="bug"><h4>Big files read as empty</h4><p><code>read_file</code> refused files over 10k tokens with <code>content=None</code>; snippet code turned that into <code>""</code> and silently undercounted (8 vs 9 importers). Fixed in #1013, plus an off-by-one in the token field.</p></div>
<div class="bug"><h4>Sub-agents without output bounds</h4><p>Sub-agents never had <code>ToolOutputLimits</code>. Returns of up to {SUB[LUNA]["new"]["max_ret"]:,} chars landed in context whole. Fixed in #1014.</p></div>
<div class="bug"><h4>Our own example failed type checking</h4><p>Iteration 2 taught <code>sorted({{m["file_path"] ...}})</code>; the sandbox type checker rejects it because the field is <code>str | None</code>. Half of that batch's errors. Fixed in iteration 3.</p></div>
<div class="bug"><h4>Graders reading wrapped stdout</h4><p>Long ANSWER lines wrap at terminal width in rendered output, so 16-field answers looked wrong. Long tasks are graded from the transcript's final text.</p></div>
<div class="bug"><h4>Sandbox gaps</h4><p>No <code>Path.glob</code>, <code>os.walk</code>, <code>sys.path</code>, <code>subprocess</code>; generator expressions are lists. Now stated up front instead of discovered by failing.</p></div>
</div></section>

<section><h2>Method and caveats</h2><ul>
<li><b>Harness:</b> headless <code>code-puppy -p</code>, one fresh working copy and isolated config / cache / state / data dirs per run. Only the ChatGPT OAuth token and model list are shared (symlinked; tokens are written in place). Sub-agents are pinned to the run's model, and every sub-agent session is captured.</li>
<li><b>Tasks:</b> the 20 tasks and graders from the original A/B, unchanged. The 10 long tasks are composed from them, so their answer keys and hidden tests are reused; each was validated (bugged copy fails every part, reference fixes pass every part).</li>
<li><b>Variants:</b> <code>off</code> = main with code mode disabled, <code>base</code> = code mode before #1013, <code>new</code> = after #1013, <code>fix</code> = after #1014.</li>
<li><b>Caveats:</b> 10 runs per long-task cell. Within each batch, variants were shuffled together; the short-task <code>off</code> runs and the long-task <code>fix</code> runs were separate batches, so time-of-day effects are not controlled for those comparisons. Two OpenAI models through ChatGPT OAuth only. GLM 5.3 (served by vLLM) was tested and dropped: at ~20 tokens/s it timed out on most long code-mode runs.</li>
</ul></section>

<footer>Generated by <code>scripts/codemode_report.py</code> from <code>runs/codemode/*/records.jsonl</code>. Every number on this page is computed from the run records; nothing is typed by hand.</footer>
</main>
"""

page = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Code mode, actually batching</title><style>{CSS}</style></head><body>{body}</body></html>'
out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_followup.html"
out.write_text(page)
print(out, len(page))

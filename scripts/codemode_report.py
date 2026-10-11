#!/usr/bin/env python3
"""Render docs/results/codemode_followup.html: code mode OFF vs ON (self-contained HTML, inline SVG).

ON is code mode as it is on code-puppy main after #1013 and #1014. Every number comes from
scripts/codemode_tables.onoff(), which reads runs/codemode/*/records.jsonl.
Usage: python3 scripts/codemode_report.py [OUT.html]
"""
from __future__ import annotations

import html
import math
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codemode_tables  # noqa: E402

D = codemode_tables.onoff()
FAN = codemode_tables.data()["fanout"]
SOL, LUNA = codemode_tables.MODELS
NAMES = {SOL: "gpt-6.1-sol", LUNA: "gpt-6-luna"}
OFF, ON = "#8b95a7", "#2dd4bf"
WL = D["workloads"]
SHORT_WL = {"short_gather": ("Short", "read+answer"), "short_code": ("Short", "bug fix"),
            "long_gather": ("Long", "read+answer"), "long_code": ("Long", "multi-fix"),
            "deleg_gather": ("Delegated", "read+answer"), "deleg_code": ("Delegated", "multi-fix")}
TASK_WL = {"g": "short_gather", "h": "short_gather", "r": "short_gather", "c": "short_code", "f": "short_code"}


def esc(s: object) -> str:
    return html.escape(str(s))


def change(on: float, off: float) -> float | None:
    return None if not off else (on - off) / off * 100


def fmt_change(c: float | None) -> str:
    return "-" if c is None else f"{c:+.0f}%"


def tone(c: float | None, lower_better: bool = True, dead: float = 5) -> str:
    """CSS class for a % change: good / bad / flat."""
    if c is None or abs(c) < dead:
        return "flat"
    return "good" if (c < 0) == lower_better else "bad"


def num(v: float) -> str:
    return f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"


# ---------------------------------------------------------------- charts

def pair_bars(title: str, m: str, key: str, fmt: str = "{:.1f}", lower_better: bool = True, unit: str = "") -> str:
    cells = D["cells"][m]
    vals = [(k, cells[k]["off"][key], cells[k]["on"][key]) for k, _ in WL]
    vmax = max(max(a, b) for _, a, b in vals) * 1.2 or 1
    w, h, pl, pb, pt = 560, 250, 10, 52, 36
    gw = (w - 2 * pl) / len(vals)
    bw = min(30, (gw - 14) / 2)
    base = h - pb
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="{esc(title)}">',
           f'<text x="{pl + 4}" y="18" class="ct">{esc(title)}</text>',
           f'<text x="{w - pl}" y="18" class="hint">{"lower" if lower_better else "higher"} is better</text>',
           f'<line x1="{pl}" y1="{base}" x2="{w - pl}" y2="{base}" class="axis"/>']
    for i, (k, a, b) in enumerate(vals):
        x0 = pl + i * gw + (gw - 2 * bw) / 2
        for j, (v, color, side) in enumerate(((a, OFF, "off"), (b, ON, "on"))):
            bh = (base - pt) * v / vmax
            x = x0 + j * bw
            out.append(f'<rect x="{x + 2:.1f}" y="{base - bh:.1f}" width="{bw - 4:.1f}" height="{bh:.1f}" rx="4" '
                       f'fill="{color}"><title>{side}: {fmt.format(v)}{unit}</title></rect>'
                       f'<text x="{x + bw / 2:.1f}" y="{base - bh - 5:.1f}" class="bv">{fmt.format(v)}</text>')
        c = change(b, a)
        cls = tone(c, lower_better)
        cx = pl + i * gw + gw / 2
        out.append(f'<text x="{cx:.1f}" y="{base + 15}" class="gl">{SHORT_WL[k][0]}</text>'
                   f'<text x="{cx:.1f}" y="{base + 28}" class="gl">{SHORT_WL[k][1]}</text>'
                   f'<text x="{cx:.1f}" y="{base + 44}" class="d {cls}">{fmt_change(c)}</text>')
    return "".join(out) + "</svg>"


def strip(m: str) -> str:
    """Every run's wall time, off vs on, per workload, on a log axis."""
    cells = D["cells"][m]
    lo, hi = 5, 1000
    w, rowh, pl, pr, pt = 560, 34, 118, 16, 40
    h = pt + rowh * len(WL) * 2 + 34
    sx = lambda v: pl + (w - pl - pr) * (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="wall time per run">',
           f'<text x="10" y="18" class="ct">Every run\'s wall time (s, log scale): {NAMES[m]}</text>']
    for t in (10, 30, 100, 300, 900):
        out.append(f'<line x1="{sx(t):.1f}" y1="{pt - 6}" x2="{sx(t):.1f}" y2="{h - 30}" class="grid"/>'
                   f'<text x="{sx(t):.1f}" y="{h - 14}" class="gl">{t}</text>')
    y = pt
    for k, _ in WL:
        out.append(f'<text x="10" y="{y + rowh - 4}" class="sl">{SHORT_WL[k][0]} {SHORT_WL[k][1]}</text>')
        for side, color in (("off", OFF), ("on", ON)):
            walls = cells[k][side]["walls"]
            cy = y + rowh / 2 + 4
            for i, v in enumerate(sorted(walls)):
                jitter = ((i * 7) % 9 - 4) * 1.4
                out.append(f'<circle cx="{sx(v):.1f}" cy="{cy + jitter:.1f}" r="3.2" fill="{color}" fill-opacity=".75">'
                           f'<title>{side}: {v:.0f}s</title></circle>')
            med = st.median(walls)
            out.append(f'<line x1="{sx(med):.1f}" y1="{cy - 10}" x2="{sx(med):.1f}" y2="{cy + 10}" stroke="#fff" '
                       f'stroke-width="2.5"><title>median {med:.0f}s</title></line>')
            y += rowh
        out.append(f'<line x1="10" y1="{y + 1}" x2="{w - pr}" y2="{y + 1}" class="sep"/>')
    return "".join(out) + "</svg>"


def mix_bars(m: str) -> str:
    """Tool calls per task by tool, off vs on (parent agent; run_code itself excluded)."""
    tools = ["read_file", "grep", "list_files", "shell", "replace_in_file", "invoke_agent"]
    colors = ["#38bdf8", "#a78bfa", "#f472b6", "#f5a524", "#34d399", "#fb7185"]
    pooled = {}
    for side in ("off", "on"):
        tot: dict[str, float] = {}
        n = 0
        for k, _ in WL:
            c = D["cells"][m][k][side]
            n += c["n"]
            for t, v in c["tool_mix"].items():
                tot[t] = tot.get(t, 0) + v * c["n"]
        pooled[side] = {t: tot.get(t, 0) / n for t in tools}
    vmax = max(sum(p.values()) for p in pooled.values()) * 1.1
    w, h, pl = 560, 150, 46
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="tool mix">',
           f'<text x="10" y="18" class="ct">Tool calls per run, by tool: {NAMES[m]}</text>']
    for row, side in enumerate(("off", "on")):
        y, x = 34 + row * 40, pl
        out.append(f'<text x="10" y="{y + 19}" class="sl">{side}</text>')
        for t, color in zip(tools, colors):
            v = pooled[side][t]
            bw = (w - pl - 60) * v / vmax
            if bw > 0.5:
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{bw:.1f}" height="28" fill="{color}"><title>{t}: '
                           f'{v:.2f} per run</title></rect>')
                if bw > 26:
                    out.append(f'<text x="{x + bw / 2:.1f}" y="{y + 18}" class="bin">{v:.1f}</text>')
            x += bw
        out.append(f'<text x="{x + 6:.1f}" y="{y + 19}" class="bvl">{sum(pooled[side].values()):.1f}</text>')
    lx = 10
    for t, color in zip(tools, colors):
        out.append(f'<rect x="{lx}" y="{h - 26}" width="10" height="10" rx="2" fill="{color}"/>'
                   f'<text x="{lx + 14}" y="{h - 17}" class="lgd">{t}</text>')
        lx += 22 + 6.4 * len(t)
    return "".join(out) + "</svg>"


# ---------------------------------------------------------------- tables

METRICS = [  # key, label, lower_better (None = neutral)
    ("success_pct", "success %", False), ("part_acc", "parts right %", False),
    ("wall_mean", "wall mean s", True), ("wall_median", "wall median s", True), ("wall_p90", "wall p90 s", True),
    ("timeouts", "timeouts", True), ("requests", "model requests", True),
    ("work_calls", "tool calls", None), ("calls_per_request", "tool calls / request", False),
    ("in_tok_k", "input tok k", True), ("in_per_request_k", "input tok k / request", True),
    ("out_tok_k", "output tok k", True), ("subagents", "sub-agents", None),
]


def scoreboard(m: str) -> str:
    cols = [("success_pct", "success", False), ("part_acc", "parts right", False), ("wall_mean", "wall", True),
            ("requests", "model requests", True), ("work_calls", "tool calls", None),
            ("in_tok_k", "input tokens", True), ("out_tok_k", "output tokens", True)]
    head = "<tr><th>workload</th>" + "".join(f"<th>{c[1]}</th>" for c in cols) + "</tr>"
    body = ""
    for k, label in WL:
        off, on = D["cells"][m][k]["off"], D["cells"][m][k]["on"]
        body += f"<tr><td class='wl'>{esc(label)} <span class='nn'>{off['n']} vs {on['n']} runs</span></td>"
        for key, _, lb in cols:
            if key in ("success_pct", "part_acc"):
                d = on[key] - off[key]
                cls = "flat" if abs(d) < 1 else ("good" if d > 0 else "bad")
                body += f'<td class="hc {cls}">{off[key]}% → {on[key]}%</td>'
            else:
                c = change(on[key], off[key])
                cls = "neutral" if lb is None else tone(c, lb)
                body += (f'<td class="hc {cls}"><b>{fmt_change(c)}</b><span class="raw">{num(off[key])} → '
                         f'{num(on[key])}</span></td>')
        body += "</tr>"
    return (f'<h3>{NAMES[m]}</h3><div class="tw"><table class="score"><thead>{head}</thead>'
            f"<tbody>{body}</tbody></table></div>")


def detail_table(m: str, wls: list[tuple[str, str]]) -> str:
    head = "<tr><th>metric</th>" + "".join(f'<th colspan="3" class="mh">{SHORT_WL[k][0]} {SHORT_WL[k][1]}</th>'
                                          for k, _ in wls) + "</tr><tr><th></th>" + \
        "<th>off</th><th>on</th><th>Δ</th>" * len(wls) + "</tr>"
    body = "<tr><td class='wl'>runs</td>" + "".join(
        f"<td>{D['cells'][m][k]['off']['n']}</td><td>{D['cells'][m][k]['on']['n']}</td><td></td>" for k, _ in wls) + "</tr>"
    for key, label, lb in METRICS:
        body += f"<tr><td class='wl'>{esc(label)}</td>"
        for k, _ in wls:
            off, on = D["cells"][m][k]["off"][key], D["cells"][m][k]["on"][key]
            if key in ("success_pct", "part_acc", "timeouts"):
                diff = on - off
                good = diff < 0 if key == "timeouts" else diff > 0
                d, cls = f"{diff:+g}", ("flat" if diff == 0 else ("good" if good else "bad"))
            else:
                c = change(on, off)
                d, cls = fmt_change(c), ("neutral" if lb is None else tone(c, lb))
            body += (f"<td>{num(off) if isinstance(off, float) else off}</td>"
                     f"<td>{num(on) if isinstance(on, float) else on}</td><td class='hc {cls}'>{d}</td>")
        body += "</tr>"
    return f'<div class="tw"><table class="detail"><thead>{head}</thead><tbody>{body}</tbody></table></div>'


def subagent_table() -> str:
    sub = codemode_tables.data()["subagents"]
    rows = ""
    for m in (SOL, LUNA):
        for k in ("deleg_gather", "deleg_code"):
            off, on = D["cells"][m][k]["off"], D["cells"][m][k]["on"]
            cells = f"<td class='wl'>{NAMES[m]}</td><td class='muted'>{SHORT_WL[k][1]}</td>"
            for key in ("subagents", "parent_requests"):
                cells += f"<td>{off[key]:.1f}</td><td>{on[key]:.1f}</td>"
            so, sn = off["requests"] - off["parent_requests"], on["requests"] - on["parent_requests"]
            cells += f"<td>{so:.1f}</td><td>{sn:.1f}</td>"
            rows += f"<tr>{cells}</tr>"
    per = "".join(
        f"<tr><td class='wl'>{NAMES[m]}</td><td>{sub[m]['off']['in_tok_k']}k</td><td>{sub[m]['fix']['in_tok_k']}k</td>"
        f"<td>{sub[m]['off']['req']}</td><td>{sub[m]['fix']['req']}</td>"
        f"<td>{sub[m]['off']['max_ret']:,}</td><td>{sub[m]['fix']['max_ret']:,}</td></tr>" for m in (SOL, LUNA))
    t1 = ("<tr><th rowspan=2>model</th><th rowspan=2>delegated task</th><th colspan=2 class='mh'>sub-agents per task</th>"
          "<th colspan=2 class='mh'>parent model requests</th><th colspan=2 class='mh'>sub-agent model requests</th></tr>"
          "<tr>" + "<th>off</th><th>on</th>" * 3 + "</tr>")
    t2 = ("<tr><th rowspan=2>model</th><th colspan=2 class='mh'>input tokens per sub-agent session</th>"
          "<th colspan=2 class='mh'>requests per sub-agent session</th><th colspan=2 class='mh'>largest tool return (chars)</th></tr>"
          "<tr>" + "<th>off</th><th>on</th>" * 3 + "</tr>")
    return (f'<div class="tw"><table class="detail"><thead>{t1}</thead><tbody>{rows}</tbody></table></div>'
            f'<div class="tw"><table class="detail"><thead>{t2}</thead><tbody>{per}</tbody></table></div>')


def task_table(m: str) -> str:
    rows = ""
    for t, v in D["tasks"][m].items():
        if "off" not in v or "on" not in v:
            continue
        a, b = v["off"], v["on"]
        wl = TASK_WL.get(t[0]) if not t.startswith(("L_", "D_")) else ("long" if t[0] == "L" else "deleg") + \
            ("_code" if t.endswith("_code") else "_gather")
        cells = f"<td>{esc(t)}</td><td class='muted'>{SHORT_WL[wl][0]} {SHORT_WL[wl][1]}</td>"
        sa, sb = a["correct"] / a["n"], b["correct"] / b["n"]
        cls = "flat" if abs(sa - sb) < 1e-9 else ("good" if sb > sa else "bad")
        cells += f"<td>{a['correct']}/{a['n']}</td><td class='hc {cls}'>{b['correct']}/{b['n']}</td>"
        for key in ("wall", "requests", "in_tok_k"):
            c = change(b[key], a[key])
            cells += f"<td>{num(a[key])}</td><td>{num(b[key])}</td><td class='hc {tone(c)}'>{fmt_change(c)}</td>"
        rows += f"<tr>{cells}</tr>"
    head = ("<tr><th rowspan=2>task</th><th rowspan=2>workload</th><th colspan=2 class='mh'>success</th>"
            "<th colspan=3 class='mh'>wall s</th><th colspan=3 class='mh'>model requests</th>"
            "<th colspan=3 class='mh'>input tok k</th></tr><tr><th>off</th><th>on</th>"
            + "<th>off</th><th>on</th><th>Δ</th>" * 3 + "</tr>")
    return f'<div class="tw"><table class="detail"><thead>{head}</thead><tbody>{rows}</tbody></table></div>'


# ---------------------------------------------------------------- page

def verdict(m: str) -> str:
    o = D["overall"][m]
    items = [("model requests", o["requests"]), ("wall time", o["wall"]), ("input tokens", o["in_tok_k"])]
    lis = "".join(
        f'<div class="vi"><div class="vv {tone(x["median_change_pct"])}">{x["median_change_pct"]:+d}%</div>'
        f'<div class="vl">{esc(lab)}</div><div class="vs">median per task · better on {x["tasks_better"]}/{o["tasks"]} tasks</div></div>'
        for lab, x in items)
    s = o["success"]
    lis += (f'<div class="vi"><div class="vv {"good" if s["on"] > s["off"] else "flat" if s["on"] == s["off"] else "bad"}">'
            f'{s["off"]}→{s["on"]}%</div><div class="vl">success</div><div class="vs">task-balanced, all {o["tasks"]} tasks</div></div>')
    return f'<div class="verdict"><h3>{NAMES[m]}</h3><div class="vg">{lis}</div></div>'


sol_d = D["cells"][SOL]["deleg_gather"], D["cells"][SOL]["deleg_code"]
_cells = [D["cells"][m][k] for m in (SOL, LUNA) for k, _ in WL]
CPR = sorted(c["on"]["calls_per_request"] for c in _cells)
CPR_OFF = sorted(c["off"]["calls_per_request"] for c in _cells)
OVERHEAD = sorted(c["on"]["in_per_request_k"] - c["off"]["in_per_request_k"] for c in _cells)
fan_off = FAN[SOL]["off_invokes_per_response"]
o_sol, o_luna = D["overall"][SOL], D["overall"][LUNA]

CSS = """
:root{--bg:#070b14;--panel:#0e1526;--panel2:#121b31;--line:#1f2a44;--text:#e6edf7;--muted:#93a1bd;--accent:#2dd4bf;--accent2:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 28px}
header{background:radial-gradient(1200px 500px at 10% -10%,#134e4a 0,transparent 60%),radial-gradient(900px 500px at 100% 0,#1e3a8a 0,transparent 55%),var(--bg);border-bottom:1px solid var(--line);padding:64px 0 48px}
.eyebrow{letter-spacing:.18em;text-transform:uppercase;font-size:12px;color:var(--accent);font-weight:700}
h1{font-size:52px;line-height:1.05;margin:14px 0 16px;letter-spacing:-.02em}h1 em{font-style:normal;background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.lede{font-size:19px;color:#c7d2e6;max-width:900px}.meta{margin-top:18px;color:var(--muted);font-size:14px;display:flex;gap:22px;flex-wrap:wrap}.meta b{color:var(--text)}
.verdicts{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:34px}
.verdict{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:18px;padding:18px 20px}
.verdict h3{margin:0 0 12px;font-size:18px}.vg{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.vv{font-size:26px;font-weight:800;letter-spacing:-.01em}.vl{font-weight:600;font-size:14px}.vs{color:var(--muted);font-size:11.5px;line-height:1.35;margin-top:2px}
.vv.good{color:#5eead4}.vv.bad{color:#fca5a5}.vv.flat{color:#e2e8f0}
section{padding:48px 0 4px}h2{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}h2 small{display:block;font-size:14px;color:var(--muted);font-weight:500;margin-top:6px}
p,li{color:#cfd8ea}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 16px 8px}
.colhead{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:14px 0 6px;color:var(--muted);font-weight:700;font-size:13px;letter-spacing:.08em;text-transform:uppercase}
.chart{width:100%;height:auto;display:block}.ct{fill:var(--text);font-weight:700;font-size:14px}.hint{fill:var(--muted);font-size:11px;text-anchor:end}
.bv{fill:var(--text);font-size:11px;font-weight:700;text-anchor:middle}.bvl{fill:var(--text);font-size:12px;font-weight:800}.bin{fill:#06121f;font-size:11px;font-weight:800;text-anchor:middle}
.gl{fill:var(--muted);font-size:11.5px;text-anchor:middle}.sl{fill:#cbd5e1;font-size:12px}.lgd{fill:var(--muted);font-size:11px}
.axis{stroke:var(--line);stroke-width:1.5}.grid{stroke:#18223a}.sep{stroke:#121a2e}
.d{font-size:12px;font-weight:800;text-anchor:middle}.d.good{fill:#5eead4}.d.bad{fill:#fca5a5}.d.flat{fill:#cbd5e1}
.legend{display:flex;gap:18px;margin:8px 0 0;color:var(--muted);font-size:13px}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:7px;vertical-align:-1px}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:14px;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th{background:var(--panel2);color:var(--muted);font-weight:600;padding:7px 8px;white-space:nowrap;border-bottom:1px solid var(--line);text-align:center}th.mh{color:#e2e8f0;border-left:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid #16203a;white-space:nowrap;text-align:center}td.wl{text-align:left;color:#e2e8f0;font-weight:600}td.muted{color:var(--muted)}
td.hc{font-weight:700}td.good{background:rgba(45,212,191,.16);color:#5eead4}td.bad{background:rgba(248,113,113,.16);color:#fca5a5}td.flat{color:#cbd5e1}td.neutral{color:#93c5fd}
table.score td{font-size:14px;padding:9px 8px}table.score td b{display:block;font-size:15px}.raw{display:block;font-size:11px;font-weight:500;color:#94a3b8}.nn{display:block;font-size:11px;font-weight:500;color:var(--muted)}h3{margin:22px 0 4px}
.callout{border-left:4px solid var(--accent2);background:var(--panel);padding:13px 18px;border-radius:10px;margin:14px 0;color:#cfd8ea}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;background:#111a2e;border:1px solid var(--line);padding:1px 6px;border-radius:6px}
footer{margin:56px 0 0;padding:26px 0 44px;border-top:1px solid var(--line);color:var(--muted);font-size:13.5px}
@media (max-width:900px){.verdicts,.grid2,.colhead{grid-template-columns:1fr}.vg{grid-template-columns:1fr 1fr}h1{font-size:38px}}
"""

legend = (f'<div class="legend"><span><i style="background:{OFF}"></i>code mode off</span>'
          f'<span><i style="background:{ON}"></i>code mode on</span></div>')


def two(fn) -> str:  # noqa: ANN001
    return (f'<div class="colhead"><div>{NAMES[SOL]}</div><div>{NAMES[LUNA]}</div></div>'
            f'<div class="grid2"><div class="card">{fn(SOL)}</div><div class="card">{fn(LUNA)}</div></div>')


n_runs = sum(c[s]["n"] for m in (SOL, LUNA) for c in D["cells"][m].values() for s in ("off", "on"))
body = f"""
<header><div class="wrap">
<div class="eyebrow">Code Puppy · code mode off vs on</div>
<h1>Code mode: <em>on vs off</em>.</h1>
<p class="lede">Same agent, same 30 tasks, same models. <b>Off</b> is plain tool calling. <b>On</b> is code mode as it
ships on Code Puppy main today (after #1013 and #1014): the model writes Python that calls tools inside a
<code>run_code</code> sandbox. Short tasks, long tasks, and long tasks delegated to sub-agents.</p>
<div class="meta"><span><b>{n_runs}</b> runs compared</span><span><b>30</b> tasks</span><span>gpt-6.1-sol and gpt-6-luna</span><span>2026-10-11</span></div>
<div class="verdicts">{verdict(SOL)}{verdict(LUNA)}</div>
</div></header>
<main class="wrap">

<section><h2>Scoreboard<small>Change from off to on per workload. Green is better, red is worse, blue is neutral (more tool calls is more work done per request, not a cost). Each cell shows the change and the raw off → on values.</small></h2>
{scoreboard(SOL)}{scoreboard(LUNA)}
<div class="callout"><b>Read it this way:</b> code mode cuts model round trips in every workload, because each request does
{CPR[0]:.1f} to {CPR[-1]:.1f} tool calls instead of {CPR_OFF[0]:.1f} to {CPR_OFF[-1]:.1f}. Whether that turns into less wall time and
fewer tokens depends on the model and the workload: a code-mode request also carries {OVERHEAD[0]:.1f}k to
{OVERHEAD[-1]:.1f}k more input tokens than a plain one (the run_code description with every sandbox function signature, plus larger snippet results), which short tasks
rarely earn back. Across all 30 tasks, sol gets faster on
{o_sol["wall"]["tasks_better"]} and luna on {o_luna["wall"]["tasks_better"]}.</div>
</section>

<section><h2>Wall time<small>Mean per workload; Δ under each pair</small></h2>{legend}
{two(lambda m: pair_bars("Wall time per task (s)", m, "wall_mean", "{:.0f}"))}
{two(strip)}
<p>White ticks mark medians. Delegated runs are where the distributions separate: sol's off runs spread out to
the 900s timeout while its on runs stay between {min(D["cells"][SOL]["deleg_gather"]["on"]["walls"] + D["cells"][SOL]["deleg_code"]["on"]["walls"]):.0f}s and
{max(D["cells"][SOL]["deleg_gather"]["on"]["walls"] + D["cells"][SOL]["deleg_code"]["on"]["walls"]):.0f}s.</p>
</section>

<section><h2>Round trips and work per request</h2>{legend}
{two(lambda m: pair_bars("Model requests per task (incl. sub-agents)", m, "requests", "{:.1f}"))}
{two(lambda m: pair_bars("Tool calls per model request", m, "calls_per_request", "{:.2f}", lower_better=False))}
{two(mix_bars)}
<p>Tool calls per run pooled over all workloads, parent agent only. With code mode on, luna reads far more
files per run ({sum(D["cells"][LUNA][k]["on"]["tool_mix"].get("read_file", 0) * D["cells"][LUNA][k]["on"]["n"] for k, _ in WL) / sum(D["cells"][LUNA][k]["on"]["n"] for k, _ in WL):.1f} vs
{sum(D["cells"][LUNA][k]["off"]["tool_mix"].get("read_file", 0) * D["cells"][LUNA][k]["off"]["n"] for k, _ in WL) / sum(D["cells"][LUNA][k]["off"]["n"] for k, _ in WL):.1f}): once reads are cheap, it casts a wide net.</p>
</section>

<section><h2>Tokens</h2>{legend}
{two(lambda m: pair_bars("Input tokens per task (k, incl. sub-agents)", m, "in_tok_k", "{:.0f}"))}
{two(lambda m: pair_bars("Input tokens per model request (k)", m, "in_per_request_k", "{:.1f}"))}
{two(lambda m: pair_bars("Output tokens per task (k)", m, "out_tok_k", "{:.2f}"))}
</section>

<section><h2>Accuracy</h2>{legend}
{two(lambda m: pair_bars("Success rate (%)", m, "success_pct", "{:.0f}", lower_better=False))}
{two(lambda m: pair_bars("Answer parts right (%)", m, "part_acc", "{:.0f}", lower_better=False))}
<p>Long and delegated tasks have 15 to 16 answer fields or four hidden test files, and success needs every one
right, so "parts right" is the steadier signal. Cells there hold 4 to 6 runs: one run is 17 to 25 points.</p>
</section>

<section><h2>Sub-agents</h2>
<div class="callout">With code mode on, the parent launches all four sub-agents from a single <code>run_code</code>
(sol {FAN[SOL]["new_invokes_per_run_code"].get(4, 0)} of 10 delegated runs, luna {FAN[LUNA]["new_invokes_per_run_code"].get(4, 0)} of 10). With it off, sol issued
{fan_off.get(1, 0)} model responses that started a single sub-agent and {fan_off.get(4, 0)} that started all four: delegation
often goes one sub-agent per turn. It shows up in sol's delegated wall time:
{fmt_change(change(sol_d[0]["on"]["wall_mean"], sol_d[0]["off"]["wall_mean"]))} (read and answer) and
{fmt_change(change(sol_d[1]["on"]["wall_mean"], sol_d[1]["off"]["wall_mean"]))} (multi-fix).</div>
{subagent_table()}
</section>

<section><h2>Every metric, every workload</h2>
<h3>{NAMES[SOL]}</h3>{detail_table(SOL, WL[:3])}{detail_table(SOL, WL[3:])}
<h3>{NAMES[LUNA]}</h3>{detail_table(LUNA, WL[:3])}{detail_table(LUNA, WL[3:])}
</section>

<section><h2>Every task</h2><small class="muted">Mean per task; Δ is on vs off.</small>
<h3>{NAMES[SOL]}</h3>{task_table(SOL)}
<h3>{NAMES[LUNA]}</h3>{task_table(LUNA)}
</section>

<section><h2>Method and caveats</h2><ul>
<li><b>Off</b> is code-puppy main with <code>enable_speculative_code_mode = false</code>. <b>On</b> is main after #1013
(short and long tasks) and after #1014 (delegated tasks; #1014 only changes sub-agents).</li>
<li>Headless <code>code-puppy -p</code>, one fresh working copy and private config / cache / state / data per run;
sub-agents pinned to the run's model. Short tasks are the original A/B's 20 tasks and graders; long tasks are
composed from them (validated answer keys and hidden tests).</li>
<li>Runs per side: short tasks 40 off / 80 on per model; long 4 to 6 per workload per side. Short off and delegated
on ran as separate batches, so time-of-day effects are not controlled for those cells.</li>
<li>Tokens and requests include every sub-agent. Wall time includes timed-out runs at 900s.</li>
<li>How code mode got here (prompt iterations, bugs fixed): <code>docs/CODEMODE_FOLLOWUP.md</code>.</li>
</ul></section>
<footer>Generated by <code>scripts/codemode_report.py</code> from <code>runs/codemode/*/records.jsonl</code>; every number is computed from the run records.</footer>
</main>
"""

page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
        f'content="width=device-width,initial-scale=1"><title>Code mode: on vs off</title><style>{CSS}</style></head>'
        f"<body>{body}</body></html>")
out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_followup.html"
out.write_text(page)
print(out, len(page))

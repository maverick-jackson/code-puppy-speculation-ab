#!/usr/bin/env python3
"""Render docs/results/codemode_summary.html: code mode off vs on per model, in plain numbers.

Tabs: "All models" (one off / on / change block per model) and one tab per model (its block plus
every task). Values are per-task averages with each of the 30 tasks counted once; "total" is one
pass through the suite (the sum of each task's average); every change is computed from the two
numbers shown. Data: codemode_tables.today(), each model's most current off-vs-on comparison.
Usage: python3 scripts/codemode_summary.py [OUT.html]
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codemode_tables  # noqa: E402

T = codemode_tables.today()
SPEND = codemode_tables.benchmark_spend()
NOISE_PCT = 5  # changes within +-5% read as "about the same" (2 runs per task per side)
NOISE_PTS = 3  # accuracy within +-3 points reads as "same"
WORKLOAD = {"g": "Short read+answer", "h": "Short read+answer", "r": "Short read+answer", "c": "Short bug fix",
            "f": "Short bug fix", "L": "Long", "D": "Delegated"}


def name(m: str) -> str:
    return m.replace("codex-", "").replace("claude-code-", "").replace("-5-5", "-5.5")


def slug(m: str) -> str:
    return name(m).replace(".", "-")


def money(v: float) -> str:
    return f"${v:,.2f}" if v >= 0.1 else f"${v:.3f}" if v >= 0.01 else f"${v:.4f}"


def signed_money(v: float) -> str:
    return ("-" if v < 0 else "+") + money(abs(v))


def esc(s: object) -> str:
    return html.escape(str(s))


def change(on: float, off: float, better: str, worse: str) -> tuple[str, str]:
    pct = round((on - off) / off * 100) if off else 0
    if abs(pct) < NOISE_PCT:
        return "about the same", "flat"
    return (f"{abs(pct)}% {better}", "good") if pct < 0 else (f"{pct}% {worse}", "bad")


def short_change(on: float, off: float) -> tuple[str, str]:
    pct = round((on - off) / off * 100) if off else 0
    return f"{pct:+d}%", ("flat" if abs(pct) < NOISE_PCT else "good" if pct < 0 else "bad")


def acc_change(off: int, on: int) -> tuple[str, str]:
    d = on - off
    if abs(d) <= NOISE_PTS:
        return "same", "flat"
    return (f"{d} points better", "good") if d > 0 else (f"{-d} points worse", "bad")


def verdict(cost_tone: str, speed_tone: str, acc_tone: str) -> tuple[str, str]:
    if acc_tone == "bad":
        return "Leave it off: less accurate", "bad"
    if cost_tone == "good" and speed_tone != "bad":
        return "Turn it on", "good"
    if cost_tone == "bad" and speed_tone == "bad":
        return "Leave it off", "bad"
    if cost_tone == "bad" and speed_tone == "good":
        return "Your call: faster, but costs more", "mixed"
    if cost_tone == "bad":
        return "Leave it off: costs more", "bad"
    if speed_tone == "good":
        return "Turn it on", "good"
    if speed_tone == "bad":
        return "Leave it off: slower", "bad"
    return "Either way: about even", "flat"


models = []
for m, d in T.items():
    o = d["overall"]
    x = dict(m=m, d=d, current=d["current"],
             cost=(o["cost"]["off_mean"], o["cost"]["on_mean"]), total=(d["suite_cost"]["off"], d["suite_cost"]["on"]),
             speed=(o["wall"]["off_mean"], o["wall"]["on_mean"]), acc=(o["success"]["off"], o["success"]["on"]))
    x["cost_c"] = change(x["cost"][1], x["cost"][0], "cheaper", "more expensive")
    x["speed_c"] = change(x["speed"][1], x["speed"][0], "faster", "slower")
    x["acc_c"] = acc_change(*x["acc"])
    x["verdict"] = verdict(x["cost_c"][1], x["speed_c"][1], x["acc_c"][1])
    models.append(x)
rank = {"good": 0, "mixed": 1, "flat": 2, "bad": 3}
models.sort(key=lambda x: (rank[x["verdict"][1]], x["cost"][1] / x["cost"][0]))


def block(x: dict) -> str:
    """One model: off / on / change rows."""
    label = esc(name(x["m"])) + ("" if x["current"] else '<span class="note">measured before PR #1015</span>')
    v, vt = x["verdict"]
    rows = f'<tbody class="model"><tr><td rowspan="3" class="name">{label}<div class="verdict {vt}">{esc(v)}</div></td>'
    for i, setting in ((0, "Code mode off"), (1, "Code mode on")):
        rows += ("" if i == 0 else "<tr>") + (
            f'<td class="setting">{setting}</td><td>{money(x["cost"][i])}</td><td>{money(x["total"][i])}</td>'
            f'<td>{x["acc"][i]}%</td><td>{x["speed"][i]:.0f} s</td></tr>')
    tc = short_change(x["total"][1], x["total"][0])
    rows += (f'<tr class="delta"><td class="setting">With code mode</td><td class="{x["cost_c"][1]}">{esc(x["cost_c"][0])}</td>'
             f'<td class="{tc[1]}">{esc(signed_money(x["total"][1] - x["total"][0]))} ({tc[0]})</td>'
             f'<td class="{x["acc_c"][1]}">{esc(x["acc_c"][0])}</td><td class="{x["speed_c"][1]}">{esc(x["speed_c"][0])}</td></tr></tbody>')
    return rows


HEAD = ('<thead><tr><th>Model</th><th>Setting</th><th>Cost per task</th><th>Total, all 30 tasks</th>'
        '<th>Accuracy</th><th>Speed (time per task)</th></tr></thead>')


def task_table(x: dict) -> str:
    rows = ""
    for t, v in x["d"]["tasks"].items():
        a, b = v["off"], v["on"]
        sa, sb = a["correct"] / a["n"], b["correct"] / b["n"]
        scls = "flat" if abs(sa - sb) < 1e-9 else ("good" if sb > sa else "bad")
        cells = (f'<td class="task">{esc(t)}</td><td class="muted">{WORKLOAD.get(t[0], "")}</td>'
                 f'<td>{a["correct"]}/{a["n"]}</td><td class="{scls} b">{b["correct"]}/{b["n"]}</td>')
        for key, fmt in (("cost", money), ("wall", lambda s: f"{s:.1f} s"), ("requests", lambda s: f"{s:.1f}")):
            txt, cls = short_change(b[key], a[key])
            cells += f'<td>{fmt(a[key])}</td><td>{fmt(b[key])}</td><td class="{cls} b">{txt}</td>'
        rows += f"<tr>{cells}</tr>"
    head = ('<thead><tr><th rowspan="2">Task</th><th rowspan="2">Kind</th><th colspan="2">Accuracy</th>'
            '<th colspan="3">Cost</th><th colspan="3">Speed (time)</th><th colspan="3">Model requests</th></tr>'
            '<tr class="sub"><th>off</th><th>on</th>' + "<th>off</th><th>on</th><th>change</th>" * 3 + "</tr></thead>")
    return f'<div class="scroll"><table class="tasks">{head}<tbody>{rows}</tbody></table></div>'


tabs = '<button class="tab active" data-tab="all">All models</button>' + "".join(
    f'<button class="tab" data-tab="{slug(x["m"])}">{esc(name(x["m"]))}</button>' for x in models)
panels = f'<div class="panel active" id="all"><table class="summary">{HEAD}{"".join(block(x) for x in models)}</table></div>'
for x in models:
    panels += (f'<div class="panel" id="{slug(x["m"])}"><table class="summary">{HEAD}{block(x)}</table>'
               f'<h3>Every task</h3><p class="hint">{x["d"]["runs"]["off"]} runs with code mode off and {x["d"]["runs"]["on"]} with it '
               f'on (at least 2 per task per setting); values are the average per task.</p>{task_table(x)}</div>')

total_spend = sum(SPEND.values())
CSS = """
*{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#1c2330;font:17px/1.55 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:44px 28px 64px}
h1{font-size:34px;margin:0 0 8px;letter-spacing:-.01em}.sub{color:#5b6576;margin:0 0 22px}h3{margin:30px 0 4px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.tab{font:inherit;font-size:15px;font-weight:600;border:1px solid #d9dee8;background:#fff;color:#3d4757;padding:8px 14px;border-radius:999px;cursor:pointer}
.tab.active{background:#1c2330;color:#fff;border-color:#1c2330}
.panel{display:none}.panel.active{display:block}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid #e3e7ef;border-radius:14px;overflow:hidden}
th{background:#eef1f6;color:#3d4757;font-size:14px;text-align:left;padding:11px 14px;font-weight:600}
td{padding:10px 14px;border-top:1px solid #edf0f5;font-variant-numeric:tabular-nums}
table.summary td{font-size:17px}tbody.model tr:first-child td{border-top:2px solid #dfe4ec}
td.name{font-weight:700;font-size:18px;vertical-align:top;width:230px;padding-top:13px}td.setting{color:#5b6576;width:160px}
tr.delta td{font-weight:600;font-size:15px;background:#fafbfd}
.good{color:#0f7a4f}.bad{color:#b4322c}.flat{color:#5b6576}.mixed{color:#9a6400}.b{font-weight:700}.muted{color:#8a93a3}
.verdict{display:inline-block;margin-top:8px;font-size:13px;font-weight:700;padding:4px 10px;border-radius:999px;background:#eef1f6}
.verdict.good{background:#e3f6ec}.verdict.bad{background:#fbe6e4}.verdict.mixed{background:#fdf1dc}
.note{display:block;font-size:12px;font-weight:500;color:#8a93a3;margin-top:2px}
.scroll{overflow-x:auto}table.tasks th,table.tasks td{text-align:center;font-size:14px;padding:8px 10px;white-space:nowrap}
table.tasks td.task{text-align:left;font-weight:600}table.tasks tr.sub th{font-size:12px;color:#5b6576;background:#f4f6fa}
.hint{color:#5b6576;font-size:14px;margin:0 0 10px}.foot{color:#5b6576;font-size:14px;margin-top:24px}.foot a{color:#2556c9}
"""
JS = """
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === b));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === b.dataset.tab));
}));
"""
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Code mode: off vs on</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Code mode: off vs on</h1>
<p class="sub">Code Puppy on 30 coding tasks (short questions and bug fixes, long multi-part tasks, and tasks split across
sub-agents). Pick a model for its per-task numbers.</p>
<div class="tabs">{tabs}</div>
{panels}
<p class="foot"><b>How to read it.</b> Cost is what the tokens would cost at API list prices (the runs used subscriptions).
"Total, all 30 tasks" is one pass through the whole suite. Accuracy is the share of tasks fully right. Speed is the average
time to finish a task. Changes within 5% (or 3 accuracy points) are shown as "about the same": each task ran twice per
setting, so smaller differences are noise. Code mode is measured as it is on main today (after PR #1015) unless marked
otherwise; speculation was on in every code-mode run. The whole benchmark ({sum(1 for _ in SPEND)} batches) cost
{money(total_spend)} at API prices. Full report: <a href="codemode_followup.html">charts, method and every metric</a>.</p>
</div><script>{JS}</script></body></html>"""

out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_summary.html"
out.write_text(page)
print(out)

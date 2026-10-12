#!/usr/bin/env python3
"""Render docs/results/codemode_summary.html: code mode off vs on per model, in plain numbers.

One row per model and setting (off / on): cost per task, accuracy, speed (average time per task).
Every value is a per-task average with each of the 30 tasks counted once, and every change is
computed from the two numbers shown next to it. Data: codemode_tables.today(), each model's most
current off-vs-on comparison. The full report (codemode_followup.html) is the appendix.
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
NOISE_PCT = 5  # changes within +-5% read as "about the same" (2 runs per task per side)
NOISE_PTS = 3  # accuracy within +-3 points reads as "same"


def name(m: str) -> str:
    return m.replace("codex-", "").replace("claude-code-", "").replace("-5-5", "-5.5")


def money(v: float) -> str:
    return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}" if v >= 0.01 else f"${v:.4f}"


def change(on: float, off: float, better: str, worse: str) -> tuple[str, str]:
    pct = round((on - off) / off * 100) if off else 0
    if abs(pct) < NOISE_PCT:
        return "about the same", "flat"
    return (f"{abs(pct)}% {better}", "good") if pct < 0 else (f"{pct}% {worse}", "bad")


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


def esc(s: object) -> str:
    return html.escape(str(s))


models = []
for m, d in T.items():
    o = d["overall"]
    cost_off, cost_on = o["cost"]["off_mean"], o["cost"]["on_mean"]
    time_off, time_on = o["wall"]["off_mean"], o["wall"]["on_mean"]
    acc_off, acc_on = o["success"]["off"], o["success"]["on"]
    c = change(cost_on, cost_off, "cheaper", "more expensive")
    s = change(time_on, time_off, "faster", "slower")
    a = acc_change(acc_off, acc_on)
    models.append(dict(m=m, current=d["current"], cost=(cost_off, cost_on, c), speed=(time_off, time_on, s),
                       acc=(acc_off, acc_on, a), verdict=verdict(c[1], s[1], a[1])))
rank = {"good": 0, "mixed": 1, "flat": 2, "bad": 3}
models.sort(key=lambda x: (rank[x["verdict"][1]], x["cost"][1] / x["cost"][0]))

rows = ""
for x in models:
    label = esc(name(x["m"])) + ("" if x["current"] else '<span class="note">measured before PR #1015</span>')
    v, vt = x["verdict"]
    rows += f'<tbody class="model"><tr><td rowspan="3" class="name">{label}<div class="verdict {vt}">{esc(v)}</div></td>'
    rows += (f'<td class="setting">Code mode off</td><td>{money(x["cost"][0])}</td><td>{x["acc"][0]}%</td>'
             f'<td>{x["speed"][0]:.0f} s</td></tr>')
    rows += (f'<tr><td class="setting">Code mode on</td><td>{money(x["cost"][1])}</td><td>{x["acc"][1]}%</td>'
             f'<td>{x["speed"][1]:.0f} s</td></tr>')
    rows += (f'<tr class="delta"><td class="setting">With code mode</td><td class="{x["cost"][2][1]}">{esc(x["cost"][2][0])}</td>'
             f'<td class="{x["acc"][2][1]}">{esc(x["acc"][2][0])}</td><td class="{x["speed"][2][1]}">{esc(x["speed"][2][0])}</td></tr></tbody>')

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#1c2330;font:17px/1.55 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:48px 28px 64px}
h1{font-size:34px;margin:0 0 8px;letter-spacing:-.01em}.sub{color:#5b6576;margin:0 0 28px}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid #e3e7ef;border-radius:14px;overflow:hidden}
th{background:#eef1f6;color:#3d4757;font-size:14px;text-align:left;padding:12px 16px;font-weight:600}
td{padding:11px 16px;border-top:1px solid #edf0f5;font-variant-numeric:tabular-nums;font-size:17px}
tbody.model tr:first-child td{border-top:2px solid #dfe4ec}
td.name{font-weight:700;font-size:18px;vertical-align:top;width:250px;padding-top:14px}
td.setting{color:#5b6576;width:170px}
tr.delta td{font-weight:600;font-size:15px;background:#fafbfd}
.good{color:#0f7a4f}.bad{color:#b4322c}.flat{color:#5b6576}.mixed{color:#9a6400}
.verdict{display:inline-block;margin-top:8px;font-size:13px;font-weight:700;padding:4px 10px;border-radius:999px;background:#eef1f6}
.verdict.good{background:#e3f6ec}.verdict.bad{background:#fbe6e4}.verdict.mixed{background:#fdf1dc}.verdict.flat{background:#eef1f6}
.note{display:block;font-size:12px;font-weight:500;color:#8a93a3;margin-top:2px}
.foot{color:#5b6576;font-size:14px;margin-top:22px}.foot a{color:#2556c9}
"""

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Code mode: off vs on</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Code mode: off vs on</h1>
<p class="sub">Code Puppy on 30 coding tasks (short questions and bug fixes, long multi-part tasks, and tasks split across
sub-agents). Each number is the average per task.</p>
<table><thead><tr><th>Model</th><th>Setting</th><th>Cost per task</th><th>Accuracy</th><th>Speed (time per task)</th></tr></thead>
{rows}</table>
<p class="foot"><b>How to read it.</b> Cost is what the tokens would cost at API list prices (the runs used subscriptions).
Accuracy is the share of tasks fully right. Speed is the average time to finish a task. Changes within 5% (or 3 accuracy
points) are shown as "about the same": each task ran twice per setting, so smaller differences are noise.
Code mode is measured as it is on main today (after PR #1015) unless marked otherwise.
Full details, per-task numbers and method: <a href="codemode_followup.html">full report</a>.</p>
</div></body></html>"""

out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_summary.html"
out.write_text(page)
print(out)

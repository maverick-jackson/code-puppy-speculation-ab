#!/usr/bin/env python3
"""Render docs/results/codemode_final.html: code mode off vs on, today (#1015), per model.

One row per model, three diverging-bar panels (cost, speed, accuracy). Each bar runs from code mode
off (centre line) to code mode on, both on today's build; green is better, red worse, grey within
noise. Same numbers as the summary page (codemode_tables.today()).
Static SVG, no JavaScript.
Usage: python3 scripts/codemode_final.py [OUT.html]
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codemode_tables  # noqa: E402

NOISE = {"cost": 5, "time": 5, "acc": 3}
PANELS = [  # key, title, unit, lower is better, better word, worse word
    ("cost", "Cost per task", "%", True, "cheaper", "more expensive"),
    ("time", "Speed (time per task)", "%", True, "faster", "slower"),
    ("acc", "Accuracy", " pts", False, "more accurate", "less accurate"),
]
def _row(d: dict) -> dict:
    """Code mode on vs off for one model; cost is None for models without an API list price."""
    o = d["overall"]
    c, w, s = o["cost"], o["wall"], o["success"]
    return {"cost": round(100 * (c["on_mean"] / c["off_mean"] - 1), 1) if d["priced"] else None,
            "time": round(100 * (w["on_mean"] / w["off_mean"] - 1), 1),
            "acc": round(s["on"] - s["off"], 1),
            "abs": {"cost": c["on_mean"], "off_cost": c["off_mean"], "time": w["on_mean"], "off_time": w["off_mean"],
                    "acc": s["on"], "off_acc": s["off"], "runs": d["runs"]["on"]}}


ROWS = sorted(((codemode_tables.display_name(m), _row(d)) for m, d in codemode_tables.today().items()),
              key=lambda r: (r[1]["cost"] is None, r[1]["cost"] or 0))


def money(v: float) -> str:
    return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}" if v >= 0.01 else f"${v:.4f}"


def raw(key: str, a: dict) -> str:
    if key == "cost":
        return f"{money(a['off_cost'])} → {money(a['cost'])}"
    if key == "time":
        return f"{a['off_time']:.0f} s → {a['time']:.0f} s"
    return f"{a['off_acc']:.0f}% → {a['acc']:.0f}%"


def tone(key: str, v: float, lower_better: bool) -> str:
    # Accuracy compares whole points, as the summary page does (98% -> 95% is "same").
    if (round(abs(v)) <= NOISE[key]) if key == "acc" else (abs(v) < NOISE[key]):
        return "flat"
    return "good" if (v < 0) == lower_better else "bad"


NAME_W, PANEL_W, ROW_H, TOP, PAD = 160, 320, 64, 58, 46
SVG_W = NAME_W + PANEL_W * len(PANELS)
SVG_H = TOP + ROW_H * len(ROWS) + 6


def panel(i: int, key: str, title: str, unit: str, lower_better: bool, better: str, worse: str) -> str:
    """One metric panel, drawn into the shared SVG at column i."""
    x_left = NAME_W + i * PANEL_W
    cx = x_left + PANEL_W / 2
    span = max(20.0, *(abs(r[1][key]) for r in ROWS if r[1][key] is not None))
    x = lambda v: cx + v / span * (PANEL_W / 2 - PAD)  # noqa: E731  (PAD leaves room for the value label)
    left, right = (better, worse) if lower_better else (worse, better)
    lt, rt = ("good", "bad") if lower_better else ("bad", "good")
    out = [f'<text x="{cx}" y="18" class="pt" text-anchor="middle">{html.escape(title)}</text>',
           f'<text x="{x_left + 14}" y="40" class="dir {lt}">← {left}</text>',
           f'<text x="{x_left + PANEL_W - 14}" y="40" class="dir {rt}" text-anchor="end">{right} →</text>',
           f'<rect x="{x(-NOISE[key])}" y="{TOP - 6}" width="{x(NOISE[key]) - x(-NOISE[key])}" height="{SVG_H - TOP}" class="noise"/>',
           f'<line x1="{cx}" x2="{cx}" y1="{TOP - 6}" y2="{SVG_H}" class="zero"/>']
    for r, (_, vals) in enumerate(ROWS):
        v, y = vals[key], TOP + r * ROW_H + 6
        if v is None:
            out.append(f'<text x="{cx}" y="{y + 16}" class="raw" text-anchor="middle">n/a: no API list price</text>')
            continue
        t = tone(key, v, lower_better)
        x0, x1 = sorted((cx, x(v)))
        out.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(x1 - x0, 2):.1f}" height="22" rx="4" class="bar {t}"/>')
        label = f"{v:+.0f}{unit}" if round(abs(v)) else f"0{unit}"
        lx, anchor = (x(v) + 7, "start") if v >= 0 else (x(v) - 7, "end")
        out.append(f'<text x="{lx:.1f}" y="{y + 16}" class="val {t}" text-anchor="{anchor}">{label}</text>')
        out.append(f'<text x="{cx}" y="{y + 42}" class="raw" text-anchor="middle">{html.escape(raw(key, vals["abs"]))}</text>')
    return "".join(out)


def chart() -> str:
    rows = "".join(f'<text x="8" y="{TOP + r * ROW_H + 23}" class="name">{html.escape(name)}</text>'
                   + (f'<line x1="0" x2="{SVG_W}" y1="{TOP + r * ROW_H - 4}" y2="{TOP + r * ROW_H - 4}" class="sep"/>' if r else "")
                   for r, (name, _) in enumerate(ROWS))
    panels = "".join(panel(i, *spec) for i, spec in enumerate(PANELS))
    return f'<svg viewBox="0 0 {SVG_W} {SVG_H}" role="img" aria-label="Code mode off vs on today">{rows}{panels}</svg>'


def count(key: str, lower_better: bool, want: str) -> int:
    return sum(r[1][key] is not None and tone(key, r[1][key], lower_better) == want for r in ROWS)


n = len(ROWS)
n_priced = sum(r[1]["cost"] is not None for r in ROWS)
cheaper, pricier = count("cost", True, "good"), count("cost", True, "bad")
faster, slower = count("time", True, "good"), count("time", True, "bad")
acc_moves = n - count("acc", False, "flat")
headline = (f"With code mode on, {cheaper} of {n_priced} priced models are cheaper and {faster} of {n} are faster; "
            + (f"{pricier} cost more" if pricier else "none costs more")
            + (f", {slower} {'is' if slower == 1 else 'are'} slower" if slower else "")
            + ". Accuracy " + ("stays within noise on every model." if acc_moves == 0 else f"moves beyond noise on {acc_moves}."))

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#1c2330;font:16px/1.5 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:40px 28px 56px}h1{font-size:32px;margin:0 0 6px}.sub{color:#5b6576;margin:0 0 6px}
.headline{font-size:19px;font-weight:600;margin:14px 0 20px}
.card{background:#fff;border:1px solid #e3e7ef;border-radius:14px;padding:16px 14px}
.name{font-weight:700;font-size:15px;fill:#1c2330}.sep{stroke:#f0f2f6}
svg{width:100%;height:auto;display:block}.pt{font-size:15px;font-weight:700;fill:#1c2330}.dir{font-size:11.5px;font-weight:600}
.noise{fill:#f1f3f7}.zero{stroke:#1c2330;stroke-width:1.5}
.bar.good{fill:#22a06b}.bar.bad{fill:#e5534b}.bar.flat{fill:#b6bdc9}
.val{font-size:14px;font-weight:700}.good{fill:#0f7a4f}.bad{fill:#b4322c}.flat{fill:#6b7484}.raw{font-size:11.5px;fill:#6b7484;paint-order:stroke;stroke:#fff;stroke-width:4px}
.foot{color:#6b7484;font-size:13px;margin-top:14px}.foot a{color:#2556c9}
"""
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Code mode today: off vs on</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Code mode today: off vs on</h1>
<p class="sub">Code Puppy as merged (with #1015), 30 coding tasks per model. Each bar starts at code mode off (the centre line)
and ends where code mode on lands.</p>
<p class="headline">{html.escape(headline)}</p>
<div class="card">{chart()}</div>
<p class="foot">Both sides measured on the same build, shuffled together, averaged over all 30 tasks with each task counted once
(60 to 120 runs per side). Cost is API list price; glm53 and qwen3.8-27b are self-hosted (vLLM), glm53 priced at
Zhipu's list price for GLM-5.3, qwen3.8-27b has none. Bars inside the grey band (within 5%, or 3 accuracy points) are noise.
How we got here: <a href="codemode_journey.html">journey</a>; per-task tables: <a href="codemode_summary.html">summary</a>;
everything else: <a href="codemode_followup.html">full report</a>.</p>
</div></body></html>"""

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_final.html"
    out.write_text(page)
    print(out)
    print(headline)
    for name, v in ROWS:
        cost = "  n/a " if v["cost"] is None else f"{v['cost']:+6.1f}"
        print(f"{name:18} cost {cost}%  time {v['time']:+6.1f}%  acc {v['acc']:+5.1f}  runs {v['abs']['runs']}")

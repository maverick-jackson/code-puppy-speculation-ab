#!/usr/bin/env python3
"""Render docs/results/codemode_journey.html: how code mode's premium moved, milestone by milestone.

A line chart per model: x = milestones in order (first ship, #1013 + #1014, hill-climb v1..v3, #1015
today), y = code mode vs code mode off on the same build (cost or time in %, accuracy in points).
Zero is break-even. Each point is a task-balanced average over all 30 tasks (each task counts once).
Rendered client-side from embedded JSON so the metric toggle needs no reload.
Usage: python3 scripts/codemode_journey.py [OUT.html]
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codemode_tables as T  # noqa: E402

N_TASKS = 30


def pick(batch: str, model: str, *variants: str) -> list[dict]:
    return [r for r in T.records(batch) if r["model"] == model and r["variant"] in variants]


def point(rs: list[dict]) -> dict | None:
    """Task-balanced cost / time / accuracy; None unless all 30 tasks are covered."""
    pt = T._per_task(rs)
    if len(pt) < N_TASKS:
        return None
    return {"cost": round(st.mean(v["cost"] for v in pt.values()), 5),
            "time": round(st.mean(v["wall"] for v in pt.values()), 1),
            "acc": round(100 * st.mean(v["correct"] / v["n"] for v in pt.values()), 1),
            "runs": len(rs)}


def gpt_pre_1013(model: str) -> list[dict]:
    return pick("base1", model, "base") + pick("conf", model, "base") + pick("long1", model, "base")


SRC = T.onoff_sources()
# Stage keys in journey order. kind: "off" (hollow), "on" (solid, on the path), "side" (dashed detour).
STAGES = [
    ("off", "Code mode off (before)", "off"),
    ("pre", "Code mode, before #1013", "on"),
    ("main", "After #1013 + #1014", "on"),
    ("v1", "Hill climb v1: lean guidance", "on"),
    ("v2", "v2: cache-stable prompt", "on"),
    ("v3", "v3: + guidance fixes", "on"),
    ("pr", "#1015 as merged (today)", "on"),
    ("off_today", "Code mode off (today)", "off"),
    ("sg", "+ smart grep (tried)", "side"),
    ("off_v2", "Code mode off (v2 build)", "off"),
    ("off_v3", "Code mode off (v3 build)", "off"),
]
SOURCES = {
    "codex-gpt-6.1-sol": {"off": SRC["codex-gpt-6.1-sol"]["off"], "pre": gpt_pre_1013("codex-gpt-6.1-sol"),
                          "main": SRC["codex-gpt-6.1-sol"]["on"], "pr": pick("sg1", "codex-gpt-6.1-sol", "on"),
                          "off_today": pick("sg1", "codex-gpt-6.1-sol", "off"),
                          "sg": pick("sg1", "codex-gpt-6.1-sol", "sg_on")},
    "codex-gpt-6-luna": {"off": SRC["codex-gpt-6-luna"]["off"], "pre": gpt_pre_1013("codex-gpt-6-luna"),
                         "off_v2": pick("lean2", "codex-gpt-6-luna", "off"), "off_v3": pick("lean3", "codex-gpt-6-luna", "off"),
                         "main": SRC["codex-gpt-6-luna"]["on"], "v1": pick("lean1", "codex-gpt-6-luna", "lean"),
                         "v2": pick("lean2", "codex-gpt-6-luna", "on"), "v3": pick("lean3", "codex-gpt-6-luna", "on"),
                         "pr": pick("lean4", "codex-gpt-6-luna", "on") + pick("sg1", "codex-gpt-6-luna", "on"),
                         "off_today": pick("sg1", "codex-gpt-6-luna", "off"),
                         "sg": pick("sg1", "codex-gpt-6-luna", "sg_on")},
    "codex-gpt-6-astra": {"off": pick("astra1", "codex-gpt-6-astra", "off"),
                          "main": pick("astra1", "codex-gpt-6-astra", "on"),
                          "pr": pick("astra1", "codex-gpt-6-astra", "pr_on"),
                          "off_today": pick("astra1", "codex-gpt-6-astra", "pr_off")},
}
for m in ("claude-code-claude-opus-5-5", "claude-code-claude-sonnet-5-5", "claude-code-claude-haiku-5-5"):
    s = {"off": SRC[m]["off"], "main": SRC[m]["on"], "pr": pick("sg1", m, "on"),
         "off_today": pick("sg1", m, "off"), "sg": pick("sg1", m, "sg_on")}
    if "haiku" not in m:
        s |= {"v1": pick("lean1", m, "lean"), "v2": pick("lean2", m, "on"), "v3": pick("lean3", m, "on"),
              "off_v2": pick("lean2", m, "off"), "off_v3": pick("lean3", m, "off")}
    SOURCES[m] = s

COLORS = {"codex-gpt-6.1-sol": "#2563eb", "codex-gpt-6-luna": "#9333ea", "codex-gpt-6-astra": "#db2777",
          "claude-code-claude-opus-5-5": "#ea580c", "claude-code-claude-sonnet-5-5": "#16a34a",
          "claude-code-claude-haiku-5-5": "#0891b2"}


name = T.display_name


DATA = {"stages": [{"key": k, "label": lbl, "kind": kind} for k, lbl, kind in STAGES], "models": []}
for m, srcs in SOURCES.items():
    pts = {}
    for k, _, _ in STAGES:
        if k in srcs and (p := point(srcs[k])):
            pts[k] = p
    DATA["models"].append({"id": m, "name": name(m), "color": COLORS[m], "points": pts})


# Milestones on the x axis: (stage key, short label, what changed). Each is compared with code mode
# off on the same build: v2, v3 and #1015 measured their own off runs; v1 changed only code-mode
# guidance, so its off build is the old one.
MILESTONES = [
    ("pre", "First ship", "code mode as first shipped (sol, luna)"),
    ("main", "#1013 + #1014", "batching guidance; sub-agents from code mode"),
    ("v1", "v1", "guidance cut from 6.0k to 2.7k chars"),
    ("v2", "v2", "agent ID + workspace path out of the cached prompt"),
    ("v3", "v3", "guidance fixes (walrus example, import asyncio)"),
    ("pr", "#1015 today", "merged: v3 + grep results typed never-empty"),
]


def premium(m: dict) -> dict:
    """Per milestone: code mode vs code mode off on the same build."""
    pts, out = m["points"], {}
    for k, _, _ in MILESTONES:
        base = pts.get({"pr": "off_today", "v2": "off_v2", "v3": "off_v3"}.get(k, "off"))
        if k in pts and base:
            p = pts[k]
            out[k] = {"cost": round(100 * (p["cost"] / base["cost"] - 1), 1),
                      "time": round(100 * (p["time"] / base["time"] - 1), 1),
                      "acc": round(p["acc"] - base["acc"], 1),
                      "abs": {"cost": p["cost"], "time": p["time"], "acc": p["acc"],
                              "off_cost": base["cost"], "off_time": base["time"], "off_acc": base["acc"], "runs": p["runs"]}}
    return out


CHART = {"milestones": [{"key": k, "label": lbl, "note": note} for k, lbl, note in MILESTONES],
         "models": [{"name": m["name"], "color": m["color"], "values": premium(m)} for m in DATA["models"]]}

JS = r'''
const D = JSON.parse(document.getElementById('data').textContent);
const S = {metric: 'cost'};
const W = 1000, H = 560, PL = 64, PR = 170, PT = 24, PB = 92;
const NS = 'http://www.w3.org/2000/svg', svg = document.getElementById('chart'), tip = document.getElementById('tip');
const META = {
  cost: {unit: '%', up: 'code mode costs more', down: 'code mode is cheaper', lowerBetter: true, noise: 5},
  time: {unit: '%', up: 'code mode is slower', down: 'code mode is faster', lowerBetter: true, noise: 5},
  acc: {unit: ' pts', up: 'code mode is more accurate', down: 'code mode is less accurate', lowerBetter: false, noise: 3},
};
function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  (parent || svg).appendChild(e); return e;
}
const fmt = (v, u) => (v > 0 ? '+' : '') + Math.round(v) + u;
const money = v => v >= 0.1 ? '$' + v.toFixed(2) : v >= 0.01 ? '$' + v.toFixed(3) : '$' + v.toFixed(4);
function render() {
  svg.innerHTML = '';
  const meta = META[S.metric], ms = D.milestones;
  const vals = D.models.flatMap(m => Object.values(m.values).map(v => v[S.metric]));
  const span = Math.max(15, ...vals.map(Math.abs)) * 1.15;
  const y0 = -Math.ceil(span / 5) * 5, y1 = Math.ceil(span / 5) * 5;
  const X = i => PL + 30 + i * (W - PL - PR - 60) / (ms.length - 1);
  const Y = v => PT + (y1 - v) / (y1 - y0) * (H - PT - PB);
  // good / bad halves
  const goodTop = meta.lowerBetter ? Y(0) : PT, goodH = meta.lowerBetter ? Y(y0) - Y(0) : Y(0) - PT;
  el('rect', {x: PL, y: goodTop, width: W - PL - PR, height: goodH, class: 'goodzone'});
  el('rect', {x: PL, y: meta.lowerBetter ? PT : Y(0), width: W - PL - PR, height: meta.lowerBetter ? Y(0) - PT : Y(y0) - Y(0), class: 'badzone'});
  el('rect', {x: PL, y: Y(meta.noise), width: W - PL - PR, height: Y(-meta.noise) - Y(meta.noise), class: 'noise'});
  el('text', {x: PL + 8, y: PT + 16, class: 'zone ' + (meta.lowerBetter ? 'bad' : 'good')}).textContent = '↑ ' + meta.up;
  el('text', {x: PL + 8, y: Y(y0) - 8, class: 'zone ' + (meta.lowerBetter ? 'good' : 'bad')}).textContent = '↓ ' + meta.down;
  for (let t = y0; t <= y1; t += (y1 - y0 > 60 ? 10 : 5)) {
    el('line', {x1: PL, x2: W - PR, y1: Y(t), y2: Y(t), class: t === 0 ? 'zero' : 'grid'});
    el('text', {x: PL - 8, y: Y(t) + 4, class: 'tick', 'text-anchor': 'end'}).textContent = t === 0 ? 'even' : fmt(t, meta.unit);
  }
  el('text', {x: PL + 8, y: Y(meta.noise) + 13, class: 'noiselbl'}).textContent = 'grey band: within noise';
  ms.forEach((m, i) => {
    el('line', {x1: X(i), x2: X(i), y1: PT, y2: H - PB, class: 'grid'});
    el('text', {x: X(i), y: H - PB + 20, class: 'ms', 'text-anchor': 'middle'}).textContent = m.label;
    const words = m.note.split(' '), lines = [''];
    for (const w of words) (lines[lines.length - 1] + ' ' + w).trim().length > 22 ? lines.push(w) : lines[lines.length - 1] = (lines[lines.length - 1] + ' ' + w).trim();
    lines.slice(0, 3).forEach((ln, j) => { el('text', {x: X(i), y: H - PB + 38 + j * 14, class: 'note', 'text-anchor': 'middle'}).textContent = ln; });
  });
  const ends = [];
  for (const m of D.models) {
    const g = el('g', {class: 'model'});
    const pts = ms.map((s, i) => [i, s.key, m.values[s.key]]).filter(x => x[2]);
    for (let j = 1; j < pts.length; j++) {  // dashed where milestones were skipped (not measured)
      const [ia, , va] = pts[j - 1], [ib, , vb] = pts[j];
      el('line', {x1: X(ia), y1: Y(va[S.metric]), x2: X(ib), y2: Y(vb[S.metric]), stroke: m.color,
                  class: ib - ia > 1 ? 'line skipped' : 'line'}, g);
    }
    for (const [i, k, v] of pts) {
      const last = k === pts[pts.length - 1][1];
      const c = el('circle', {cx: X(i), cy: Y(v[S.metric]), r: last ? 7 : 5, fill: m.color, class: 'pt'}, g);
      c.addEventListener('mousemove', e => {
        const a = v.abs, ms_ = ms[i];
        tip.style.display = 'block'; tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 14) + 'px';
        tip.innerHTML = `<b style="color:${m.color}">${m.name}</b> at <b>${ms_.label}</b><br><span>${ms_.note}</span><br>` +
          `cost ${money(a.off_cost)} off → ${money(a.cost)} on (${fmt(v.cost, '%')})<br>` +
          `time ${a.off_time.toFixed(0)} s → ${a.time.toFixed(0)} s (${fmt(v.time, '%')})<br>` +
          `accuracy ${a.off_acc.toFixed(0)}% → ${a.acc.toFixed(0)}% (${fmt(v.acc, ' pts')})<br><span>${a.runs} code-mode runs</span>`;
      });
      c.addEventListener('mouseleave', () => tip.style.display = 'none');
    }
    const [li, , lv] = pts[pts.length - 1];
    ends.push({g, x: X(li) + 14, y: Y(lv[S.metric]) + 4, text: `${m.name}  ${fmt(lv[S.metric], meta.unit)}`, color: m.color});
  }
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 16) ends[i].y = ends[i - 1].y + 16;
  for (const e of ends) el('text', {x: e.x, y: e.y, class: 'end', fill: e.color}, e.g).textContent = e.text;
}
document.querySelectorAll('[data-metric]').forEach(b => b.onclick = () => { S.metric = b.dataset.metric;
  document.querySelectorAll('[data-metric]').forEach(x => x.classList.toggle('on', x === b)); render(); });
render();
'''

CSS = '''
*{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#1c2330;font:16px/1.5 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 28px 56px}h1{font-size:32px;margin:0 0 6px}.sub{color:#5b6576;margin:0 0 18px}
.seg-ctl{display:inline-flex;background:#e8ecf3;border-radius:999px;padding:3px;margin:0 0 12px}
.seg-ctl button{font:inherit;font-size:14px;font-weight:600;border:0;background:none;color:#4b5565;padding:6px 16px;border-radius:999px;cursor:pointer}
.seg-ctl button.on{background:#1c2330;color:#fff}
.card{background:#fff;border:1px solid #e3e7ef;border-radius:14px;padding:10px}svg{width:100%;height:auto;display:block}
.grid{stroke:#eef1f6}.zero{stroke:#1c2330;stroke-width:1.5}.goodzone{fill:#e9f7ef}.badzone{fill:#fcecea}.noise{fill:#f1f3f7;opacity:.85}
.zone{font-size:13px;font-weight:700}.zone.good{fill:#0f7a4f}.zone.bad{fill:#b4322c}.noiselbl{font-size:11px;fill:#8a93a3}
.tick{font-size:12px;fill:#6b7484}.ms{font-size:14px;font-weight:700;fill:#1c2330}.note{font-size:11.5px;fill:#6b7484}
.line{fill:none;stroke-width:3;stroke-linecap:round;opacity:.9}.line.skipped{stroke-dasharray:2 7;stroke-width:2.5;opacity:.6}.pt{cursor:pointer;stroke:#fff;stroke-width:2}
.end{font-size:13.5px;font-weight:700;paint-order:stroke;stroke:#fff;stroke-width:4px}
svg:has(g.model:hover) g.model:not(:hover){opacity:.15}g.model{transition:opacity .15s}
#tip{position:fixed;display:none;background:#1c2330;color:#fff;font-size:13px;padding:8px 11px;border-radius:8px;pointer-events:none;
line-height:1.45;box-shadow:0 6px 20px rgba(0,0,0,.2);max-width:340px}#tip span{color:#aab3c2}
.foot{color:#6b7484;font-size:13px;margin-top:14px}.foot a{color:#2556c9}
'''

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The code mode journey</title><style>{CSS}</style></head><body><div class="wrap">
<h1>The code mode journey</h1>
<p class="sub">How much more (or less) code mode costs than leaving it off, after each change we made. Zero is break-even;
below the line, code mode wins.</p>
<div class="seg-ctl"><button data-metric="cost" class="on">Cost</button><button data-metric="time">Speed</button><button data-metric="acc">Accuracy</button></div>
<div class="card"><svg id="chart" viewBox="0 0 1000 560" role="img" aria-label="Code mode vs off, per milestone"></svg></div>
<p class="foot">Each point compares code mode with code mode off on the same build (today's build for "#1015 today"), averaged
over all 30 tasks with each task counted once, from 60 to 120 runs per point. Cost is API list price. Changes inside the grey
band are noise. Lines start where a model was first measured: sol and luna at first ship; the others at #1013 + #1014; Haiku and
Astra skipped the v1 to v3 hill climb (dotted where a model skipped steps). The self-hosted glm53 and qwen3.8-27b
were only measured today, so they appear on the final scoreboard, not here. Hover a point for the raw numbers.
Per-model tables: <a href="codemode_summary.html">summary</a>; everything else: <a href="codemode_followup.html">full report</a>.</p>
</div><div id="tip"></div>
<script type="application/json" id="data">{json.dumps(CHART)}</script><script>{JS}</script></body></html>"""

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_journey.html"
    out.write_text(page)
    print(out)
    for m in CHART["models"]:
        print(m["name"], {k: (v["cost"], v["time"], v["acc"]) for k, v in m["values"].items()})

#!/usr/bin/env python3
"""Render docs/results/codemode_journey.html: the whole code-mode journey on one chart.

Accuracy (y) against cost or speed (x, toggle), one path per model through every build that was
measured: code mode off -> code mode before #1013 -> after #1013/#1014 -> hill-climb v1..v3 ->
#1015 as merged, plus "code mode off, today" and the smart grep side trip. Every point is a
task-balanced average over all 30 tasks (each task counts once). Rendered client-side from
embedded JSON so the toggles need no reload.
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
]
SOURCES = {
    "codex-gpt-6.1-sol": {"off": SRC["codex-gpt-6.1-sol"]["off"], "pre": gpt_pre_1013("codex-gpt-6.1-sol"),
                          "main": SRC["codex-gpt-6.1-sol"]["on"], "pr": pick("sg1", "codex-gpt-6.1-sol", "on"),
                          "off_today": pick("sg1", "codex-gpt-6.1-sol", "off"),
                          "sg": pick("sg1", "codex-gpt-6.1-sol", "sg_on")},
    "codex-gpt-6-luna": {"off": SRC["codex-gpt-6-luna"]["off"], "pre": gpt_pre_1013("codex-gpt-6-luna"),
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
        s |= {"v1": pick("lean1", m, "lean"), "v2": pick("lean2", m, "on"), "v3": pick("lean3", m, "on")}
    SOURCES[m] = s

COLORS = {"codex-gpt-6.1-sol": "#2563eb", "codex-gpt-6-luna": "#9333ea", "codex-gpt-6-astra": "#db2777",
          "claude-code-claude-opus-5-5": "#ea580c", "claude-code-claude-sonnet-5-5": "#16a34a",
          "claude-code-claude-haiku-5-5": "#0891b2"}


def name(m: str) -> str:
    return m.replace("codex-", "").replace("claude-code-", "").replace("-5-5", "-5.5")


DATA = {"stages": [{"key": k, "label": lbl, "kind": kind} for k, lbl, kind in STAGES], "models": []}
for m, srcs in SOURCES.items():
    pts = {}
    for k, _, _ in STAGES:
        if k in srcs and (p := point(srcs[k])):
            pts[k] = p
    DATA["models"].append({"id": m, "name": name(m), "color": COLORS[m], "points": pts})

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const S = {metric: 'cost', scale: 'rel', steps: 'key', hidden: new Set()};
const KEY_STEPS = new Set(['off', 'pre', 'main', 'pr']);
const W = 1000, H = 620, PL = 70, PR = 30, PT = 30, PB = 60;
const NS = 'http://www.w3.org/2000/svg';
const svg = document.getElementById('chart'), tip = document.getElementById('tip');
const stageIdx = Object.fromEntries(D.stages.map((s, i) => [s.key, i]));
const stage = Object.fromEntries(D.stages.map(s => [s.key, s]));

function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  (parent || svg).appendChild(e); return e;
}
function xval(m, p) {
  const v = p[S.metric];
  return S.scale === 'rel' ? 100 * v / m.points.off[S.metric] : v;
}
function fmtX(v) {
  if (S.scale === 'rel') return v.toFixed(0);
  if (S.metric === 'time') return v.toFixed(0) + ' s';
  return v >= 0.1 ? '$' + v.toFixed(2) : v >= 0.01 ? '$' + v.toFixed(3) : '$' + v.toFixed(4);
}
function niceTicks(lo, hi, n) {
  const step0 = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= step0);
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function arrows() {
  const defs = el('defs', {});
  for (const m of D.models) {
    const mk = el('marker', {id: `arr-${m.id}`, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6,
                             orient: 'auto-start-reverse'}, defs);
    el('path', {d: 'M0,0 L10,5 L0,10 z', fill: m.color}, mk);
  }
}
function render() {
  svg.innerHTML = '';
  arrows();
  const models = D.models.filter(m => !S.hidden.has(m.id));
  const solo = models.length === 1, labels = [];
  const all = models.flatMap(m => Object.entries(m.points).filter(([k]) => S.steps === 'all' || KEY_STEPS.has(k))
    .map(([, p]) => ({x: xval(m, p), y: p.acc})));
  if (!all.length) return;
  const log = S.scale === 'abs' && S.metric === 'cost';
  const tx = log ? Math.log10 : (v => v);
  let x0 = Math.min(...all.map(p => tx(p.x))), x1 = Math.max(...all.map(p => tx(p.x)));
  const padx = (x1 - x0) * 0.08 || (log ? 0.1 : 5); x0 -= padx; x1 += padx;
  let y0 = Math.min(...all.map(p => p.y)), y1 = 100;
  y0 = Math.max(0, Math.floor((y0 - 4) / 5) * 5); y1 = 101;
  const X = v => PL + (tx(v) - x0) / (x1 - x0) * (W - PL - PR);
  const Y = v => PT + (y1 - v) / (y1 - y0) * (H - PT - PB);
  // grid
  for (const t of niceTicks(y0, 100, 6)) {
    el('line', {x1: PL, x2: W - PR, y1: Y(t), y2: Y(t), class: 'grid'});
    el('text', {x: PL - 10, y: Y(t) + 4, class: 'tick', 'text-anchor': 'end'}).textContent = t + '%';
  }
  const xt = log ? [0.001,0.002,0.005,0.01,0.02,0.05,0.1,0.2,0.5,1].filter(v => Math.log10(v) >= x0 && Math.log10(v) <= x1)
                 : niceTicks(x0, x1, 8);
  for (const t of xt) {
    el('line', {x1: X(t), x2: X(t), y1: PT, y2: H - PB, class: 'grid'});
    el('text', {x: X(t), y: H - PB + 20, class: 'tick', 'text-anchor': 'middle'}).textContent = fmtX(t);
  }
  if (S.scale === 'rel' && 100 > x0 && 100 < x1)
    el('line', {x1: X(100), x2: X(100), y1: PT, y2: H - PB, class: 'ref'});
  const word = S.metric === 'cost' ? 'cost per task' : 'time per task';
  el('text', {x: (PL + W - PR) / 2, y: H - 14, class: 'axis', 'text-anchor': 'middle'}).textContent =
    (S.scale === 'rel' ? `${word}, index (same model, code mode off before = 100)` : word + (log ? ' (log scale)' : '')) +
    `   ← ${S.metric === 'cost' ? 'cheaper' : 'faster'}`;
  el('text', {x: 18, y: (PT + H - PB) / 2, class: 'axis', 'text-anchor': 'middle',
              transform: `rotate(-90 18 ${(PT + H - PB) / 2})`}).textContent = 'accuracy (tasks fully right) →';
  // paths
  for (const m of models) {
    const keys = Object.keys(m.points).filter(k => S.steps === 'all' || KEY_STEPS.has(k));
    const path = keys.filter(k => stage[k].kind !== 'side' && k !== 'off_today').sort((a, b) => stageIdx[a] - stageIdx[b]);
    const g = el('g', {class: 'model'});
    const P = k => [X(xval(m, m.points[k])), Y(m.points[k].acc)];
    for (let i = 1; i < path.length; i++) {
      const [ax, ay] = P(path[i - 1]), [bx, by] = P(path[i]);
      const len = Math.hypot(bx - ax, by - ay), gap = (path[i] === 'pr' ? 9 : 6) + 3;
      if (len <= gap + 2) continue;  // points on top of each other: no arrow
      const ex = bx - (bx - ax) * gap / len, ey = by - (by - ay) * gap / len;
      el('line', {x1: ax, y1: ay, x2: ex, y2: ey, stroke: m.color, class: 'seg', 'marker-end': `url(#arr-${m.id})`}, g);
    }
    if (keys.includes('sg')) { const [ax, ay] = P('pr'), [bx, by] = P('sg');
      el('line', {x1: ax, y1: ay, x2: bx, y2: by, stroke: m.color, class: 'seg side'}, g); }
    if (keys.includes('off_today')) { const [ax, ay] = P('off'), [bx, by] = P('off_today');
      el('line', {x1: ax, y1: ay, x2: bx, y2: by, stroke: m.color, class: 'seg offline'}, g); }
    for (const k of keys) {
      const [cx, cy] = P(k), s = stage[k];
      const r = k === 'pr' ? 9 : 6;
      const dot = s.kind === 'off'
        ? el('rect', {x: cx - 6, y: cy - 6, width: 12, height: 12, fill: '#fff', stroke: m.color, 'stroke-width': 2.5,
                      transform: `rotate(45 ${cx} ${cy})`}, g)
        : el('circle', {cx, cy, r, fill: s.kind === 'side' ? '#fff' : m.color, stroke: m.color, 'stroke-width': 2.5,
                        'stroke-dasharray': s.kind === 'side' ? '3 2' : ''}, g);
      dot.classList.add('pt');
      const p = m.points[k];
      dot.addEventListener('mousemove', e => {
        tip.style.display = 'block'; tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 14) + 'px';
        const cost = p.cost >= 0.1 ? '$' + p.cost.toFixed(2) : p.cost >= 0.01 ? '$' + p.cost.toFixed(3) : '$' + p.cost.toFixed(4);
        const rel = m.points.off; const pc = (a, b) => { const d = Math.round(100 * (a - b) / b); return (d > 0 ? '+' : '') + d + '%'; };
        tip.innerHTML = `<b style="color:${m.color}">${m.name}</b><br>${s.label}<br>` +
          `cost ${cost}/task <span>(${pc(p.cost, rel.cost)} vs off)</span><br>time ${p.time.toFixed(0)} s/task ` +
          `<span>(${pc(p.time, rel.time)})</span><br>accuracy ${p.acc.toFixed(0)}%<br><span>${p.runs} runs</span>`;
      });
      dot.addEventListener('mouseleave', () => tip.style.display = 'none');
    }
    if (solo) for (const k of keys) {
      const [cx, cy] = P(k);
      labels.push({cx, x: cx + 12, y: cy + 4, text: stage[k].label, color: m.color, g, small: true});
    }
    else if (m.points.pr) { const [cx, cy] = P('pr'); labels.push({cx, x: cx + 13, y: cy + 4, text: m.name, color: m.color, g}); }
  }
  // Nudge labels apart vertically (greedy, in y order) so none overlap.
  labels.sort((a, b) => a.y - b.y);
  const placed = [];
  for (const l of labels) {
    const w = l.text.length * (l.small ? 6.2 : 7.4);
    let anchor = 'start';
    if (l.x + w > W - PR) { l.x = l.cx - 12; anchor = 'end'; }  // would run off the right edge: label on the left
    const left = anchor === 'end' ? l.x - w : l.x;
    for (const q of placed) if (Math.abs(q.left - left) < Math.max(q.w, w) && Math.abs(q.y - l.y) < 15) l.y = q.y + 15;
    placed.push({left, y: l.y, w});
    el('text', {x: l.x, y: l.y, class: l.small ? 'lbl small' : 'lbl', fill: l.color, 'text-anchor': anchor}, l.g).textContent = l.text;
  }
}
document.querySelectorAll('[data-metric]').forEach(b => b.onclick = () => { S.metric = b.dataset.metric;
  document.querySelectorAll('[data-metric]').forEach(x => x.classList.toggle('on', x === b)); render(); });
document.querySelectorAll('[data-steps]').forEach(b => b.onclick = () => { S.steps = b.dataset.steps;
  document.querySelectorAll('[data-steps]').forEach(x => x.classList.toggle('on', x === b)); render(); });
document.querySelectorAll('[data-scale]').forEach(b => b.onclick = () => { S.scale = b.dataset.scale;
  document.querySelectorAll('[data-scale]').forEach(x => x.classList.toggle('on', x === b)); render(); });
const chips = document.getElementById('chips');
function syncChips() { chips.querySelectorAll('[data-m]').forEach(c => c.classList.toggle('on', !S.hidden.has(c.dataset.m))); }
const allChip = document.createElement('button'); allChip.className = 'chip on all'; allChip.textContent = 'All';
allChip.onclick = () => { S.hidden.clear(); syncChips(); render(); };
chips.appendChild(allChip);
for (const m of D.models) {
  const c = document.createElement('button'); c.className = 'chip on'; c.dataset.m = m.id;
  c.innerHTML = `<i style="background:${m.color}"></i>${m.name}`;
  c.title = 'Click to show or hide; double-click to show only this model, with every step labelled';
  c.onclick = () => { S.hidden.has(m.id) ? S.hidden.delete(m.id) : S.hidden.add(m.id); syncChips(); render(); };
  c.ondblclick = () => { S.hidden = new Set(D.models.map(x => x.id).filter(id => id !== m.id)); syncChips(); render(); };
  chips.appendChild(c);
}
render();
"""

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#1c2330;font:16px/1.5 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 28px 56px}h1{font-size:32px;margin:0 0 6px}.sub{color:#5b6576;margin:0 0 18px}
.bar{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin:0 0 12px}
.seg-ctl{display:inline-flex;background:#e8ecf3;border-radius:999px;padding:3px}
.seg-ctl button{font:inherit;font-size:14px;font-weight:600;border:0;background:none;color:#4b5565;padding:6px 14px;border-radius:999px;cursor:pointer}
.seg-ctl button.on{background:#1c2330;color:#fff}
#chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font:inherit;font-size:13px;font-weight:600;border:1px solid #d9dee8;background:#fff;
color:#9aa3b2;padding:5px 11px;border-radius:999px;cursor:pointer}.chip.on{color:#1c2330}
.chip i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;opacity:.3}.chip.on i{opacity:1}
.card{background:#fff;border:1px solid #e3e7ef;border-radius:14px;padding:10px}
svg{width:100%;height:auto;display:block}.grid{stroke:#eef1f6}.ref{stroke:#9aa3b2;stroke-dasharray:4 4}
.tick{font-size:12px;fill:#6b7484}.axis{font-size:13px;fill:#4b5565;font-weight:600}
.seg{stroke-width:2.5;opacity:.75}.seg.side{stroke-dasharray:5 4;opacity:.6}.seg.offline{stroke-dasharray:1 4;stroke-linecap:round;opacity:.6}
.pt{cursor:pointer}.lbl{font-size:13px;font-weight:700;paint-order:stroke;stroke:#fff;stroke-width:4px}.lbl.small{font-size:12px;font-weight:600}
svg:has(g.model:hover) g.model:not(:hover){opacity:.15}g.model{transition:opacity .15s}
.legend{display:flex;flex-wrap:wrap;gap:18px;color:#4b5565;font-size:13px;margin:12px 4px 0}
.legend svg{display:inline-block;width:auto;vertical-align:middle;margin-right:6px}
#tip{position:fixed;display:none;background:#1c2330;color:#fff;font-size:13px;padding:8px 11px;border-radius:8px;pointer-events:none;
line-height:1.45;box-shadow:0 6px 20px rgba(0,0,0,.2)}#tip span{color:#aab3c2}
.steps{color:#4b5565;font-size:14px;margin-top:18px}.steps li{margin:3px 0}.foot{color:#6b7484;font-size:13px;margin-top:14px}
.foot a{color:#2556c9}
"""

LEGEND = """<div class="legend">
<span><svg width="18" height="18"><rect x="4" y="4" width="10" height="10" fill="#fff" stroke="#4b5565" stroke-width="2" transform="rotate(45 9 9)"/></svg>code mode off (before, and today)</span>
<span><svg width="18" height="18"><circle cx="9" cy="9" r="5" fill="#4b5565"/></svg>a code-mode build along the way</span>
<span><svg width="22" height="22"><circle cx="11" cy="11" r="8" fill="#4b5565"/></svg>#1015 as merged (today, labelled)</span>
<span><svg width="18" height="18"><circle cx="9" cy="9" r="5" fill="#fff" stroke="#4b5565" stroke-width="2" stroke-dasharray="3 2"/></svg>+ smart grep (tried, not adopted)</span>
<span>Up and left is better. Hover a point for its numbers; double-click a model to see its steps labelled.</span></div>"""

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The code mode journey</title><style>{CSS}</style></head><body><div class="wrap">
<h1>The code mode journey</h1>
<p class="sub">Every build of code mode we measured, per model: accuracy against cost or speed. Each path starts at code
mode off and follows each change until today.</p>
<div class="bar">
<div class="seg-ctl"><button data-metric="cost" class="on">Cost</button><button data-metric="time">Speed</button></div>
<div class="seg-ctl"><button data-steps="key" class="on">Main steps</button><button data-steps="all">Every build</button></div>
<div class="seg-ctl"><button data-scale="rel" class="on">Relative to code mode off</button><button data-scale="abs">Absolute</button></div>
<div id="chips"></div></div>
<div class="card"><svg id="chart" viewBox="0 0 1000 620" role="img" aria-label="Code mode journey chart"></svg></div>
{LEGEND}
<ol class="steps">
<li><b>Code mode off</b>: the starting point (the same model without code mode).</li>
<li><b>Before #1013</b>: code mode as first shipped (sol and luna only; the other models were added later).</li>
<li><b>After #1013 + #1014</b>: batching guidance, and sub-agents called from code mode.</li>
<li><b>Hill climb v1 to v3</b>: shorter guidance; then the agent ID and workspace path moved out of the cached prompt
(the big step for Claude); then guidance fixes (Opus, Sonnet and luna only).</li>
<li><b>#1015 as merged</b>: today's main, plus grep results typed as never empty.</li></ol>
<p class="foot">Each point is the average over all 30 tasks, each task counted once, from 60 to 120 runs. Cost is API list price.
Accuracy is the share of tasks fully right. Points from different batches carry run-to-run noise of a few percent.
Per-model tables: <a href="codemode_summary.html">summary</a>; everything else: <a href="codemode_followup.html">full report</a>.</p>
</div><div id="tip"></div>
<script type="application/json" id="data">{json.dumps(DATA)}</script><script>{JS}</script></body></html>"""

out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "docs" / "results" / "codemode_journey.html"
out.write_text(page)
print(out)
for m in DATA["models"]:
    print(m["name"], {k: (p["cost"], p["time"], p["acc"], p["runs"]) for k, p in m["points"].items()})

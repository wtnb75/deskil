"""Turn usage timelines into a view model and a single self-contained HTML page.

Standard library only; the page has no external references.
"""

import json
from datetime import datetime


def _seconds(start: object, end: object) -> float:
    """Seconds from start to end (ISO strings); 0 when either is unreadable."""
    try:
        a = datetime.fromisoformat(str(start))
        b = datetime.fromisoformat(str(end))
        return (b - a).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _tokens(item: dict) -> tuple[int, bool]:
    """Sum of the four token fields and whether all of them are known."""
    keys = ("input", "cache_create", "cache_read", "output")
    values = [item.get(k) for k in keys]
    known = all(isinstance(v, int | float) for v in values)
    return sum(v for v in values if isinstance(v, int | float)), known


def _subs(visit: dict, sec: float) -> list[list]:
    if sec <= 0:
        return []
    out = []
    for agent in visit.get("agents") or []:
        off = max(0.0, _seconds(visit.get("start"), agent.get("start")))
        dur = max(1.0, _seconds(agent.get("start"), agent.get("end")))
        dur = min(dur, sec)
        if off + dur > sec:
            off = max(0.0, sec - dur)
        out.append([agent.get("name", ""), off, dur, _tokens(agent)[0]])
    return out


def build_view(*, run_id: str, definition: str, timeline: list[dict]) -> dict:
    """Build the per-run view model drawn by the page."""
    parts = [p for p in str(definition).replace("\\", "/").split("/") if p]
    note = "/".join(parts[-2:]) if len(parts) > 2 else str(definition)
    count: dict[str, int] = {}
    for v in timeline:
        count[v["state"]] = count.get(v["state"], 0) + 1
    seen: dict[str, int] = {}
    visits = []
    tokens = 0
    wait = 0.0
    total = 0.0
    for v in timeline:
        state = v["state"]
        seen[state] = seen.get(state, 0) + 1
        sec = max(0.0, _seconds(v.get("start"), v.get("end")))
        tok, known = _tokens(v)
        if not known:
            tok = 0
        subs = _subs(v, sec)
        tokens += tok + sum(s[3] for s in subs)
        total += sec
        gate = bool(v.get("gate"))
        if gate:
            wait += sec
        visits.append(
            {
                "state": state,
                "label": f"{state} #{seen[state]}" if count[state] > 1 else state,
                "sec": sec,
                "tok": tok,
                "gate": gate,
                "known": known,
                "subs": subs,
            }
        )
    return {
        "id": run_id,
        "note": note,
        "total_sec": total,
        "tokens": tokens,
        "wait_sec": wait,
        "visits": visits,
    }


def _embed(obj: object) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    for ch, esc in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        (" ", "\\u2028"),
        (" ", "\\u2029"),
    ):
        text = text.replace(ch, esc)
    return text


def render_html(views: list[dict]) -> str:
    """Return a complete HTML document drawing the given run views."""
    return _TEMPLATE.replace("__DATA__", _embed({"runs": views}))


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flow Timeline</title>
<style>
  /* Layout: runs stacked on one shared time axis. Bar width = time, height = tokens per minute, so area = tokens.
     A step that used subagents is one dashed box: the session at the bottom, subagents stacked on top while they ran. */
  :root {
    --bg: #f6f7f8; --panel: #ffffff; --fg: #1b2127; --muted: #5f6b76; --line: #dde2e6;
    --wait: #8a95a0; --wait-bg: rgba(138,149,160,.16);
    --s1: #2f6fb0; --s2: #2a9d8f; --s3: #c9822b; --s4: #7a5cb8; --s5: #b84f6d; --s6: #5f8a3c;
    --focus: #1b2127;
    --sans: system-ui, -apple-system, "Segoe UI", sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #12171b; --panel: #1a2127; --fg: #e7ebee; --muted: #93a0ab; --line: #2b343b;
      --wait: #7d8993; --wait-bg: rgba(125,137,147,.2);
      --s1: #6fa8dc; --s2: #5cc4b5; --s3: #e0a458; --s4: #a690dc; --s5: #e07f9b; --s6: #93bf6c;
      --focus: #e7ebee; color-scheme: dark;
    }
  }
  :root[data-theme="dark"] {
    --bg: #12171b; --panel: #1a2127; --fg: #e7ebee; --muted: #93a0ab; --line: #2b343b;
    --wait: #7d8993; --wait-bg: rgba(125,137,147,.2);
    --s1: #6fa8dc; --s2: #5cc4b5; --s3: #e0a458; --s4: #a690dc; --s5: #e07f9b; --s6: #93bf6c;
    --focus: #e7ebee; color-scheme: dark;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 14px; line-height: 1.5; margin: 0;
         padding-block: 24px 56px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
  main { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0; text-wrap: balance; }
  .sub { color: var(--muted); margin: 4px 0 0; max-width: 70ch; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center; color: var(--muted); }
  .controls label { display: inline-flex; gap: 8px; align-items: center; cursor: pointer; color: var(--fg); }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .sw { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
  .sw.wait { background: repeating-linear-gradient(135deg, var(--wait-bg) 0 4px, transparent 4px 8px); border: 1px solid var(--wait); }
  .sw.agent { background: var(--muted); opacity: .45; }
  .run { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px 12px; }
  .run-head { display: flex; flex-wrap: wrap; gap: 4px 20px; align-items: baseline; margin-bottom: 10px; }
  .run-id { font-family: var(--mono); font-weight: 500; }
  .run-note { color: var(--muted); }
  .empty { color: var(--muted); padding: 12px 0; }
  .stat { font-family: var(--mono); font-size: 13px; }
  .stat b { font-weight: 500; }
  .stat .k { color: var(--muted); font-family: var(--sans); margin-right: 4px; }
  .lane { position: relative; height: 150px; border-bottom: 1px solid var(--line); background:
          linear-gradient(to bottom, transparent 24%, var(--line) 24% calc(24% + 1px), transparent calc(24% + 1px) 49%, var(--line) 49% calc(49% + 1px), transparent calc(49% + 1px) 74%, var(--line) 74% calc(74% + 1px), transparent calc(74% + 1px)); }
  .seg { position: absolute; bottom: 0; border-radius: 2px 2px 0 0; cursor: default; outline-offset: 1px; min-width: 2px; }
  .seg.work { opacity: .92; }
  .seg.work:hover, .seg.work:focus-visible { opacity: 1; filter: brightness(1.08); }
  .seg.unk { height: 30%; border: 1px dotted var(--muted); border-bottom: 0; border-radius: 0; }
  .seg.wait { height: 100%; background: repeating-linear-gradient(135deg, var(--wait-bg) 0 5px, transparent 5px 10px); border-left: 1px solid var(--wait); border-right: 1px solid var(--wait); border-radius: 0; }
  .seg.wait .brk { position: absolute; inset: 0; display: grid; place-items: center; font: 500 11px var(--mono); color: var(--muted); }
  .seg:focus-visible, .box:focus-visible { outline: 2px solid var(--focus); }
  .box { position: absolute; bottom: 0; border: 1px dashed var(--muted); border-bottom: 0; outline-offset: 1px; }
  .layer { position: absolute; border-top: 1px solid var(--panel); }
  .layer:hover { filter: brightness(1.12); }
  .axis { position: relative; height: 22px; font: 11px var(--mono); color: var(--muted); }
  .axis i { position: absolute; top: 4px; transform: translateX(-50%); font-style: normal; white-space: nowrap; }
  .axis i::before { content: ""; position: absolute; left: 50%; top: -5px; width: 1px; height: 4px; background: var(--muted); }
  .axis i:first-child { transform: none; } .axis i:first-child::before { left: 0; }
  .yl { position: absolute; left: 4px; top: 2px; font: 11px var(--mono); color: var(--muted); pointer-events: none; }
  details { margin-top: 6px; }
  summary { cursor: pointer; color: var(--muted); font-size: 13px; padding: 4px 0; }
  .tw { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; min-width: 520px; }
  th, td { text-align: right; padding: 5px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; } th { font-weight: 500; color: var(--muted); }
  td { font-family: var(--mono); } td:first-child { font-family: var(--sans); }
  td .sw { margin-right: 8px; vertical-align: -1px; }
  tr.is-wait td { color: var(--muted); }
  tr.is-agent td { color: var(--muted); } tr.is-agent td:first-child { padding-left: 34px; }
  #tip { position: fixed; z-index: 20; pointer-events: none; background: var(--fg); color: var(--bg); padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.5; max-width: 260px; opacity: 0; transition: opacity .08s; }
  #tip.on { opacity: 1; }
  #tip b { font-weight: 600; } #tip .m { font-family: var(--mono); }
  .note { color: var(--muted); font-size: 12px; max-width: 80ch; }
  @media (prefers-reduced-motion: reduce) { #tip { transition: none; } }
</style>
</head>
<body>
<main>
  <header>
    <h1>Flow Timeline</h1>
    <p class="sub">Runs of a flow drawn on the same time axis. Bar width is time, bar height is tokens per minute, so a bar's area is its tokens. Hatched columns are waits for a person (gate).</p>
  </header>

  <div class="controls">
    <label><input type="checkbox" id="compress"> Shorten long waits to make the work readable</label>
    <div class="legend" id="legend" aria-label="Legend"></div>
  </div>

  <div id="runs"></div>

  <p class="note">Hover or focus a bar for its numbers. Read the shape first: tall bars are token-heavy work, wide hatched columns are waiting, and wide short bars are time spent without many tokens (for example a slow command). A dashed box is a step that used subagents: the step's own session is at the bottom and each subagent is stacked on top while it ran, so a taller box means more work at the same moment. A dotted outline is a step whose token usage is unknown.</p>
</main>
<div id="tip" role="tooltip"></div>

<script type="application/json" id="data">__DATA__</script>
<script>
  // Visit shape inside the page: [state, seconds, tokens in the step's own session, isGate, subagents, known].
  // A subagent is [name, offset seconds, seconds, tokens].
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const RUNS = (DATA.runs || []).map(r => ({
    id: r.id, note: r.note,
    visits: (r.visits || []).map(v => [v.state, v.sec, v.tok, v.gate ? 1 : 0, v.subs || [], v.known !== false])
  }));
  const PALETTE = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"];
  const STATES = [];
  RUNS.forEach(r => r.visits.forEach(v => { if (!v[3] && !STATES.includes(v[0])) STATES.push(v[0]); }));
  const LAYER_OPACITY = [0.5, 0.64, 0.78, 0.9];
  const WAIT_CAP = 120; // seconds of width a wait gets when shortened

  const fmtDur = s => s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.floor(s/60)}m${String(Math.round(s%60)).padStart(2,"0")}s`
                    : `${Math.floor(s/3600)}h${String(Math.round((s%3600)/60)).padStart(2,"0")}m`;
  const fmtTok = n => n < 1000 ? String(n) : n < 999950 ? `${(n/1000).toFixed(1)}k` : `${(n/1e6).toFixed(1)}M`;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const colorOf = state => { const i = STATES.indexOf(state); return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]; };
  const perMin = (tok, sec) => sec > 0 ? tok / (sec / 60) : 0;

  const tip = document.getElementById("tip");
  function showTip(el, html) {
    tip.innerHTML = html; tip.classList.add("on");
    const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    const x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8);
    let y = r.top - h - 8; if (y < 8) y = r.bottom + 8;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  const hideTip = () => tip.classList.remove("on");
  function bindTip(el, html) {
    el.addEventListener("mouseenter", () => showTip(el, html)); el.addEventListener("mouseleave", hideTip);
    el.addEventListener("focus", () => showTip(el, html)); el.addEventListener("blur", hideTip);
  }

  // Cut a step into time slices; in each slice the layers are the step's own session plus the subagents running then.
  function stackOf(v) {
    const bounds = new Set([0, v.sec]);
    v.subs.forEach(([, off, dur]) => { bounds.add(off); bounds.add(Math.min(off + dur, v.sec)); });
    const xs = [...bounds].sort((a, b) => a - b), out = [];
    for (let i = 0; i < xs.length - 1; i++) {
      const m = (xs[i] + xs[i + 1]) / 2, layers = [{ main: true, rate: v.rate }];
      v.subs.forEach(([, off, dur, tok], k) => { if (off <= m && m < off + dur) layers.push({ k, rate: perMin(tok, dur) }); });
      out.push({ a: xs[i], b: xs[i + 1], layers, total: layers.reduce((s, l) => s + l.rate, 0) });
    }
    return out;
  }

  function enrich(run) {
    let t = 0; const seen = {}, count = {};
    run.visits.forEach(v => count[v[0]] = (count[v[0]] || 0) + 1);
    return run.visits.map(([state, sec, tok, gate, subs, known]) => {
      seen[state] = (seen[state] || 0) + 1;
      const o = { state, sec, tok, gate: !!gate, known, start: t, label: count[state] > 1 ? `${state} #${seen[state]}` : state,
                  rate: gate || !known ? 0 : perMin(tok, sec), subs: subs || [] };
      o.subTok = o.subs.reduce((a, s) => a + s[3], 0); o.allTok = o.tok + o.subTok;
      o.allRate = gate || !known ? 0 : perMin(o.allTok, sec);
      o.stack = known && !gate && o.subs.length && sec > 0 ? stackOf(o) : null;
      o.peak = o.stack ? Math.max(...o.stack.map(s => s.total)) : o.rate;
      t += sec; return o;
    });
  }

  function render() {
    const compress = document.getElementById("compress").checked;
    const root = document.getElementById("runs"); root.innerHTML = "";
    if (!RUNS.length) { root.innerHTML = `<p class="empty">No runs</p>`; return; }
    const runs = RUNS.map(r => ({ ...r, vs: enrich(r) }));
    runs.forEach(r => {
      let x = 0;
      r.vs.forEach(v => { v.dw = compress && v.gate ? Math.min(v.sec, WAIT_CAP) : v.sec; v.x = x; x += v.dw; });
      r.span = x; r.total = r.vs.reduce((a, v) => a + v.sec, 0);
      r.tokens = r.vs.reduce((a, v) => a + v.allTok, 0);
      r.waitSec = r.vs.filter(v => v.gate).reduce((a, v) => a + v.sec, 0);
    });
    const maxSpan = Math.max(0, ...runs.map(r => r.span)) || 1;
    const maxRate = Math.max(0, ...runs.flatMap(r => r.vs.map(v => v.peak))) || 1;
    const hp = rate => Math.max(4, 100 * rate / maxRate * 0.96); // height in percent of the lane

    runs.forEach(r => {
      const el = document.createElement("section"); el.className = "run";
      const head = `<div class="run-head"><span class="run-id">${esc(r.id)}</span><span class="run-note">${esc(r.note)}</span>
        <span class="stat"><span class="k">time</span><b>${fmtDur(r.total)}</b></span>
        <span class="stat"><span class="k">tokens</span><b>${fmtTok(r.tokens)}</b></span>
        <span class="stat"><span class="k">waiting</span><b>${r.total > 0 ? Math.round(100 * r.waitSec / r.total) : 0}%</b></span></div>`;
      if (!r.vs.length) { el.innerHTML = head + `<p class="empty">No visits</p>`; root.appendChild(el); return; }
      const tipFor = [];
      const segs = r.vs.map((v, i) => {
        const left = 100 * v.x / maxSpan, width = 100 * v.dw / maxSpan;
        if (v.gate) {
          const cut = compress && v.sec > WAIT_CAP;
          tipFor[i] = `<b>${esc(v.label)}</b><br>waiting for a person<br><span class="m">${fmtDur(v.sec)}</span>`;
          return `<div class="seg wait" data-i="${i}" tabindex="0" style="left:${left}%;width:${width}%" aria-label="${esc(v.label)}, waiting ${fmtDur(v.sec)}">${cut ? `<span class="brk">≈ ${fmtDur(v.sec)}</span>` : ""}</div>`;
        }
        if (!v.known) {
          tipFor[i] = `<b>${esc(v.label)}</b><br><span class="m">${fmtDur(v.sec)} · tokens unknown</span>`;
          return `<div class="seg unk" data-i="${i}" tabindex="0" style="left:${left}%;width:${width}%" aria-label="${esc(v.label)}, ${fmtDur(v.sec)}, tokens unknown"></div>`;
        }
        if (v.stack) {
          // One dashed box for the whole step; its height is the busiest moment, layers are placed in percent of the box.
          const peak = v.peak || 1;
          const slices = v.stack.map(s => {
            let base = 0;
            return s.layers.map(l => {
              const bottom = 100 * base / peak, h = 100 * l.rate / peak; base += l.rate;
              const op = l.main ? 0.92 : LAYER_OPACITY[l.k % LAYER_OPACITY.length];
              return `<div class="layer" data-i="${i}" data-k="${l.main ? "m" : l.k}" style="left:${100 * s.a / v.sec}%;width:${100 * (s.b - s.a) / v.sec}%;bottom:${bottom}%;height:${h}%;background:${colorOf(v.state)};opacity:${op}"></div>`;
            }).join("");
          }).join("");
          tipFor[i] = `<b>${esc(v.label)}</b> (whole step)<br><span class="m">${fmtDur(v.sec)} · ${fmtTok(v.allTok)} tokens<br>${fmtTok(v.tok)} in the step's own session<br>${fmtTok(v.subTok)} in ${v.subs.length} subagents</span>`;
          return `<div class="box" data-i="${i}" tabindex="0" style="left:${left}%;width:${width}%;height:${hp(peak)}%" aria-label="${esc(v.label)}, ${fmtDur(v.sec)}, ${fmtTok(v.allTok)} tokens including ${v.subs.length} subagents">${slices}</div>`;
        }
        tipFor[i] = `<b>${esc(v.label)}</b><br><span class="m">${fmtDur(v.sec)} · ${fmtTok(v.tok)} tokens<br>${fmtTok(Math.round(v.rate))}/min</span>`;
        return `<div class="seg work" data-i="${i}" tabindex="0" style="left:${left}%;width:${width}%;height:${hp(v.rate)}%;background:${colorOf(v.state)}" aria-label="${esc(v.label)}, ${fmtDur(v.sec)}, ${fmtTok(v.tok)} tokens"></div>`;
      }).join("");
      let axis = "";
      if (!compress) {
        const steps = [30, 60, 120, 300, 600, 900, 1800, 3600], step = steps.find(s => maxSpan / s <= 8) || 3600;
        for (let s = 0; s <= r.span; s += step) axis += `<i style="left:${100 * s / maxSpan}%">${s === 0 ? "0" : fmtDur(s)}</i>`;
      } else axis = `<i style="left:0">start</i>`;
      const rows = r.vs.map(v => {
        const main = `<tr class="${v.gate ? "is-wait" : ""}"><td><span class="sw ${v.gate ? "wait" : ""}" style="${v.gate ? "" : `background:${colorOf(v.state)}`}"></span>${esc(v.label)}${v.gate ? " (waiting)" : ""}</td>
          <td>${fmtDur(v.sec)}</td><td>${v.gate ? "–" : v.known ? fmtTok(v.allTok) : "unknown"}</td><td>${v.gate || !v.known ? "–" : fmtTok(Math.round(v.allRate)) + "/min"}</td></tr>`;
        const subs = v.subs.map(([name, off, dur, tok]) => `<tr class="is-agent"><td>${esc(name)}</td><td>${fmtDur(dur)}</td><td>${fmtTok(tok)}</td><td>${fmtTok(Math.round(perMin(tok, dur)))}/min</td></tr>`).join("");
        return main + subs;
      }).join("");
      el.innerHTML = head + `<div class="lane" role="group" aria-label="Timeline of ${esc(r.id)}"><span class="yl">tokens/min ↑</span>${segs}</div><div class="axis">${axis}</div>
        <details><summary>Numbers per visit</summary><div class="tw"><table><thead><tr><th>Visit</th><th>Time</th><th>Tokens (with subagents)</th><th>Rate</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
      el.querySelectorAll(".seg, .box").forEach(s => bindTip(s, tipFor[+s.dataset.i]));
      el.querySelectorAll(".layer").forEach(s => {
        const v = r.vs[+s.dataset.i];
        if (s.dataset.k === "m") return bindTip(s, `<b>${esc(v.label)}</b><br>the step's own session<br><span class="m">${fmtTok(v.tok)} tokens</span>`);
        const [name, , dur, tok] = v.subs[+s.dataset.k];
        bindTip(s, `<b>${esc(name)}</b><br>subagent during ${esc(v.label)}<br><span class="m">${fmtDur(dur)} · ${fmtTok(tok)} tokens</span>`);
      });
      root.appendChild(el);
    });
  }

  document.getElementById("legend").innerHTML = STATES.map(s => `<span><i class="sw" style="background:${colorOf(s)}"></i>${esc(s)}</span>`).join("")
    + `<span><i class="sw agent"></i>subagent (lighter, stacked)</span><span><i class="sw wait"></i>waiting for a person</span>`;
  document.getElementById("compress").addEventListener("change", render);
  render();
</script>
</body>
</html>
"""

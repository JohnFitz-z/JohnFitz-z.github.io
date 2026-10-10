// Performance views: record tiles, units chart, closing line, model vs market, breakdowns.
import {esc, num, prob, decOf, profitOf, fmtU, pct, spct, sign, cls, clvOf, fmtDay, byDateAsc, isW, isL, GRADED, state, modelStats} from "./core.js?v=587c58a5b8";
import {lineChart} from "./charts.js?v=587c58a5b8";

const tile = (k, v, sub, c) => `<div class="tile"><div class="k">${k}</div><div class="v ${c || ""}">${v}</div><div class="s">${sub || "&nbsp;"}</div></div>`;

export function tilesHTML(compact){
  const s = modelStats();
  const wr = (s.W + s.L) ? s.W / (s.W + s.L) : null;
  const roi = s.staked ? s.units / s.staked : null;
  const beat = s.cl.filter(p => clvOf(p) > 0).length;
  const avgClv = s.cl.length ? s.cl.reduce((a, p) => a + clvOf(p), 0) / s.cl.length : null;
  const t = [
    tile("Record", `${s.W}-${s.L}-${s.P}`, "Won · lost · push"),
    tile("Units", s.g.length ? fmtU(s.units) : "0.00u", "Profit in units", cls(s.units)),
    tile("Win rate", wr === null ? "—" : pct(wr), s.be !== null ? `Break-even ${pct(s.be)}` : "Excludes pushes", wr !== null && s.be !== null ? (wr >= s.be ? "pos" : "neg") : ""),
    tile("ROI", roi === null ? "—" : spct(roi), s.staked ? `On ${s.staked.toFixed(2)}u staked` : "Return per unit bet", roi !== null ? cls(roi) : ""),
    tile("Streak", s.streak || "—", "Wins or losses in a row", s.streak ? (s.streak[0] === "W" ? "pos" : "neg") : ""),
    tile("Beat the close", s.cl.length ? `${beat}/${s.cl.length}` : "—", avgClv !== null ? `Average CLV ${spct(avgClv)}` : "Price moved our way", avgClv !== null ? cls(avgClv) : "")
  ];
  return (compact ? t.slice(0, 4) : t).join("");
}

export function gradedCountText(){
  const s = modelStats();
  return `${s.g.length} graded · ${s.pending} pending`;
}

export function renderUnitsChart(el){
  if(!el) return;
  const g = state.picks.filter(p => GRADED.has(p.status)).sort(byDateAsc);
  if(!g.length){ el.innerHTML = `<p class="empty">The line starts once the first pick is graded.</p>`; return; }
  const pts = [{v: 0}]; let c = 0;
  for(const p of g){ c += profitOf(p); pts.push({v: c}); }
  const ax = v => { const av = Math.abs(v), lab = Number.isInteger(av) ? String(av) : av.toFixed(2).replace(/0$/, ""); return (v > 1e-9 ? "+" : v < -1e-9 ? "−" : "") + lab; };
  lineChart(el, pts, {base: 0, minSpan: 1, steps: [0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100], fmtAxis: ax, fmtEnd: fmtU,
    label: `Cumulative units: ${fmtU(c)} after ${g.length} graded picks`, first: g[0].date, last: g[g.length - 1].date});
}

export function renderClv(el){
  if(!el) return;
  const rows = state.picks.filter(p => clvOf(p) !== null).sort(byDateAsc).reverse();
  if(!rows.length){ el.innerHTML = `<p class="empty">Fills in once a graded pick has its closing price recorded.</p>`; return; }
  const beat = rows.filter(p => clvOf(p) > 0).length;
  const avg = rows.reduce((a, p) => a + clvOf(p), 0) / rows.length;
  el.innerHTML = `<div class="stats">
      <div class="stat"><div class="k">Beat the close</div><div class="v">${beat} of ${rows.length}</div><div class="s">${pct(beat / rows.length, 0)} of picks</div></div>
      <div class="stat"><div class="k">Average CLV</div><div class="v ${cls(avg)}">${spct(avg)}</div><div class="s">Value against the closing price</div></div>
    </div>
    <div class="tbl"><table><thead><tr><th>Date</th><th class="wrapcell">Bet</th><th>Taken</th><th>Close</th><th>CLV</th></tr></thead><tbody>
    ${rows.slice(0, 8).map(p => `<tr><td>${esc(fmtDay(p.date, {weekday: undefined}))}</td><td class="wrapcell">${esc(p.bet || "")}</td><td>${decOf(p) ? decOf(p).toFixed(2) : "—"}</td><td>${num(p.close.odds_decimal) ? num(p.close.odds_decimal).toFixed(2) : "—"}</td><td class="${cls(clvOf(p))}">${spct(clvOf(p))}</td></tr>`).join("")}
    </tbody></table></div>
    ${rows.length < 30 ? `<p class="caveat">Small sample. Average CLV starts to mean something after about 30 picks.</p>` : ""}`;
}

export function renderMvm(el){
  if(!el) return;
  const rows = state.picks.filter(p => (p.status === "won" || p.status === "lost") && prob(p.model_prob) !== null && prob(p.fair_prob) !== null);
  if(!rows.length){ el.innerHTML = `<p class="empty">Fills in as picks priced by the model are graded. Lower Brier score means more accurate estimates.</p>`; return; }
  const y = p => p.status === "won" ? 1 : 0;
  const bm = rows.reduce((a, p) => a + Math.pow(prob(p.model_prob) - y(p), 2), 0) / rows.length;
  const bk = rows.reduce((a, p) => a + Math.pow(prob(p.fair_prob) - y(p), 2), 0) / rows.length;
  const closer = rows.filter(p => Math.abs(prob(p.model_prob) - y(p)) < Math.abs(prob(p.fair_prob) - y(p))).length;
  const gap = rows.reduce((a, p) => a + prob(p.model_prob) - prob(p.fair_prob), 0) / rows.length;
  const mx = Math.max(bm, bk, 0.3), better = bm < bk;
  el.innerHTML = `<div class="stats">
      <div class="stat"><div class="k">Closer to the result</div><div class="v">${closer} of ${rows.length}</div><div class="s">Model beat the market's estimate</div></div>
      <div class="stat"><div class="k">Average gap</div><div class="v">${sign(gap * 100)}${Math.abs(gap * 100).toFixed(1)} pts</div><div class="s">Our estimate above the market</div></div>
    </div>
    <h3 class="sub">Brier score, lower is better</h3>
    <div class="hbars">
      <div class="hb model"><span>Our model</span><span class="tr"><span class="fl" style="width:${(bm / mx * 100).toFixed(1)}%"></span></span><span class="n ${better ? "pos" : ""}">${bm.toFixed(3)}</span></div>
      <div class="hb"><span>Market</span><span class="tr"><span class="fl" style="width:${(bk / mx * 100).toFixed(1)}%"></span></span><span class="n ${!better ? "pos" : ""}">${bk.toFixed(3)}</span></div>
    </div>
    ${rows.length < 100 ? `<p class="caveat">Based on ${rows.length} graded pick${rows.length === 1 ? "" : "s"}. This needs about 100 before it says anything reliable.</p>` : ""}`;
}

export function renderBreakdowns(sportEl, confEl){
  const g = state.picks.filter(p => GRADED.has(p.status));
  const empty = `<p class="empty">Fills in as picks are graded.</p>`;
  if(!g.length){ if(sportEl) sportEl.innerHTML = empty; if(confEl) confEl.innerHTML = empty; return; }
  if(sportEl){
    const groups = {};
    for(const p of g){ const k = p.sport || "Other"; (groups[k] = groups[k] || []).push(p); }
    const rows = Object.keys(groups).map(k => { const a = groups[k]; const w = a.filter(p => isW(p.status)).length, l = a.filter(p => isL(p.status)).length, pu = a.length - w - l; const u = a.reduce((s, p) => s + profitOf(p), 0); return {k, w, l, pu, u}; }).sort((a, b) => b.u - a.u);
    sportEl.innerHTML = `<div class="tbl"><table><thead><tr><th>Sport</th><th>Record</th><th>Win %</th><th>Units</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(r.k)}</td><td>${r.w}-${r.l}${r.pu ? "-" + r.pu : ""}</td><td>${(r.w + r.l) ? pct(r.w / (r.w + r.l), 0) : "—"}</td><td class="${cls(r.u)}">${fmtU(r.u)}</td></tr>`).join("")}</tbody></table></div>`;
  }
  if(confEl){
    const crow = ["High", "Medium", "Low"].map(t => { const a = g.filter(p => String(p.confidence || "").toLowerCase() === t.toLowerCase() && p.status !== "push"); if(!a.length) return ""; const w = a.filter(p => isW(p.status)).length; const ests = a.map(p => prob(p.model_prob)).filter(v => v !== null); const est = ests.length ? ests.reduce((s, v) => s + v, 0) / ests.length : null; return `<tr><td>${t}</td><td>${a.length}</td><td>${est !== null ? pct(est, 0) : "—"}</td><td class="${est !== null ? (w / a.length >= est ? "pos" : "neg") : ""}">${pct(w / a.length, 0)}</td></tr>`; }).join("");
    confEl.innerHTML = crow ? `<div class="tbl"><table><thead><tr><th>Confidence</th><th>Picks</th><th>Estimated</th><th>Actual</th></tr></thead><tbody>${crow}</tbody></table></div>` : empty;
  }
}

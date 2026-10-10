// Responsive SVG line chart used for units and bankroll.
import {esc, fmtDay} from "./core.js?v=95b2cd7a35";

export function lineChart(el, pts, o){
  const W = Math.max(300, Math.round(el.clientWidth || 640)), H = W < 480 ? 190 : 230;
  const L = o.left || 40, R = 64, T = 14, B = 26;
  const vals = pts.map(p => p.v);
  let lo = Math.min(o.base, ...vals), hi = Math.max(o.base, ...vals);
  if(hi - lo < o.minSpan){ hi += o.minSpan / 2; lo -= o.minSpan / 2; }
  const step = o.steps.find(s => (hi - lo) / s <= 5) || o.steps[o.steps.length - 1] * 2;
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const x = i => L + i * (W - L - R) / Math.max(1, pts.length - 1);
  const y = v => T + (hi - v) * (H - T - B) / (hi - lo);
  let grid = "";
  for(let v = lo; v <= hi + 1e-9; v += step){
    const yy = y(v).toFixed(1), isBase = Math.abs(v - o.base) < 1e-9;
    grid += `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" stroke="${isBase ? "var(--ink-3)" : "var(--rule)"}" stroke-width="1" ${isBase ? 'stroke-dasharray="4 4"' : ""}/>`;
    grid += `<text class="ax" x="${L - 8}" y="${(+yy + 4).toFixed(1)}" text-anchor="end">${o.fmtAxis(v)}</text>`;
  }
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(pts.length - 1).toFixed(1)},${y(o.base).toFixed(1)} L${x(0).toFixed(1)},${y(o.base).toFixed(1)} Z`;
  const endV = pts[pts.length - 1].v, ex = x(pts.length - 1), ey = y(endV);
  el.innerHTML = (o.caption ? `<h3 class="sub">${esc(o.caption)}</h3>` : "") + `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label)}">
    ${grid}
    <path d="${area}" fill="var(--accent)" fill-opacity="0.12" stroke="none"/>
    <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="2.25" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="4.5" fill="var(--accent)" stroke="var(--card)" stroke-width="2"/>
    <text class="end" x="${(ex + 9).toFixed(1)}" y="${(ey + 4).toFixed(1)}">${o.fmtEnd(endV)}</text>
    ${o.first ? `<text class="ax" x="${L}" y="${H - 6}">${esc(fmtDay(o.first, {weekday: undefined}))}</text>` : ""}
    ${o.last && o.last !== o.first ? `<text class="ax" x="${W - R}" y="${H - 6}" text-anchor="end">${esc(fmtDay(o.last, {weekday: undefined}))}</text>` : ""}
  </svg>`;
}

// Error finder page: reads the scanner output from the feed branch (refreshed three times a day).
import {$, esc, fmtTime, fmtStamp} from "./core.js";
import {bankState, bankStats, riskMult, fmt$} from "./bank.js";

const stakeFor = units => { if(!bankState.loaded) return null; const s = bankStats(); const v = (units || 0) / 100 * Math.max(0, s.balance + s.inPlay) * riskMult(); return v <= 0 ? null : v < 10 ? Math.max(0.1, Math.round(v * 10) / 10) : Math.round(v * 2) / 2; };

const FEED = "https://raw.githubusercontent.com/JohnFitz-z/JohnFitz-z.github.io/feed/errors/";
const err = {data: null, log: null, failed: false};
const pct = (n, d = 1) => (n >= 0 ? "+" : "−") + Math.abs(n * 100).toFixed(d) + "%";
const tile = (k, v, sub, c) => `<div class="tile"><div class="k">${k}</div><div class="v ${c || ""}">${v}</div><div class="s">${sub || "&nbsp;"}</div></div>`;
const TYPE = {stale: "Same bet, Pinnacle cheaper", offline: "Line Pinnacle doesn't offer", self: "Stake disagrees with itself"};
const SPORT = {soccer: "Soccer", basketball: "Basketball", "ice-hockey": "Hockey", baseball: "Baseball", tennis: "Tennis", "american-football": "Football"};

async function getJSON(name){
  const r = await fetch(FEED + name + "?t=" + Date.now(), {cache: "no-store"});
  if(!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

export const errorsData = () => err.data;

export async function loadErrors(){
  try {
    err.data = await getJSON("latest.json");
    const m = new Date().toISOString().slice(0, 7);
    try { err.log = await getJSON(`log/${m}.json`); } catch(e){ err.log = null; }
    err.failed = false;
  } catch(e){ err.failed = true; }
}

function card(e){
  const start = fmtTime(e.start_time);
  const league = [SPORT[e.sport] || e.sport, e.country, e.league].filter(Boolean).map(esc).join(" · ");
  return `<div class="prow" style="grid-template-columns:1fr auto;align-items:center">
    <span class="c-bet">
      <span class="b2" style="display:block">${league}</span>
      <span class="b1" style="display:block">${esc(e.outcome)} · ${esc(e.market)}</span>
      <span class="b2" style="display:block">${esc(e.home)} vs ${esc(e.away)} · ${esc(start)}</span>
      <span class="b2" style="display:block">Stake <b>${Number(e.stake_price).toFixed(2)}</b> · fair ${Number(e.fair_odds).toFixed(2)}${e.pinnacle_price ? " · Pinnacle " + Number(e.pinnacle_price).toFixed(2) : ""} · take at <b>${Number(e.take_at).toFixed(2)}+</b> · ${stakeFor(e.units) ? "bet <b>" + fmt$(stakeFor(e.units)) + "</b>" : e.units + "u"}</span>
      <span class="b2" style="display:block"><b>${esc(TYPE[e.type] || "")}</b>${e.why ? ": " + esc(e.why) : ""}${e.model_goals ? " Expected goals: " + esc(e.model_goals) + "." : ""}</span>
      ${e.steam ? `<span class="b2 pos" style="display:block">${esc(e.steam)}</span>` : ""}
    </span>
    <span style="text-align:right">
      <span class="v pos" style="display:block;font-size:1.25rem;font-weight:700">${pct(e.ev)}</span>
      ${e.stake_link ? `<a href="${esc(e.stake_link)}" target="_blank" rel="noopener" class="b2">Open on Stake →</a>` : ""}
    </span>
  </div>`;
}

export function renderErrors(){
  const tiles = $("#errTiles"), list = $("#errList"), rec = $("#errRecord"), stamp = $("#errStamp");
  if(!list) return;
  if(err.failed || !err.data){
    list.innerHTML = `<p class="empty">${err.failed ? "Couldn't load the error finder yet. It appears after its first scan." : "Loading…"}</p>`;
    return;
  }
  const d = err.data, errors = d.errors || [];
  const when = d.scanned_at || d.checked_at;
  if(stamp) stamp.textContent = when ? "Scanned " + fmtStamp(when) : "";
  const m = d.month || {};
  tiles.innerHTML =
    tile("Live errors", String(errors.length), d.markets_compared ? `${d.markets_compared} markets compared` : "") +
    tile("Biggest edge", errors.length ? pct(errors[0].ev) : "—", errors.length ? esc(errors[0].outcome) : "", errors.length ? "pos" : "") +
    tile("Flagged this month", String(m.flagged || 0), m.avg_ev != null ? "avg edge " + pct(m.avg_ev) : "") +
    tile("Beat the close", m.closed ? `${m.beat_close}/${m.closed}` : "—", m.avg_clv != null ? "avg CLV " + pct(m.avg_clv) : "after kick-off", m.avg_clv > 0 ? "pos" : (m.avg_clv < 0 ? "neg" : ""));
  if(d.status && d.status !== "ok"){
    list.innerHTML = `<div class="callout">${d.status === "waiting for key" ? "Waiting for the OddsPapi key. Add it as the ODDSPAPI_KEY secret on GitHub and the first scan runs at the next scheduled time." : esc(d.status)}</div>`
      + (errors.length ? errors.map(card).join("") : "");
  } else {
    list.innerHTML = errors.length ? errors.map(card).join("")
      : `<p class="empty">No errors right now. ${d.both_books || 0} games were checked against Pinnacle; Stake's prices were all at or below fair.</p>`;
  }
  const rows = err.log ? Object.values(err.log).sort((a, b) => b.first_seen.localeCompare(a.first_seen)) : [];
  rec.innerHTML = rows.length ? `<div class="tbl"><table>
      <thead><tr><th>Flagged</th><th>Bet</th><th>Stake</th><th>Edge</th><th>CLV</th></tr></thead>
      <tbody>${rows.slice(0, 40).map(r => `<tr>
        <td>${esc(fmtStamp(r.first_seen).split(",")[0])}</td>
        <td class="wrapcell">${esc(r.outcome)} · ${esc(r.market)}<br><span class="b2">${esc(r.home)} vs ${esc(r.away)}</span></td>
        <td>${Number(r.stake_price).toFixed(2)}</td>
        <td class="pos">${pct(r.ev)}</td>
        <td class="${r.closed ? (r.clv > 0 ? "pos" : "neg") : ""}">${r.closed ? pct(r.clv) : "open"}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="empty">Fills in as errors are flagged.</p>`;
}

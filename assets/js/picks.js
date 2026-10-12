// Views for a single pick: the ticket, how the number was built, the write-up, and list rows.
import {esc, num, prob, decOf, amOf, amFromDec, unitsOf, profitOf, evOf, sign, fmtU, pct, spct, cls, list, clvOf, pickUrl,
        STATUS, GRADED, fmtDay, fmtTime, todayISO} from "./core.js?v=2c1dc196fa";
import {stakeOf, myProfit, sfmt$, fmt$, suggested, choiceOf} from "./bank.js?v=2c1dc196fa";
import {planStakes} from "./money.js?v=2c1dc196fa";

function ladderHTML(p){
  const m = p.model || {}, d = decOf(p);
  const steps = (m.steps || []).filter(s => num(s.prob) !== null);
  if(!steps.length || !d) return "";
  const need = 1 / d;
  const vals = steps.map(s => s.prob).concat([need]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max(0.015, (hi - lo) * 0.18);
  lo = Math.max(0, Math.floor((lo - pad) * 100) / 100); hi = Math.min(1, Math.ceil((hi + pad) * 100) / 100);
  const X = v => (((v - lo) / (hi - lo)) * 100).toFixed(2);
  const mk = steps.find(s => s.key === "market");
  let chain = null;
  const rows = steps.map(s => {
    let bar = "", delta = "";
    if(s.key === "market"){ chain = s.prob; }
    else if(s.key === "blend" || s.key === "adj" || (s.key === "final" && chain !== null)){
      const from = s.key === "final" ? (mk ? mk.prob : chain) : (chain === null ? s.prob : chain);
      const a = Math.min(from, s.prob), b = Math.max(from, s.prob);
      if(b - a > 0.0004) bar = `<span class="lbar ${s.prob < from ? "down" : ""}" style="left:${X(a)}%;width:${(X(b) - X(a)).toFixed(2)}%"></span>`;
      const dd = s.prob - from;
      if(s.key !== "final" || mk) delta = `<span class="ld ${cls(dd)}">${sign(dd * 100)}${Math.abs(dd * 100).toFixed(1)}</span>`;
      if(s.key !== "final") chain = s.prob;
    }
    let sub = s.detail || "";
    if(s.key === "adj" && s.size) sub = s.size[0].toUpperCase() + s.size.slice(1) + (sub ? " · " + sub : "");
    return `<div class="lrow k-${esc(s.key)}">
      <div class="lname">${esc(s.label)}${sub ? `<span class="lsub">${esc(sub)}</span>` : ""}</div>
      <div class="ltrack"><span class="lneed" style="left:${X(need)}%"></span>${bar}<span class="ldot" style="left:${X(s.prob)}%"></span></div>
      <div class="lval">${pct(s.prob)}${delta}</div></div>`;
  }).join("");
  const needX = +X(need);
  const tf = needX < 18 ? "transform:none" : needX > 82 ? "transform:translateX(-100%)" : "";
  const books = Array.isArray(m.books) ? m.books : [];
  const notes = [m.inputs_text].concat(Array.isArray(m.notes) ? m.notes : []).filter(Boolean);
  return `<div><h3 class="sub">How the number was built</h3>
    <div class="ladder">${rows}</div>
    <div class="laxis"><div class="ax"><span style="left:0">${Math.round(lo * 100)}%</span><span style="right:0">${Math.round(hi * 100)}%</span><span class="need" style="left:${needX}%;${tf}">Price needs ${pct(need)}</span></div></div>
    ${notes.length ? `<div class="mnotes">${notes.map(n => `<span>${esc(n)}</span>`).join("")}</div>` : ""}
    ${books.length ? `<details class="books"><summary>Prices used (${books.length} book${books.length === 1 ? "" : "s"})</summary><div class="mini"><table><thead><tr><th>Book</th><th>Price</th><th>Decimal</th><th>Fair</th><th>Margin</th></tr></thead><tbody>${books.map(b => `<tr><td>${esc(b.book)}</td><td>${esc(b.price)}</td><td>${num(b.decimal) ? num(b.decimal).toFixed(2) : "—"}</td><td>${num(b.fair) !== null ? pct(num(b.fair)) : "—"}</td><td>${num(b.margin) !== null ? pct(num(b.margin)) : "—"}</td></tr>`).join("")}</tbody></table></div></details>` : ""}
  </div>`;
}

function priceGuideHTML(p){
  const minD = num(p.min_odds_decimal) || num(p.model && p.model.min_odds_decimal);
  const fairD = num(p.model && p.model.fair_odds_decimal);
  const mf = prob(p.fair_prob);
  if(!minD && !fairD && mf === null) return "";
  const item = (k, v, s, main) => `<div class="pg ${main ? "main" : ""}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  return `<div class="pguide">
    ${item("Take at", minD ? minD.toFixed(2) + "+" : "—", minD ? amFromDec(minD) + " or better" : "", true)}
    ${item("Our fair price", fairD ? fairD.toFixed(2) : "—", prob(p.model_prob) !== null ? pct(prob(p.model_prob)) + " chance" : "")}
    ${item("Market fair price", mf ? (1 / mf).toFixed(2) : "—", mf !== null ? pct(mf) + ", margin removed" : "")}
  </div>`;
}

function legacyEdge(p){
  const dec = decOf(p), mod = prob(p.model_prob);
  let imp = prob(p.implied_prob); if(imp === null && dec) imp = 1 / dec;
  if(mod === null || imp === null) return "";
  const e = mod - imp, lo = Math.min(mod, imp), w = Math.abs(e);
  return `<div class="edge"><div class="lbls"><span>Odds imply <b>${pct(imp)}</b></span><span>Our estimate <b>${pct(mod)}</b></span><span class="e">Edge ${sign(e * 100)}${Math.abs(e * 100).toFixed(1)} pts</span></div>
    <div class="bar" role="img" aria-label="Odds imply ${pct(imp)}, estimate ${pct(mod)}"><div class="mkt" style="width:${(imp * 100).toFixed(2)}%"></div><div class="gap ${e < 0 ? "neg" : ""}" style="left:${(lo * 100).toFixed(2)}%;width:${(w * 100).toFixed(2)}%"></div></div></div>`;
}

const KEY_NAME = {main: "the top pick", b1: "backup 1", b2: "backup 2"};

// Every bet on a day's list, best first: the top pick, then the rest of the card. Backups are not shown.
export const betsOf = p => [Object.assign({}, p, {key: "main"})].concat((Array.isArray(p.card) ? p.card : []).map(c => Object.assign({}, c)));
export const betId = (p, b) => b.key === "main" ? p.id : `${p.id}:${b.key}`;
const norm = s => { const v = String(s || "pending").toLowerCase().replace("-", "_"); return STATUS[v] ? v : "pending"; };

function betRow(p, b, i, stakes){
  const st = norm(b.status), pc = (p.price_check || {})[b.key];
  const d = num(b.odds_decimal), minD = num(b.min_odds_decimal);
  const now = pc && num(pc.odds_decimal);
  const gone = st === "pending" && pc && pc.value === false;
  const amt = stakes ? stakes.get(betId(p, b)) : null;
  const why = b.key === "main" ? (b.note || p.summary) : b.note;
  const res = GRADED.has(st) || st === "void" ? esc(b.final_score || "") : "";
  const meta = [b.sport, fmtTime(b.start_time), b.confidence ? b.confidence + " confidence" : ""].filter(Boolean).join(" · ");
  return `<div class="bet-row${gone ? " skip" : ""}">
    <div class="br-n">${i + 1}</div>
    <div class="br-main">
      <div class="b1">${b.key === "main" ? `<a href="${pickUrl(p)}">${esc(b.bet || "")}</a>` : esc(b.bet || "")}</div>
      <div class="b2">${esc(b.event || "")}${meta ? " · " + esc(meta) : ""}</div>
      ${why ? `<div class="br-why">${esc(why)}</div>` : ""}
      ${gone ? `<div class="b2 neg">Price moved to ${now.toFixed(2)}. No longer worth it: skip.</div>` : ""}
      ${res ? `<div class="b2">${res}</div>` : ""}
    </div>
    <div class="br-side">
      <div class="br-odds">${d ? d.toFixed(2) : "—"}</div>
      <div class="b2">${!gone && now && Math.abs(now - d) > 0.004 ? `now ${now.toFixed(2)} · ` : ""}take ${minD ? minD.toFixed(2) : "—"}+</div>
      ${amt && st === "pending" && !gone ? `<div class="br-amt">Bet ${fmt$(amt)}</div>` : ""}
      <span class="pill ${st}">${STATUS[st]}</span>
    </div>
  </div>`;
}

export function listHTML(p, stakes){
  return `<div class="bet-list">${betsOf(p).map((b, i) => betRow(p, b, i, stakes)).join("")}</div>`;
}

function cardHTML(p){
  const cs = Array.isArray(p.card) ? p.card : [];
  if(!cs.length) return "";
  return `<div><h3 class="sub">The full list for this day: ${cs.length + 1} bets</h3>${listHTML(p)}</div>`;
}

function priceCheckHTML(p){
  const pc = p.price_check;
  if(!pc || !pc.at || p.status !== "pending") return "";
  const when = new Date(pc.at);
  const t = isNaN(when) ? "" : new Intl.DateTimeFormat("en-US", {timeZone: "America/Halifax", hour: "numeric", minute: "2-digit"}).format(when);
  const m = pc.main || {};
  if(!num(m.odds_decimal)) return "";
  const ok = m.value !== false;
  const msg = ok ? `Still good at ${num(m.odds_decimal).toFixed(2)}. Take it at ${num(m.min_odds_decimal) ? num(m.min_odds_decimal).toFixed(2) : "the take-at price"} or better.`
                 : `The price moved to ${num(m.odds_decimal).toFixed(2)}, so it's no longer worth betting. Skip it if you haven't placed it.`;
  return `<div class="pcheck ${ok ? "ok" : "bad"}"><b>Price check${t ? " · " + t : ""}</b><span>${msg}</span></div>`;
}

function resultHTML(p){
  if(!(GRADED.has(p.status) || p.status === "void")) return "";
  const pl = profitOf(p), c = clvOf(p);
  const close = c !== null ? ` · Closed ${num(p.close.odds_decimal) ? num(p.close.odds_decimal).toFixed(2) : "?"}, CLV ${spct(c)}` : "";
  const mine = stakeOf(p) > 0 && choiceOf(p) === "main" ? ` · You ${sfmt$(myProfit(p))}` : "";
  return `<div class="result ${esc(p.status)}"><span class="pill ${esc(p.status)}">${STATUS[p.status]}</span><span>${esc(p.final_score || "")}</span><span class="mono">${fmtU(pl)}${mine}${close}</span></div>`;
}

export function detailHTML(p){
  const out = [];
  const hasModel = p.model && Array.isArray(p.model.steps) && p.model.steps.length;
  if(!hasModel){ const le = legacyEdge(p); if(le) out.push(le); }
  out.push(priceCheckHTML(p));
  if(p.summary) out.push(`<p class="thesis">${esc(p.summary)}</p>`);
  out.push(resultHTML(p));
  if(hasModel) out.push(priceGuideHTML(p));
  const why = list(p.reasoning);
  if(why.length) out.push(`<div><h3 class="sub">Why this bet</h3><ul class="pts">${why.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`);
  const risks = list(p.risks);
  if(risks.length) out.push(`<div><h3 class="sub">What could go wrong</h3><ul class="pts risks">${risks.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`);
  out.push(cardHTML(p));
  const alts = (Array.isArray(p.passed) ? p.passed.map(a => ({bet: a.bet, event: a.event, note: a.why})) : []).concat(Array.isArray(p.candidates) ? p.candidates : []);
  const more = (hasModel ? ladderHTML(p) : "")
    + (alts.length ? `<div><h3 class="sub">Also looked at</h3><div class="alts">${alts.map(a => typeof a === "string" ? `<div class="alt"><span class="a2">${esc(a)}</span></div>` : `<div class="alt"><span class="a1">${esc(a.bet || "")}${a.event ? " · " + esc(a.event) : ""}</span><span class="a2">${esc(a.note || a.reason || "")}</span></div>`).join("")}</div></div>` : "");
  if(more) out.push(`<details class="more-detail"><summary>How the number was built</summary>${more}</details>`);
  const srcs = Array.isArray(p.sources) ? p.sources : [];
  const links = srcs.map(s => { const u = typeof s === "string" ? s : (s && s.url); const t = typeof s === "string" ? s.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] : (s.title || s.url); return /^https?:\/\//.test(u || "") ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>` : ""; }).filter(Boolean);
  if(links.length) out.push(`<div><h3 class="sub">Sources</h3><div class="srcs">${links.join("")}</div></div>`);
  return out.filter(Boolean).join("");
}

// The home page: today's whole list in one place.
function errorRow(e, i){
  return `<div class="bet-row">
    <div class="br-n">${i}</div>
    <div class="br-main"><div class="b1">${esc(e.label)}</div><div class="b2">${esc(e.sub)} · Error finder</div>
      <div class="br-why">Stake is paying more than the fair price here (edge ${(e.ev * 100).toFixed(1)}%). These get corrected fast.${e.link ? ` <a href="${esc(e.link)}" target="_blank" rel="noopener">Open on Stake →</a>` : ""}</div></div>
    <div class="br-side"><div class="br-odds">${Number(e.odds).toFixed(2)}</div><div class="b2">take ${e.takeAt ? Number(e.takeAt).toFixed(2) : "—"}+</div>${e.stake ? `<div class="br-amt">Bet ${fmt$(e.stake)}</div>` : ""}</div>
  </div>`;
}

export function todayHTML(p, stakes, errs){
  const isToday = p.date === todayISO(), bets = betsOf(p);
  const open = bets.filter(b => norm(b.status) === "pending").length;
  const label = isToday ? "Today's bets" : "Latest list · " + esc(fmtDay(p.date));
  const total = (stakes ? bets.filter(b => norm(b.status) === "pending").reduce((a, b) => a + (stakes.get(betId(p, b)) || 0), 0) : 0)
    + (isToday && errs ? errs.reduce((a, e) => a + (e.stake || 0), 0) : 0);
  return `
    <div class="t-head">
      <div class="t-eyebrow">
        <div class="l"><span class="chip">${label}</span></div>
        <div class="l"><span class="when">${bets.length} bet${bets.length === 1 ? "" : "s"}${open && open < bets.length ? ` · ${open} still to play` : ""}</span></div>
      </div>
      <h2 class="t-bet" style="margin-top:12px">${isToday ? (open ? `${bets.length} bet${bets.length === 1 ? "" : "s"} today` : "Today's bets are all in") : "Today's list posts by 10 AM"}</h2>
      <div class="t-event">${isToday ? `Place them early, each at its take-at price or better.${total ? ` Total to bet: <b>${fmt$(total)}</b>.` : ""}` : "Here's the most recent list until then."}</div>
    </div>
    <div class="perf" aria-hidden="true"></div>
    <div class="t-body">
      ${listHTML(p, stakes)}
      ${errs && errs.length && p.date === todayISO() ? `<h3 class="sub">Live now from the error finder</h3><div class="bet-list">${errs.map((e, i) => errorRow(e, betsOf(p).length + i + 1)).join("")}</div>` : ""}
      <p class="caveat">Amounts come from your money plan on the <a href="/bankroll/">Bankroll</a> page. Tap a bet there to log it. <a href="${pickUrl(p)}">Full write-up →</a></p>
    </div>`;
}

// mode "detail": a pick's own page.
export function ticketHTML(p, mode){
  const today = todayISO(), isToday = p.date === today, dec = decOf(p), ev = evOf(p);
  const st = STATUS[p.status] ? p.status : "pending";
  const minD = num(p.min_odds_decimal);
  const take = minD ? `<div class="take ${dec && dec < minD ? "warn" : ""}">Take at <b>${minD.toFixed(2)}</b> or better</div>` : "";
  const label = mode === "detail" ? (isToday ? "Today's pick" : esc(fmtDay(p.date, {weekday: "long", month: "long", day: "numeric", year: "numeric"})))
                                   : (isToday ? "Today's pick" : "Latest pick · " + esc(fmtDay(p.date)));
  const ps = planStakes(), sug = ps && ps.get(p.id) ? ps.get(p.id) : 0;
  const notice = mode === "today" && !isToday ? `<div class="notice">Today's pick hasn't posted yet. It lands at 10:00 AM Atlantic.</div>` : "";
  return `
    <div class="t-head">
      <div class="t-eyebrow">
        <div class="l"><span class="chip">${label}</span><span class="chip plain">${esc([p.sport, p.league && p.league !== p.sport ? p.league : ""].filter(Boolean).join(" · "))}</span></div>
        <div class="l"><span class="when">${esc(fmtTime(p.start_time) || "")}</span><span class="pill ${st}">${STATUS[st]}</span></div>
      </div>
      <div class="t-main">
        <div>${mode === "detail" ? `<h1 class="t-bet">${esc(p.bet || "")}</h1>` : `<h2 class="t-bet">${esc(p.bet || "")}</h2>`}<div class="t-event">${esc(p.event || "")}</div></div>
        <div class="t-odds"><div class="dec">${dec ? dec.toFixed(2) : "—"}</div><div class="am">${esc(amOf(p))} American</div>${take}</div>
      </div>
      <div class="t-facts">
        <div class="fact"><div class="k">Size</div><div class="v">${unitsOf(p)}u${sug > 0 ? `<span class="k" style="margin-left:6px">≈ ${fmt$(sug)}</span>` : ""}</div></div>
        <div class="fact"><div class="k">Confidence</div><div class="v">${esc(p.confidence || "—")}</div></div>
        <div class="fact"><div class="k">Expected value</div><div class="v ${ev !== null ? cls(ev) : ""}">${ev !== null ? spct(ev) : "—"}</div></div>
        <div class="fact"><div class="k">Market</div><div class="v">${esc(p.market || "—")}</div></div>
      </div>
    </div>
    <div class="perf" aria-hidden="true"></div>
    <div class="t-body">
      ${notice}
      ${p.no_edge ? `<div class="notice"><b>No clear edge today.</b> Nothing on the slate priced above break-even, so this is the closest call at the minimum stake.</div>` : ""}
      ${detailHTML(p)}
    </div>`;
}

export function rowHTML(p){
  const st = STATUS[p.status] ? p.status : "pending", pl = profitOf(p), dec = decOf(p), c = clvOf(p);
  const bits = [esc(p.event || ""), dec ? dec.toFixed(2) : "—", unitsOf(p) + "u"];
  if(p.confidence) bits.push(esc(p.confidence));
  if(c !== null) bits.push("CLV " + spct(c));
  return `<a class="prow" href="${pickUrl(p)}">
    <span class="c-date">${esc(fmtDay(p.date))}</span>
    <span class="c-sport">${esc(p.sport || "")}</span>
    <span class="c-bet"><span class="b1" style="display:block">${esc(p.bet || "")}</span><span class="b2" style="display:block">${bits.join(" · ")}</span></span>
    <span class="c-res"><span class="pill ${st}">${STATUS[st]}</span></span>
    <span class="c-pl ${cls(pl)}">${GRADED.has(st) ? fmtU(pl) : "—"}</span>
  </a>`;
}

// Money plan: how much to put on each of today's bets.
//  Normal mode  stakes from the bankroll and each bet's edge (engine units, 1u = 1% at quarter Kelly) x risk level.
//  Target mode  stakes that give the best chance of reaching a target balance by a date (see target.js).
// Either way, stakes never go up to chase a loss.
import {$, esc, num, unitsOf, evOf, todayPick, todayISO, fmtTime, state} from "./core.js?v=44bd56026e";
import {bankState, bankStats, fmt$, sfmt$, addExtra, Store, myProfit, extraProfit, extraResult, stakeOf, oddsTaken} from "./bank.js?v=44bd56026e";
import {errorsData} from "./errors.js?v=44bd56026e";
import {dayDP, bestPortfolio} from "./target.js?v=44bd56026e";

export const RISK = {
  steady: {label: "Steady", mult: 0.5, cap: 0.04, kelly: "1/8 Kelly", halve: "almost 0%"},
  standard: {label: "Standard", mult: 1, cap: 0.06, kelly: "1/4 Kelly", halve: "about 1%"},
  aggressive: {label: "Aggressive", mult: 2, cap: 0.12, kelly: "1/2 Kelly", halve: "about 13%"},
};

const settings = () => bankState.bank.money || (bankState.bank.money = {risk: "standard"});
const risk = () => RISK[settings().risk] || RISK.standard;
export const capital = () => { if(!bankState.loaded) return 0; const s = bankStats(); return Math.max(0, s.balance + s.inPlay); };
const round$ = v => v <= 0 ? 0 : v < 10 ? Math.max(0.1, Math.round(v * 10) / 10) : Math.round(v * 2) / 2;
export const dollarsFor = units => round$((units || 0) / 100 * capital() * risk().mult);

function endOfMonth(){ const d = new Date(todayISO() + "T12:00:00Z"); return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).toISOString().slice(0, 10); }
const deadline = () => settings().by || endOfMonth();
const daysLeft = () => Math.round((new Date(deadline() + "T12:00:00Z") - new Date(todayISO() + "T12:00:00Z")) / 864e5) + 1;
const perDay = () => settings().perDay || 10;
const targetOn = () => settings().mode === "target" && (settings().target || 0) > capital() && daysLeft() >= 1;

let dpCache = null;
function table(target, days, n, edge){
  const key = [target, days, n, edge].join("|");
  if(!dpCache || dpCache.key !== key) dpCache = {key, D: dayDP(target, days, n, edge)};
  return dpCache.D;
}

// ---- today's bets -----------------------------------------------------------------------------
const extraById = id => (bankState.bank.extras || []).find(x => x.id === id);
const legEv = l => { const p = (state.allPicks || []).find(x => x.id === l.pick); if(!p) return 0;
  const e = l.key === "main" ? p : (p.card || []).concat(p.backups || []).find(c => c.key === l.key); return e ? (evOf(e) || 0) : 0; };

function candidates(){
  const items = [], now = Date.now(), p = todayPick();
  const started = t => t && new Date(t).getTime() <= now;
  if(p){
    // The afternoon price check reprices every bet: use its odds, and drop a bet whose edge has gone.
    const pc = p.price_check || {};
    const fresh = (key, d) => { const c = pc[key]; return c && num(c.odds_decimal) ? {odds: num(c.odds_decimal), takeAt: num(c.min_odds_decimal), ev: num(c.ev) || 0, gone: c.value === false} : d; };
    const m = fresh("main", {odds: num(p.odds_decimal), takeAt: num(p.min_odds_decimal), ev: evOf(p) || 0});
    items.push({kind: "pick", gone: m.gone, id: p.id, key: "main", pickId: p.id, label: p.bet, sub: [p.event, fmtTime(p.start_time)].filter(Boolean).join(" · "),
      odds: m.odds, takeAt: m.takeAt, units: unitsOf(p), ev: m.ev, note: "Daily pick", start: p.start_time, parlayable: true});
    for(const c of p.card || []){
      const q = fresh(c.key, {odds: num(c.odds_decimal), takeAt: num(c.min_odds_decimal), ev: num(c.ev) || 0});
      items.push({kind: "card", gone: q.gone, id: `${p.id}:${c.key}`, key: c.key, pickId: p.id, date: p.date, label: c.bet,
        sub: [c.event, fmtTime(c.start_time)].filter(Boolean).join(" · "), odds: q.odds, takeAt: q.takeAt,
        units: num(c.units) || 0.25, ev: q.ev, note: "Card", start: c.start_time, parlayable: true});
    }
  }
  const ed = errorsData();
  let nErr = 0;
  for(const e of (ed && ed.errors) || []){
    if(nErr >= 5) break;
    nErr++;
    items.push({kind: "error", id: e.id, label: `${e.outcome} · ${e.market}`, sub: `${e.home} vs ${e.away} · ${fmtTime(e.start_time)}`,
      odds: e.stake_price, takeAt: e.take_at, units: e.units, ev: e.ev, date: e.start_time, start: e.start_time, link: e.stake_link, note: "Error finder"});
  }
  for(const i of items){
    if(i.kind === "pick"){ const s = p ? stakeOf(p) : 0; if(s > 0) i.logged = {stake: s, odds: oddsTaken(p)}; }
    else { const x = extraById(i.id); if(x && x.stake > 0) i.logged = {stake: x.stake, odds: x.odds}; }
  }
  // Logged parlays: their legs are already in play.
  const today = todayISO();
  const pars = (bankState.bank.extras || []).filter(x => x.legs && x.legs.length && String(x.date).slice(0, 10) === today && extraResult(x) === "pending");
  const inPar = new Set(pars.flatMap(x => x.legs.map(l => l.key === "main" ? l.pick : `${l.pick}:${l.key}`)));
  const out = items.filter(i => i.logged || (i.odds > 1 && i.ev > 0 && !i.gone && !started(i.start) && !inPar.has(i.id)));
  if(pars.length) for(const i of out) i.parlayable = false;
  return {items: out, pars};
}

// Bets already placed today that are still open (they change how much more to put down).
function placedToday(items){
  const fixed = items.filter(i => i.logged).map(i => ({odds: i.logged.odds || i.odds, ev: i.ev, stake: i.logged.stake}));
  const ids = new Set(items.map(i => i.id));
  const today = todayISO();
  for(const x of bankState.bank.extras || []){
    if(ids.has(x.id) || !(x.stake > 0) || extraResult(x) !== "pending" || String(x.date).slice(0, 10) !== today) continue;
    fixed.push({odds: x.odds, ev: x.legs && x.legs.length ? x.legs.reduce((a, l) => a * (1 + legEv(l)), 1) - 1 : 0, stake: x.stake});
  }
  return fixed;
}

export function todaysPlan(){
  const st = settings(), cap0 = capital();
  const {items, pars} = candidates();
  items.sort((a, b) => b.ev - a.ev);
  const target = targetOn();
  let chance = null, parlay = null, scaled = false;
  if(target && cap0 > 0){
    const open = items.filter(i => !i.logged);
    const avg = open.length ? open.reduce((a, i) => a + i.ev, 0) / open.length : 0.04;
    const edge = Math.round(Math.min(0.06, Math.max(0.01, avg)) * 200) / 200;
    const days = daysLeft(), D = table(st.target, days, perDay(), edge);
    const res = bestPortfolio(open, cap0, D, days, round$, placedToday(items));
    chance = res.chance;
    for(const i of items) i.stake = i.logged ? i.logged.stake : (res.stakes.get(i.id) || 0);
    if(res.parlay){
      const legs = res.parlay.parlay.map(id => items.find(i => i.id === id));
      parlay = {kind: "parlay", id: res.parlay.id, label: legs.map(l => l.label).join(" + "), sub: "2-leg parlay · both must win · different games",
        odds: Math.round(res.parlay.odds * 100) / 100, takeAt: legs.every(l => l.takeAt) ? Math.round(legs[0].takeAt * legs[1].takeAt * 100) / 100 : null,
        ev: res.parlay.ev, stake: res.stakes.get(res.parlay.id), note: "Parlay", legs: legs.map(l => ({pick: l.pickId, key: l.key}))};
    }
  } else {
    const cap = (st.cap || risk().cap) * cap0;
    const open = items.filter(i => !i.logged);
    const used = items.filter(i => i.logged).reduce((a, i) => a + i.logged.stake, 0);
    const want = open.reduce((a, i) => a + i.units / 100 * cap0 * risk().mult, 0);
    const room = Math.max(0, cap - used), scale = want > room && want > 0 ? room / want : 1;
    scaled = scale < 1;
    for(const i of items) i.stake = i.logged ? i.logged.stake : round$(i.units / 100 * cap0 * risk().mult * scale);
  }
  const shown = pars.map(x => ({kind: "parlay", id: x.id, label: String(x.label).replace(/^Parlay: /, ""), sub: "Parlay · both must win", odds: x.odds,
    ev: x.legs.reduce((a, l) => a * (1 + legEv(l)), 1) - 1, stake: x.stake, logged: {stake: x.stake, odds: x.odds}, note: "Parlay"}));
  const list = shown.concat(parlay ? [parlay] : [], items.filter(i => i.stake > 0));
  const fresh = list.filter(i => !i.logged);
  return {items: list, total: fresh.reduce((a, i) => a + i.stake, 0), placed: list.filter(i => i.logged).reduce((a, i) => a + i.stake, 0),
          expected: list.reduce((a, i) => a + i.stake * i.ev, 0), target, chance, scaled, parlayUsed: !!parlay, skipped: items.filter(i => !i.stake).length};
}

function monthProfit(){
  const s = bankStats(), m = todayISO().slice(0, 7);
  let v = 0;
  for(const p of s.settled) if(String(p.date).slice(0, 7) === m) v += myProfit(p);
  for(const x of s.xSettled) if(String(x.date).slice(0, 7) === m) v += extraProfit(x);
  return v;
}

const shortDate = iso => new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"});

export function renderMoney(force){
  const el = $("#moneyPlan"); if(!el) return;
  if(!force && el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  if(!bankState.loaded || !state.loaded){ el.innerHTML = `<p class="empty">Loading…</p>`; return; }
  const st = settings(), r = risk(), cap0 = capital();
  const plan = todaysPlan();
  const tmode = st.mode === "target";
  const rows = plan.items.map(i => `<div class="plan-row">
      <div class="pr-main"><div class="b2">${esc(i.note)} · edge ${(i.ev * 100).toFixed(1)}%</div><div class="b1">${esc(i.label)}</div><div class="b2">${esc(i.sub)}</div>
        <div class="b2">${i.odds ? Number(i.odds).toFixed(2) : ""}${i.takeAt ? ` · take it at <b>${Number(i.takeAt).toFixed(2)}+</b>` : ""}${i.link ? ` · <a href="${esc(i.link)}" target="_blank" rel="noopener">Open on Stake →</a>` : ""}</div></div>
      <div class="pr-amt"><div class="v">${fmt$(i.stake)}</div>${i.logged ? `<button type="button" class="btn" disabled>Logged ✓</button>` : `<button type="button" class="btn" data-log="${esc(i.id)}">Log it</button>`}</div>
    </div>`).join("");
  const goal = st.goal || 0, mp = monthProfit();
  const head = plan.items.length
    ? `${plan.total ? `Put down ${fmt$(plan.total)} more` : "All placed"}${plan.placed ? ` (${fmt$(plan.placed)} already on)` : ""} of ${fmt$(cap0)} · expected profit ${sfmt$(plan.expected)}${plan.scaled ? " · scaled down to your daily limit" : ""}`
    : "Nothing to bet right now. The daily card posts by 10 AM and the error finder scans every 3 hours.";
  let tLine = "";
  if(tmode){
    if(cap0 >= (st.target || 0)) tLine = `<p class="callout">Target reached: ${fmt$(cap0)}. Sizing is back to normal to protect it. Raise the target to keep going.</p>`;
    else if(daysLeft() < 1) tLine = `<p class="callout">The deadline has passed. Pick a new date to keep going.</p>`;
    else tLine = `<p class="callout"><b>Target: ${fmt$(st.target || 0)} by ${esc(shortDate(deadline()))}</b> (${daysLeft()} day${daysLeft() === 1 ? "" : "s"} left, including today). Chance of getting there from here: <b>${plan.chance !== null ? Math.round(plan.chance * 100) + "%" : "—"}</b>. These stakes are the ones that make that chance as high as it can be${plan.parlayUsed ? "; today that includes a 2-leg parlay" : ""}${plan.skipped ? `. ${plan.skipped} smaller-edge bet${plan.skipped === 1 ? " is" : "s are"} left out today` : ""}.</p>`;
  }
  el.innerHTML = `
    <div class="mm-set">
      <label><span class="k">Mode</span><select class="inp" id="mmMode"><option value="normal"${!tmode ? " selected" : ""}>Normal (steady growth)</option><option value="target"${tmode ? " selected" : ""}>Target (hit a number by a date)</option></select></label>
      ${tmode ? `
      <label><span class="k">Target balance ($)</span><input class="inp" id="mmTarget" type="number" min="1" step="10" inputmode="decimal" value="${st.target || ""}" placeholder="1000"></label>
      <label><span class="k">By</span><input class="inp" id="mmBy" type="date" value="${deadline()}"></label>
      <label><span class="k">Bets per day</span><input class="inp" id="mmPerDay" type="number" min="1" max="20" step="1" inputmode="numeric" value="${perDay()}"></label>` : `
      <label><span class="k">Risk level</span><select class="inp" id="mmRisk">${Object.entries(RISK).map(([k, v]) => `<option value="${k}"${st.risk === k ? " selected" : ""}>${v.label}</option>`).join("")}</select></label>
      <label><span class="k">Daily limit (% of bankroll)</span><input class="inp" id="mmCap" type="number" min="1" max="50" step="1" inputmode="decimal" value="${Math.round((st.cap || r.cap) * 100)}"></label>
      <label><span class="k">Monthly goal ($)</span><input class="inp" id="mmGoal" type="number" min="0" step="1" inputmode="decimal" placeholder="e.g. 50" value="${st.goal || ""}"></label>`}
    </div>
    ${tmode ? tLine : `<p class="b2 mm-note">${esc(r.label)} bets ${r.kelly}: each bet is sized from your bankroll and its edge. If the edges are real, the chance of ever dropping to half your bankroll is ${r.halve}.</p>`}
    <div class="ph" style="margin-top:14px"><div><h2>Today's bets</h2><p>${head}</p></div></div>
    ${rows}
    ${!tmode ? `<div class="ph" style="margin-top:14px"><div><h2>Monthly goal</h2><p>${goal ? `${sfmt$(mp)} of ${fmt$(goal)} this month` : "Set a goal to track it here."}</p></div></div>
    ${goal ? `<div class="goalbar"><span style="width:${Math.max(0, Math.min(100, mp / goal * 100)).toFixed(1)}%"></span></div>` : ""}` : ""}`;
}

export function initMoney(onChange){
  const changed = e => {
    const t = e.target, st = settings();
    if(t.id === "mmRisk"){ st.risk = RISK[t.value] ? t.value : "standard"; delete st.cap; }
    else if(t.id === "mmMode"){ st.mode = t.value === "target" ? "target" : "normal"; if(st.mode === "target" && !st.target) st.target = 1000; }
    else if(t.id === "mmCap"){ const v = num(t.value); if(v !== null && v >= 1 && v <= 50) st.cap = v / 100; else return; }
    else if(t.id === "mmGoal"){ const v = num(t.value); if(v !== null && v > 0) st.goal = Math.round(v * 100) / 100; else delete st.goal; }
    else if(t.id === "mmTarget"){ const v = num(t.value); if(v !== null && v > 0) st.target = Math.round(v); else return; }
    else if(t.id === "mmBy"){ if(/^\d{4}-\d{2}-\d{2}$/.test(t.value)) st.by = t.value; else return; }
    else if(t.id === "mmPerDay"){ const v = num(t.value); if(v !== null && v >= 1 && v <= 20) st.perDay = Math.round(v); else return; }
    else return;
    bankState.dirty = true; Store.save(bankState.bank);
    if(t.tagName === "SELECT") renderMoney(true); else updateTexts();
    onChange();
  };
  document.addEventListener("input", changed);
  document.addEventListener("click", e => {
    const t = e.target;
    if(!t || !t.dataset || !t.dataset.log) return;
    const item = todaysPlan().items.find(i => i.id === t.dataset.log);
    if(!item) return;
    const day = String(item.date || todayISO()).slice(0, 10);
    if(item.kind === "pick"){
      const bets = bankState.bank.bets, cur = Object.assign({}, bets[item.id] || {});
      cur.stake = item.stake; delete cur.choice; bets[item.id] = cur;
    } else if(item.kind === "card"){
      addExtra({id: item.id, ref: {pick: item.pickId, key: item.key}, date: day, label: `${item.label} (${item.sub.split(" · ")[0]})`, odds: item.odds, stake: item.stake});
    } else if(item.kind === "parlay"){
      addExtra({id: item.id, legs: item.legs, date: todayISO(), label: `Parlay: ${item.label}`, odds: item.odds, stake: item.stake});
    } else {
      addExtra({id: item.id, date: day, label: `${item.label} (${item.sub.split(" · ")[0]})`, odds: item.odds, stake: item.stake});
    }
    bankState.dirty = true; Store.save(bankState.bank);
    t.textContent = "Logged ✓"; t.disabled = true;
    onChange();
  });
}

function updateTexts(){ const a = document.activeElement; const id = a && a.id; renderMoney(true); if(id){ const n = document.getElementById(id); if(n){ n.focus(); try { n.setSelectionRange(n.value.length, n.value.length); } catch(err){} } } }

// Money manager: how much to put on each bet today, a daily limit, and a monthly goal.
// Stakes come from the bankroll and each bet's edge (the engine's units, 1 unit = 1% of the
// bankroll at quarter Kelly), scaled by the chosen risk level. A goal never raises stakes.
import {$, esc, num, unitsOf, todayPick, todayISO, fmtTime} from "./core.js?v=95b2cd7a35";
import {bankState, bankStats, fmt$, sfmt$, addExtra, Store, choiceOf, myProfit, extraProfit} from "./bank.js?v=95b2cd7a35";
import {errorsData} from "./errors.js?v=95b2cd7a35";

export const RISK = {
  steady: {label: "Steady", mult: 0.5, cap: 0.04, kelly: "1/8 Kelly", halve: "almost 0%"},
  standard: {label: "Standard", mult: 1, cap: 0.06, kelly: "1/4 Kelly", halve: "about 1%"},
  aggressive: {label: "Aggressive", mult: 2, cap: 0.12, kelly: "1/2 Kelly", halve: "about 13%"},
};

const settings = () => bankState.bank.money || (bankState.bank.money = {risk: "standard"});
const risk = () => RISK[settings().risk] || RISK.standard;
export const capital = () => { if(!bankState.loaded) return 0; const s = bankStats(); return Math.max(0, s.balance + s.inPlay); };
const round$ = v => v <= 0 ? 0 : v < 10 ? Math.max(0.1, Math.round(v * 10) / 10) : Math.round(v * 2) / 2;

// Dollar stake for a bet sized in units, before the daily limit.
export const dollarsFor = units => round$((units || 0) / 100 * capital() * risk().mult);

// Today's bets: the daily pick (or the backup the price check switched to) plus live error finder bets,
// sized from the bankroll and scaled down together if they'd go over the daily limit.
export function todaysPlan(){
  const items = [];
  const p = todayPick();
  if(p){
    const rec = p.price_check && p.price_check.recommend;
    const key = rec && rec !== "none" && rec !== "main" ? rec : (choiceOf(p) !== "main" ? choiceOf(p) : "main");
    const bet = key === "main" ? p : (p.backups || []).find(b => b.key === key) || p;
    const skip = rec === "none";
    items.push({kind: "pick", id: p.id, key, label: bet.bet || p.bet, sub: (bet.event || p.event || "") + (bet.start_time ? " · " + fmtTime(bet.start_time) : ""),
                odds: num(bet.odds_decimal), takeAt: num(bet.min_odds_decimal), units: unitsOf(bet), ev: num(bet.ev) || 0, skip,
                note: skip ? "The price check found no value at current prices, so skip it today." : key !== "main" ? `Backup ${key.slice(1)} (the price check switched to it).` : "Daily pick."});
  }
  const ed = errorsData();
  const now = Date.now();
  for(const e of (ed && ed.errors) || []){
    if(new Date(e.start_time).getTime() <= now) continue;
    if(items.filter(i => i.kind === "error").length >= 3) break;
    items.push({kind: "error", id: e.id, label: `${e.outcome} · ${e.market}`, sub: `${e.home} vs ${e.away} · ${fmtTime(e.start_time)}`,
                odds: e.stake_price, takeAt: e.take_at, units: e.units, ev: e.ev, date: e.start_time, link: e.stake_link, note: "Error finder."});
  }
  const cap = (settings().cap || risk().cap) * capital();
  let total = items.filter(i => !i.skip).reduce((a, i) => a + i.units / 100 * capital() * risk().mult, 0);
  const scale = total > cap && total > 0 ? cap / total : 1;
  for(const i of items) i.stake = i.skip ? 0 : round$(i.units / 100 * capital() * risk().mult * scale);
  total = items.reduce((a, i) => a + i.stake, 0);
  const expected = items.reduce((a, i) => a + i.stake * i.ev, 0);
  return {items, total, cap, scaled: scale < 1, expected};
}

function monthProfit(){
  const s = bankStats(), m = todayISO().slice(0, 7);
  let v = 0;
  for(const p of s.settled) if(String(p.date).slice(0, 7) === m) v += myProfit(p);
  for(const x of s.xSettled) if(String(x.date).slice(0, 7) === m) v += extraProfit(x);
  return v;
}

export function renderMoney(force){
  const el = $("#moneyPlan"); if(!el) return;
  if(!force && el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  if(!bankState.loaded){ el.innerHTML = `<p class="empty">Loading…</p>`; return; }
  const st = settings(), r = risk(), cap0 = capital();
  const plan = todaysPlan();
  const rows = plan.items.map(i => `<div class="plan-row${i.skip ? " skip" : ""}">
      <div class="pr-main"><div class="b2">${esc(i.note)}</div><div class="b1">${esc(i.label)}</div><div class="b2">${esc(i.sub)}</div>
        <div class="b2">Take it at <b>${i.takeAt ? Number(i.takeAt).toFixed(2) : "—"}+</b>${i.link ? ` · <a href="${esc(i.link)}" target="_blank" rel="noopener">Open on Stake →</a>` : ""}</div></div>
      <div class="pr-amt"><div class="v">${i.skip ? "Skip" : fmt$(i.stake)}</div>${i.skip ? "" : `<button type="button" class="btn" data-log="${esc(i.id)}" data-kind="${i.kind}">Log it</button>`}</div>
    </div>`).join("");
  const goal = st.goal || 0, mp = monthProfit();
  const monthlyExp = plan.expected * 30;
  const needBank = goal && monthlyExp > 0 ? cap0 * goal / monthlyExp : null;
  el.innerHTML = `
    <div class="mm-set">
      <label><span class="k">Risk level</span>
        <select class="inp" id="mmRisk">${Object.entries(RISK).map(([k, v]) => `<option value="${k}"${st.risk === k ? " selected" : ""}>${v.label}</option>`).join("")}</select></label>
      <label><span class="k">Daily limit (% of bankroll)</span><input class="inp" id="mmCap" type="number" min="1" max="50" step="1" inputmode="decimal" value="${Math.round((st.cap || r.cap) * 100)}"></label>
      <label><span class="k">Monthly goal ($)</span><input class="inp" id="mmGoal" type="number" min="0" step="1" inputmode="decimal" placeholder="e.g. 50" value="${st.goal || ""}"></label>
    </div>
    <p class="b2 mm-note">${esc(r.label)} bets ${r.kelly}: each bet is sized from your bankroll and its edge. If the edges are real, the chance of ever dropping to half your bankroll is ${r.halve}. Stakes never go up to chase a goal or a loss.</p>
    <div class="ph" style="margin-top:14px"><div><h2>Today's bets</h2><p>${plan.items.length ? `Total ${fmt$(plan.total)} of ${fmt$(cap0)} (${cap0 ? Math.round(plan.total / cap0 * 100) : 0}%) · expected profit ${sfmt$(plan.expected)}${plan.scaled ? " · scaled down to stay under your daily limit" : ""}` : "Nothing to bet yet. The daily pick posts by 10 AM and the error finder scans every 3 hours."}</p></div></div>
    ${rows}
    <div class="ph" style="margin-top:14px"><div><h2>Monthly goal</h2><p>${goal ? `${sfmt$(mp)} of ${fmt$(goal)} this month` : "Set a goal to track it here."}</p></div></div>
    ${goal ? `<div class="goalbar"><span style="width:${Math.max(0, Math.min(100, mp / goal * 100)).toFixed(1)}%"></span></div>
      <p class="b2 mm-note">At today's edges and stakes, a typical month makes about ${sfmt$(monthlyExp)} on a ${fmt$(cap0)} bankroll.${needBank && needBank > cap0 * 1.05 ? ` Reaching ${fmt$(goal)} a month at the same edges takes a bankroll of about ${fmt$(needBank)}.` : monthlyExp >= goal && goal ? " That's on pace for your goal." : ""}</p>` : ""}`;
}

export function initMoney(onChange){
  document.addEventListener("input", e => {
    const t = e.target, st = settings();
    if(t.id === "mmRisk"){ st.risk = RISK[t.value] ? t.value : "standard"; delete st.cap; }
    else if(t.id === "mmCap"){ const v = num(t.value); if(v !== null && v >= 1 && v <= 50) st.cap = v / 100; else return; }
    else if(t.id === "mmGoal"){ const v = num(t.value); if(v !== null && v > 0) st.goal = Math.round(v * 100) / 100; else delete st.goal; }
    else return;
    bankState.dirty = true; Store.save(bankState.bank);
    if(t.id === "mmRisk") renderMoney(); else updateTexts();
    onChange();
  });
  document.addEventListener("click", e => {
    const t = e.target;
    if(!t || !t.dataset || !t.dataset.log) return;
    const plan = todaysPlan(), item = plan.items.find(i => i.id === t.dataset.log);
    if(!item) return;
    if(item.kind === "pick"){
      const bets = bankState.bank.bets, cur = Object.assign({}, bets[item.id] || {});
      cur.stake = item.stake;
      if(item.key !== "main") cur.choice = item.key; else delete cur.choice;
      bets[item.id] = cur;
    } else {
      addExtra({id: item.id, date: String(item.date || todayISO()).slice(0, 10), label: `${item.label} (${item.sub.split(" · ")[0]})`, odds: item.odds, stake: item.stake});
    }
    bankState.dirty = true; Store.save(bankState.bank);
    t.textContent = "Logged ✓"; t.disabled = true;
    onChange();
  });
}

function updateTexts(){ const a = document.activeElement; const id = a && a.id; renderMoney(true); if(id){ const n = document.getElementById(id); if(n){ n.focus(); try { n.setSelectionRange(n.value.length, n.value.length); } catch(err){} } } }

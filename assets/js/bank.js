// My bankroll: the viewer's own bets, kept privately in this browser.
import {$, esc, num, decOf, unitsOf, GRADED, STATUS, isW, isL, cls, spct, fmtDay, byDateAsc, state, todayPick, pickUrl} from "./core.js?v=44bd56026e";
import {lineChart} from "./charts.js?v=44bd56026e";

const KEY = "ml-bank";
export const Store = {
  where: "Saved in this browser on this device only. The home-screen app and Safari keep separate copies, so stick to one, and copy a backup code now and then.",
  note: "",
  async load(){
    try { localStorage.setItem("ml-probe", "1"); localStorage.removeItem("ml-probe"); }
    catch(e){ this.note = "Not saving"; this.where = "This browser is blocking storage, so bets you enter here won't be kept. Try the home-screen app or a normal browser window."; return null; }
    try { const s = localStorage.getItem(KEY); return s ? JSON.parse(s) : null; } catch(e){ return null; }
  },
  async save(st){ try { localStorage.setItem(KEY, JSON.stringify(st)); return true; } catch(e){ return false; } }
};

export const bankState = {bank: {v: 1, start: 100, bets: {}, extras: [], money: {risk: "standard"}}, loaded: false, dirty: false};
export const RESULTS = {pending: "Pending", won: "Won", lost: "Lost", push: "Push", void: "Void"};

export function normBank(st){
  const out = {v: 1, start: 100, bets: {}, extras: [], money: {risk: "standard"}};
  if(!st || typeof st !== "object") return out;
  const m = st.money && typeof st.money === "object" ? st.money : {};
  out.money.risk = ["steady", "standard", "aggressive"].includes(m.risk) ? m.risk : "standard";
  const cap = num(m.cap); if(cap !== null && cap > 0 && cap <= 0.5) out.money.cap = cap;
  const goal = num(m.goal); if(goal !== null && goal > 0) out.money.goal = Math.round(goal * 100) / 100;
  if(m.mode === "target") out.money.mode = "target";
  const tgt = num(m.target); if(tgt !== null && tgt > 0) out.money.target = Math.round(tgt);
  if(/^\d{4}-\d{2}-\d{2}$/.test(String(m.by || ""))) out.money.by = m.by;
  const pd = num(m.perDay); if(pd !== null && pd >= 1 && pd <= 20) out.money.perDay = Math.round(pd);
  for(const x of Array.isArray(st.extras) ? st.extras : []){
    if(!x || typeof x !== "object" || !x.id) continue;
    const stake = num(x.stake), odds = num(x.odds);
    const rec = {id: String(x.id), date: String(x.date || "").slice(0, 10), label: String(x.label || "Bet").slice(0, 160),
      stake: stake !== null && stake > 0 ? Math.round(stake * 100) / 100 : 0, odds: odds !== null && odds > 1 ? Math.round(odds * 1000) / 1000 : 0,
      result: RESULTS[x.result] ? x.result : "pending"};
    if(x.ref && x.ref.pick && x.ref.key) rec.ref = {pick: String(x.ref.pick), key: String(x.ref.key)};
    if(Array.isArray(x.legs)) rec.legs = x.legs.filter(l => l && l.pick && l.key).map(l => ({pick: String(l.pick), key: String(l.key)})).slice(0, 4);
    out.extras.push(rec);
  }
  const s = num(st.start); if(s !== null && s >= 0) out.start = s;
  const b = st.bets && typeof st.bets === "object" ? st.bets : {};
  for(const k of Object.keys(b)){
    const stake = num(b[k] && b[k].stake), odds = num(b[k] && b[k].odds);
    const e = {};
    if(stake !== null && stake > 0) e.stake = Math.round(stake * 100) / 100;
    if(odds !== null && odds > 1) e.odds = Math.round(odds * 1000) / 1000;
    if(b[k] && (b[k].choice === "b1" || b[k].choice === "b2")) e.choice = b[k].choice;
    if(e.stake || e.odds || e.choice) out.bets[k] = e;
  }
  return out;
}

export const fmt$ = n => (n < -0.004 ? "−$" : "$") + Math.abs(n).toFixed(2);
export const sfmt$ = n => (n > 0.004 ? "+$" : n < -0.004 ? "−$" : "$") + Math.abs(n).toFixed(2);
// The bet the viewer actually placed for a pick day: the main pick or one of its backups.
export const choiceOf = p => { const b = bankState.bank.bets[p.id]; return b && b.choice ? b.choice : "main"; };
export const betFor = p => {
  const c = choiceOf(p);
  if(c === "main") return p;
  const bk = (p.backups || []).find(x => x.key === c);
  return bk ? Object.assign({}, bk, {status: String(bk.status || "pending").toLowerCase().replace("-", "_")}) : p;
};
export const stakeOf = p => { const b = bankState.bank.bets[p.id]; return b && b.stake > 0 ? b.stake : 0; };
export const oddsTaken = p => { const b = bankState.bank.bets[p.id]; return b && b.odds > 1 ? b.odds : decOf(betFor(p)); };
export const myProfit = p => {
  const s = stakeOf(p); if(!s) return 0;
  const b = (oddsTaken(p) || 2) - 1, st = betFor(p).status;
  return st === "won" ? s * b : st === "half_won" ? s * b / 2 : st === "lost" ? -s : st === "half_lost" ? -s / 2 : 0;
};
const settledBet = p => { const st = betFor(p).status; return GRADED.has(st) || st === "void"; };

// Other bets: card bets and parlays (graded automatically from the pick data), error finder bets and
// anything else logged by hand (the viewer sets the result).
const legStatus = l => {
  const p = (state.allPicks || state.picks).find(x => x.id === l.pick); if(!p) return "pending";
  const e = l.key === "main" ? p : [...(p.card || []), ...(p.backups || [])].find(c => c.key === l.key);
  return e ? String(e.status || "pending").toLowerCase().replace("-", "_") : "pending";
};
export const extraResult = x => {
  if(x.ref) return legStatus(x.ref);
  if(x.legs && x.legs.length){
    const st = x.legs.map(legStatus);
    if(st.some(v => v === "lost" || v === "half_lost")) return "lost";
    if(st.every(v => v === "void" || v === "push")) return "void";
    if(st.every(v => v === "won" || v === "void" || v === "push")) return "won";
    return "pending";
  }
  return x.result || "pending";
};
export const extraProfit = x => {
  if(!x.stake) return 0;
  const r = extraResult(x), b = (x.odds || 2) - 1;
  return r === "won" ? x.stake * b : r === "half_won" ? x.stake * b / 2 : r === "lost" ? -x.stake : r === "half_lost" ? -x.stake / 2 : 0;
};

export function bankStats(){
  const bank = bankState.bank, extras = (bank.extras || []).filter(x => x.stake > 0);
  const placed = state.picks.filter(p => stakeOf(p) > 0);
  const settled = placed.filter(settledBet);
  const open = placed.filter(p => !settledBet(p));
  const xSettled = extras.filter(x => extraResult(x) !== "pending"), xOpen = extras.filter(x => extraResult(x) === "pending");
  const profit = settled.reduce((a, p) => a + myProfit(p), 0) + xSettled.reduce((a, x) => a + extraProfit(x), 0);
  const inPlay = open.reduce((a, p) => a + stakeOf(p), 0) + xOpen.reduce((a, x) => a + x.stake, 0);
  const staked = settled.filter(p => betFor(p).status !== "void").reduce((a, p) => a + stakeOf(p), 0)
               + xSettled.filter(x => extraResult(x) !== "void").reduce((a, x) => a + x.stake, 0);
  const W = settled.filter(p => isW(betFor(p).status)).length + xSettled.filter(x => isW(extraResult(x))).length;
  const L = settled.filter(p => isL(betFor(p).status)).length + xSettled.filter(x => isL(extraResult(x))).length;
  return {placed, settled, open, extras, xSettled, xOpen, profit, inPlay, staked, W, L, nPlaced: placed.length + extras.length,
          balance: bank.start + profit - inPlay};
}

// Model stake in dollars: units are percent of the bankroll before open bets.
const RISK_MULT = {steady: 0.5, standard: 1, aggressive: 2};
export const riskMult = () => RISK_MULT[(bankState.bank.money || {}).risk] || 1;
const round$ = v => v <= 0 ? 0 : v < 10 ? Math.max(0.1, Math.round(v * 10) / 10) : Math.round(v * 2) / 2;
export const suggested = p => { if(!bankState.loaded) return 0; const s = bankStats(); const base = s.balance + s.inPlay; return base > 0 ? round$(unitsOf(p) / 100 * base * riskMult()) : 0; };

let saveTimer = null;
function saveBank(){ clearTimeout(saveTimer); saveTimer = setTimeout(() => { Store.save(bankState.bank); }, 350); }

const sel = (id, f) => `input[data-id="${window.CSS && CSS.escape ? CSS.escape(id) : id}"][data-f="${f}"]`;

function choiceSelect(p, id){
  const bks = p.backups || [];
  if(!bks.length) return "";
  const c = choiceOf(p), opt = (v, label) => `<option value="${v}"${c === v ? " selected" : ""}>${esc(label)}</option>`;
  return `<select class="inp choice" id="${id}" data-id="${esc(p.id)}" data-f="choice" aria-label="Which bet you placed">
    ${opt("main", "Main: " + (p.bet || ""))}${bks.map((b, i) => opt(b.key, `Backup ${i + 1}: ${b.bet || ""}`)).join("")}</select>`;
}

function plText(p){
  const st = stakeOf(p), bs = betFor(p).status;
  if(!st) return {t: "—", c: ""};
  if(bs === "void") return {t: "Refunded", c: ""};
  if(!GRADED.has(bs)) return {t: "In play", c: ""};
  const v = myProfit(p); return {t: sfmt$(v), c: cls(v)};
}

function rowHTML(p){
  const b = bankState.bank.bets[p.id] || {}, bet = betFor(p), bst = STATUS[bet.status] ? bet.status : "pending";
  const st = bst, d = decOf(bet), id = esc(p.id), name = esc(p.bet || "");
  return `<div class="mrow">
    <div class="m-date">${esc(fmtDay(p.date, {weekday: undefined}))}</div>
    <div class="m-pick"><div class="b1"><a href="${pickUrl(p)}">${name}</a></div><div class="b2">${esc(p.event || "")}<span id="po-${id}">${d ? " · pick odds " + d.toFixed(2) : ""}</span></div>${choiceSelect(p, "choice-" + id)}</div>
    <div class="m-res"><span class="pill ${st}" id="st-${id}">${STATUS[st]}</span></div>
    <label class="m-stake"><span class="lbl">Your stake</span><span class="bin">$<input class="inp" id="stake-${id}" data-id="${id}" data-f="stake" type="number" min="0" step="0.01" inputmode="decimal" placeholder="0" value="${b.stake || ""}" aria-label="Your stake on ${name}"></span></label>
    <label class="m-odds"><span class="lbl">Odds you got</span><input class="inp" id="odds-${id}" data-id="${id}" data-f="odds" type="number" min="1.01" step="0.01" inputmode="decimal" placeholder="${d ? d.toFixed(2) : ""}" value="${b.odds || ""}" aria-label="Odds you got on ${name}"></label>
    <div class="m-pl" id="pl-${id}"></div>
  </div>`;
}

function renderMoneyList(){
  const el = $("#moneyList"); if(!el) return;
  if(el.contains(document.activeElement)) return;
  if(!state.loaded){ el.innerHTML = ""; return; }
  const rows = state.picks.slice().sort(byDateAsc).reverse();
  if(!rows.length){ el.innerHTML = `<p class="empty" style="padding-top:12px">Your bets show here once picks are posted.</p>`; return; }
  el.innerHTML = `<div class="mrow head"><span class="m-date">Date</span><span class="m-pick">Pick</span><span class="m-res">Result</span><span class="m-stake">Your stake</span><span class="m-odds">Odds you got</span><span class="m-pl">Profit</span></div>` + rows.map(rowHTML).join("");
  renderExtras();
}

function extraRow(x, i){
  const auto = !!(x.ref || (x.legs && x.legs.length)), r = extraResult(x);
  const opts = Object.entries(RESULTS).map(([k, v]) => `<option value="${k}"${x.result === k ? " selected" : ""}>${v}</option>`).join("");
  const resCell = auto ? `<span class="pill ${STATUS[r] ? r : "pending"}">${STATUS[r] || "Pending"}</span>` : `<select class="inp choice" data-x="${i}" data-xf="result" aria-label="Result">${opts}</select>`;
  const v = extraProfit(x);
  return `<div class="mrow">
    <div class="m-date">${esc(fmtDay(x.date || "", {weekday: undefined}))}</div>
    <div class="m-pick"><div class="b1">${esc(x.label)}</div><button type="button" class="linkbtn" data-xdel="${i}">Remove</button></div>
    <div class="m-res">${resCell}</div>
    <label class="m-stake"><span class="lbl">Your stake</span><span class="bin">$<input class="inp" data-x="${i}" data-xf="stake" type="number" min="0" step="0.01" inputmode="decimal" value="${x.stake || ""}"></span></label>
    <label class="m-odds"><span class="lbl">Odds you got</span><input class="inp" data-x="${i}" data-xf="odds" type="number" min="1.01" step="0.01" inputmode="decimal" value="${x.odds || ""}"></label>
    <div class="m-pl ${r === "pending" ? "" : cls(v)}" id="xpl-${i}">${!x.stake ? "—" : r === "pending" ? "In play" : r === "void" || r === "push" ? "Refunded" : sfmt$(v)}</div>
  </div>`;
}

function renderExtras(){
  const el = $("#extraList"); if(!el) return;
  if(el.contains(document.activeElement)) return;
  const xs = bankState.bank.extras || [];
  el.innerHTML = (xs.length ? xs.map(extraRow).join("") : `<p class="empty" style="padding-top:10px">Error finder bets and anything else you bet show here. Tap "Log it" on a bet in the money plan, or add one below.</p>`)
    + `<div class="addx"><input class="inp" id="xLabel" placeholder="Bet (e.g. Over 2.5 · Colo-Colo vs U. de Chile)" aria-label="Bet">
       <input class="inp" id="xOdds" type="number" min="1.01" step="0.01" inputmode="decimal" placeholder="Odds" aria-label="Odds">
       <input class="inp" id="xStake" type="number" min="0" step="0.01" inputmode="decimal" placeholder="$ stake" aria-label="Stake">
       <button type="button" class="btn" id="xAdd">Add bet</button></div>`;
}

export function addExtra(x){
  const bank = bankState.bank;
  bank.extras = bank.extras || [];
  const i = bank.extras.findIndex(e => e.id === x.id);
  const rec = Object.assign({result: "pending"}, i >= 0 ? bank.extras[i] : {}, x);
  if(i >= 0) bank.extras[i] = rec; else bank.extras.unshift(rec);
  bankState.dirty = true; Store.save(bank);
}

function renderTodayBet(){
  const el = $("#todayBet"); if(!el) return;
  if(el.contains(document.activeElement)) return;
  if(!state.loaded){ el.innerHTML = ""; return; }
  const p = todayPick();
  if(!p){ el.innerHTML = `<div class="k">Bet on today's pick</div><div class="tb-out">Today's pick posts at 10:00 AM. You can log your stake here once it's up.</div>`; return; }
  const b = bankState.bank.bets[p.id] || {}, d = decOf(betFor(p)), id = esc(p.id);
  el.innerHTML = `<div class="k">Bet on today's pick</div><div class="tb-name">${esc(p.bet || "")}</div>${choiceSelect(p, "tb-choice")}
    <div class="tb-row">
      <label for="tb-stake"><span class="k">Amount</span><span class="bin">$<input class="inp" id="tb-stake" data-id="${id}" data-f="stake" type="number" min="0" step="0.01" inputmode="decimal" placeholder="0" value="${b.stake || ""}"></span></label>
      <label for="tb-odds"><span class="k">Odds you got</span><input class="inp" id="tb-odds" data-id="${id}" data-f="odds" type="number" min="1.01" step="0.01" inputmode="decimal" placeholder="${d ? d.toFixed(2) : ""}" value="${b.odds || ""}"></label>
    </div>
    <div class="tb-out" id="tb-out"></div>`;
}

function renderMoneyChart(s){
  const el = $("#moneyChart"); if(!el) return;
  const bank = bankState.bank;
  const done = s.settled.slice().sort(byDateAsc);
  if(!done.length){ el.innerHTML = `<p class="empty">Your balance line starts once a pick you bet on is graded.</p>`; return; }
  const pts = [{v: bank.start}]; let c = bank.start;
  for(const p of done){ c += myProfit(p); pts.push({v: c}); }
  lineChart(el, pts, {base: bank.start, minSpan: Math.max(10, bank.start * 0.1), steps: [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000],
    fmtAxis: v => "$" + (Number.isInteger(v) ? v : v.toFixed(2)), fmtEnd: fmt$, left: 52,
    caption: "Balance after each settled bet" + (s.inPlay > 0 ? ", before the " + fmt$(s.inPlay) + " in play" : ""),
    label: `Settled balance ${fmt$(c)} after ${done.length} bets`, first: done[0].date, last: done[done.length - 1].date});
}

// Numbers only: never rebuilds the inputs someone may be typing in.
export function updateMoney(){
  const bank = bankState.bank, s = bankStats();
  const bal = $("#curBal");
  if(bal){
    bal.textContent = fmt$(s.balance);
    $("#curSub").textContent = s.inPlay > 0 ? `${fmt$(s.inPlay)} in play · ${sfmt$(s.profit)} settled` : (s.nPlaced ? `${sfmt$(s.profit)} since you started` : "Log a bet to start tracking");
    $("#bankNote").textContent = Store.note || "";
  }
  const where = $("#bkWhere"); if(where) where.textContent = Store.where;
  const stats = $("#moneyStats");
  if(stats){
    const roi = s.staked ? s.profit / s.staked : null;
    const tile = (k, v, sub, c) => `<div class="stat"><div class="k">${k}</div><div class="v ${c || ""}">${v}</div><div class="s">${sub}</div></div>`;
    stats.innerHTML =
      tile("Balance", fmt$(s.balance), s.inPlay > 0 ? `${fmt$(s.inPlay)} in play` : `Started with ${fmt$(bank.start)}`, "") +
      tile("Profit", sfmt$(s.profit), "From settled bets", cls(s.profit)) +
      tile("Return", roi === null ? "—" : spct(roi), s.staked ? `On ${fmt$(s.staked)} bet` : "Profit per dollar bet", roi !== null ? cls(roi) : "") +
      tile("Your record", `${s.W}-${s.L}`, `${s.nPlaced} bet${s.nPlaced === 1 ? "" : "s"} placed`, "");
  }
  renderMoneyChart(s);
  for(const p of state.picks){
    const c = document.getElementById("pl-" + p.id); if(c){ const r = plText(p); c.textContent = r.t; c.className = "m-pl " + r.c; }
    const bet = betFor(p), bs = STATUS[bet.status] ? bet.status : "pending";
    const pill = document.getElementById("st-" + p.id); if(pill){ pill.textContent = STATUS[bs]; pill.className = "pill " + bs; }
    const po = document.getElementById("po-" + p.id); if(po){ const d = decOf(bet); po.textContent = d ? " · pick odds " + d.toFixed(2) : ""; }
  }
  const out = document.getElementById("tb-out"), cp = todayPick();
  if(out && cp){
    const st = stakeOf(cp), d = oddsTaken(cp) || 0, sug = suggested(cp);
    out.textContent = st ? `Pays ${fmt$(st * d)} if it wins (${sfmt$(st * (d - 1))} profit). Your money plan says bet ${fmt$(sug)}.`
                         : `Your money plan says bet ${fmt$(sug)} on this one.`;
  }
}

export function renderBank(){
  const sm = $("#startMoney");
  if(sm && document.activeElement !== sm) sm.value = bankState.bank.start;
  renderTodayBet(); renderMoneyList(); updateMoney();
}

// Wires inputs and backup buttons once. onChange re-renders anything else that shows money.
export function initBank(onChange){
  document.addEventListener("input", e => {
    const t = e.target, bank = bankState.bank;
    if(t.id === "startMoney"){
      const v = num(t.value); bank.start = v !== null && v >= 0 ? Math.round(v * 100) / 100 : 0;
      bankState.dirty = true; saveBank(); updateMoney(); onChange(); return;
    }
    if(t.dataset && t.dataset.x !== undefined && t.dataset.xf){
      const x = (bank.extras || [])[Number(t.dataset.x)]; if(!x) return;
      const v = num(t.value);
      if(t.dataset.xf === "stake") x.stake = v !== null && v > 0 ? Math.round(v * 100) / 100 : 0;
      if(t.dataset.xf === "odds") x.odds = v !== null && v > 1 ? Math.round(v * 1000) / 1000 : 0;
      if(t.dataset.xf === "result") x.result = RESULTS[t.value] ? t.value : "pending";
      const c = document.getElementById("xpl-" + t.dataset.x);
      if(c){ const pv = extraProfit(x), rr = extraResult(x); c.textContent = !x.stake ? "—" : rr === "pending" ? "In play" : rr === "void" || rr === "push" ? "Refunded" : sfmt$(pv); c.className = "m-pl " + (rr === "pending" ? "" : cls(pv)); }
      bankState.dirty = true; saveBank(); updateMoney(); onChange(); return;
    }
    if(!t.dataset || !t.dataset.f || !t.dataset.id) return;
    const id = t.dataset.id, f = t.dataset.f, v = num(t.value);
    const entry = Object.assign({}, bank.bets[id] || {});
    if(f === "stake"){ if(v !== null && v > 0) entry.stake = Math.round(v * 100) / 100; else delete entry.stake; }
    if(f === "odds"){ if(v !== null && v > 1) entry.odds = Math.round(v * 1000) / 1000; else delete entry.odds; }
    if(f === "choice"){ if(t.value === "b1" || t.value === "b2") entry.choice = t.value; else delete entry.choice; }
    if(entry.stake || entry.odds || entry.choice) bank.bets[id] = entry; else delete bank.bets[id];
    document.querySelectorAll(sel(id, f)).forEach(x => { if(x !== t) x.value = t.value; });
    if(f === "choice"){
      const p = state.picks.find(x => x.id === id), d = p ? decOf(betFor(p)) : null;
      document.querySelectorAll(sel(id, "odds")).forEach(x => { x.placeholder = d ? d.toFixed(2) : ""; });
    }
    bankState.dirty = true; saveBank(); updateMoney(); onChange();
  });

  document.addEventListener("change", e => {
    // selects fire "change"; route result changes for other bets through the same handler as typing
    if(e.target && e.target.dataset && e.target.dataset.xf === "result") e.target.dispatchEvent(new Event("input", {bubbles: true}));
  });
  document.addEventListener("click", e => {
    const t = e.target;
    if(t && t.dataset && t.dataset.xdel !== undefined){
      bankState.bank.extras.splice(Number(t.dataset.xdel), 1);
      bankState.dirty = true; Store.save(bankState.bank); renderExtras(); updateMoney(); onChange();
    }
    if(t && t.id === "xAdd"){
      const label = $("#xLabel").value.trim(), odds = num($("#xOdds").value), stake = num($("#xStake").value);
      if(!label || !(odds > 1) || !(stake > 0)) return;
      addExtra({id: "x" + Date.now(), date: new Date().toISOString().slice(0, 10), label, odds, stake});
      renderExtras(); updateMoney(); onChange();
    }
  });

  const copy = $("#bkCopy");
  if(copy){
    copy.addEventListener("click", async () => {
      const code = btoa(unescape(encodeURIComponent(JSON.stringify(bankState.bank))));
      const out = $("#bkOut"), msg = $("#bkMsg");
      out.value = code;
      try { await navigator.clipboard.writeText(code); out.hidden = true; msg.textContent = "Copied. Keep it somewhere safe, like your Notes app."; }
      catch(err){ out.hidden = false; out.focus(); out.select(); msg.textContent = "Copy the code below."; }
    });
    let armed = false;
    $("#bkIn").addEventListener("input", () => { armed = false; const er = $("#bkErr"); er.textContent = ""; er.className = "bmsg"; });
    $("#bkRestore").addEventListener("click", () => {
      const raw = $("#bkIn").value.trim(), er = $("#bkErr");
      if(!raw){ er.textContent = "Paste a backup code first."; er.className = "bmsg err"; return; }
      let st = null;
      try { st = JSON.parse(raw); } catch(e1){ try { st = JSON.parse(decodeURIComponent(escape(atob(raw.replace(/\s+/g, ""))))); } catch(e2){ st = null; } }
      if(!st || typeof st !== "object" || !st.bets || typeof st.bets !== "object"){ er.textContent = "That isn't a Morning Line backup code. Check you copied all of it."; er.className = "bmsg err"; return; }
      if(!armed){ armed = true; er.textContent = "This replaces the bets saved here. Tap Restore again to confirm."; er.className = "bmsg"; return; }
      armed = false; bankState.bank = normBank(st); bankState.dirty = true; Store.save(bankState.bank); $("#bkIn").value = "";
      const n = Object.keys(bankState.bank.bets).length;
      er.textContent = `Restored ${n} bet${n === 1 ? "" : "s"}.`; er.className = "bmsg";
      renderBank(); onChange();
    });
  }

  return Store.load().then(st => { if(!bankState.dirty) bankState.bank = normBank(st); bankState.loaded = true; });
}

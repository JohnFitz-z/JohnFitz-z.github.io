// My bankroll: the viewer's own bets, kept privately in this browser.
import {$, esc, num, decOf, unitsOf, GRADED, STATUS, isW, isL, cls, spct, fmtDay, byDateAsc, state, todayPick, pickUrl} from "./core.js?v=c1dd44d874";
import {lineChart} from "./charts.js?v=c1dd44d874";

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

export const bankState = {bank: {v: 1, start: 100, bets: {}}, loaded: false, dirty: false};

export function normBank(st){
  const out = {v: 1, start: 100, bets: {}};
  if(!st || typeof st !== "object") return out;
  const s = num(st.start); if(s !== null && s >= 0) out.start = s;
  const b = st.bets && typeof st.bets === "object" ? st.bets : {};
  for(const k of Object.keys(b)){
    const stake = num(b[k] && b[k].stake), odds = num(b[k] && b[k].odds);
    const e = {};
    if(stake !== null && stake > 0) e.stake = Math.round(stake * 100) / 100;
    if(odds !== null && odds > 1) e.odds = Math.round(odds * 1000) / 1000;
    if(e.stake || e.odds) out.bets[k] = e;
  }
  return out;
}

export const fmt$ = n => (n < -0.004 ? "−$" : "$") + Math.abs(n).toFixed(2);
export const sfmt$ = n => (n > 0.004 ? "+$" : n < -0.004 ? "−$" : "$") + Math.abs(n).toFixed(2);
export const stakeOf = p => { const b = bankState.bank.bets[p.id]; return b && b.stake > 0 ? b.stake : 0; };
export const oddsTaken = p => { const b = bankState.bank.bets[p.id]; return b && b.odds > 1 ? b.odds : decOf(p); };
export const myProfit = p => {
  const s = stakeOf(p); if(!s) return 0;
  const b = (oddsTaken(p) || 2) - 1;
  return p.status === "won" ? s * b : p.status === "half_won" ? s * b / 2 : p.status === "lost" ? -s : p.status === "half_lost" ? -s / 2 : 0;
};

export function bankStats(){
  const bank = bankState.bank;
  const placed = state.picks.filter(p => stakeOf(p) > 0);
  const settled = placed.filter(p => GRADED.has(p.status) || p.status === "void");
  const open = placed.filter(p => !(GRADED.has(p.status) || p.status === "void"));
  const profit = settled.reduce((a, p) => a + myProfit(p), 0);
  const inPlay = open.reduce((a, p) => a + stakeOf(p), 0);
  const staked = settled.filter(p => p.status !== "void").reduce((a, p) => a + stakeOf(p), 0);
  const W = settled.filter(p => isW(p.status)).length, L = settled.filter(p => isL(p.status)).length;
  return {placed, settled, open, profit, inPlay, staked, W, L, balance: bank.start + profit - inPlay};
}

// Model stake in dollars: units are percent of the bankroll before open bets.
export const suggested = p => { if(!bankState.loaded) return 0; const s = bankStats(); const base = s.balance + s.inPlay; return base > 0 ? unitsOf(p) / 100 * base : 0; };

let saveTimer = null;
function saveBank(){ clearTimeout(saveTimer); saveTimer = setTimeout(() => { Store.save(bankState.bank); }, 350); }

const sel = (id, f) => `input[data-id="${window.CSS && CSS.escape ? CSS.escape(id) : id}"][data-f="${f}"]`;

function plText(p){
  const st = stakeOf(p);
  if(!st) return {t: "—", c: ""};
  if(p.status === "void") return {t: "Refunded", c: ""};
  if(!GRADED.has(p.status)) return {t: "In play", c: ""};
  const v = myProfit(p); return {t: sfmt$(v), c: cls(v)};
}

function rowHTML(p){
  const b = bankState.bank.bets[p.id] || {}, st = STATUS[p.status] ? p.status : "pending", d = decOf(p), id = esc(p.id), name = esc(p.bet || "");
  return `<div class="mrow">
    <div class="m-date">${esc(fmtDay(p.date, {weekday: undefined}))}</div>
    <div class="m-pick"><div class="b1"><a href="${pickUrl(p)}">${name}</a></div><div class="b2">${esc(p.event || "")}${d ? " · pick odds " + d.toFixed(2) : ""}</div></div>
    <div class="m-res"><span class="pill ${st}">${STATUS[st]}</span></div>
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
}

function renderTodayBet(){
  const el = $("#todayBet"); if(!el) return;
  if(el.contains(document.activeElement)) return;
  if(!state.loaded){ el.innerHTML = ""; return; }
  const p = todayPick();
  if(!p){ el.innerHTML = `<div class="k">Bet on today's pick</div><div class="tb-out">Today's pick posts at 10:00 AM. You can log your stake here once it's up.</div>`; return; }
  const b = bankState.bank.bets[p.id] || {}, d = decOf(p), id = esc(p.id);
  el.innerHTML = `<div class="k">Bet on today's pick</div><div class="tb-name">${esc(p.bet || "")}</div>
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
    $("#curSub").textContent = s.inPlay > 0 ? `${fmt$(s.inPlay)} in play · ${sfmt$(s.profit)} settled` : (s.placed.length ? `${sfmt$(s.profit)} since you started` : "Log a bet to start tracking");
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
      tile("Your record", `${s.W}-${s.L}`, `${s.placed.length} bet${s.placed.length === 1 ? "" : "s"} placed`, "");
  }
  renderMoneyChart(s);
  for(const p of state.picks){ const c = document.getElementById("pl-" + p.id); if(c){ const r = plText(p); c.textContent = r.t; c.className = "m-pl " + r.c; } }
  const out = document.getElementById("tb-out"), cp = todayPick();
  if(out && cp){
    const st = stakeOf(cp), d = oddsTaken(cp) || 0, sug = suggested(cp);
    out.textContent = st ? `Pays ${fmt$(st * d)} if it wins (${sfmt$(st * (d - 1))} profit). Model size ≈ ${fmt$(sug)}.`
                         : `Model size ≈ ${fmt$(sug)}, which is ${unitsOf(cp)}% of your bankroll.`;
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
    if(!t.dataset || !t.dataset.f || !t.dataset.id) return;
    const id = t.dataset.id, f = t.dataset.f, v = num(t.value);
    const entry = Object.assign({}, bank.bets[id] || {});
    if(f === "stake"){ if(v !== null && v > 0) entry.stake = Math.round(v * 100) / 100; else delete entry.stake; }
    if(f === "odds"){ if(v !== null && v > 1) entry.odds = Math.round(v * 1000) / 1000; else delete entry.odds; }
    if(entry.stake || entry.odds) bank.bets[id] = entry; else delete bank.bets[id];
    document.querySelectorAll(sel(id, f)).forEach(x => { if(x !== t) x.value = t.value; });
    bankState.dirty = true; saveBank(); updateMoney(); onChange();
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

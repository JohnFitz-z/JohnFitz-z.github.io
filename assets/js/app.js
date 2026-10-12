// Boots whichever page is open: loads the data, renders that page's views, keeps them fresh.
import {$, esc, state, loadPicks, todayISO, fmtDay, fmtStamp, newestFirst, pickById, latestPick, pickUrl} from "./core.js?v=2c1dc196fa";
import {ticketHTML, todayHTML, rowHTML} from "./picks.js?v=2c1dc196fa";
import {tilesHTML, gradedCountText, renderUnitsChart, renderClv, renderMvm, renderBreakdowns} from "./stats.js?v=2c1dc196fa";
import {initBank, renderBank, bankState, bankStats, myBets, myBetRowHTML, renderMoneyChart, fmt$, sfmt$} from "./bank.js?v=2c1dc196fa";
import {loadErrors, renderErrors} from "./errors.js?v=2c1dc196fa";
import {initMoney, renderMoney, planStakes, liveErrorBets} from "./money.js?v=2c1dc196fa";

const page = document.body.dataset.page;

function pickIdFromPath(){
  const m = location.pathname.match(/\/pick\/([^/]+)\/?$/);
  return document.body.dataset.pick || (m ? decodeURIComponent(m[1]) : null);
}

function loadingTicket(){
  return `<div class="t-head"><div class="t-eyebrow"><span class="chip">Loading</span></div><div class="t-empty"><div class="t-bet" style="margin-top:16px">${state.failed ? "Picks unavailable" : "Loading…"}</div>${state.failed ? `<p>${esc(state.failed)}</p>` : ""}</div></div>`;
}

function renderChrome(){
  const tl = $("#todayLabel"); if(tl) tl.textContent = fmtDay(todayISO(), {weekday: "long", month: "long", day: "numeric", year: "numeric"});
  const up = $("#updated"); if(up && state.updatedAt) up.textContent = "Updated " + fmtStamp(state.updatedAt);
  const gc = $("#gradedCount"); if(gc && state.loaded) gc.textContent = gradedCountText();
}

const tile = (k, v, sub, c) => `<div class="tile"><div class="k">${k}</div><div class="v ${c || ""}">${v}</div><div class="s">${sub || "&nbsp;"}</div></div>`;
const cls$ = n => n > 0.004 ? "pos" : n < -0.004 ? "neg" : "";

function myTiles(){
  if(!bankState.loaded) return "";
  const s = bankStats(), roi = s.staked ? s.profit / s.staked : null;
  return tile("Profit", sfmt$(s.profit), "From settled bets", cls$(s.profit))
    + tile("In play", fmt$(s.inPlay), s.xOpen.length + s.open.length ? `${s.xOpen.length + s.open.length} open bet${s.xOpen.length + s.open.length === 1 ? "" : "s"}` : "Nothing open")
    + tile("Record", `${s.W}-${s.L}`, `${s.nPlaced} bet${s.nPlaced === 1 ? "" : "s"} placed`)
    + tile("Return", roi === null ? "—" : (roi >= 0 ? "+" : "−") + Math.abs(roi * 100).toFixed(1) + "%", "Profit per dollar bet", roi !== null ? cls$(roi) : "");
}

function renderToday(){
  const el = $("#ticket");
  if(!state.loaded){ el.innerHTML = loadingTicket(); return; }
  const p = latestPick();
  if(!(el.contains(document.activeElement) && document.activeElement.tagName === "INPUT"))
    el.innerHTML = p ? todayHTML(p, planStakes(), liveErrorBets())
      : `<div class="t-head"><div class="t-eyebrow"><span class="chip">Today's bets</span></div><div class="t-empty"><div class="t-bet" style="margin-top:16px">The first list lands at 10:00 AM</div></div></div>`;
  $("#tiles").innerHTML = myTiles();
  const mine = bankState.loaded ? myBets().slice(0, 6) : [];
  $("#recent").innerHTML = mine.length ? mine.map(myBetRowHTML).join("") : `<p class="empty" style="padding-top:12px">Bets you place show here once you log them on the Bankroll page.</p>`;
}

function renderResults(){
  const all = $("#fAll"), fs = $("#fSport"), fst = $("#fStatus");
  const showAll = all && all.checked;
  fs.hidden = !showAll;
  $("#logTitle").textContent = showAll ? "Every pick posted" : "Your bets";
  const el = $("#log");
  if(!state.loaded){ el.innerHTML = `<p class="empty" style="padding-top:12px">${state.failed ? esc(state.failed) : "Loading…"}</p>`; return; }
  const want = st => !fst.value || String(st || "pending").replace("half_", "") === fst.value;
  if(showAll){
    const cur = fs.value, sports = Array.from(new Set(state.picks.map(p => p.sport).filter(Boolean))).sort();
    fs.innerHTML = `<option value="">All sports</option>` + sports.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    fs.value = sports.includes(cur) ? cur : "";
    renderUnitsChart($("#chart"));
    const rows = newestFirst().filter(p => (!fs.value || p.sport === fs.value) && want(p.status));
    el.innerHTML = rows.length ? rows.map(rowHTML).join("") : `<p class="empty" style="padding-top:12px">No picks match these filters.</p>`;
    return;
  }
  if(!bankState.loaded) return;
  renderMoneyChart(null, $("#chart"));
  const rows = myBets().filter(b => want(b.status));
  el.innerHTML = rows.length ? rows.map(myBetRowHTML).join("")
    : `<p class="empty" style="padding-top:12px">${myBets().length ? "No bets match this filter." : "No bets logged yet. Tap \"Log it\" on the Bankroll page when you place a bet."}</p>`;
}

function renderPick(){
  const el = $("#ticket"), nav = $("#pnav");
  if(!state.loaded){ el.innerHTML = loadingTicket(); return; }
  const id = pickIdFromPath(), p = id ? pickById(id) : null;
  if(!p){
    el.innerHTML = `<div class="t-head nf"><h1>Pick not found</h1><p>There's no pick for ${esc(id || "this address")}. <a href="/results/">See all results</a>.</p></div>`;
    if(nav) nav.innerHTML = "";
    return;
  }
  document.title = `${p.bet} · ${fmtDay(p.date, {weekday: undefined})} · Morning Line`;
  el.innerHTML = (p.excluded ? `<div class="callout" style="margin-bottom:14px"><b>Not counted in the record.</b> ${esc(p.excluded_reason || "This pick was replaced and not bet.")}</div>` : "")
    + ticketHTML(p, "detail");
  if(nav && p.excluded){ nav.innerHTML = ""; return; }
  if(nav){
    const all = newestFirst(), i = all.findIndex(x => x.id === p.id);
    const newer = all[i - 1], older = all[i + 1];
    nav.innerHTML = (older ? `<a class="prev" href="${pickUrl(older)}"><span class="k">← Previous pick · ${esc(fmtDay(older.date, {weekday: undefined}))}</span><span class="t">${esc(older.bet || "")}</span></a>` : "")
                  + (newer ? `<a class="next" href="${pickUrl(newer)}"><span class="k">Next pick · ${esc(fmtDay(newer.date, {weekday: undefined}))} →</span><span class="t">${esc(newer.bet || "")}</span></a>` : "");
  }
}

function renderStats(){
  $("#tiles").innerHTML = tilesHTML(false);
  renderUnitsChart($("#chart"));
  renderClv($("#clvPanel"));
  renderMvm($("#mvm"));
  renderBreakdowns($("#bySport"), $("#byConf"));
}

function render(){
  renderChrome();
  if(page === "today") renderToday();
  else if(page === "results") renderResults();
  else if(page === "pick" || (page === "404" && pickIdFromPath())) renderPick();
  else if(page === "stats") renderStats();
  else if(page === "errors") renderErrors();
  if(document.getElementById("bank") || document.getElementById("moneyList")) renderBank();
  if(document.getElementById("moneyPlan")) renderMoney();
}

// Money changes affect the suggested stake on tickets.
const onMoneyChange = () => { if(page === "today" || page === "pick") { const a = document.activeElement; if(!(a && a.closest && a.closest("#ticket"))) render(); } };

async function refresh(){
  if(page === "errors" || page === "bankroll" || page === "today"){ await loadErrors(); render(); }
  if(await loadPicks()) render();
}

document.addEventListener("change", e => { if(e.target.id === "fSport" || e.target.id === "fStatus" || e.target.id === "fAll") renderResults(); });
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(render, 150); });
document.addEventListener("visibilitychange", () => { if(document.visibilityState === "visible") refresh(); });
setInterval(() => { if(document.visibilityState === "visible") refresh(); }, 5 * 60 * 1000);
window.addEventListener("online", () => { const o = $("#offline"); if(o) o.hidden = true; refresh(); });
window.addEventListener("offline", () => { const o = $("#offline"); if(o) o.hidden = false; });

render();
const bankReady = initBank(onMoneyChange);
initMoney(() => { if(page === "errors") renderErrors(); render(); });
Promise.all([loadPicks(), bankReady]).then(render);
if(page === "errors" || page === "bankroll" || page === "today") Promise.all([loadErrors(), bankReady]).then(render);

if("serviceWorker" in navigator && location.protocol === "https:"){
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

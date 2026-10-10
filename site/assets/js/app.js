// Boots whichever page is open: loads the data, renders that page's views, keeps them fresh.
import {$, esc, state, loadPicks, todayISO, fmtDay, fmtStamp, newestFirst, pickById, latestPick, pickUrl} from "./core.js";
import {ticketHTML, rowHTML} from "./picks.js";
import {tilesHTML, gradedCountText, renderUnitsChart, renderClv, renderMvm, renderBreakdowns} from "./stats.js";
import {initBank, renderBank} from "./bank.js";
import {loadErrors, renderErrors} from "./errors.js";

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

function renderToday(){
  const el = $("#ticket");
  if(!state.loaded){ el.innerHTML = loadingTicket(); return; }
  const p = latestPick();
  el.innerHTML = p ? ticketHTML(p, "today")
    : `<div class="t-head"><div class="t-eyebrow"><span class="chip">Today's pick</span></div><div class="t-empty"><div class="t-bet" style="margin-top:16px">First pick lands at 10:00 AM</div><p>Each morning the research runs across the full slate, settles on one bet, and posts it here.</p></div></div>`;
  $("#tiles").innerHTML = tilesHTML(true);
  const recent = newestFirst().filter(x => !p || x.id !== p.id).slice(0, 5);
  $("#recent").innerHTML = recent.length ? recent.map(rowHTML).join("") : `<p class="empty" style="padding-top:12px">Past picks show here.</p>`;
}

function renderResults(){
  const fs = $("#fSport"), fst = $("#fStatus"), cur = fs.value;
  const sports = Array.from(new Set(state.picks.map(p => p.sport).filter(Boolean))).sort();
  fs.innerHTML = `<option value="">All sports</option>` + sports.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  fs.value = sports.includes(cur) ? cur : "";
  renderUnitsChart($("#chart"));
  const el = $("#log");
  if(!state.loaded){ el.innerHTML = `<p class="empty" style="padding-top:12px">${state.failed ? esc(state.failed) : "Loading…"}</p>`; return; }
  const rows = newestFirst().filter(p => (!fs.value || p.sport === fs.value) && (!fst.value || (p.status || "pending").replace("half_", "") === fst.value));
  el.innerHTML = rows.length ? rows.map(rowHTML).join("") : `<p class="empty" style="padding-top:12px">${state.picks.length ? "No picks match these filters." : "No picks yet."}</p>`;
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
}

// Money changes affect the suggested stake on tickets.
const onMoneyChange = () => { if(page === "today" || page === "pick") { const a = document.activeElement; if(!(a && a.closest && a.closest("#ticket"))) render(); } };

async function refresh(){
  if(page === "errors"){ await loadErrors(); renderErrors(); }
  if(await loadPicks()) render();
}

document.addEventListener("change", e => { if(e.target.id === "fSport" || e.target.id === "fStatus") renderResults(); });
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(render, 150); });
document.addEventListener("visibilitychange", () => { if(document.visibilityState === "visible") refresh(); });
setInterval(() => { if(document.visibilityState === "visible") refresh(); }, 5 * 60 * 1000);
window.addEventListener("online", () => { const o = $("#offline"); if(o) o.hidden = true; refresh(); });
window.addEventListener("offline", () => { const o = $("#offline"); if(o) o.hidden = false; });

render();
const bankReady = initBank(onMoneyChange);
Promise.all([loadPicks(), bankReady]).then(render);
if(page === "errors") loadErrors().then(renderErrors);

if("serviceWorker" in navigator && location.protocol === "https:"){
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

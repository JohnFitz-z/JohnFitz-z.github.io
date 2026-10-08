// Shared state, data loading and formatting for every page.

export const TZ = "America/Halifax";
export const GRADED = new Set(["won", "lost", "push", "half_won", "half_lost"]);
export const STATUS = {pending: "Pending", won: "Won", lost: "Lost", push: "Push", void: "Void", half_won: "Half won", half_lost: "Half lost"};
export const isW = s => s === "won" || s === "half_won";
export const isL = s => s === "lost" || s === "half_lost";

export const state = {picks: [], loaded: false, failed: "", updatedAt: null, stamp: ""};

export const $ = (s, root = document) => root.querySelector(s);
export const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
export const num = v => (v === null || v === undefined || v === "" || isNaN(Number(v))) ? null : Number(v);
export const prob = v => { const n = num(v); if(n === null) return null; return n > 1 ? n / 100 : n; };
export const decOf = p => { const d = num(p.odds_decimal); if(d && d > 1) return d; const a = num(p.odds_american); if(!a) return null; return a > 0 ? 1 + a / 100 : 1 + 100 / Math.abs(a); };
export const amFromDec = d => d >= 2 ? "+" + Math.round((d - 1) * 100) : String(Math.round(-100 / (d - 1)));
export const amOf = p => { const a = num(p.odds_american); if(a) return (a > 0 ? "+" : "") + Math.round(a); const d = decOf(p); return d ? amFromDec(d) : ""; };
export const unitsOf = p => { const u = num(p.units); return u && u > 0 ? u : 1; };
export const profitOf = p => {
  const r = num(p.result_units); if(r !== null && GRADED.has(p.status)) return r;
  const u = unitsOf(p), b = (decOf(p) || 2) - 1;
  return p.status === "won" ? u * b : p.status === "half_won" ? u * b / 2 : p.status === "lost" ? -u : p.status === "half_lost" ? -u / 2 : 0;
};
export const evOf = p => { const e = num(p.ev); if(e !== null) return Math.abs(e) > 1 ? e / 100 : e; const m = prob(p.model_prob), d = decOf(p); return (m !== null && d) ? m * d - 1 : null; };
export const sign = n => n > 0.0049 ? "+" : n < -0.0049 ? "−" : "";
export const fmtU = n => sign(n) + Math.abs(n).toFixed(2) + "u";
export const pct = (n, d) => (n * 100).toFixed(d === undefined ? 1 : d) + "%";
export const spct = (n, d) => sign(n * 100) + Math.abs(n * 100).toFixed(d === undefined ? 1 : d) + "%";
export const cls = n => n > 0.0049 ? "pos" : n < -0.0049 ? "neg" : "";
export const list = v => Array.isArray(v) ? v.filter(Boolean) : (v ? String(v).split(/\n+/).map(s => s.trim()).filter(Boolean) : []);
export const byDateAsc = (a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
export const clvOf = p => p && p.close ? num(p.close.clv) : null;
export const pickUrl = p => `/pick/${encodeURIComponent(p.id)}/`;

export const todayISO = () => new Intl.DateTimeFormat("en-CA", {timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date());
export const fmtDay = (d, opts) => { try { return new Intl.DateTimeFormat("en-US", Object.assign({weekday: "short", month: "short", day: "numeric"}, opts || {}, {timeZone: "UTC"})).format(new Date(d + "T12:00:00Z")); } catch(e){ return String(d || ""); } };
export const fmtTime = iso => { if(!iso) return ""; const t = new Date(iso); if(isNaN(t)) return String(iso); return new Intl.DateTimeFormat("en-US", {timeZone: TZ, hour: "numeric", minute: "2-digit", timeZoneName: "short"}).format(t); };
export const fmtStamp = iso => { const t = new Date(iso); if(isNaN(t)) return ""; return new Intl.DateTimeFormat("en-US", {timeZone: TZ, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}).format(t); };

export const newestFirst = () => state.picks.slice().sort(byDateAsc).reverse();
export const pickById = id => state.picks.find(p => p.id === id) || null;
export const todayPick = () => state.picks.find(p => p.date === todayISO()) || null;
export const latestPick = () => newestFirst()[0] || null;

// Record of the published picks, in units.
export function modelStats(){
  const g = state.picks.filter(p => GRADED.has(p.status));
  const W = g.filter(p => isW(p.status)).length, L = g.filter(p => isL(p.status)).length, P = g.filter(p => p.status === "push").length;
  const units = g.reduce((s, p) => s + profitOf(p), 0);
  const staked = g.reduce((s, p) => s + unitsOf(p), 0);
  const wl = g.filter(p => p.status !== "push");
  const be = wl.length ? wl.reduce((s, p) => s + 1 / (decOf(p) || 2), 0) / wl.length : null;
  const desc = wl.slice().sort(byDateAsc).reverse();
  let streak = "";
  if(desc.length){ const k = isW(desc[0].status); let n = 0; for(const p of desc){ if(isW(p.status) === k) n++; else break; } streak = (k ? "W" : "L") + n; }
  const cl = state.picks.filter(p => clvOf(p) !== null);
  return {g, W, L, P, units, staked, be, streak, cl, pending: state.picks.filter(p => p.status === "pending" || !p.status).length};
}

// Loads data/picks.json. Returns true when the data changed.
export async function loadPicks(){
  try {
    const r = await fetch("/data/picks.json?t=" + Date.now(), {cache: "no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    const text = await r.text();
    if(text === state.stamp && state.loaded) return false;
    const j = JSON.parse(text);
    state.stamp = text;
    const arr = Array.isArray(j) ? j : (j.picks || []);
    state.picks = arr.filter(Boolean).map(b => Object.assign({}, b, {
      id: b.id || b.date, date: b.date || b.id,
      status: String(b.status || "pending").toLowerCase().replace("-", "_")
    }));
    state.updatedAt = j.updated_at || null;
    state.loaded = true; state.failed = "";
    return true;
  } catch(e){
    if(!state.loaded){ state.failed = "Couldn't load the picks. Check your connection and pull down to refresh."; return true; }
    return false;
  }
}

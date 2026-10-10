// Target-mode maths (no page code, so it can be tested on its own).
// The question: what stakes give the best chance of reaching a target balance by a deadline?
// 1. dayDP works out, for every bankroll and every number of days left, the best chance of getting there,
//    when each day brings `perDay` bets of a typical size and edge. All of a day's bets are placed together
//    and settle together, so the chance it reports is the real one for betting a daily card, not the higher
//    number you'd get if you could see each result before placing the next bet.
// 2. bestPortfolio takes today's actual bets (their own odds and edges) and finds the stakes that maximize
//    the chance of hitting the target, using the value table from step 1 for the days after today.

export function binom(k, p){
  const out = new Float64Array(k + 1);
  out[0] = Math.pow(1 - p, k);
  for(let w = 1; w <= k; w++) out[w] = out[w - 1] * (k - w + 1) / w * p / (1 - p);
  return out;
}

export function dayDP(target, days, perDay, edge){
  const step = Math.max(1, Math.round(target / 200)), S = Math.round(target / step);
  const acts = [];
  for(const k of [...new Set([1, 2, 3, 5, perDay])].filter(k => k >= 1 && k <= perDay)) acts.push({k, o: 2.0, e: edge});
  for(const k of [...new Set([1, 2, Math.floor(perDay / 2)])].filter(k => k >= 1 && 2 * k <= perDay)) acts.push({k, o: 4.0, e: (1 + edge) * (1 + edge) - 1});
  for(const a of acts) a.bin = binom(a.k, Math.min(0.99, (1 + a.e) / a.o));
  let V = new Float64Array(S + 1); V[S] = 1;
  const levels = [V];                   // levels[j]: chance with j days left, by bankroll (grid units)
  for(let d = 1; d <= days; d++){
    const NV = new Float64Array(S + 1); NV[S] = 1;
    for(let b = 1; b < S; b++){
      let best = V[b];
      for(const a of acts){
        const w = a.o - 1, pr = a.bin, k = a.k;
        for(let s = 1; s * k <= b; s++){
          let v = 0;
          for(let x = 0; x <= k; x++){
            const nb = b + Math.round(s * (x * w - (k - x)));
            v += pr[x] * (nb >= S ? 1 : nb <= 0 ? 0 : V[nb]);
          }
          if(v > best) best = v;
        }
      }
      NV[b] = best;
    }
    levels.push(NV); V = NV;
  }
  return {step, S, levels};
}

export const valueAt = (W, S, x) => { if(x >= S) return 1; if(x <= 0) return 0; const i = Math.floor(x), f = x - i; return W[i] * (1 - f) + W[Math.min(S, i + 1)] * f; };

// Profit distribution of a set of simultaneous bets, to the nearest 50 cents.
export function pnlDist(bets){
  let dist = new Map([[0, 1]]);
  for(const b of bets){
    const up = Math.round(b.stake * (b.odds - 1) * 2), dn = Math.round(b.stake * 2), nd = new Map();
    for(const [k, v] of dist){
      nd.set(k + up, (nd.get(k + up) || 0) + v * b.p);
      nd.set(k - dn, (nd.get(k - dn) || 0) + v * (1 - b.p));
    }
    dist = nd;
  }
  return dist;
}

export function chanceAfter(bets, bank, D, W){
  let v = 0;
  for(const [k, pr] of pnlDist(bets)) v += pr * valueAt(W, D.S, (bank + k / 2) / D.step);
  return v;
}

// bets: [{id, odds, ev, parlayable?}] sorted best first. fixed: bets already placed today [{odds, ev, stake}].
// Returns {stakes: Map id -> $, chance, parlay, total}.
// Stakes inside a set are proportional to each bet's Kelly fraction; the search picks how many of the top
// bets to use, whether to pair the top two into a parlay, and the total to put down today.
export function bestPortfolio(bets, bank, D, daysLeft, round, fixed){
  const W = D.levels[Math.max(0, daysLeft - 1)];
  const r = round || (v => v);
  const fx = (fixed || []).filter(b => b.stake > 0 && b.odds > 1).map(b => ({odds: b.odds, stake: b.stake, p: Math.min(0.99, (1 + Math.max(0, b.ev || 0)) / b.odds)}));
  const fxTot = fx.reduce((a, b) => a + b.stake, 0), free = bank - fxTot;
  const prep = bets.filter(b => b.odds > 1 && b.ev > 0).map(b => Object.assign({}, b, {p: Math.min(0.99, (1 + b.ev) / b.odds), f: b.ev / (b.odds - 1)}));
  let best = {stakes: new Map(), chance: fx.length ? chanceAfter(fx, bank, D, W) : valueAt(W, D.S, bank / D.step), parlay: null, total: 0};
  if(!prep.length || free <= 0) return best;
  const sets = [];
  const n = prep.length;
  for(const k of [...new Set([1, 2, 3, 5, 8, n])].filter(k => k <= n)) sets.push(prep.slice(0, k));
  const legs = prep.filter(b => b.parlayable).slice(0, 2);
  if(legs.length === 2){
    const o = legs[0].odds * legs[1].odds, p = legs[0].p * legs[1].p, ev = p * o - 1;
    if(ev > 0){
      const par = {id: "parlay:" + legs.map(l => l.id).join("+"), odds: o, ev, p, f: ev / (o - 1), parlay: legs.map(l => l.id)};
      const rest = prep.filter(b => b !== legs[0] && b !== legs[1]);
      for(const k of [...new Set([0, 1, 3, rest.length])].filter(k => k <= rest.length)) sets.push([par, ...rest.slice(0, k)]);
    }
  }
  for(const set of sets){
    const fs = set.reduce((a, b) => a + b.f, 0);
    for(let T = 0.02; T <= 1.0001; T += 0.02){
      const bs = set.map(b => Object.assign({}, b, {stake: r(T * free * b.f / fs)})).filter(b => b.stake > 0);
      const tot = bs.reduce((a, b) => a + b.stake, 0);
      if(!bs.length || tot > free) continue;
      const c = chanceAfter(fx.concat(bs), bank, D, W);
      if(c > best.chance + 1e-6) best = {stakes: new Map(bs.map(b => [b.id, b.stake])), chance: c, parlay: bs.find(b => b.parlay) || null, total: tot};
    }
  }
  return best;
}

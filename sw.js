// Morning Line service worker: works offline, always tries for fresh picks first.
const VERSION = "587c58a5b8";
const CACHE = "ml-" + VERSION;
const CORE = ["/", "/results/", "/stats/", "/bankroll/", "/method/", "/404.html", "/manifest.webmanifest", "/favicon.png", "/icon-192.png", "/assets/css/main.css?v=587c58a5b8", "/assets/js/app.js?v=587c58a5b8", "/assets/js/bank.js?v=587c58a5b8", "/assets/js/charts.js?v=587c58a5b8", "/assets/js/core.js?v=587c58a5b8", "/assets/js/errors.js?v=587c58a5b8", "/assets/js/money.js?v=587c58a5b8", "/assets/js/picks.js?v=587c58a5b8", "/assets/js/stats.js?v=587c58a5b8", "/assets/js/target.js?v=587c58a5b8"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("ml-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function networkFirst(req, key){
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(req, {cache: "no-store"});
    if(res.ok) cache.put(key, res.clone());
    return res;
  } catch(e){
    const hit = await cache.match(key, {ignoreSearch: true});
    if(hit) return hit;
    if(req.mode === "navigate"){ const home = await cache.match("/"); if(home) return home; }
    throw e;
  }
}

async function cacheFirst(req){
  const cache = await caches.open(CACHE);
  const hit = await cache.match(req);
  if(hit) return hit;
  const res = await fetch(req);
  if(res.ok) cache.put(req, res.clone());
  return res;
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if(req.method !== "GET") return;
  const url = new URL(req.url);
  if(url.origin !== self.location.origin) return;
  if(url.pathname === "/data/picks.json") { e.respondWith(networkFirst(req, "/data/picks.json")); return; }
  if(req.mode === "navigate") { e.respondWith(networkFirst(req, url.pathname)); return; }
  if(url.pathname.startsWith("/assets/")) { e.respondWith(cacheFirst(req)); return; }
});

// Jarvis's phone app service worker (HTTPS only — on the relay's address; the computer's plain-http address has
// none). Two jobs:
//  - notifications: show one when it arrives, and open confirm.html when a "connect my phone" request is tapped
//    (everything confirm.html needs is in its own link; see confirm.html and relay/server.py's /decide);
//  - the app shell: it makes the page an installable app that opens even when the computer is off or the phone is offline:
// the app shell (the page, its Jarvis agent, the icons) is kept here and refreshed on every load that reaches the
// network. The network always comes first — an updated Jarvis reaches the phone the next time the app is opened —
// and the kept copy is used only when the network doesn't answer in time (a sleeping relay, no signal).

const SHELL = "jarvis-shell-v1";
const SHELL_FILES = ["/agent.js", "/manifest.webmanifest", "/apple-touch-icon.png", "/icons/icon-192.png",
                     "/vendor/fonts/orbitron-latin.woff2"];   // the display face: the app looks itself offline too
const NETWORK_WAIT = 3500;   // ms before the kept copy is used instead

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

const OFFLINE_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#02040a"><title>Jarvis</title><style>
@font-face{font-family:Orbitron;src:url(/vendor/fonts/orbitron-latin.woff2) format("woff2");font-weight:400 900}
html,body{height:100%;margin:0;background:#02040a;color:#e8f4ff;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;
padding:24px calc(24px + env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom)) calc(24px + env(safe-area-inset-left));
background:radial-gradient(120% 56% at 50% -12%,rgb(120 135 172/.2),transparent 64%),#02040a}
.orb{width:96px;height:96px;border-radius:50%;border:1px solid rgb(120 135 172/.3);border-top-color:#7887ac;
animation:t 9s linear infinite;margin-bottom:10px}@keyframes t{to{transform:rotate(360deg)}}
h1{font:600 21px/1.25 Orbitron,system-ui,sans-serif;letter-spacing:.02em;margin:0}
p{margin:0;color:#8fa3c4;max-width:290px;font-size:15.5px}button{margin-top:12px;border:0;min-height:52px;
padding:0 28px;font:600 16px system-ui,sans-serif;background:#4fd8ff;color:#021019;
clip-path:polygon(11px 0,100% 0,100% calc(100% - 11px),calc(100% - 11px) 100%,0 100%,0 11px)}
@media (prefers-reduced-motion:reduce){.orb{animation:none}}
</style></head><body><div class="orb"></div><h1>You're offline</h1>
<p>Jarvis will reconnect as soon as your phone is back online.</p>
<button onclick="location.reload()">Try again</button>
<script>addEventListener("online",()=>location.reload());setInterval(()=>navigator.onLine&&location.reload(),8000)</script>
</body></html>`;

/** Network first (and keep what it returns); the kept copy only if the network is too slow or unreachable. */
async function networkThenKept(request, keyUrl) {
  const cache = await caches.open(SHELL);
  const fromNetwork = fetch(request).then((response) => {
    if (response.ok) cache.put(keyUrl, response.clone()).catch(() => {});
    return response;
  });
  const timeout = new Promise((resolve) => setTimeout(resolve, NETWORK_WAIT, null));
  try {
    const first = await Promise.race([fromNetwork, timeout]);
    if (first) return first;
  } catch { /* network failed: fall through to the kept copy */ }
  const kept = await cache.match(keyUrl);
  if (kept) return kept;
  try { return await fromNetwork; } catch { return null; }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;   // Groq, websites: the browser's own handling, untouched
  if (request.mode === "navigate") {
    // Every launch of the app is the same page, whatever its ?query or #handoff: kept under one key.
    event.respondWith(networkThenKept(request, "/").then((r) => r ||
      new Response(OFFLINE_PAGE, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } })));
  } else if (SHELL_FILES.includes(url.pathname)) {
    event.respondWith(networkThenKept(request, url.pathname).then((r) => r || Response.error()));
  }
});

self.addEventListener("push", (event) => {
  let data = { title: "Jarvis", body: "", actions: [], data: {} };
  try { data = { ...data, ...event.data.json() }; } catch { /* a non-JSON push: keep the default text */ }
  event.waitUntil(
    self.registration.showNotification(data.title || "Jarvis", {
      body: data.body || "",
      tag: data.tag || "jarvis",
      actions: data.actions || [],
      data: data.data || {},
      requireInteraction: (data.actions || []).length > 0,   // a session request waits for a real tap, not a timeout
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  const sessionData = event.notification.data || {};
  const isSessionRequest = !!sessionData.sessionId;
  event.notification.close();

  if (!isSessionRequest) {
    event.waitUntil(self.clients.openWindow("/"));
    return;
  }

  // A native action button (where the platform supports one) already says which way this was decided — added as
  // &decision= so confirm.html auto-submits instead of asking again. A plain tap on the notification body leaves
  // it out, and the page shows its own Confirmed/Not Confirmed buttons. Either way, the link alone is everything
  // confirm.html needs; nothing here has to remember or look anything up for it.
  const decision = event.action === "confirm" || event.action === "reject" ? event.action : null;
  const target = `/confirm?computerId=${encodeURIComponent(sessionData.computerId || "")}` +
    `&sessionId=${encodeURIComponent(sessionData.sessionId)}&secret=${encodeURIComponent(sessionData.secret || "")}` +
    (decision ? `&decision=${decision}` : "");

  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of clients) {
      if ("navigate" in client) {
        try {
          await client.navigate(target);
          return client.focus();
        } catch { /* fall through to opening a fresh window instead */ }
      }
    }
    if (self.clients.openWindow) return self.clients.openWindow(target);
  })());
});

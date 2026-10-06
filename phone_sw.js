// Jarvis's phone page: the only thing this service worker does is show a notification when one arrives, and open
// confirm.html when it's tapped — a small, self-contained page that only ever needs the session id and secret
// already present in this link to decide a "connect my phone" request (see confirm.html and relay/server.py's
// /decide). Nothing is cached or looked up afterward; there's nothing left here that can go stale or fail to
// match up with a later page load.

//
// It also makes the page installable as an app (Chrome/Samsung Internet want a service worker that handles page
// loads) — deliberately without caching anything: every page load always goes to the network, so an updated
// Jarvis reaches the phone the very next time the app is opened, never a stale copy. The only thing it adds is a
// small built-in screen for when there's no connection at all (OFFLINE_PAGE), instead of the browser's own error
// page inside an installed app; it retries by itself as soon as the network is back.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

const OFFLINE_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05070f"><title>Jarvis</title><style>
html,body{height:100%;margin:0;background:#05070f;color:#e9eefb;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;
padding:24px calc(24px + env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom)) calc(24px + env(safe-area-inset-left))}
.orb{width:56px;height:56px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#8fe7ff,#4fd8ff 40%,#a58bff);
box-shadow:0 0 40px #4fd8ff55;animation:b 2.4s ease-in-out infinite}
@keyframes b{50%{transform:scale(.92);opacity:.7}}h1{font-size:20px;margin:8px 0 0;font-weight:650}
p{margin:0;color:#8f9bb8;max-width:280px;font-size:15px}button{margin-top:10px;border:0;border-radius:999px;
padding:13px 26px;font:600 15px system-ui,sans-serif;background:#e9eefb;color:#05070f}
</style></head><body><div class="orb"></div><h1>You're offline</h1>
<p>Jarvis will reconnect as soon as your phone is back online.</p>
<button onclick="location.reload()">Try again</button>
<script>addEventListener("online",()=>location.reload());setInterval(()=>navigator.onLine&&location.reload(),8000)</script>
</body></html>`;

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.mode !== "navigate") return;   // everything else: the browser's own default handling, untouched
  event.respondWith(fetch(request).catch(() =>
    new Response(OFFLINE_PAGE, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } })));
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

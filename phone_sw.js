// Jervis's phone page: the only thing this service worker does is show a notification when one arrives, and open
// confirm.html when it's tapped — a small, self-contained page that only ever needs the session id and secret
// already present in this link to decide a "connect my phone" request (see confirm.html and relay/server.py's
// /decide). Nothing is cached or looked up afterward; there's nothing left here that can go stale or fail to
// match up with a later page load.

self.addEventListener("push", (event) => {
  let data = { title: "Jervis", body: "", actions: [], data: {} };
  try { data = { ...data, ...event.data.json() }; } catch { /* a non-JSON push: keep the default text */ }
  event.waitUntil(
    self.registration.showNotification(data.title || "Jervis", {
      body: data.body || "",
      tag: data.tag || "jervis",
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

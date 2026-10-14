// Jarvis's phone tools for the web app (phone_client.html, installed to the Home Screen), sharing the native app's
// agent and app catalog. A web page can only hand the phone a link: it can't ask iOS whether an app is installed,
// read contacts, set alarms or open Settings. So each tool opens the app's link and watches whether the page went
// to the background (the app opened) — and says so plainly when it didn't, instead of claiming success.
import { findApp } from "../core/apps.ts";
import type { Tool, ToolResult } from "../core/tools.ts";

const UA = typeof navigator === "undefined" ? "" : navigator.userAgent;
const IOS = /iPad|iPhone|iPod/.test(UA) || (typeof navigator !== "undefined" && navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const ANDROID = /Android/i.test(UA);
const PHONE = IOS ? "iPhone" : "phone";
const enc = encodeURIComponent;
const str = (v: unknown) => String(v ?? "").trim();
const S = (description: string) => ({ type: "string", description });

/** Opens a link that belongs to an app; true if the app came up (this page went to the background). */
export function launch(url: string, wait = 2500): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (opened: boolean) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onHide);
      clearTimeout(timer);
      resolve(opened);
    };
    const onVisibility = () => { if (document.hidden) finish(true); };
    const onHide = () => finish(true);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onHide);
    const timer = setTimeout(() => finish(false), wait);
    try { window.location.href = url; } catch { finish(false); }
  });
}

/** A website in a new tab (never navigating the Jarvis app itself away). */
function openWeb(url: string): boolean {
  try { return !!window.open(url, "_blank", "noopener"); } catch { return false; }
}

/** Android: a custom-scheme link aimed at one app ("spotify:…" in com.spotify.music). */
function androidIntent(url: string, pkg?: string): string {
  const m = /^([a-z][a-z0-9+.-]*):(?:\/\/)?(.*)$/i.exec(url);
  if (!m || !pkg) return url;
  return `intent://${m[2]}#Intent;scheme=${m[1]};package=${pkg};end`;
}

const ANDROID_LINKS: Record<string, string> = {   // system apps reachable by a plain link on Android
  messages: "sms:", phone: "tel:", maps: "geo:0,0?q=", mail: "mailto:",
};

async function openApp(name: string): Promise<ToolResult> {
  const app = findApp(name);
  if (!app) return { ok: false, message: `I don't know how to open “${name}” on this ${PHONE} yet.` };
  if (app.id === "browser" || app.id === "google") {
    return openWeb("https://www.google.com") ? { ok: true, message: "Opened Google." } : { ok: false, message: "I couldn't open the browser." };
  }
  let url = "";
  if (IOS) url = app.iosNote ? "" : app.ios ?? "";
  else if (ANDROID) url = ANDROID_LINKS[app.id] ?? (app.ios && /:\/\/$/.test(app.ios) ? androidIntent(app.ios, app.android?.find((l) => l.package)?.package) : "");
  if (!url || /^(?:app-prefs|x-web-search|clock-alarm|calshow|contacts|shareddocuments)/i.test(url)) {
    return { ok: false, message: `The web app can't open ${app.name} on this ${PHONE}${app.iosNote ? ` (${app.iosNote.toLowerCase()})` : ""}. The full Jarvis app can.` };
  }
  if (await launch(url)) return { ok: true, message: `Opened ${app.name}.` };
  if (app.web && openWeb(app.web)) return { ok: false, message: `${app.name} didn't open (it may not be installed), so I opened its website.` };
  return { ok: false, message: `${app.name} didn't open. It may not be installed on this ${PHONE}.` };
}

export function webPhoneTools(): Tool[] {
  return [
    {
      name: "open_app", where: "phone",
      description: `Open an app on this ${PHONE} by name (Spotify, YouTube, Maps, WhatsApp, Instagram, Messages, Photos, Gmail, ...).`,
      parameters: { type: "object", properties: { app: S("App name as the user said it") }, required: ["app"] },
      label: (a) => `Opening ${findApp(str(a.app))?.name ?? str(a.app)}`,
      run: (a) => openApp(str(a.app)),
    },
    {
      name: "spotify", where: "phone",
      description: "Find music on Spotify on this phone (artist, song, album, playlist). Opens Spotify on that search; the user taps play.",
      parameters: { type: "object", properties: { query: S("What to find") }, required: ["query"] },
      label: (a) => `Finding ${str(a.query)} on Spotify`,
      run: async (a) => {
        const q = str(a.query);
        const url = `spotify:search:${enc(q)}`;
        if (await launch(ANDROID ? androidIntent(url, "com.spotify.music") : url)) return { ok: true, message: `Opened Spotify on “${q}”. Tap play to start it.` };
        return openWeb(`https://open.spotify.com/search/${enc(q)}`)
          ? { ok: false, message: `Spotify didn't open (it may not be installed), so I searched “${q}” on the Spotify website.` }
          : { ok: false, message: "Spotify didn't open." };
      },
    },
    {
      name: "youtube", where: "phone",
      description: "Search YouTube on this phone.",
      parameters: { type: "object", properties: { query: S("What to search for") }, required: ["query"] },
      label: (a) => `Searching YouTube for ${str(a.query)}`,
      run: async (a) => {
        const q = str(a.query), web = `https://www.youtube.com/results?search_query=${enc(q)}`;
        const app = IOS ? `youtube://results?search_query=${enc(q)}` : ANDROID ? `intent://www.youtube.com/results?search_query=${enc(q)}#Intent;scheme=https;package=com.google.android.youtube;end` : "";
        if (app && (await launch(app))) return { ok: true, message: `Searching YouTube for “${q}”.` };
        return openWeb(web) ? { ok: true, message: `Searching YouTube for “${q}” in the browser.` } : { ok: false, message: "I couldn't open YouTube." };
      },
    },
    {
      name: "maps", where: "phone",
      description: "Maps on this phone: search places (\"coffee near me\") or get directions to a destination.",
      parameters: { type: "object", properties: { query: S("Place or kind of place"), destination: S("Where to get directions to"),
                                                  mode: { type: "string", enum: ["driving", "walking", "transit", "cycling"] } } },
      label: (a) => (a.destination ? `Directions to ${str(a.destination)}` : `Finding ${str(a.query)}`),
      run: async (a) => {
        const dest = str(a.destination), q = str(a.query) || dest;
        if (!q) return { ok: false, message: "Where to?" };
        const mode = str(a.mode) || "driving";
        const url = IOS
          ? (dest ? `maps://?daddr=${enc(dest)}&dirflg=${({ driving: "d", walking: "w", transit: "r", cycling: "c" } as Record<string, string>)[mode] ?? "d"}` : `maps://?q=${enc(q)}`)
          : ANDROID ? (dest ? `google.navigation:q=${enc(dest)}` : `geo:0,0?q=${enc(q)}`) : "";
        if (url && (await launch(url))) return { ok: true, message: dest ? `Getting directions to ${dest}.` : `Showing “${q}” in Maps.` };
        const web = dest ? `https://www.google.com/maps/dir/?api=1&destination=${enc(dest)}` : `https://www.google.com/maps/search/?api=1&query=${enc(q)}`;
        return openWeb(web) ? { ok: true, message: dest ? `Opened directions to ${dest}.` : `Opened “${q}” in Google Maps.` } : { ok: false, message: "I couldn't open Maps." };
      },
    },
    {
      name: "call", where: "phone",
      description: "Call a phone number from this phone. (The web app can't see contacts: it needs the number.)",
      parameters: { type: "object", properties: { who: S("Phone number, or the person's name") }, required: ["who"] },
      label: (a) => `Calling ${str(a.who)}`,
      run: async (a) => {
        const who = str(a.who);
        if (!/^\+?[\d\s()-]{5,}$/.test(who)) return { ok: false, message: `The web app can't see your contacts, so I don't have ${who}'s number. Tell me the number, or the full Jarvis app can look it up.` };
        return (await launch(`tel:${who.replace(/[^\d+]/g, "")}`, 4000)) ? { ok: true, message: `Calling ${who}.` } : { ok: true, message: `Your phone should be showing the call to ${who}.` };
      },
    },
    {
      name: "message", where: "phone",
      description: "Write a text message to a phone number from this phone (opens it ready to send).",
      parameters: { type: "object", properties: { who: S("Phone number, or the person's name"), text: S("The message") }, required: ["who"] },
      label: (a) => `Writing to ${str(a.who)}`,
      run: async (a) => {
        const who = str(a.who), text = str(a.text);
        if (!/^\+?[\d\s()-]{5,}$/.test(who)) return { ok: false, message: `The web app can't see your contacts, so I don't have ${who}'s number. Tell me the number, or the full Jarvis app can look it up.` };
        const url = `sms:${who.replace(/[^\d+]/g, "")}${text ? `${IOS ? "&" : "?"}body=${enc(text)}` : ""}`;
        return (await launch(url, 4000)) ? { ok: true, message: `Your message to ${who} is ready. Tap send.` } : { ok: false, message: "Messages didn't open." };
      },
    },
    {
      name: "email", where: "phone",
      description: "Write an email (opens the mail app with it filled in).",
      parameters: { type: "object", properties: { to: S("Address"), subject: S("Subject"), body: S("Body") } },
      label: () => "Writing an email",
      run: async (a) => {
        const q = [a.subject && `subject=${enc(str(a.subject))}`, a.body && `body=${enc(str(a.body))}`].filter(Boolean).join("&");
        return (await launch(`mailto:${enc(str(a.to))}${q ? `?${q}` : ""}`, 4000)) ? { ok: true, message: "Your email is ready to send." } : { ok: false, message: "No mail app opened." };
      },
    },
    {
      name: "web_search", where: "phone",
      description: "Open a Google search in the browser (when the user wants to browse results themselves).",
      parameters: { type: "object", properties: { query: S("Search terms") }, required: ["query"] },
      label: (a) => `Searching Google for ${str(a.query)}`,
      run: async (a) => (openWeb(`https://www.google.com/search?q=${enc(str(a.query))}`)
        ? { ok: true, message: `Searching Google for “${str(a.query)}”.` } : { ok: false, message: "I couldn't open the browser." }),
    },
    {
      name: "open_url", where: "phone",
      description: "Open a website.",
      parameters: { type: "object", properties: { url: S("The address") }, required: ["url"] },
      label: (a) => `Opening ${str(a.url)}`,
      run: async (a) => {
        const url = /^https?:\/\//i.test(str(a.url)) ? str(a.url) : `https://${str(a.url)}`;
        return openWeb(url) ? { ok: true, message: `Opened ${str(a.url)}.` } : { ok: false, message: `I couldn't open ${str(a.url)}.` };
      },
    },
  ];
}

export const WEB_APP_NOTE =
  "This is the Jarvis web app on the phone: it can't read contacts (calls and texts need a number), set alarms, " +
  "timers or reminders, add calendar events, open Settings, or switch Wi-Fi/Bluetooth. Say so plainly when asked, " +
  "and suggest the iPhone's Siri or the Clock app for alarms and timers.";

// Jarvis's phone capabilities, each using the mechanism the platform actually provides (URL schemes and universal
// links on iOS; intents, categories and packages on Android). Every message says exactly what happened — if the OS
// doesn't allow something, Jarvis says so instead of pretending. Registered as Tools (see src/core/tools.ts).
import { Linking, Platform, Share } from "react-native";
import Constants from "expo-constants";
import * as IntentLauncher from "expo-intent-launcher";
import * as Notifications from "expo-notifications";
import * as ImagePicker from "expo-image-picker";
import { Contact, ContactField, requestPermissionsAsync as requestContactsPermission } from "expo-contacts";
import { findApp, type AndroidLaunch, type AppEntry } from "../core/apps.ts";
import type { Tool, ToolResult } from "../core/tools.ts";

const IOS = Platform.OS === "ios";
const ANDROID = Platform.OS === "android";
const PHONE = IOS ? "iPhone" : "phone";
export const IN_EXPO_GO = Constants.executionEnvironment === "storeClient";
const enc = encodeURIComponent;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ launching
/** true if the system opened `url` (iOS rejects when no installed app handles it). */
async function openUrl(url: string): Promise<boolean> {
  try { await Linking.openURL(url); return true; } catch { return false; }
}

/** Android: an intent; resolves true once it's clearly launched, false if nothing could handle it. */
async function startActivity(action: string, params: IntentLauncher.IntentLauncherParams = {}): Promise<boolean> {
  // startActivityAsync only settles when the user comes back, so a quick rejection = nothing could handle it.
  const outcome = await Promise.race([
    IntentLauncher.startActivityAsync(action, params).then(() => "returned", () => "failed"),
    sleep(900).then(() => "launched"),
  ]);
  return outcome !== "failed";
}

async function launchAndroid(launch: AndroidLaunch): Promise<boolean> {
  if (launch.package) {
    try { IntentLauncher.openApplication(launch.package); return true; } catch { return false; }
  }
  if (launch.category) return startActivity("android.intent.action.MAIN", { category: launch.category });
  if (!launch.action) return false;
  return startActivity(launch.action, launch.data ? { data: launch.data } : {});
}

async function launchApp(app: AppEntry): Promise<ToolResult> {
  if (IOS) {
    if (app.id === "camera") return openCamera();
    if (app.iosNote || !app.ios) return { ok: false, message: `${app.iosNote ?? `I can't open ${app.name} on iPhone`}.` };
    if (await openUrl(app.ios)) return { ok: true, message: `Opened ${app.name}.` };
    if (app.id === "settings" && (await openUrl("app-settings:"))) return { ok: true, message: "Opened Settings." };
    return { ok: false, message: `${app.name} isn't installed on this iPhone${app.iosStore ? " (I can open it in the App Store)" : ""}.`,
             data: { notInstalled: true } };
  }
  if (ANDROID) {
    for (const launch of app.android ?? []) if (await launchAndroid(launch)) return { ok: true, message: `Opened ${app.name}.` };
    // Most apps register the same URL scheme on Android as on iOS; opening it doesn't need package visibility.
    if (app.ios && /^[a-z][a-z0-9.+-]*:\/\/$/i.test(app.ios) && !/^(?:app-prefs|x-web-search|calshow|clock-alarm|mobilephone|contacts|message|music|photos-redirect|shareddocuments|mobilenotes|itms-apps):/i.test(app.ios)
        && (await openUrl(app.ios))) return { ok: true, message: `Opened ${app.name}.` };
    return { ok: false, message: `${app.name} isn't installed on this phone.`, data: { notInstalled: true } };
  }
  if (app.web && (await openUrl(app.web))) return { ok: true, message: `Opened ${app.name} in the browser.` };
  return { ok: false, message: `I can't open ${app.name} here.` };
}

// ------------------------------------------------------------------ contacts
type Person = { name: string; number: string };
async function findPerson(who: string): Promise<Person | Person[] | string> {
  const raw = (who || "").trim();
  if (/^\+?[\d\s()-]{5,}$/.test(raw)) return { name: raw, number: raw.replace(/[^\d+]/g, "") };
  const { granted } = await requestContactsPermission();
  if (!granted) return "I need access to your contacts for that. You can allow it in Settings.";
  const found = await Contact.getAllDetails([ContactField.FULL_NAME, ContactField.PHONES], { name: raw, limit: 10 });
  const people = found.flatMap((c) => (c.phones ?? []).slice(0, 1).filter((p) => p.number)
    .map((p) => ({ name: c.fullName || raw, number: String(p.number) })));
  if (!people.length) return `I couldn't find ${raw} in your contacts.`;
  const exact = people.filter((p) => p.name.toLowerCase() === raw.toLowerCase());
  if (exact.length === 1 || people.length === 1) return exact[0] ?? people[0];
  return people.slice(0, 4);
}
const whichOne = (people: Person[]) => `Which one: ${people.map((p) => p.name).join(", ")}?`;

// ------------------------------------------------------------------ notifications (timers/reminders on iPhone)
async function notifyAt(when: Date | number, title: string, body: string): Promise<boolean> {
  const perm = await Notifications.requestPermissionsAsync();
  if (!perm.granted) return false;
  const trigger = typeof when === "number"
    ? { type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL, seconds: Math.max(1, Math.round(when)) } as const
    : { type: Notifications.SchedulableTriggerInputTypes.DATE, date: when } as const;
  await Notifications.scheduleNotificationAsync({ content: { title, body, sound: true }, trigger });
  return true;
}
const clock = (d: Date) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const duration = (s: number) => s >= 3600 ? `${+(s / 3600).toFixed(1)} hour${s === 3600 ? "" : "s"}`
  : s >= 60 ? `${Math.round(s / 60)} minute${Math.round(s / 60) === 1 ? "" : "s"}` : `${s} seconds`;

// ------------------------------------------------------------------ camera
async function openCamera(): Promise<ToolResult> {
  if (ANDROID && (await startActivity("android.media.action.STILL_IMAGE_CAMERA"))) return { ok: true, message: "Opened the camera." };
  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) return { ok: false, message: "I need camera access for that. You can allow it in Settings." };
  const shot = await ImagePicker.launchCameraAsync({ quality: 0.8 });
  if (shot.canceled) return { ok: true, message: IOS ? "iPhone doesn't let apps open the Camera app, so I opened the camera here. No photo taken." : "No photo taken." };
  return { ok: true, message: "Got the photo.", data: { imageUri: shot.assets[0]?.uri } };
}

// ------------------------------------------------------------------ the tools
const str = (v: unknown) => String(v ?? "").trim();
const S = (description: string) => ({ type: "string", description });

export function phoneTools(): Tool[] {
  return [
    {
      name: "open_app", where: "phone",
      description: `Open an app on this ${PHONE} by name (Spotify, YouTube, Maps, Camera, Photos, Messages, Settings, Calendar, Clock, WhatsApp, ...).`,
      parameters: { type: "object", properties: { app: S("App name as the user said it") }, required: ["app"] },
      label: (a) => `Opening ${findApp(str(a.app))?.name ?? str(a.app)}`,
      run: async (a) => {
        const app = findApp(str(a.app));
        return app ? launchApp(app) : { ok: false, message: `I don't know how to open “${str(a.app)}” on this ${PHONE} yet.` };
      },
    },
    {
      name: "spotify", where: "phone",
      description: "Find music on Spotify on this phone (an artist, song, album or playlist). Opens Spotify on that search; the user taps play — phone apps can't press play in Spotify.",
      parameters: { type: "object", properties: { query: S("What to find, e.g. 'Radiohead' or 'OK Computer'") }, required: ["query"] },
      label: (a) => `Finding ${str(a.query)} on Spotify`,
      run: async (a) => {
        const q = str(a.query);
        if (await openUrl(`spotify:search:${enc(q)}`)) return { ok: true, message: `Opened Spotify on “${q}”. Tap play to start it.` };
        return { ok: false, message: `Spotify isn't installed on this ${PHONE}.`, data: { notInstalled: true } };
      },
    },
    {
      name: "youtube", where: "phone",
      description: "Search YouTube on this phone (opens the YouTube app, or the browser if it isn't installed).",
      parameters: { type: "object", properties: { query: S("What to search for") }, required: ["query"] },
      label: (a) => `Searching YouTube for ${str(a.query)}`,
      run: async (a) => {
        const q = str(a.query), web = `https://www.youtube.com/results?search_query=${enc(q)}`;
        if (IOS && (await openUrl(`youtube://results?search_query=${enc(q)}`))) return { ok: true, message: `Searching YouTube for “${q}”.` };
        if (ANDROID && (await startActivity("android.intent.action.VIEW", { data: web, packageName: "com.google.android.youtube" })))
          return { ok: true, message: `Searching YouTube for “${q}”.` };
        return (await openUrl(web)) ? { ok: true, message: `Searching YouTube for “${q}” in the browser.` } : { ok: false, message: "I couldn't open YouTube." };
      },
    },
    {
      name: "web_search", where: "phone",
      description: "Open a Google search in the browser on this phone (when the user wants to browse results themselves).",
      parameters: { type: "object", properties: { query: S("Search terms") }, required: ["query"] },
      label: (a) => `Searching Google for ${str(a.query)}`,
      run: async (a) => (await openUrl(`https://www.google.com/search?q=${enc(str(a.query))}`))
        ? { ok: true, message: `Searching Google for “${str(a.query)}”.` } : { ok: false, message: "I couldn't open the browser." },
    },
    {
      name: "open_url", where: "phone",
      description: "Open a website or link on this phone.",
      parameters: { type: "object", properties: { url: S("The address") }, required: ["url"] },
      label: (a) => `Opening ${str(a.url)}`,
      run: async (a) => {
        const url = /^[a-z][a-z0-9+.-]*:/i.test(str(a.url)) ? str(a.url) : `https://${str(a.url)}`;
        return (await openUrl(url)) ? { ok: true, message: `Opened ${str(a.url)}.` } : { ok: false, message: `I couldn't open ${str(a.url)}.` };
      },
    },
    {
      name: "maps", where: "phone",
      description: "Maps on this phone: search places (\"coffee near me\", an address) or get directions to a destination.",
      parameters: { type: "object", properties: {
        query: S("A place or kind of place to search for, e.g. 'coffee shop near me'"),
        destination: S("Where to get directions to"),
        mode: { type: "string", enum: ["driving", "walking", "transit", "cycling"] } } },
      label: (a) => a.destination ? `Directions to ${str(a.destination)}` : `Finding ${str(a.query)}`,
      run: async (a) => {
        const dest = str(a.destination), q = str(a.query) || dest;
        if (!q) return { ok: false, message: "Where to?" };
        const mode = str(a.mode) || "driving";
        if (IOS) {
          const flag = { driving: "d", walking: "w", transit: "r", cycling: "c" }[mode] ?? "d";
          const ok = await openUrl(dest ? `maps://?daddr=${enc(dest)}&dirflg=${flag}` : `maps://?q=${enc(q)}`);
          return ok ? { ok: true, message: dest ? `Getting directions to ${dest}.` : `Showing “${q}” in Maps.` } : { ok: false, message: "I couldn't open Maps." };
        }
        if (dest) {
          const gm = { driving: "d", walking: "w", cycling: "b", transit: "d" }[mode] ?? "d";
          if (await startActivity("android.intent.action.VIEW", { data: `google.navigation:q=${enc(dest)}&mode=${gm}` }))
            return { ok: true, message: `Starting directions to ${dest}.` };
        }
        return (await startActivity("android.intent.action.VIEW", { data: `geo:0,0?q=${enc(q)}` }))
          ? { ok: true, message: dest ? `Showing ${dest} in Maps.` : `Showing “${q}” in Maps.` } : { ok: false, message: "There's no maps app on this phone." };
      },
    },
    {
      name: "call", where: "phone",
      description: "Call someone from this phone, by contact name or number. The phone shows its own call screen.",
      parameters: { type: "object", properties: { who: S("Contact name or phone number") }, required: ["who"] },
      label: (a) => `Calling ${str(a.who)}`,
      run: async (a) => {
        const p = await findPerson(str(a.who));
        if (typeof p === "string") return { ok: false, message: p };
        if (Array.isArray(p)) return { ok: false, message: whichOne(p), data: { candidates: p.map((x) => x.name) } };
        return (await openUrl(`tel:${p.number}`)) ? { ok: true, message: IOS ? `Calling ${p.name}.` : `Dialing ${p.name}. Tap call.` }
          : { ok: false, message: "This device can't make calls." };
      },
    },
    {
      name: "message", where: "phone",
      description: "Write a text message (or WhatsApp) to someone. Opens the message ready to send; the user taps send.",
      parameters: { type: "object", properties: { who: S("Contact name or number"), text: S("The message"),
                                                  app: { type: "string", enum: ["sms", "whatsapp"] } }, required: ["who"] },
      label: (a) => `Writing to ${str(a.who)}`,
      run: async (a) => {
        const p = await findPerson(str(a.who));
        if (typeof p === "string") return { ok: false, message: p };
        if (Array.isArray(p)) return { ok: false, message: whichOne(p), data: { candidates: p.map((x) => x.name) } };
        const text = str(a.text);
        if (str(a.app) === "whatsapp") {
          const ok = await openUrl(`whatsapp://send?phone=${p.number.replace(/[^\d]/g, "")}${text ? `&text=${enc(text)}` : ""}`);
          return ok ? { ok: true, message: `Opened WhatsApp to ${p.name}. Tap send.` } : { ok: false, message: "WhatsApp isn't installed." };
        }
        const url = `sms:${p.number}${text ? `${IOS ? "&" : "?"}body=${enc(text)}` : ""}`;
        return (await openUrl(url)) ? { ok: true, message: `Your message to ${p.name} is ready. Tap send.` } : { ok: false, message: "This device can't send texts." };
      },
    },
    {
      name: "email", where: "phone",
      description: "Write an email on this phone (opens the mail app with it filled in; the user sends it).",
      parameters: { type: "object", properties: { to: S("Address"), subject: S("Subject"), body: S("Body") } },
      label: () => "Writing an email",
      run: async (a) => {
        const q = [a.subject && `subject=${enc(str(a.subject))}`, a.body && `body=${enc(str(a.body))}`].filter(Boolean).join("&");
        return (await openUrl(`mailto:${enc(str(a.to))}${q ? `?${q}` : ""}`)) ? { ok: true, message: "Your email is ready to send." }
          : { ok: false, message: "There's no mail app set up on this phone." };
      },
    },
    {
      name: "camera", where: "phone", description: "Open the camera to take a photo.",
      parameters: { type: "object", properties: {} }, label: () => "Opening the camera", run: () => openCamera(),
    },
    {
      name: "set_alarm", where: "phone",
      description: "Set an alarm on this phone's clock (24-hour time).",
      parameters: { type: "object", properties: { hour: { type: "integer", minimum: 0, maximum: 23 }, minute: { type: "integer", minimum: 0, maximum: 59 },
                                                  label: S("Optional name") }, required: ["hour"] },
      label: (a) => `Setting an alarm for ${String(a.hour).padStart(2, "0")}:${String(a.minute ?? 0).padStart(2, "0")}`,
      run: async (a) => {
        const at = new Date(); at.setHours(Number(a.hour), Number(a.minute ?? 0), 0, 0);
        if (ANDROID) {
          const ok = await startActivity("android.intent.action.SET_ALARM", { extra: {
            "android.intent.extra.alarm.HOUR": Number(a.hour), "android.intent.extra.alarm.MINUTES": Number(a.minute ?? 0),
            "android.intent.extra.alarm.MESSAGE": str(a.label) || "Jarvis", "android.intent.extra.alarm.SKIP_UI": true } });
          if (ok) return { ok: true, message: `Alarm set for ${clock(at)}.` };
          return (await startActivity("android.intent.action.SHOW_ALARMS"))
            ? { ok: false, message: `I couldn't set it myself, so I opened your alarms. Add ${clock(at)} there.` }
            : { ok: false, message: "This phone's clock app didn't accept the alarm." };
        }
        const opened = await openUrl("clock-alarm://");
        return { ok: false, message: `iPhone doesn't let apps set alarms in the Clock app${opened ? ", so I opened it for you. Add " + clock(at) + " there" : ""}. I can remind you at ${clock(at)} with a notification instead.` };
      },
    },
    {
      name: "set_timer", where: "phone",
      description: "Start a timer on this phone.",
      parameters: { type: "object", properties: { seconds: { type: "integer", minimum: 1 }, label: S("Optional name") }, required: ["seconds"] },
      label: (a) => `Timer for ${duration(Number(a.seconds))}`,
      run: async (a) => {
        const seconds = Math.round(Number(a.seconds));
        if (ANDROID && (await startActivity("android.intent.action.SET_TIMER", { extra: {
          "android.intent.extra.alarm.LENGTH": seconds, "android.intent.extra.alarm.MESSAGE": str(a.label) || "Jarvis",
          "android.intent.extra.alarm.SKIP_UI": true } }))) return { ok: true, message: `Timer set for ${duration(seconds)}.` };
        return (await notifyAt(seconds, "Time's up", str(a.label) || `Your ${duration(seconds)} timer is done.`))
          ? { ok: true, message: `Timer set for ${duration(seconds)}. I'll notify you.` }
          : { ok: false, message: "I need permission to send notifications for timers. You can allow it in Settings." };
      },
    },
    {
      name: "reminder", where: "phone",
      description: "Remind the user about something at a time (sent as a notification on this phone).",
      parameters: { type: "object", properties: { text: S("What to remind about"), at: S("When, ISO 8601 local time, e.g. 2026-10-07T17:00:00") }, required: ["text", "at"] },
      label: (a) => `Reminder: ${str(a.text)}`,
      run: async (a) => {
        const at = new Date(str(a.at));
        if (isNaN(at.getTime()) || at.getTime() < Date.now()) return { ok: false, message: "When should I remind you?" };
        return (await notifyAt(at, "Reminder", str(a.text)))
          ? { ok: true, message: `I'll remind you ${sameDay(at) ? "at" : "on " + at.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }) + " at"} ${clock(at)}.` }
          : { ok: false, message: "I need permission to send notifications for reminders. You can allow it in Settings." };
      },
    },
    {
      name: "calendar_event", where: "phone",
      description: "Add an event to the calendar on this phone.",
      parameters: { type: "object", properties: { title: S("Event title"), start: S("Start, ISO 8601 local time"), end: S("End, ISO 8601 local time (optional)"),
                                                  location: S("Optional") }, required: ["title", "start"] },
      label: (a) => `Adding “${str(a.title)}” to your calendar`,
      confirm: (a) => ({ title: `Add “${str(a.title)}” to your calendar?`, detail: describeWhen(str(a.start), str(a.end)) }),
      run: (a) => addCalendarEvent(str(a.title), str(a.start), str(a.end), str(a.location)),
    },
    {
      name: "settings", where: "phone",
      description: "Open this phone's settings, e.g. Wi-Fi, Bluetooth, location, display, sound, battery. (Apps can't switch Wi-Fi/Bluetooth themselves; this opens the right place.)",
      parameters: { type: "object", properties: { section: { type: "string", enum: ["general", "wifi", "bluetooth", "location", "airplane", "display", "sound", "battery", "notifications", "hotspot", "nfc", "internet"] } } },
      label: (a) => `Opening ${str(a.section) || "settings"}`,
      run: (a) => openSettings(str(a.section)),
    },
    {
      name: "share", where: "phone",
      description: "Share text or a link from this phone (opens the share sheet).",
      parameters: { type: "object", properties: { text: S("What to share") }, required: ["text"] },
      label: () => "Sharing",
      run: async (a) => { await Share.share({ message: str(a.text) }); return { ok: true, message: "Shared." }; },
    },
  ];
}

const sameDay = (d: Date) => d.toDateString() === new Date().toDateString();
function describeWhen(start: string, end: string): string {
  const s = new Date(start);
  if (isNaN(s.getTime())) return start;
  const day = s.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const e = end ? new Date(end) : null;
  return `${day}, ${clock(s)}${e && !isNaN(e.getTime()) ? `–${clock(e)}` : ""}`;
}

async function addCalendarEvent(title: string, start: string, end: string, location: string): Promise<ToolResult> {
  const s = new Date(start);
  if (isNaN(s.getTime())) return { ok: false, message: "When is it?" };
  const e = end && !isNaN(new Date(end).getTime()) ? new Date(end) : new Date(s.getTime() + 3600000);
  if (!IN_EXPO_GO) {
    try {
      // The full app: straight into the calendar (expo-calendar isn't part of Expo Go).
      const Calendar = require("expo-calendar") as typeof import("expo-calendar");
      const perm = await Calendar.requestCalendarPermissions();
      if (!perm.granted) return { ok: false, message: "I need calendar access for that. You can allow it in Settings." };
      const calendar = IOS ? Calendar.getDefaultCalendarSync() : (await Calendar.getCalendars()).find((c) => c.allowsModifications);
      if (!calendar) return { ok: false, message: "I couldn't find a calendar I'm allowed to add to." };
      await calendar.createEvent({ title, startDate: s, endDate: e, location: location || undefined });
      return { ok: true, message: `Added “${title}” to your calendar for ${describeWhen(s.toISOString(), e.toISOString())}.` };
    } catch { /* fall through to the system screen */ }
  }
  if (ANDROID && (await startActivity("android.intent.action.INSERT", { data: "content://com.android.calendar/events", extra: {
    title, beginTime: s.getTime(), endTime: e.getTime(), eventLocation: location } }))) {
    return { ok: true, message: `Opened a new “${title}” event in your calendar. Tap save to add it.` };
  }
  await openUrl(`calshow:${Math.floor(s.getTime() / 1000 - 978307200)}`);
  return { ok: false, message: "Adding events directly needs the full Jarvis app (not the preview). I opened your calendar at that day so you can add it." };
}

async function openSettings(section: string): Promise<ToolResult> {
  const why: Record<string, string> = {
    wifi: "Apps can't switch Wi-Fi themselves", bluetooth: "Apps can't switch Bluetooth themselves",
    airplane: "Apps can't switch airplane mode themselves", hotspot: "Apps can't turn on the hotspot themselves",
  };
  if (ANDROID) {
    const actions: Record<string, string[]> = {
      wifi: ["android.settings.panel.action.WIFI", "android.settings.WIFI_SETTINGS"],
      internet: ["android.settings.panel.action.INTERNET_CONNECTIVITY", "android.settings.WIRELESS_SETTINGS"],
      bluetooth: ["android.settings.BLUETOOTH_SETTINGS"], location: ["android.settings.LOCATION_SOURCE_SETTINGS"],
      airplane: ["android.settings.AIRPLANE_MODE_SETTINGS"], display: ["android.settings.DISPLAY_SETTINGS"],
      sound: ["android.settings.panel.action.VOLUME", "android.settings.SOUND_SETTINGS"], battery: ["android.settings.BATTERY_SAVER_SETTINGS"],
      notifications: ["android.settings.ALL_APPS_NOTIFICATION_SETTINGS", "android.settings.NOTIFICATION_SETTINGS"],
      hotspot: ["android.settings.TETHER_SETTINGS", "android.settings.WIRELESS_SETTINGS"], nfc: ["android.settings.panel.action.NFC", "android.settings.NFC_SETTINGS"],
      general: ["android.settings.SETTINGS"],
    };
    for (const action of actions[section] ?? actions.general) {
      if (await startActivity(action)) {
        const name = section && section !== "general" ? `${pretty(section)} settings` : "Settings";
        return { ok: true, message: why[section] ? `${why[section]} on Android, so I opened ${name}. Flip the switch there.` : `Opened ${name}.` };
      }
    }
    return { ok: false, message: "I couldn't open Settings." };
  }
  if (await openUrl("App-Prefs:")) {
    return { ok: true, message: why[section] ? `${why[section]} on iPhone, so I opened Settings. Quickest is Control Center: swipe down from the top-right corner.` : "Opened Settings." };
  }
  await Linking.openSettings();
  return { ok: !why[section], message: why[section] ? `${why[section]} on iPhone. Use Control Center: swipe down from the top-right corner.` : "Opened Jarvis's settings." };
}
const pretty = (s: string) => ({ wifi: "Wi-Fi", nfc: "NFC" } as Record<string, string>)[s] ?? s[0].toUpperCase() + s.slice(1);

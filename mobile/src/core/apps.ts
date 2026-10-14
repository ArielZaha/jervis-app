// Apps Jarvis can open on the phone, as data. iOS opens apps through their URL schemes (an app that isn't installed
// makes the open fail, which is how "isn't installed" is detected — never assumed). Android prefers a system
// *category* where one exists (whatever gallery/messages/calendar app this Samsung or Xiaomi actually uses), else
// the app's package. Add an app here and "open <it>" just works; nothing else changes.

/** One way to open it on Android: a package, a system category (e.g. APP_GALLERY), or an intent action. */
export type AndroidLaunch = { package?: string; category?: string; action?: string; data?: string };

export type AppEntry = {
  id: string;
  name: string;
  aliases: string[];
  ios?: string;                  // URL that opens the app
  iosNote?: string;              // why it can't be opened on iPhone (shown instead of failing silently)
  android?: AndroidLaunch[];     // tried in order
  web?: string;                  // a sensible fallback (offered, not silently swapped in)
  iosStore?: string;             // App Store id
  androidStore?: string;         // Play Store package
};

const CAT = (c: string) => ({ category: `android.intent.category.${c}` });
const PKG = (p: string) => ({ package: p });

export const APPS: AppEntry[] = [
  { id: "spotify", name: "Spotify", aliases: ["spotify"], ios: "spotify://", android: [PKG("com.spotify.music")], web: "https://open.spotify.com", iosStore: "324684580", androidStore: "com.spotify.music" },
  { id: "youtube", name: "YouTube", aliases: ["youtube", "you tube", "yt"], ios: "youtube://", android: [PKG("com.google.android.youtube")], web: "https://m.youtube.com", iosStore: "544007664", androidStore: "com.google.android.youtube" },
  { id: "youtube-music", name: "YouTube Music", aliases: ["youtube music", "yt music"], ios: "youtubemusic://", android: [PKG("com.google.android.apps.youtube.music")] },
  { id: "google", name: "Google", aliases: ["google", "google app", "google search"], ios: "google://", android: [PKG("com.google.android.googlequicksearchbox")], web: "https://www.google.com" },
  { id: "chrome", name: "Chrome", aliases: ["chrome", "google chrome"], ios: "googlechrome://", android: [PKG("com.android.chrome")] },
  { id: "browser", name: "your browser", aliases: ["browser", "internet", "web browser", "safari", "samsung internet"], ios: "x-web-search://", android: [CAT("APP_BROWSER")], web: "https://www.google.com" },
  { id: "maps", name: "Maps", aliases: ["maps", "map", "apple maps", "navigation"], ios: "maps://", android: [{ action: "android.intent.action.VIEW", data: "geo:0,0" }, PKG("com.google.android.apps.maps")], web: "https://maps.google.com" },
  { id: "google-maps", name: "Google Maps", aliases: ["google maps"], ios: "comgooglemaps://", android: [PKG("com.google.android.apps.maps")], web: "https://maps.google.com" },
  { id: "waze", name: "Waze", aliases: ["waze"], ios: "waze://", android: [PKG("com.waze")] },
  { id: "camera", name: "Camera", aliases: ["camera", "my camera", "the camera"], iosNote: "iPhone doesn't let apps open the Camera app", android: [{ action: "android.media.action.STILL_IMAGE_CAMERA" }] },
  { id: "photos", name: "Photos", aliases: ["photos", "my photos", "gallery", "pictures", "my pictures", "google photos"], ios: "photos-redirect://", android: [CAT("APP_GALLERY"), PKG("com.google.android.apps.photos")] },
  { id: "messages", name: "Messages", aliases: ["messages", "my messages", "texts", "sms", "imessage"], ios: "sms:", android: [CAT("APP_MESSAGING")] },
  { id: "phone", name: "Phone", aliases: ["phone", "phone app", "dialer", "dial pad", "keypad"], ios: "mobilephone://", android: [{ action: "android.intent.action.DIAL" }] },
  { id: "contacts", name: "Contacts", aliases: ["contacts", "my contacts", "address book"], ios: "contacts://", android: [CAT("APP_CONTACTS")] },
  { id: "calendar", name: "Calendar", aliases: ["calendar", "my calendar", "agenda"], ios: "calshow://", android: [CAT("APP_CALENDAR")] },
  { id: "clock", name: "Clock", aliases: ["clock", "alarms", "my alarms", "alarm clock", "timer app"], ios: "clock-alarm://", android: [{ action: "android.intent.action.SHOW_ALARMS" }] },
  { id: "settings", name: "Settings", aliases: ["settings", "the settings", "phone settings", "my settings"], ios: "App-Prefs:", android: [{ action: "android.settings.SETTINGS" }] },
  { id: "mail", name: "Mail", aliases: ["mail", "email", "e-mail", "my email", "inbox"], ios: "message://", android: [CAT("APP_EMAIL")] },
  { id: "gmail", name: "Gmail", aliases: ["gmail"], ios: "googlegmail://", android: [PKG("com.google.android.gm")] },
  { id: "music", name: "Music", aliases: ["music app", "apple music"], ios: "music://", android: [CAT("APP_MUSIC")] },
  { id: "calculator", name: "Calculator", aliases: ["calculator"], iosNote: "iPhone doesn't let apps open the Calculator", android: [CAT("APP_CALCULATOR")] },
  { id: "notes", name: "Notes", aliases: ["notes", "my notes", "samsung notes", "keep", "google keep"], ios: "mobilenotes://", android: [PKG("com.samsung.android.app.notes"), PKG("com.miui.notes"), PKG("com.google.android.keep")] },
  { id: "files", name: "Files", aliases: ["files", "my files", "file manager"], ios: "shareddocuments://", android: [PKG("com.sec.android.app.myfiles"), PKG("com.mi.android.globalFileexplorer"), PKG("com.google.android.apps.nbu.files")] },
  { id: "app-store", name: "App Store", aliases: ["app store", "play store", "store", "google play"], ios: "itms-apps://", android: [PKG("com.android.vending")] },
  { id: "whatsapp", name: "WhatsApp", aliases: ["whatsapp", "whats app"], ios: "whatsapp://", android: [PKG("com.whatsapp")], iosStore: "310633997", androidStore: "com.whatsapp" },
  { id: "instagram", name: "Instagram", aliases: ["instagram", "insta"], ios: "instagram://", android: [PKG("com.instagram.android")] },
  { id: "facebook", name: "Facebook", aliases: ["facebook"], ios: "fb://", android: [PKG("com.facebook.katana")] },
  { id: "messenger", name: "Messenger", aliases: ["messenger", "facebook messenger"], ios: "fb-messenger://", android: [PKG("com.facebook.orca")] },
  { id: "telegram", name: "Telegram", aliases: ["telegram"], ios: "tg://", android: [PKG("org.telegram.messenger")] },
  { id: "tiktok", name: "TikTok", aliases: ["tiktok", "tik tok"], ios: "tiktok://", android: [PKG("com.zhiliaoapp.musically"), PKG("com.ss.android.ugc.trill")] },
  { id: "x", name: "X", aliases: ["twitter", "x app", "x"], ios: "twitter://", android: [PKG("com.twitter.android")] },
  { id: "snapchat", name: "Snapchat", aliases: ["snapchat", "snap"], ios: "snapchat://", android: [PKG("com.snapchat.android")] },
  { id: "netflix", name: "Netflix", aliases: ["netflix"], ios: "nflx://", android: [PKG("com.netflix.mediaclient")] },
  { id: "discord", name: "Discord", aliases: ["discord"], ios: "discord://", android: [PKG("com.discord")] },
  { id: "zoom", name: "Zoom", aliases: ["zoom"], ios: "zoomus://", android: [PKG("us.zoom.videomeetings")] },
  { id: "teams", name: "Teams", aliases: ["teams", "microsoft teams"], ios: "msteams://", android: [PKG("com.microsoft.teams")] },
  { id: "outlook", name: "Outlook", aliases: ["outlook"], ios: "ms-outlook://", android: [PKG("com.microsoft.office.outlook")] },
  { id: "uber", name: "Uber", aliases: ["uber"], ios: "uber://", android: [PKG("com.ubercab")] },
  { id: "linkedin", name: "LinkedIn", aliases: ["linkedin", "linked in"], ios: "linkedin://", android: [PKG("com.linkedin.android")] },
  { id: "reddit", name: "Reddit", aliases: ["reddit"], ios: "reddit://", android: [PKG("com.reddit.frontpage")] },
  { id: "soundcloud", name: "SoundCloud", aliases: ["soundcloud", "sound cloud"], ios: "soundcloud://", android: [PKG("com.soundcloud.android")] },
  { id: "amazon", name: "Amazon", aliases: ["amazon"], ios: "com.amazon.mobile.shopping://", android: [PKG("com.amazon.mShop.android.shopping")] },
];

const normalize = (s: string) =>
  ` ${(s || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\b(the|my|app|application|please|on my phone|on the phone)\b/g, " ").replace(/\s+/g, " ").trim()} `;

/** The catalog entry the user means ("the spotify app", "my photos", "Gallery"), or null. */
export function findApp(name: string): AppEntry | null {
  const wanted = normalize(name).trim();
  if (!wanted) return null;
  let best: { app: AppEntry; score: number } | null = null;
  for (const app of APPS) {
    for (const alias of [app.name, ...app.aliases]) {
      const a = normalize(alias).trim();
      if (!a) continue;
      const score = a === wanted ? 3 : ` ${wanted} `.includes(` ${a} `) ? 2 + a.length / 100 : 0;
      if (score && (!best || score > best.score)) best = { app, score };
    }
  }
  return best?.app ?? null;
}

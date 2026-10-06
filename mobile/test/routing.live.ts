// The real AI deciding device and tool for the spec's scenarios (Groq, gpt-oss-120b). Phone tools only record what
// they'd do; the computer tool records the request. Run: GROQ_KEY=... node test/routing.live.ts
import { JarvisAgent, type Turn, type Mode } from "../src/core/agent.ts";
import { ToolRegistry, type Tool } from "../src/core/tools.ts";

const key = process.env.GROQ_KEY!;
const config = { provider: "groq" as const, apiKey: key, model: process.env.MODEL || "openai/gpt-oss-120b", transcribeModel: "whisper-large-v3-turbo", userName: "Ariel" };
let calls: Array<{ name: string; args: any }> = [];
const rec = (name: string, where: Tool["where"], props: Record<string, unknown>, message: (a: any) => string): Tool => ({
  name, where, description: DESCR[name], parameters: { type: "object", properties: props }, label: () => name,
  run: async (args) => { calls.push({ name, args }); return { ok: true, message: message(args), final: where === "none" }; },
});
const s = { type: "string" };
const DESCR: Record<string, string> = {
  open_app: "Open an app on this phone (Spotify, YouTube, Maps, Camera, Photos, Messages, Settings, Calendar, Clock, WhatsApp...).",
  spotify: "Find music on Spotify on this phone (artist, song, album, playlist). Opens Spotify on that search.",
  youtube: "Search YouTube on this phone.",
  web_search: "Open a Google search in the browser on this phone.",
  maps: "Maps on this phone: search places or get directions.",
  call: "Call someone from this phone, by contact name or number.",
  message: "Write a text message to someone from this phone.",
  set_alarm: "Set an alarm on this phone's clock (24-hour time).",
  set_timer: "Start a timer on this phone.",
  camera: "Open the camera to take a photo.",
  settings: "Open this phone's settings, e.g. Wi-Fi, Bluetooth (apps can't switch these themselves).",
  run_on_computer: "Have Jarvis on the user's computer do something there with all of its own abilities: desktop apps, Spotify and YouTube on the computer, browser, files, take control of mouse and keyboard. Its answer comes back.",
  web_answer: "Look something up on the web right now and answer in the chat: news, current events, anything recent.",
};
const registry = new ToolRegistry().register(
  rec("open_app", "phone", { app: s }, (a) => `Opened ${a.app}.`),
  rec("spotify", "phone", { query: s }, (a) => `Opened Spotify on “${a.query}”.`),
  rec("youtube", "phone", { query: s }, (a) => `Searching YouTube for “${a.query}”.`),
  rec("web_search", "phone", { query: s }, (a) => `Searching Google for “${a.query}”.`),
  rec("maps", "phone", { query: s, destination: s, mode: s }, (a) => `Maps: ${a.destination || a.query}.`),
  rec("call", "phone", { who: s }, (a) => `Calling ${a.who}.`),
  rec("message", "phone", { who: s, text: s }, (a) => `Message to ${a.who} ready.`),
  rec("set_alarm", "phone", { hour: { type: "integer" }, minute: { type: "integer" } }, (a) => `Alarm set for ${a.hour}:${String(a.minute ?? 0).padStart(2, "0")}.`),
  rec("set_timer", "phone", { seconds: { type: "integer" } }, (a) => `Timer for ${a.seconds}s.`),
  rec("settings", "phone", { section: s }, (a) => `Opened ${a.section} settings.`),
  rec("camera", "phone", {}, () => "Opened the camera."),
  rec("run_on_computer", "computer", { request: s }, (a) => `Computer did: ${a.request}`),
  rec("web_answer", "none", { question: s }, () => "GTA 6 releases November 19, 2026."),
);
const usage: number[] = [];
const meteredFetch = async (url: string, init: any) => {
  const res = await fetch(url, init);
  const clone = res.clone();
  clone.json().then((j: any) => j?.usage && usage.push(j.usage.prompt_tokens + j.usage.completion_tokens)).catch(() => {});
  return res;
};
const agent = new JarvisAgent({ registry, platform: "ios", getConfig: () => ({ ...config, fallbackModel: "openai/gpt-oss-20b" }), fetch: meteredFetch as any });

type Case = { say: string; mode?: Mode; online?: boolean; history?: Turn[]; expect: (c: typeof calls, reply: string) => boolean; why: string };
const tool = (name: string, test: (a: any) => boolean = () => true) => (c: typeof calls) => c.length >= 1 && c.some((x) => x.name === name && test(x.args));
const none = (c: typeof calls) => c.length === 0;
const has = (re: RegExp) => (v: unknown) => re.test(String(v ?? ""));

const cases: Case[] = [
  { say: "Open Spotify.", expect: tool("open_app", (a) => has(/spotify/i)(a.app)), why: "phone mode → phone" },
  { say: "Can you open Spotify for me?", expect: tool("open_app", (a) => has(/spotify/i)(a.app)), why: "polite phrasing" },
  { say: "Open Spotify and play Radiohead on my computer.", expect: (c) => tool("run_on_computer", (a) => has(/radiohead/i)(a.request))(c) && !c.some((x) => x.name !== "run_on_computer"), why: "explicit computer" },
  { say: "Play this on my computer: Bohemian Rhapsody", expect: tool("run_on_computer", (a) => has(/bohemian/i)(a.request)), why: "explicit computer, music" },
  { say: "Open Maps on my phone", mode: "computer", expect: (c) => tool("open_app", (a) => has(/map/i)(a.app))(c) || tool("maps")(c), why: "computer mode, explicit phone" },
  { say: "Take control of my computer and open Chrome.", expect: tool("run_on_computer", (a) => has(/take control/i)(a.request) && has(/chrome/i)(a.request)), why: "computer control, wording kept" },
  { say: "Open Spotify on my computer.", online: false, expect: (c, r) => none(c) && /offline/i.test(r), why: "computer offline → honest" },
  { say: "Open Spotify.", online: false, expect: tool("open_app", (a) => has(/spotify/i)(a.app)), why: "phone works with computer offline" },
  { say: "Search the web for the latest GTA 6 news.", expect: (c) => tool("web_answer")(c) || tool("web_search")(c), why: "web" },
  { say: "Set an alarm for 7 AM.", expect: tool("set_alarm", (a) => a.hour === 7 && !a.minute), why: "alarm" },
  { say: "Set a timer for 10 minutes", expect: tool("set_timer", (a) => a.seconds === 600), why: "timer" },
  { say: "Call Mom", expect: tool("call", (a) => has(/mom/i)(a.who)), why: "call" },
  { say: "Send a message to Dana saying I'm running late", expect: tool("message", (a) => has(/dana/i)(a.who) && has(/late/i)(a.text)), why: "message" },
  { say: "Take me to Dizengoff Center", expect: tool("maps", (a) => has(/dizengoff/i)(a.destination || a.query)), why: "directions" },
  { say: "Find the nearest coffee shop.", expect: tool("maps", (a) => has(/coffee/i)(a.query || a.destination)), why: "nearby" },
  { say: "Turn on Bluetooth.", expect: tool("settings", (a) => has(/bluetooth/i)(a.section)), why: "settings (honest)" },
  { say: "Open my camera", expect: (c) => tool("camera")(c) || tool("open_app", (a) => has(/camera/i)(a.app))(c), why: "camera" },
  { say: "Show me my photos", expect: tool("open_app", (a) => has(/photo|gallery/i)(a.app)), why: "photos" },
  { say: "Open them on Spotify.", history: [{ role: "user", content: "Find Radiohead" }, { role: "assistant", content: "Radiohead is an English rock band from Abingdon, Oxfordshire." }],
    expect: tool("spotify", (a) => has(/radiohead/i)(a.query)), why: "context: them = Radiohead" },
  { say: "Open the first one in Maps.", history: [{ role: "user", content: "Search for a good restaurant in Tel Aviv" }, { role: "assistant", content: "Top picks: 1. OCD, 2. Popina, 3. Shila." }],
    expect: tool("maps", (a) => has(/ocd/i)(a.query || a.destination)), why: "context: the first one" },
  { say: "Now play it on my computer instead.", history: [{ role: "user", content: "Find Radiohead on Spotify" }, { role: "assistant", content: "Opened Spotify on “Radiohead”." }],
    expect: tool("run_on_computer", (a) => has(/radiohead/i)(a.request)), why: "context + device switch" },
  { say: "What's 15% of 80?", expect: none, why: "plain question, no tool" },
];

let pass = 0;
for (const c of cases) {
  calls = [];
  const t0 = Date.now();
  let reply = "";
  try {
    const r = await agent.respond({ text: c.say, mode: c.mode ?? "phone", history: c.history ?? [],
      computer: { online: c.online ?? true, name: "Ariel's Mac", status: c.online === false ? "Jarvis is closed on your computer." : "ready" },
      ctx: { platform: "ios", confirm: async () => true } });
    reply = r.text + (r.usedAI ? "" : "   [instant, no AI]");
  } catch (e) { reply = "ERROR " + e; }
  const ok = c.expect(calls, reply);
  if (ok) pass++;
  const took = Date.now() - t0;
  await new Promise((r) => setTimeout(r, reply.includes("[instant") ? 0 : 7000));   // stay inside 8k tokens/min
  console.log(`${ok ? "✔" : "✖"} [${c.mode ?? "phone"}${c.online === false ? ",offline" : ""}] ${c.say}  (${c.why}, ${took}ms)\n     → ${calls.map((x) => `${x.name}(${JSON.stringify(x.args)})`).join(", ") || "no tool"}  “${reply.slice(0, 110)}”`);
}
console.log(`\n${pass}/${cases.length} correct; tokens per AI call: ${usage.join(", ")}`);

// The app's brain on the React side: one Jarvis conversation, one connection to the computer, one agent. Screens
// read a snapshot (useJarvis) and call these methods; nothing in the UI talks to the network or the AI directly.
import { AppState, Platform } from "react-native";
import * as Device from "expo-device";
import * as Haptics from "expo-haptics";
import * as Notifications from "expo-notifications";
import * as Speech from "expo-speech";
import { getRandomBytes } from "expo-crypto";
import { ComputerConnection } from "../core/connection.ts";
import { setRandomSource } from "../core/crypto.ts";
import { JarvisAgent, type Activity, type Mode, type Turn } from "../core/agent.ts";
import { ToolRegistry, type Platform as ToolPlatform } from "../core/tools.ts";
import { computerTool, webAnswerTool } from "../core/coreTools.ts";
import { explicitTarget } from "../core/intent.ts";
import { pair, parsePairingInput } from "../core/pairing.ts";
import type { AiConfig, ChatMessage, ConnState, DeviceCredentials } from "../core/protocol.ts";
import { phoneTools } from "../platform/phoneTools.ts";
import { deleteSecret, getData, getSecret, setData, setSecret } from "../platform/storage.ts";
import { transcribe } from "../platform/voice.ts";

setRandomSource((n) => getRandomBytes(n));

export type Msg =
  | { id: string; kind: "user"; text: string; ts: number; via?: "phone" | "computer"; queued?: boolean; voice?: boolean }
  | { id: string; kind: "jarvis"; text: string; ts: number; where?: "phone" | "computer" | "none"; quick?: string[] }
  | { id: string; kind: "activity"; text: string; ts: number; where: "phone" | "computer" | "none"; status: Activity["status"]; detail?: string }
  | { id: string; kind: "confirm"; text: string; ts: number; detail?: string; state: "open" | "yes" | "no" }
  | { id: string; kind: "note"; text: string; ts: number; tone?: "ok" | "err" };

export type Snapshot = {
  booted: boolean;
  device: DeviceCredentials | null;
  conn: ConnState;
  transport: "lan" | "relay" | null;
  computerName: string;
  mode: Mode;
  messages: Msg[];          // oldest first
  thinking: false | "phone" | "computer";
  recording: boolean;
  transcribing: boolean;
  aiReady: boolean;
  prefs: Prefs;
};

type Prefs = { mode: Mode; speak: boolean; notify: boolean };
const DEFAULT_PREFS: Prefs = { mode: "phone", speak: false, notify: true };
const K = { device: "jarvis.device", ai: "jarvis.ai", prefs: "jarvis.prefs", chat: "jarvis.chat" };
const MAX_MESSAGES = 200;

const platform: ToolPlatform = Platform.OS === "ios" ? "ios" : Platform.OS === "android" ? "android" : "web";
const id = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
const norm = (t: string) => t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
const tap = (style = Haptics.ImpactFeedbackStyle.Light) => { if (Platform.OS !== "web") void Haptics.impactAsync(style).catch(() => {}); };

export function deviceName(): string {
  if (Platform.OS === "ios") return Device.modelName?.startsWith("iPad") ? "iPad" : "iPhone";
  const brand = (Device.manufacturer || Device.brand || "").toLowerCase();
  if (brand.includes("samsung")) return "Samsung Galaxy";
  if (/xiaomi|redmi|poco/.test(brand)) return "Xiaomi";
  if (brand.includes("google")) return "Google Pixel";
  return Platform.OS === "android" ? "Android phone" : "Phone";
}

class Controller {
  private listeners = new Set<() => void>();
  private snap: Snapshot = { booted: false, device: null, conn: "idle", transport: null, computerName: "", mode: "phone",
                             messages: [], thinking: false, recording: false, transcribing: false, aiReady: false, prefs: DEFAULT_PREFS };
  private connection: ComputerConnection | null = null;
  private ai: AiConfig | null = null;
  private agent: JarvisAgent;
  private registry = new ToolRegistry();
  private outgoing: string[] = [];             // texts sent to the computer, awaiting their echo
  private heldReplies: Array<{ text: string; timer: ReturnType<typeof setTimeout> }> = [];
  private computerBusy = 0;
  private pendingTurns: Array<{ user: string; reply: string }> = [];
  private confirmResolvers = new Map<string, (yes: boolean) => void>();
  private saveTimer: ReturnType<typeof setTimeout> | undefined;
  private inBackground = false;

  constructor() {
    this.registry.register(...phoneTools(), computerTool(() => this.connection),
                           webAnswerTool((q) => this.agent.searchWeb(q)));
    this.agent = new JarvisAgent({ registry: this.registry, platform, getConfig: () => this.ai,
                                   fetch: (url, init) => fetch(url, init as RequestInit) as any });
  }

  // ------------------------------------------------------------------ store plumbing
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  getSnapshot = () => this.snap;
  private set(patch: Partial<Snapshot>) {
    this.snap = { ...this.snap, ...patch };
    for (const fn of this.listeners) fn();
  }
  private push(msg: Msg) {
    const messages = [...this.snap.messages, msg];
    this.set({ messages: messages.length > MAX_MESSAGES ? messages.slice(-MAX_MESSAGES) : messages });
    this.saveSoon();
  }
  private patchMsg(msgId: string, patch: Partial<Msg>) {
    this.set({ messages: this.snap.messages.map((m) => (m.id === msgId ? ({ ...m, ...patch } as Msg) : m)) });
    this.saveSoon();
  }
  private saveSoon() {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => {
      const keep = this.snap.messages.filter((m) => m.kind === "user" || m.kind === "jarvis").slice(-60);
      void setData(K.chat, keep);
    }, 800);
  }

  // ------------------------------------------------------------------ lifecycle
  async boot() {
    if (this.snap.booted) return;
    const [device, ai, prefs, chat] = await Promise.all([
      getSecret<DeviceCredentials>(K.device), getSecret<AiConfig>(K.ai), getData<Prefs>(K.prefs, DEFAULT_PREFS), getData<Msg[]>(K.chat, []),
    ]);
    this.ai = ai;
    const merged = { ...DEFAULT_PREFS, ...prefs };
    this.set({ booted: true, device, prefs: merged, mode: merged.mode, messages: chat, aiReady: !!ai?.apiKey,
               computerName: device?.computerName || "" });
    if (device) this.connect(device);
    AppState.addEventListener("change", (state) => {
      this.inBackground = state !== "active";
      if (state === "active") this.connection?.wake();
      else if (state === "background") this.connection?.suspend();
    });
    if (Platform.OS !== "web") {
      Notifications.setNotificationHandler({
        handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
      });
    }
  }

  private connect(device: DeviceCredentials) {
    this.connection?.stop();
    const conn = new ComputerConnection(device, (url) => new WebSocket(url) as any, {
      onState: (state, info) => {
        this.set({ conn: state, transport: info.transport });
        if (state === "ready") void this.onReady();
      },
      onMessage: (m) => this.onComputerMessage(m),
      onUnpaired: () => void this.forget("This phone was unpaired from your computer. Scan a new code to pair it again."),
    });
    this.connection = conn;
    conn.start(true);
  }

  private async onReady() {
    // The AI settings come from the computer (same Groq account), over this encrypted session only; kept in
    // secure storage so Phone Mode keeps working when the computer is off.
    try {
      const cfg = await this.connection!.requestAiConfig();
      this.ai = cfg;
      await setSecret(K.ai, cfg);
      this.set({ aiReady: true });
    } catch { /* keep any earlier config */ }
    // Phone-handled turns from while the computer was unreachable join the shared conversation now.
    for (const t of this.pendingTurns.splice(0)) this.connection?.send({ type: "phone_turn", ...t });
    const queued = this.snap.messages.filter((m): m is Extract<Msg, { kind: "user" }> => m.kind === "user" && !!m.queued);
    for (const m of queued) { this.patchMsg(m.id, { queued: false } as Partial<Msg>); void this.toComputer(m.text, false); }
  }

  // ------------------------------------------------------------------ messages from the computer
  private onComputerMessage(m: Record<string, unknown>) {
    switch (m.type) {
      case "session_info": {
        const name = String(m.computerName || "");
        if (name) {
          this.set({ computerName: name });
          if (this.snap.device && this.snap.device.computerName !== name) {
            const device = { ...this.snap.device, computerName: name };
            this.set({ device });
            void setSecret(K.device, device);
          }
        }
        const history = (m.history as ChatMessage[] | undefined) ?? [];
        if (history.length) this.mergeHistory(history);
        break;
      }
      case "chat": this.onMirroredChat(m as unknown as ChatMessage); break;
      case "status":
        if (m.status === "thinking") this.set({ thinking: this.snap.thinking || "computer" });
        else if (this.snap.thinking === "computer" && !this.computerBusy) this.set({ thinking: false });
        break;
      case "result":
        this.push({ id: id(), kind: "note", ts: Date.now(), text: String(m.message || m.status), tone: m.status === "SUCCEEDED" ? "ok" : "err" });
        break;
      case "reply": {
        // An answer to one of our own requests: already on its way to the screen (via the agent or askComputer),
        // so drop the mirrored copy we were holding back.
        const text = String(m.text || "");
        const held = this.heldReplies.findIndex((h) => h.text === text);
        if (held >= 0) { clearTimeout(this.heldReplies[held].timer); this.heldReplies.splice(held, 1); }
        if (!m.requestId && !this.snap.messages.slice(-6).some((x) => x.kind === "jarvis" && x.text === text)) {
          this.push({ id: id(), kind: "jarvis", text, ts: Date.now(), where: "computer", quick: quickReplies(text) });
        }
        break;
      }
    }
  }

  private onMirroredChat(c: ChatMessage) {
    const text = (c.text || "").trim();
    if (!text) return;

    if (c.sender === "user") {
      const i = this.outgoing.indexOf(norm(text));
      if (i >= 0) { this.outgoing.splice(i, 1); return; }   // our own request, echoed back
      this.push({ id: id(), kind: "user", text, ts: c.ts || Date.now(), via: "computer" });
      return;
    }
    if (this.computerBusy > 0) {
      // Probably the answer to our own pending request — hold it briefly; its reply (with our request id) follows.
      const timer = setTimeout(() => {
        const i = this.heldReplies.findIndex((h) => h.timer === timer);
        if (i >= 0) { this.heldReplies.splice(i, 1); this.showComputerSaid(text, c.ts); }
      }, 4000);
      this.heldReplies.push({ text, timer });
      return;
    }
    this.showComputerSaid(text, c.ts);
  }

  private showComputerSaid(text: string, ts?: number) {
    if (this.snap.thinking === "computer") this.set({ thinking: false });
    // Computer-Jarvis also mirrors its yes/no questions as "… (yes / no)" (made for the web page), besides
    // answering with the same question ("… Say yes or no."). One question on screen, not two — whichever came first.
    if (this.snap.messages.slice(-4).some((m) => m.kind === "jarvis" && sameQuestion(m.text, text))) return;
    this.push({ id: id(), kind: "jarvis", text, ts: ts || Date.now(), where: "computer", quick: quickReplies(text) });
    if (this.inBackground && this.snap.prefs.notify && Platform.OS !== "web") {
      void Notifications.scheduleNotificationAsync({ content: { title: "Jarvis", body: text.slice(0, 180) }, trigger: null }).catch(() => {});
    }
  }

  private mergeHistory(history: ChatMessage[]) {
    // The computer's conversation is the shared record; keep anything newer that only this phone has.
    const fromComputer: Msg[] = history.filter((h) => h.text).map((h) => (h.sender === "user"
      ? { id: id(), kind: "user", text: h.text, ts: h.ts || 0, via: "computer" }
      : { id: id(), kind: "jarvis", text: h.text, ts: h.ts || 0, where: "computer" }) as Msg);
    const lastTs = fromComputer.reduce((t, m) => Math.max(t, m.ts), 0);
    const known = new Set(fromComputer.map((m) => `${m.kind}:${m.text}`));
    const localOnly = this.snap.messages.filter((m) => (m.ts > lastTs || m.kind === "activity" || m.kind === "note") && !known.has(`${m.kind}:${m.text}`));
    this.set({ messages: [...fromComputer, ...localOnly].slice(-MAX_MESSAGES) });
    this.saveSoon();
  }

  // ------------------------------------------------------------------ sending
  setMode(mode: Mode) {
    if (mode === this.snap.mode) return;
    tap(Haptics.ImpactFeedbackStyle.Medium);
    const prefs = { ...this.snap.prefs, mode };
    this.set({ mode, prefs });
    void setData(K.prefs, prefs);
  }

  setPref<K2 extends keyof Prefs>(key: K2, value: Prefs[K2]) {
    const prefs = { ...this.snap.prefs, [key]: value };
    this.set({ prefs });
    void setData(K.prefs, prefs);
  }

  private turns: Promise<void> = Promise.resolve();

  /** One turn at a time, in order: you can keep typing, and each request sees the answer to the one before it. */
  send(raw: string, opts: { voice?: boolean } = {}): Promise<void> {
    const text = raw.trim();
    if (!text) return Promise.resolve();
    tap();
    if (Platform.OS !== "web") Speech.stop().catch(() => {});
    // Which Jarvis handles it is decided now, by the mode it was sent in — and the message shows up right away.
    const toComputer = this.snap.mode === "computer" && explicitTarget(text) !== "phone";
    const mode = this.snap.mode;
    const msgId = id();
    this.push({ id: msgId, kind: "user", text, ts: Date.now(), via: toComputer ? "computer" : "phone", voice: opts.voice });
    const run = this.turns.then(() => (toComputer ? this.toComputer(text, !!opts.voice) : this.handle(text, mode, msgId, opts))).catch(() => {});
    this.turns = run;
    return run;
  }

  private async handle(text: string, mode: Mode, msgId: string, opts: { voice?: boolean }) {
    const history = this.historyForAI(msgId);
    this.set({ thinking: "phone" });
    const activityIds = new Map<string, string>();
    const reply = await this.agent.respond({
      text, mode, history,
      computer: { online: !!this.connection?.ready, name: this.snap.computerName, status: this.connection?.offlineReason() ?? "not paired" },
      ctx: { platform, confirm: (title, detail) => this.askConfirm(title, detail) },
      onActivity: (a) => {
        if (a.tool === "run_on_computer") {
          if (a.status === "running") { this.computerBusy++; this.outgoing.push(norm(a.label.replace(/^On your computer: /, ""))); this.set({ thinking: "computer" }); }
          else this.computerBusy = Math.max(0, this.computerBusy - 1);
        }
        const existing = activityIds.get(a.id);
        if (existing) this.patchMsg(existing, { status: a.status, detail: a.message } as Partial<Msg>);
        else {
          const msgId = id();
          activityIds.set(a.id, msgId);
          this.push({ id: msgId, kind: "activity", text: a.label, ts: Date.now(), where: a.where, status: a.status });
        }
      },
    });
    this.set({ thinking: false });
    // Collapse a single, successful action into the reply itself: "✓ Opened Spotify." instead of a chip + a bubble.
    this.push({ id: id(), kind: "jarvis", text: reply.text, ts: Date.now(), where: reply.where, quick: quickReplies(reply.text) });
    if ((opts.voice || this.snap.prefs.speak) && Platform.OS !== "web") Speech.speak(reply.text, { rate: 1.02 });
    if (reply.where !== "computer") this.logPhoneTurn(text, reply.text);
  }

  /** Computer mode (and queued messages): the request goes to computer-Jarvis as-is. */
  private async toComputer(text: string, voice: boolean) {
    const conn = this.connection;
    if (!conn?.ready) {
      const last = [...this.snap.messages].reverse().find((m) => m.kind === "user" && m.text === text);
      if (last && (this.snap.conn === "starting" || this.snap.conn === "connecting" || this.snap.conn === "waiting")) {
        this.patchMsg(last.id, { queued: true } as Partial<Msg>);   // sent the moment the computer is back
        return;
      }
      this.push({ id: id(), kind: "jarvis", ts: Date.now(), where: "none",
                  text: `${conn ? conn.offlineReason() : "Your computer isn't paired yet."} Switch to Phone to do things here.` });
      return;
    }
    this.outgoing.push(norm(text));
    if (this.outgoing.length > 20) this.outgoing.shift();
    this.computerBusy++;
    this.set({ thinking: "computer" });
    try {
      const answer = await conn.askComputer(text);
      if (!this.snap.messages.slice(-4).some((m) => m.kind === "jarvis" && (m.text === answer || sameQuestion(m.text, answer)))) {
        this.push({ id: id(), kind: "jarvis", text: answer, ts: Date.now(), where: "computer", quick: quickReplies(answer) });
      }
      if (voice && Platform.OS !== "web") Speech.speak(answer, { rate: 1.02 });
    } catch (e) {
      this.push({ id: id(), kind: "jarvis", text: e instanceof Error ? e.message : "Your computer didn't answer.", ts: Date.now(), where: "none" });
    } finally {
      this.computerBusy = Math.max(0, this.computerBusy - 1);
      if (!this.computerBusy) this.set({ thinking: false });
    }
  }

  private logPhoneTurn(user: string, reply: string) {
    if (this.connection?.ready) this.connection.send({ type: "phone_turn", user, reply });
    else { this.pendingTurns.push({ user, reply }); if (this.pendingTurns.length > 20) this.pendingTurns.shift(); }
  }

  /** The conversation before message `beforeId` (that message itself is the new request). */
  private historyForAI(beforeId: string): Turn[] {
    const turns: Turn[] = [];
    const end = this.snap.messages.findIndex((m) => m.id === beforeId);
    for (const m of this.snap.messages.slice(0, end < 0 ? undefined : end).slice(-40)) {
      if (m.kind === "user") turns.push({ role: "user", content: m.via === "computer" && this.snap.mode === "phone" ? `(on the computer) ${m.text}` : m.text });
      else if (m.kind === "jarvis") turns.push({ role: "assistant", content: m.text });
      else if (m.kind === "activity" && m.status !== "running") turns.push({ role: "assistant", content: `[${m.text}: ${m.detail ?? m.status}]` });
    }
    // the API wants alternating, non-empty turns; merge consecutive same-role ones
    return turns.reduce<Turn[]>((acc, t) => {
      const prev = acc[acc.length - 1];
      if (prev && prev.role === t.role) prev.content += `\n${t.content}`; else acc.push({ ...t });
      return acc;
    }, []).slice(-20);
  }

  // ------------------------------------------------------------------ confirmations
  private askConfirm(title: string, detail?: string): Promise<boolean> {
    tap(Haptics.ImpactFeedbackStyle.Medium);
    const msgId = id();
    this.push({ id: msgId, kind: "confirm", text: title, detail, ts: Date.now(), state: "open" });
    return new Promise((resolve) => this.confirmResolvers.set(msgId, resolve));
  }

  answerConfirm(msgId: string, yes: boolean) {
    const resolve = this.confirmResolvers.get(msgId);
    if (!resolve) return;
    this.confirmResolvers.delete(msgId);
    this.patchMsg(msgId, { state: yes ? "yes" : "no" } as Partial<Msg>);
    tap();
    resolve(yes);
  }

  /** Quick replies under a computer question ("Can I use your mouse and keyboard? (yes / no)"). */
  quickReply(text: string) {
    const lastQuestion = [...this.snap.messages].reverse().find((m) => m.kind === "jarvis");
    if (lastQuestion?.kind === "jarvis" && lastQuestion.where === "computer") void this.toComputerDirect(text);
    else void this.send(text);
  }
  private async toComputerDirect(text: string) {
    this.push({ id: id(), kind: "user", text, ts: Date.now(), via: "computer" });
    await this.toComputer(text, false);
  }

  // ------------------------------------------------------------------ voice
  setRecording(recording: boolean) { this.set({ recording }); }
  async handleRecording(uri: string | null, mime?: string) {
    this.set({ recording: false });
    if (!uri) return;
    if (!this.ai?.apiKey) {
      this.push({ id: id(), kind: "jarvis", text: "Voice needs one connection to your computer first, to set up the AI. Try typing for now.", ts: Date.now(), where: "none" });
      return;
    }
    this.set({ transcribing: true });
    try {
      const text = await transcribe(uri, this.ai, mime);
      this.set({ transcribing: false });
      if (text) await this.send(text, { voice: true });
      else this.push({ id: id(), kind: "note", text: "I didn't catch that.", ts: Date.now() });
    } catch (e) {
      this.set({ transcribing: false });
      this.push({ id: id(), kind: "note", tone: "err", ts: Date.now(), text: e instanceof Error ? e.message : "I couldn't understand that recording." });
    }
  }

  // ------------------------------------------------------------------ pairing
  async pairWith(input: string): Promise<string | null> {
    const target = parsePairingInput(input);
    if (!target) return "That isn't a Jarvis pairing code. Scan the QR code your computer shows after you say “Connect my phone”.";
    try {
      const device = await pair(target, deviceName(), (url) => new WebSocket(url) as any, this.snap.device);
      await setSecret(K.device, device);
      tap(Haptics.ImpactFeedbackStyle.Heavy);
      this.set({ device, computerName: "" });
      this.connect(device);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : "Pairing didn't work.";
    }
  }

  reconnect() { tap(); this.connection?.start(true); }
  disconnect() { tap(); this.connection?.send({ type: "disconnect" }); setTimeout(() => this.connection?.stop("stopped"), 80); }

  async unpair() {
    if (this.connection?.ready) this.connection.send({ type: "unpair" });
    await this.forget("This phone is unpaired.");
  }

  private async forget(note: string) {
    this.connection?.stop("unpaired");
    this.connection = null;
    await deleteSecret(K.device);
    await deleteSecret(K.ai);
    this.ai = null;
    this.set({ device: null, conn: "idle", aiReady: false, computerName: "" });
    this.push({ id: id(), kind: "note", text: note, ts: Date.now() });
  }

  clearChat() { this.set({ messages: [] }); void setData(K.chat, []); }
}

const asQuestion = (t: string) => norm(t.replace(/\s*\(yes\s*\/\s*no\)\s*$|\s*say yes or no\.?\s*$/i, ""));
function sameQuestion(a: string, b: string): boolean {
  const yesNo = /\(yes\s*\/\s*no\)\s*$|say yes or no\.?\s*$/i;
  return yesNo.test(a) && yesNo.test(b) && asQuestion(a) === asQuestion(b);
}

/** "…? (yes / no)" from the computer gets tap-able answers. */
function quickReplies(text: string): string[] | undefined {
  const t = text.trim();
  if (/\(yes\s*\/\s*no\)\s*$/i.test(t) || /\bsay yes or no\.?$/i.test(t) || /^(?:can|shall|should|may|do you want|would you like) [^.!]+\?$/i.test(t)) return ["Yes", "No"];
  return undefined;
}

export const jarvis = new Controller();

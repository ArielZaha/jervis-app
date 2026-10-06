// One persistent, encrypted connection from the phone to Jarvis on the computer — over the home Wi-Fi when it's
// reachable, through the relay otherwise. Same protocol as the web app (phone_client.html), with two differences
// that a native app can afford: it always encrypts (the web page on plain http can't), and over the relay it
// proves who it is with its key instead of sending its token through a middlebox (phone_session.verify_attach_proof).
import { decrypt, encrypt, isEnvelope, keyFromB64, random } from "./crypto.ts";
import { bytesToB64url } from "./b64.ts";
import type { AiConfig, ConnState, DeviceCredentials } from "./protocol.ts";

type Transport = "lan" | "relay";
type WS = {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: ((ev: unknown) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
};
export type WebSocketFactory = (url: string) => WS;

export type ConnectionEvents = {
  onState?: (state: ConnState, info: { transport: Transport | null; attempt: number }) => void;
  onMessage?: (message: Record<string, unknown>) => void;
  onUnpaired?: () => void;
};

const OPEN = 1;
const BACKOFF = [500, 1000, 2000, 4000, 8000, 15000];
const LAN_OPEN_TIMEOUT = 2500;     // the computer on this Wi-Fi answers in milliseconds, or isn't here
const RELAY_OPEN_TIMEOUT = 25000;  // a free relay may be waking up
const ATTACH_TIMEOUT = 8000;
const WAKING_WINDOW = 120000;      // how long to keep knocking briskly while Jarvis Wake opens Jarvis
const PING_EVERY = 25000;
const PONG_TIMEOUT = 6000;

export class ComputerConnection {
  state: ConnState = "idle";
  transport: Transport | null = null;
  private ws: WS | null = null;
  private key: Uint8Array;
  private attempt = 0;
  private hold: ConnState | null = null;
  private wantWake = true;
  private wakingSince = 0;
  private preferred: Transport = "lan";
  private timers: Record<string, ReturnType<typeof setTimeout> | undefined> = {};
  private pending = new Map<string, { resolve: (text: string) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  private aiConfigWaiters: Array<(cfg: AiConfig | { error: string }) => void> = [];
  private suspended = false;

  private device: DeviceCredentials;
  private makeSocket: WebSocketFactory;
  private events: ConnectionEvents;

  constructor(device: DeviceCredentials, makeSocket: WebSocketFactory, events: ConnectionEvents = {}) {
    this.device = device;
    this.makeSocket = makeSocket;
    this.events = events;
    this.key = keyFromB64(device.key);
  }

  get ready() { return this.state === "ready"; }

  private transports(): Transport[] {
    const all: Transport[] = [];
    if (this.device.localUrl) all.push("lan");
    // The relay: any relay address that isn't simply this computer's own (with no relay configured, pairing hands
    // out the computer's LAN address there too).
    if (/^wss?:\/\//.test(this.device.relayUrl || "") && this.device.relayUrl !== this.device.localUrl) all.push("relay");
    return all.sort((a, b) => (a === this.preferred ? -1 : b === this.preferred ? 1 : 0));
  }

  /** Open (or re-open) the connection; `wake` lets Jarvis Wake start Jarvis if he's closed. */
  start(wake = true): void {
    this.hold = null;
    this.attempt = 0;
    this.wantWake = wake;
    this.suspended = false;
    void this.connect();
  }

  stop(hold: ConnState = "stopped"): void {
    this.hold = hold;
    this.clearTimers();
    this.closeSocket();
    this.failPending("Disconnected from your computer.");
    this.setState(hold);
  }

  /** The app went to the background: stop retrying (the OS will freeze us anyway). */
  suspend(): void {
    this.suspended = true;
    clearTimeout(this.timers.retry);
  }

  /** Back in the foreground (or network back): check right away; this counts as opening the app. */
  wake(): void {
    this.suspended = false;
    if (this.hold && this.hold !== "closed") return;
    if (this.ready) { this.ping(4000); return; }
    if (this.ws && this.ws.readyState !== OPEN) return;   // already on its way
    this.hold = null;
    this.attempt = 0;
    this.wantWake = true;
    void this.connect();
  }

  private setState(state: ConnState) {
    if (this.state === state) return;
    this.state = state;
    this.events.onState?.(state, { transport: this.transport, attempt: this.attempt });
  }

  private clearTimers() {
    for (const k of Object.keys(this.timers)) { clearTimeout(this.timers[k]); clearInterval(this.timers[k]); }
    this.timers = {};
  }

  private closeSocket() {
    const ws = this.ws;
    this.ws = null;
    if (ws) { try { ws.close(); } catch { /* already closed */ } }
  }

  private async connect(): Promise<void> {
    if (this.hold || this.suspended) return;
    this.clearTimers();
    this.closeSocket();
    this.setState(this.wakingSince ? "starting" : this.attempt ? "waiting" : "connecting");
    for (const transport of this.transports()) {
      if (this.hold || this.suspended) return;
      const outcome = await this.tryTransport(transport);
      if (outcome === "attached" || outcome === "final") return;
      if (outcome === "door") break;   // Jarvis Wake answered on the LAN: no point trying the relay
    }
    this.scheduleRetry();
  }

  /** "attached" | "final" (a definite answer: stop trying) | "door" | "failed" */
  private tryTransport(transport: Transport): Promise<"attached" | "final" | "door" | "failed"> {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (outcome: "attached" | "final" | "door" | "failed") => {
        if (settled) return;
        settled = true;
        clearTimeout(this.timers.open);
        clearTimeout(this.timers.attach);
        resolve(outcome);
      };
      const url = transport === "lan" ? this.device.localUrl : this.device.relayUrl;
      let ws: WS;
      try { ws = this.makeSocket(url); } catch { finish("failed"); return; }
      this.ws = ws;
      this.timers.open = setTimeout(() => { if (this.ws === ws) this.closeSocket(); finish("failed"); },
                                    transport === "lan" ? LAN_OPEN_TIMEOUT : RELAY_OPEN_TIMEOUT);
      ws.onopen = () => {
        if (this.ws !== ws) return;
        clearTimeout(this.timers.open);
        this.timers.attach = setTimeout(() => { if (this.ws === ws) this.closeSocket(); finish("failed"); }, ATTACH_TIMEOUT);
        ws.send(JSON.stringify({ type: "hello", role: "phone", computerId: this.device.computerId }));
        if (transport === "lan") {
          ws.send(JSON.stringify({ type: "auto_attach", deviceId: this.device.id, token: this.device.token,
                                   encrypt: true, wake: this.wantWake }));
        } else {
          const proof = encrypt(this.key, { type: "attach", deviceId: this.device.id, ts: Date.now() });
          ws.send(JSON.stringify({ type: "auto_attach", deviceId: this.device.id, proof }));
        }
        this.wantWake = false;
      };
      ws.onerror = () => { try { ws.close(); } catch { /* */ } };
      ws.onclose = () => {
        const current = this.ws === ws;   // a socket we already replaced or closed on purpose doesn't count
        if (current) this.ws = null;
        if (!settled) { finish("failed"); return; }
        if (current && this.state === "ready") this.dropped();
      };
      ws.onmessage = (ev) => {
        if (this.ws !== ws) return;
        let data: Record<string, unknown>;
        try { data = JSON.parse(String(ev.data)); } catch { return; }
        if (isEnvelope(data)) {
          const message = decrypt<Record<string, unknown>>(this.key, data);
          if (!message) return;
          if (message.type === "session_ready") {
            this.transport = transport;
            this.preferred = transport;
            this.attempt = 0;
            this.wakingSince = 0;
            finish("attached");
            this.setState("ready");
            this.startHeartbeat();
          }
          this.handle(message);
          return;
        }
        switch (data.type) {
          case "hello_ok": return;
          case "offline": this.setState("unreachable"); finish("failed"); return;   // relay: computer not connected
          case "waking": this.wakingSince = Date.now(); this.setState("starting"); finish("door"); return;
          case "jarvis_closed": this.setState("closed"); finish("door"); return;
          case "wake_refused": this.setState("unreachable"); finish("door"); return;
          case "session_error":
            if (data.code === "unpaired") {
              finish("final");
              this.stop("unpaired");
              this.events.onUnpaired?.();
            } else finish("failed");
            return;
        }
      };
    });
  }

  private dropped() {
    this.stopHeartbeat();
    this.failPending("The connection to your computer dropped before it answered.");
    if (this.hold) { this.setState(this.hold); return; }
    this.attempt = 0;
    this.scheduleRetry();
  }

  private scheduleRetry() {
    if (this.hold || this.suspended) return;
    if (this.wakingSince && Date.now() - this.wakingSince < WAKING_WINDOW) {
      this.setState("starting");
      this.timers.retry = setTimeout(() => void this.connect(), 1000);
      return;
    }
    this.wakingSince = 0;
    const delay = BACKOFF[Math.min(this.attempt, BACKOFF.length - 1)] * (1 + Math.random() * 0.3);
    this.attempt++;
    if (this.state !== "closed" && this.state !== "unreachable") this.setState("waiting");
    if (this.attempt >= 4 && this.state === "waiting") this.setState("unreachable");
    this.timers.retry = setTimeout(() => void this.connect(), delay);
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.timers.ping = setInterval(() => this.ping(), PING_EVERY) as unknown as ReturnType<typeof setTimeout>;
  }
  private stopHeartbeat() { clearInterval(this.timers.ping); clearTimeout(this.timers.pong); }
  private ping(timeout = PONG_TIMEOUT) {
    if (!this.ready) return;
    this.send({ type: "ping", t: Date.now() });
    clearTimeout(this.timers.pong);
    this.timers.pong = setTimeout(() => this.closeSocketAndRetry(), timeout);
  }
  private closeSocketAndRetry() {
    const ws = this.ws;
    this.ws = null;
    if (ws) { try { ws.close(); } catch { /* */ } }
    this.dropped();
  }

  private handle(message: Record<string, unknown>) {
    switch (message.type) {
      case "pong": clearTimeout(this.timers.pong); return;
      case "reply": {
        const id = String(message.requestId || "");
        const waiter = id ? this.pending.get(id) : undefined;
        if (waiter) { clearTimeout(waiter.timer); this.pending.delete(id); waiter.resolve(String(message.text || "")); }
        break;
      }
      case "ai_config": {
        const waiters = this.aiConfigWaiters.splice(0);
        for (const w of waiters) w(message as unknown as AiConfig | { error: string });
        return;
      }
      case "session_replaced": this.stop("replaced"); break;
      case "session_ended": if (this.hold !== "stopped") this.stop("ended"); break;
      case "unpaired": this.stop("unpaired"); this.events.onUnpaired?.(); break;
    }
    this.events.onMessage?.(message);
  }

  /** Encrypted send; false if not connected. */
  send(message: Record<string, unknown>): boolean {
    const ws = this.ws;
    if (!ws || ws.readyState !== OPEN || !this.ready) return false;
    try { ws.send(JSON.stringify(encrypt(this.key, message))); return true; } catch { return false; }
  }

  /** Ask computer-Jarvis to do something, exactly as if typed at the computer; resolves with his answer. */
  askComputer(text: string, timeoutMs = 180000): Promise<string> {
    if (!this.ready) return Promise.reject(new Error(this.offlineReason()));
    const requestId = bytesToB64url(random(9));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error("Your computer didn't answer in time. It may still be working on it."));
      }, timeoutMs);
      this.pending.set(requestId, { resolve, reject, timer });
      if (!this.send({ type: "text", text, requestId })) {
        clearTimeout(timer);
        this.pending.delete(requestId);
        reject(new Error(this.offlineReason()));
      }
    });
  }

  /** The Groq settings the computer shares with its paired phone (only over this encrypted session). */
  requestAiConfig(timeoutMs = 8000): Promise<AiConfig> {
    return new Promise((resolve, reject) => {
      if (!this.send({ type: "get_ai_config" })) { reject(new Error(this.offlineReason())); return; }
      const timer = setTimeout(() => reject(new Error("no answer")), timeoutMs);
      this.aiConfigWaiters.push((cfg) => {
        clearTimeout(timer);
        if ("error" in cfg && cfg.error) reject(new Error(String(cfg.error)));
        else resolve(cfg as AiConfig);
      });
    });
  }

  offlineReason(): string {
    switch (this.state) {
      case "closed": return "Jarvis is closed on your computer.";
      case "starting": return "Jarvis is still opening on your computer.";
      case "offline": return "This phone is offline.";
      case "stopped": return "You disconnected from your computer.";
      case "replaced": return "Jarvis is connected to another device right now.";
      case "ended": return "Your computer ended the connection.";
      default: return "Your computer is offline right now, so I can't control it.";
    }
  }

  private failPending(reason: string) {
    for (const [id, w] of this.pending) { clearTimeout(w.timer); w.reject(new Error(reason)); this.pending.delete(id); }
  }
}

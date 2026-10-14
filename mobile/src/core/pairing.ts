// First-time pairing, reusing "Connect my phone" exactly as it is. The QR code on the computer holds one of two links:
//  - https://<jarvis's secure address>/?computerId=…#pair=<one-time key>: pairs from anywhere, through the relay. The
//    request and the answer are sealed with that key, so the relay only passes them along (phone_session._pair_secure);
//  - http://192.168.1.20:8766/?code=123456 (when the computer has no relay, or typed by hand): the computer's own
//    address and the short one-time code, same Wi-Fi only (phone_control.try_pair).
// Either way the code is short-lived and single-use, and only someone who can see the computer's screen has it.
import type { DeviceCredentials } from "./protocol.ts";
import type { WebSocketFactory } from "./connection.ts";
import { decrypt, encrypt, keyFromB64 } from "./crypto.ts";

export type LocalPairTarget = { localUrl: string; code: string };
export type SecurePairTarget = { relayUrl: string; computerId: string; secret: string };
export type PairTarget = LocalPairTarget | SecurePairTarget;

/** What a scanned QR link (or a typed "192.168.1.20 123456") says: where to pair, and with what. */
export function parsePairingInput(input: string): PairTarget | null {
  const text = (input || "").trim();
  const secure = /^(https?):\/\/([^/?#\s]+)\/?\?(?:[^#\s]*&)?computerId=([^&#\s]+)[^#\s]*#pair=([A-Za-z0-9_-]{40,})$/i.exec(text);
  if (secure) {
    let computerId = secure[3];
    try { computerId = decodeURIComponent(computerId); } catch { /* used as written */ }
    return { relayUrl: `${secure[1].toLowerCase() === "https" ? "wss" : "ws"}://${secure[2]}/`, computerId, secret: secure[4] };
  }
  const link = /^(?:https?|wss?):\/\/([^/?#\s]+)[^?#\s]*\?(?:[^#\s]*&)?code=(\d{6})\b/i.exec(text);
  if (link) return { localUrl: `ws://${link[1]}/`, code: link[2] };
  const typed = /^((?:\d{1,3}\.){3}\d{1,3})(?::(\d{2,5}))?[\s,/]+(\d{3})\s?(\d{3})$/.exec(text);
  if (typed) return { localUrl: `ws://${typed[1]}:${typed[2] || "8766"}/`, code: typed[3] + typed[4] };
  return null;
}

const EXPIRED = "That code has expired. Say “Connect my phone” on your computer for a fresh one.";

/** Through the relay, with the QR code's one-time key. */
function pairSecure(target: SecurePairTarget, deviceName: string, makeSocket: WebSocketFactory,
                    previous?: DeviceCredentials | null, timeoutMs = 30000): Promise<DeviceCredentials> {
  return new Promise((resolve, reject) => {
    let key: Uint8Array, ws: ReturnType<WebSocketFactory>;
    try { key = keyFromB64(target.secret); } catch { reject(new Error("That isn't a Jarvis pairing code.")); return; }
    try { ws = makeSocket(target.relayUrl); } catch { reject(new Error("Couldn't reach Jarvis's address. Check your internet connection.")); return; }
    const timer = setTimeout(() => done(() => reject(new Error(
      "Your computer didn't answer. Check that Jarvis is open there and online, then scan the code again."))), timeoutMs);
    const done = (fn: () => void) => { clearTimeout(timer); try { ws.close(); } catch { /* */ } fn(); };
    ws.onopen = () => ws.send(JSON.stringify({ type: "hello", role: "phone", computerId: target.computerId }));
    ws.onerror = () => done(() => reject(new Error("Couldn't reach Jarvis's address. Check your internet connection and try again.")));
    ws.onmessage = (ev) => {
      let data: Record<string, unknown>;
      try { data = JSON.parse(String(ev.data)); } catch { return; }
      if (data.type === "hello_ok") {
        ws.send(JSON.stringify({ type: "pair_secure", envelope: encrypt(key, {
          type: "pair", ts: Date.now(), deviceName, previousDeviceId: previous?.id || "", previousToken: previous?.token || "" }) }));
      } else if (data.type === "offline" || data.type === "jarvis_closed" || data.type === "wake_refused" || data.type === "waking") {
        done(() => reject(new Error("Jarvis isn't open on your computer. Open Jarvis there, say “Connect my phone”, and scan the new code.")));
      } else if (data.type === "pair_error") {
        done(() => reject(new Error(/expired|wrong/i.test(String(data.message || "")) ? EXPIRED : String(data.message || "Pairing didn't work. Try again."))));
      } else if (data.type === "paired_secure") {
        const answer = decrypt<Record<string, string>>(key, data.envelope);
        if (!answer || answer.type !== "paired" || !answer.deviceId || !answer.key) { done(() => reject(new Error(EXPIRED))); return; }
        done(() => resolve({ id: answer.deviceId, token: answer.token, key: answer.key, computerId: answer.computerId,
                             relayUrl: answer.relayUrl || target.relayUrl, localUrl: answer.localUrl || "", name: answer.deviceName }));
      }
    };
  });
}

export function pair(target: PairTarget, deviceName: string, makeSocket: WebSocketFactory,
                     previous?: DeviceCredentials | null, timeoutMs?: number): Promise<DeviceCredentials> {
  if ("secret" in target) return pairSecure(target, deviceName, makeSocket, previous, timeoutMs);
  return new Promise((resolve, reject) => {
    let ws: ReturnType<WebSocketFactory>;
    try { ws = makeSocket(target.localUrl); } catch { reject(new Error("Couldn't reach your computer.")); return; }
    const timer = setTimeout(() => { try { ws.close(); } catch { /* */ } reject(new Error(
      "Your computer didn't answer. Make sure your phone is on the same Wi-Fi as your computer.")); }, timeoutMs ?? 10000);
    const done = (fn: () => void) => { clearTimeout(timer); try { ws.close(); } catch { /* */ } fn(); };
    ws.onopen = () => ws.send(JSON.stringify({ type: "pair", code: target.code, deviceName,
                                               previousDeviceId: previous?.id || "", previousToken: previous?.token || "" }));
    ws.onerror = () => done(() => reject(new Error("Couldn't reach your computer. Make sure your phone is on the same Wi-Fi.")));
    ws.onmessage = (ev) => {
      let data: Record<string, string>;
      try { data = JSON.parse(String(ev.data)); } catch { return; }
      if (data.type === "paired") {
        done(() => resolve({ id: data.deviceId, token: data.token, key: data.key, computerId: data.computerId,
                             relayUrl: data.relayUrl || "", localUrl: target.localUrl, name: data.deviceName }));
      } else if (data.type === "pair_error") {
        done(() => reject(new Error(/expired|wrong/i.test(data.message || "") ? EXPIRED : data.message || "Pairing didn't work. Try again.")));
      }
    };
  });
}

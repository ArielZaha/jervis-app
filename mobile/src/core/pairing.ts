// First-time pairing, reusing "Connect my phone" exactly as it is: the QR code on the computer holds a link like
// http://192.168.1.20:8766/?code=123456 — the app reads the computer's address and the one-time code from it and
// pairs over that same local connection (phone_control.try_pair). Same Wi-Fi only, by design: the code is short-
// lived and single-use, and the device credentials it yields never cross the internet.
import type { DeviceCredentials } from "./protocol.ts";
import type { WebSocketFactory } from "./connection.ts";

export type PairTarget = { localUrl: string; code: string };

/** The computer's address and code from a scanned QR link, or a typed "192.168.1.20 123456". */
export function parsePairingInput(input: string): PairTarget | null {
  const text = (input || "").trim();
  const link = /^(?:https?|wss?):\/\/([^/?#\s]+)[^?#\s]*\?(?:[^#\s]*&)?code=(\d{6})\b/i.exec(text);
  if (link) return { localUrl: `ws://${link[1]}/`, code: link[2] };
  const typed = /^((?:\d{1,3}\.){3}\d{1,3})(?::(\d{2,5}))?[\s,/]+(\d{3})\s?(\d{3})$/.exec(text);
  if (typed) return { localUrl: `ws://${typed[1]}:${typed[2] || "8766"}/`, code: typed[3] + typed[4] };
  return null;
}

export function pair(target: PairTarget, deviceName: string, makeSocket: WebSocketFactory,
                     previous?: DeviceCredentials | null, timeoutMs = 10000): Promise<DeviceCredentials> {
  return new Promise((resolve, reject) => {
    let ws: ReturnType<WebSocketFactory>;
    try { ws = makeSocket(target.localUrl); } catch { reject(new Error("Couldn't reach your computer.")); return; }
    const timer = setTimeout(() => { try { ws.close(); } catch { /* */ } reject(new Error(
      "Your computer didn't answer. Make sure your phone is on the same Wi-Fi as your computer.")); }, timeoutMs);
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
        done(() => reject(new Error(/expired|wrong/i.test(data.message || "")
          ? "That code has expired. Say “Connect my phone” on your computer for a fresh one."
          : data.message || "Pairing didn't work. Try again.")));
      }
    };
  });
}

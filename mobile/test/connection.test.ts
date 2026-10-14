// The connection's state machine against scripted sockets: Jarvis Wake answering for a closed Jarvis, then Jarvis
// himself; a phone that only taps "Open Jarvis" when it wants to; and a refused (unknown) phone.
import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { ComputerConnection } from "../src/core/connection.ts";
import { encrypt, keyFromB64 } from "../src/core/crypto.ts";
import type { ConnState, DeviceCredentials } from "../src/core/protocol.ts";

const KEY = Buffer.alloc(32, 3).toString("base64url");
const device: DeviceCredentials = { id: "d1", token: "t", key: KEY, computerId: "c", relayUrl: "", localUrl: "ws://lan/", name: "iPhone" };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const live: ComputerConnection[] = [];
afterEach(() => { for (const c of live.splice(0)) c.stop(); });   // never leave retry timers running

type Script = (sent: any[], reply: (m: unknown) => void, close: () => void) => void;
function fakeSockets(scripts: Script[]) {
  const attaches: any[] = [];
  const factory = (_url: string) => {
    const script = scripts.length > 1 ? scripts.shift() : scripts[0];   // the last script keeps answering
    const sent: any[] = [];
    const ws: any = { readyState: 0, onopen: null, onclose: null, onerror: null, onmessage: null,
      send(data: string) {
        const msg = JSON.parse(data); sent.push(msg);
        if (msg.type === "auto_attach") { attaches.push(msg); script?.(sent, (m) => ws.onmessage?.({ data: JSON.stringify(m) }), () => ws.close()); }
      },
      close() { if (ws.readyState === 3) return; ws.readyState = 3; setTimeout(() => ws.onclose?.({}), 0); } };
    setTimeout(() => { ws.readyState = 1; ws.onopen?.({}); }, 5);
    return ws;
  };
  return { factory, attaches };
}
const jarvisWake: Script = (_s, reply, close) => { reply({ type: "waking" }); close(); };
const jarvisClosed: Script = (_s, reply, close) => { reply({ type: "jarvis_closed" }); close(); };
const jarvisUp: Script = (_s, reply) => reply(encrypt(keyFromB64(KEY), { type: "session_ready" }));

test("Jarvis closed: Jarvis Wake opens him, the app keeps knocking, then it's connected", async () => {
  const { factory, attaches } = fakeSockets([jarvisWake, jarvisWake, jarvisUp]);
  const states: ConnState[] = [];
  const conn = new ComputerConnection(device, factory as any, { onState: (s) => states.push(s) });
  live.push(conn);
  conn.start(true);
  for (let i = 0; i < 80 && !conn.ready; i++) await sleep(50);
  assert.ok(conn.ready, `ready (states: ${states.join(" → ")})`);
  assert.ok(states.includes("starting"), "showed 'Opening Jarvis on your computer…'");
  assert.equal(attaches[0].wake, true, "opening the app asks to open Jarvis");
  assert.equal(attaches[0].encrypt, true, "the native app always asks for an encrypted session");
  assert.equal(attaches.at(-1).wake, false, "retries don't ask again");
  conn.stop();
});

test("a background reconnect never reopens a Jarvis that was just quit; a tap does", async () => {
  const { factory, attaches } = fakeSockets([jarvisClosed, jarvisUp]);
  const conn = new ComputerConnection(device, factory as any);
  live.push(conn);
  conn.start(false);
  for (let i = 0; i < 40 && conn.state !== "closed"; i++) await sleep(25);
  assert.equal(conn.state, "closed");
  assert.equal(attaches[0].wake, false);
  conn.start(true);   // the "Open Jarvis" tap
  for (let i = 0; i < 80 && !conn.ready; i++) await sleep(25);
  assert.ok(conn.ready);
  assert.equal(attaches.at(-1).wake, true);
  conn.stop();
});

test("an unknown phone is refused without being told to forget its pairing", async () => {
  let unpaired = false;
  const { factory } = fakeSockets([(_s, reply, close) => { reply({ type: "wake_refused" }); close(); }]);
  const conn = new ComputerConnection(device, factory as any, { onUnpaired: () => { unpaired = true; } });
  live.push(conn);
  conn.start(true);
  for (let i = 0; i < 40 && conn.state !== "unreachable"; i++) await sleep(25);
  assert.equal(conn.state, "unreachable");
  assert.equal(unpaired, false);
  conn.stop();
});

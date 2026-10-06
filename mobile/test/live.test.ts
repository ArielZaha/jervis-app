// The app's connection layer against the REAL computer side: app.py's phone server (sandboxed) and relay/server.py,
// as separate processes. Pairing, encrypted LAN session, relay with key proof, run_on_computer, the AI key handoff,
// phone-mode turns joining the conversation, reconnects, "disconnect my phone", unpairing.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { ComputerConnection } from "../src/core/connection.ts";
import { pair, parsePairingInput } from "../src/core/pairing.ts";
import type { ConnState, DeviceCredentials } from "../src/core/protocol.ts";

const ROOT = new URL("../..", import.meta.url).pathname;
const PY = process.env.JARVIS_PY || ROOT + "venv/bin/python";
const PORT = 8797, CTRL = 8796, RELAY_PORT = 8795;
const procs: ChildProcess[] = [];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const ctl = async (path: string) => (await fetch(`http://127.0.0.1:${CTRL}${path}`)).json() as Promise<any>;
const makeSocket = (url: string) => new WebSocket(url) as any;

async function waitFor(fn: () => boolean | Promise<boolean>, ms = 10000, what = "condition") {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await fn()) return; await sleep(50); }
  throw new Error(`timed out waiting for ${what}`);
}

before(async () => {
  procs.push(spawn(PY, ["relay/server.py"], { cwd: ROOT, env: { ...process.env, PORT: String(RELAY_PORT) }, stdio: "ignore" }));
  await sleep(800);
  procs.push(spawn(PY, ["mobile/test/support/harness.py"], {
    cwd: ROOT, stdio: "ignore",
    env: { ...process.env, PORT: String(PORT), CTRL: String(CTRL), RELAY: `ws://127.0.0.1:${RELAY_PORT}/`, HARNESS_GROQ_KEY: "gsk_test_key" } }));
  await waitFor(async () => { try { await ctl("/state"); return true; } catch { return false; } }, 30000, "harness");
});
after(() => { for (const p of procs) p.kill(); });

let device: DeviceCredentials;

test("pairing straight from the QR link", async () => {
  const { pairUrl } = await ctl("/pair");
  const target = parsePairingInput(pairUrl.replace(/\/\/[^:/]+:/, "//127.0.0.1:"));
  assert.ok(target, "QR link understood");
  device = await pair(target!, "Samsung Galaxy", makeSocket);
  assert.equal(device.name, "Samsung Galaxy");
  assert.equal(device.localUrl, `ws://127.0.0.1:${PORT}/`);
  assert.equal(device.relayUrl, `ws://127.0.0.1:${RELAY_PORT}/`);
  assert.equal((await ctl("/state")).devices.length, 1);
  await assert.rejects(pair(target!, "Again", makeSocket), /expired|No pairing/);   // single use
});

test("encrypted session on the home Wi-Fi: computer requests, AI key, phone turns, reconnects", async () => {
  const states: ConnState[] = [];
  const messages: any[] = [];
  const conn = new ComputerConnection(device, makeSocket, { onState: (s) => states.push(s), onMessage: (m) => messages.push(m) });
  conn.start();
  await waitFor(() => conn.ready, 8000, "ready");
  assert.equal(conn.transport, "lan");
  assert.deepEqual((await ctl("/state")).connected, ["Samsung Galaxy"]);
  assert.ok(messages.some((m) => m.type === "session_info"), "history/info arrived");

  // run_on_computer: the computer's own pipeline, its exact answer back to the right request
  const answer = await conn.askComputer("open youtube");
  assert.equal(answer, "Opened YouTube.");
  const [a, b] = await Promise.all([conn.askComputer("first thing"), conn.askComputer("second thing")]);
  assert.deepEqual([a, b], ["Computer here: first thing", "Computer here: second thing"]);

  // the Groq key only ever over an encrypted session
  const cfg = await conn.requestAiConfig();
  assert.equal(cfg.apiKey, "gsk_test_key");
  assert.equal(cfg.model, "openai/gpt-oss-120b");

  // something handled on the phone joins the one conversation (window + the computer AI's memory)
  await ctl("/set_history");
  conn.send({ type: "phone_turn", user: "Open Spotify", reply: "Opened Spotify." });
  await waitFor(async () => (await ctl("/state")).history.length >= 3, 3000, "phone turn logged");
  const st = await ctl("/state");
  assert.match(st.history[1].content, /\(said on Samsung Galaxy, handled there\) Open Spotify/);
  assert.equal(st.history[2].content, "Opened Spotify.");
  assert.equal(st.window.at(-1).text, "Opened Spotify.");

  // a dropped connection comes back by itself
  await ctl("/kick");
  await waitFor(() => !conn.ready, 3000, "drop noticed");
  await waitFor(() => conn.ready, 8000, "reconnected");

  // "disconnect my phone" at the computer: stays disconnected until asked
  await ctl("/end");
  await waitFor(() => conn.state === "ended", 3000, "ended");
  await sleep(2500);
  assert.equal(conn.state, "ended");
  conn.start();
  await waitFor(() => conn.ready, 8000, "back after tap");
  conn.stop();
});

test("through the relay: key proof (no token), end-to-end encrypted", async () => {
  const relayOnly = { ...device, localUrl: "ws://127.0.0.1:9/" };   // home Wi-Fi unreachable
  const conn = new ComputerConnection(relayOnly, makeSocket);
  conn.start();
  await waitFor(() => conn.ready, 15000, "ready via relay");
  assert.equal(conn.transport, "relay");
  assert.equal(await conn.askComputer("open youtube"), "Opened YouTube.");
  conn.stop();
});

test("the computer off: requests fail honestly, quickly", async () => {
  const nowhere = { ...device, localUrl: "ws://127.0.0.1:9/", relayUrl: "" };
  const states: ConnState[] = [];
  const conn = new ComputerConnection(nowhere, makeSocket, { onState: (s) => states.push(s) });
  conn.start();
  await waitFor(() => states.includes("waiting") || states.includes("unreachable"), 6000, "gave up for now");
  await assert.rejects(conn.askComputer("open spotify"), /offline/);
  conn.stop();
});

test("unpairing from the phone revokes it on the computer", async () => {
  let unpaired = false;
  const conn = new ComputerConnection(device, makeSocket, { onUnpaired: () => { unpaired = true; } });
  conn.start();
  await waitFor(() => conn.ready, 8000, "ready");
  conn.send({ type: "unpair" });
  await waitFor(() => unpaired, 3000, "unpaired");
  assert.deepEqual((await ctl("/state")).devices, []);
  const again = new ComputerConnection(device, makeSocket, { onUnpaired: () => { unpaired = true; } });
  unpaired = false;
  again.start();
  await waitFor(() => unpaired && again.state === "unpaired", 5000, "old credentials refused");
});

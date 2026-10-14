// The phone's encryption must interoperate exactly with the computer's (phone_crypto.py): checked against the real
// Python implementation, both directions.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { decrypt, encrypt, keyFromB64 } from "../src/core/crypto.ts";
import { b64ToBytes, bytesToB64, bytesToB64url } from "../src/core/b64.ts";

const ROOT = new URL("../..", import.meta.url).pathname;
const PY = process.env.JARVIS_PY || ROOT + "venv/bin/python";
const py = (code: string, input = "") => execFileSync(PY, ["-c", code], { cwd: ROOT, input }).toString().trim();

test("base64 round-trips every length and matches the standard encoding", () => {
  for (let n = 0; n < 70; n++) {
    const bytes = Uint8Array.from({ length: n }, (_, i) => (i * 37 + n) & 255);
    assert.equal(bytesToB64(bytes), Buffer.from(bytes).toString("base64"));
    assert.equal(bytesToB64url(bytes), Buffer.from(bytes).toString("base64url"));
    assert.deepEqual(b64ToBytes(bytesToB64url(bytes)), bytes);
    assert.deepEqual(b64ToBytes(bytesToB64(bytes)), bytes);
  }
});

test("Python decrypts what the phone encrypted, and the phone decrypts what Python encrypted", () => {
  const keyB64 = py("import phone_crypto; print(phone_crypto.key_to_b64(phone_crypto.new_key()))");
  const key = keyFromB64(keyB64);
  const message = { type: "text", text: "Open Spotify and play Radiohead — שלום 🎵", requestId: "r1" };
  const envelope = encrypt(key, message);
  const fromPython = py(
    `import json, sys, phone_crypto\nk = phone_crypto.key_from_b64(${JSON.stringify(keyB64)})\n` +
    `print(json.dumps(phone_crypto.decrypt(k, json.load(sys.stdin)), ensure_ascii=False))`, JSON.stringify(envelope));
  assert.deepEqual(JSON.parse(fromPython), message);

  const pyEnvelope = py(
    `import json, phone_crypto\nk = phone_crypto.key_from_b64(${JSON.stringify(keyB64)})\n` +
    `print(json.dumps(phone_crypto.encrypt(k, {"type": "reply", "text": "Playing Karma Police."})))`);
  assert.deepEqual(decrypt(key, JSON.parse(pyEnvelope)), { type: "reply", text: "Playing Karma Police." });
});

test("tampered or wrong-key envelopes are rejected", () => {
  const key = keyFromB64(Buffer.alloc(32, 7).toString("base64url"));
  const other = keyFromB64(Buffer.alloc(32, 8).toString("base64url"));
  const env = encrypt(key, { a: 1 });
  assert.equal(decrypt(other, env), null);
  assert.equal(decrypt(key, { ...env, ct: env.ct.slice(0, -2) + (env.ct.endsWith("A") ? "B" : "A") + env.ct.slice(-1) }), null);
  assert.equal(decrypt(key, { nope: true }), null);
});

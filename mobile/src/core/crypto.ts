// End-to-end encryption for phone <-> computer traffic: AES-256-GCM, exactly phone_crypto.py's format —
// {"n": nonce, "ct": ciphertext+tag}, both unpadded base64url, the plaintext being JSON. The native app encrypts
// on the home Wi-Fi too (unlike the web page on plain http, which can't), and always through the relay.
import { gcm } from "@noble/ciphers/aes.js";
import { b64ToBytes, bytesToB64url, fromUtf8, utf8 } from "./b64.ts";

export type Envelope = { n: string; ct: string };
export type RandomBytes = (length: number) => Uint8Array;

let randomBytes: RandomBytes = (length) => {
  const out = new Uint8Array(length);
  const c = (globalThis as { crypto?: { getRandomValues?: (a: Uint8Array) => Uint8Array } }).crypto;
  if (!c?.getRandomValues) throw new Error("no secure random source");
  return c.getRandomValues(out);
};

/** The app installs the platform's secure random source at startup (expo-crypto); tests use Node's. */
export function setRandomSource(source: RandomBytes): void {
  randomBytes = source;
}
export const random = (length: number) => randomBytes(length);

export function keyFromB64(keyB64: string): Uint8Array {
  const key = b64ToBytes(keyB64);
  if (key.length !== 32) throw new Error("expected a 32-byte key");
  return key;
}

export function encrypt(key: Uint8Array, message: unknown): Envelope {
  const nonce = randomBytes(12);
  const ct = gcm(key, nonce).encrypt(utf8(JSON.stringify(message)));
  return { n: bytesToB64url(nonce), ct: bytesToB64url(ct) };
}

/** The original message, or null if this isn't genuinely an envelope sealed with `key` (tampered, wrong key). */
export function decrypt<T = unknown>(key: Uint8Array, envelope: unknown): T | null {
  try {
    const env = envelope as Envelope;
    if (!env || typeof env.n !== "string" || typeof env.ct !== "string") return null;
    const pt = gcm(key, b64ToBytes(env.n)).decrypt(b64ToBytes(env.ct));
    return JSON.parse(fromUtf8(pt)) as T;
  } catch {
    return null;
  }
}

export const isEnvelope = (x: unknown): x is Envelope =>
  !!x && typeof (x as Envelope).n === "string" && typeof (x as Envelope).ct === "string";

// base64 / base64url without relying on atob/btoa (not guaranteed on every JS engine the app runs on).
// Unpadded base64url is what phone_crypto.py and the web page exchange (phone_crypto._b64url_decode re-pads it).

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const LOOKUP = new Int16Array(256).fill(-1);
for (let i = 0; i < ALPHABET.length; i++) LOOKUP[ALPHABET.charCodeAt(i)] = i;
LOOKUP["-".charCodeAt(0)] = 62;
LOOKUP["_".charCodeAt(0)] = 63;

export function bytesToB64(bytes: Uint8Array, url = false): string {
  let out = "";
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + ALPHABET[n & 63];
  }
  const rest = bytes.length - i;
  if (rest === 1) {
    const n = bytes[i] << 16;
    out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + (url ? "" : "==");
  } else if (rest === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + (url ? "" : "=");
  }
  return url ? out.replace(/\+/g, "-").replace(/\//g, "_") : out;
}

export const bytesToB64url = (bytes: Uint8Array) => bytesToB64(bytes, true);

export function b64ToBytes(s: string): Uint8Array {
  const clean = s.replace(/[=\s]/g, "");
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let buffer = 0, bits = 0, j = 0;
  for (let i = 0; i < clean.length; i++) {
    const v = LOOKUP[clean.charCodeAt(i)];
    if (v < 0) throw new Error("invalid base64");
    buffer = (buffer << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[j++] = (buffer >> bits) & 0xff;
    }
  }
  return out.subarray(0, j);
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();
export const utf8 = (s: string) => encoder.encode(s);
export const fromUtf8 = (b: Uint8Array) => decoder.decode(b);

// Pairing credentials and the AI key live in the platform's secure storage (iOS Keychain, Android Keystore-backed
// SecureStore). Everything else (preferences, the cached conversation) in plain app storage.
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

const web = Platform.OS === "web";

export async function getSecret<T>(key: string): Promise<T | null> {
  try {
    const raw = web ? globalThis.localStorage?.getItem(key) ?? null : await SecureStore.getItemAsync(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export async function setSecret(key: string, value: unknown): Promise<void> {
  const raw = JSON.stringify(value);
  if (web) globalThis.localStorage?.setItem(key, raw);
  else await SecureStore.setItemAsync(key, raw, { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY });
}

export async function deleteSecret(key: string): Promise<void> {
  if (web) globalThis.localStorage?.removeItem(key);
  else await SecureStore.deleteItemAsync(key);
}

// Non-secret app data. SecureStore values are size-limited on some Android versions, so the conversation cache is
// split into small chunks there.
const CHUNK = 1800;
export async function getData<T>(key: string, fallback: T): Promise<T> {
  try {
    if (web) { const raw = globalThis.localStorage?.getItem(key); return raw ? JSON.parse(raw) : fallback; }
    const count = Number(await SecureStore.getItemAsync(`${key}.n`)) || 0;
    if (!count) return fallback;
    let raw = "";
    for (let i = 0; i < count; i++) raw += (await SecureStore.getItemAsync(`${key}.${i}`)) ?? "";
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export async function setData(key: string, value: unknown): Promise<void> {
  const raw = JSON.stringify(value);
  if (web) { globalThis.localStorage?.setItem(key, raw); return; }
  const parts = Math.ceil(raw.length / CHUNK) || 1;
  for (let i = 0; i < parts; i++) await SecureStore.setItemAsync(`${key}.${i}`, raw.slice(i * CHUNK, (i + 1) * CHUNK));
  await SecureStore.setItemAsync(`${key}.n`, String(parts));
}

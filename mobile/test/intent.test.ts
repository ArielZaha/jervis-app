import { test } from "node:test";
import assert from "node:assert/strict";
import { explicitTarget, fallbackIntent } from "../src/core/intent.ts";
import { findApp } from "../src/core/apps.ts";

test("explicit device targeting", () => {
  for (const s of ["Open Spotify on my computer", "play this on my computer", "take control of my computer and open Chrome",
                   "open youtube on the laptop", "use my computer to open Downloads"]) assert.equal(explicitTarget(s), "computer", s);
  for (const s of ["Open Spotify on my phone", "play this on my phone", "open maps on this phone", "show my photos on my iPhone"])
    assert.equal(explicitTarget(s), "phone", s);
  for (const s of ["Open Spotify", "Play Radiohead", "what's the weather", "move this from my phone to my computer"])
    assert.equal(explicitTarget(s), null, s);
});

test("the offline fallback understands plain requests", () => {
  const cases: Array<[string, string, Record<string, unknown>]> = [
    ["Open Spotify.", "open_app", { app: "Spotify" }],
    ["Can you open Spotify for me?", "open_app", { app: "Spotify" }],
    ["Jarvis, open my camera", "camera", {}],
    ["play Radiohead on Spotify", "spotify", { query: "Radiohead" }],
    ["Search YouTube for the new GTA 6 trailer", "youtube", { query: "the new GTA 6 trailer" }],
    ["search the web for the latest GTA 6 news", "web_search", { query: "the latest GTA 6 news" }],
    ["take me to Dizengoff Center", "maps", { destination: "Dizengoff Center" }],
    ["find the nearest coffee shop", "maps", { query: "coffee shop near me" }],
    ["call Mom", "call", { who: "Mom" }],
    ["text Dana saying I'm on my way", "message", { who: "Dana", text: "I'm on my way" }],
    ["set an alarm for 7 AM", "set_alarm", { hour: 7, minute: 0 }],
    ["set an alarm for 6:30 pm", "set_alarm", { hour: 18, minute: 30 }],
    ["set a timer for 10 minutes", "set_timer", { seconds: 600 }],
    ["turn on Bluetooth", "settings", { section: "bluetooth" }],
    ["turn on Wi-Fi", "settings", { section: "wifi" }],
    ["open google.com", "open_url", { url: "google.com" }],
  ];
  for (const [said, name, args] of cases) assert.deepEqual(fallbackIntent(said), { name, args }, said);
  assert.equal(fallbackIntent("what's the meaning of life"), null);
});

test("app names resolve the way people say them", () => {
  const cases: Array<[string, string]> = [["Spotify", "spotify"], ["the spotify app", "spotify"], ["my photos", "photos"],
    ["Gallery", "photos"], ["my messages", "messages"], ["Google Maps", "google-maps"], ["maps", "maps"],
    ["the settings", "settings"], ["WhatsApp", "whatsapp"], ["YouTube Music", "youtube-music"], ["play store", "app-store"],
    ["my calendar", "calendar"], ["camera", "camera"], ["Samsung Notes", "notes"]];
  for (const [said, id] of cases) assert.equal(findApp(said)?.id, id, said);
  assert.equal(findApp("some app that doesn't exist"), null);
});

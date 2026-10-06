# Jarvis for iPhone and Android

One Jarvis on two devices. The app is a full assistant on the phone (**Phone** mode) and a remote for Jarvis on the
computer (**Computer** mode), and it moves between them on its own: "open Spotify" happens on the phone, "open
Spotify on my computer" happens on the computer, in either mode.

```
            📱 Jarvis app                               💻 Jarvis on the computer (app.py)
  ┌────────────────────────────────┐        encrypted         ┌──────────────────────────────┐
  │ Jarvis agent (Groq)            │ ─── run_on_computer ───▶ │ the same pipeline as typing  │
  │  ├─ phone tools (src/platform) │ ◀──── its answer ─────── │ at the computer: direct      │
  │  ├─ web_answer                 │                          │ commands, AI, Spotify,       │
  │  └─ run_on_computer            │ ◀─ the conversation ──── │ YouTube, take control, …     │
  └────────────────────────────────┘ ─ phone-handled turns ─▶ └──────────────────────────────┘
```

- **Computer mode** sends what you say straight to computer-Jarvis, exactly like typing at the computer. Nothing about
  computer control is reimplemented on the phone.
- **Phone mode** runs the phone's own agent with the phone tools. Plain commands ("open Spotify", "call Mom", "set an
  alarm for 7") run instantly without an AI call; anything else, including follow-ups like "open them on Spotify",
  goes to the AI, which picks the tool and the device. Naming the computer always sends your exact words there.
- **One conversation**: the computer's history comes to the phone on connect, and requests handled on the phone are
  reported back into the computer's window and its AI's memory.
- **Works with the computer off**: the AI settings (your Groq key) come from the computer once, over the encrypted
  session, and are kept in the phone's secure storage (Keychain / Keystore). Phone actions keep working; computer
  actions say plainly that the computer is offline.

## Run it on your phone now (Expo Go)

1. Install **Expo Go** from the App Store / Google Play.
2. On the computer: `cd mobile && npm install && npx expo start`
3. Scan the QR code it prints (iPhone: Camera app; Android: Expo Go). Phone and computer on the same Wi-Fi.
4. In the app, tap **Scan the code**, then on the computer say **"Connect my phone"** and scan Jarvis's QR code.

Expo Go is the quick way to try it; it needs `expo start` running. A few features need the real app instead:
adding calendar events directly (Expo Go opens a pre-filled event or the calendar), and on Android setting alarms
without opening the clock app.

## Install it for real (EAS Build, no Xcode or Android Studio needed)

```
npx eas-cli@latest login          # free Expo account
npm run build:android             # an .apk you can install on any Samsung / Xiaomi / Android phone
npm run build:ios                 # needs an Apple Developer account ($99/year) to install on iPhone
```

## What it can do on each phone

| Request | iPhone | Samsung / Xiaomi (Android) |
|---|---|---|
| Open an app ("open Spotify") | ✅ via its URL scheme; says so if it isn't installed | ✅ via the system / package; says so if it isn't installed |
| Spotify / YouTube search | ✅ opens the search; you tap play | ✅ same |
| Web answers ("latest GTA 6 news") | ✅ answered in the chat | ✅ same |
| Maps, directions, "nearest coffee" | ✅ Apple Maps | ✅ default maps app / Google Maps navigation |
| Call / text / email someone | ✅ by contact name; the phone shows its own call screen / you tap send | ✅ same |
| Alarm | ❌ iPhone doesn't allow apps to set alarms: opens Clock, offers a reminder | ✅ set directly |
| Timer, reminder | ✅ as a notification | ✅ the clock app's timer; reminders as notifications |
| Calendar event | ✅ after you confirm (real app) | ✅ after you confirm (real app) |
| Camera, photos | ✅ (camera opens inside Jarvis: iPhone doesn't let apps open the Camera app) | ✅ the phone's own camera / gallery |
| Wi-Fi / Bluetooth on/off | ❌ no app can: opens Settings and says so | ❌ no app can: opens the Wi-Fi / Bluetooth panel |
| Siri, "Hey Jarvis" on the phone | not yet (needs native iOS code) | n/a |

Voice: the mic records only while you hold or tap it, and is transcribed with the same Groq account (Whisper).

## Security

- Pairing is the existing "Connect my phone" QR code: a single-use, short-lived code, same Wi-Fi only.
- Every session is end-to-end encrypted (AES-256-GCM, `src/core/crypto.ts` = `phone_crypto.py`), on the Wi-Fi too.
- Through the relay, the phone proves who it is with its key; its token never passes through the relay.
- Credentials live in the iOS Keychain / Android Keystore. Unpairing in the app revokes the phone on the computer.
- Consequential phone actions (adding to your calendar) ask first; computer-Jarvis keeps its own confirmations
  ("Can I use your mouse and keyboard?"), shown with Yes / No buttons.

## Code

- `src/core/` — platform-free TypeScript, unit-tested in Node: protocol, encryption, connection, pairing, the agent,
  the tool registry, the app catalog, the offline command parser.
- `src/platform/` — the phone tools (iOS URL schemes, Android intents), secure storage, voice transcription.
- `src/state/controller.ts` — the conversation, the connection and the agent, for the screens.
- `src/ui/` — the screens.
- `plugins/withLauncherQueries.js` — lets the Android app see installed apps (needed to open them on Android 11+).

## Tests

```
npm run typecheck
npm test                            # unit tests + live tests against the real app.py phone server and relay
GROQ_KEY=… npm run test:ai          # the real AI choosing device and tool for 22 spoken requests
```

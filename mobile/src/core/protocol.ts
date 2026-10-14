// Shapes shared with the computer side (phone_session.py, phone_control.py, wake/jarvis_wake.py, relay/server.py).

/** What pairing gives this phone, kept in the device's secure storage. */
export type DeviceCredentials = {
  id: string;
  token: string;
  key: string;            // base64url, 32 bytes: end-to-end key for this phone (phone_crypto.py)
  computerId: string;     // relay routing id (not a secret)
  relayUrl: string;       // wss://… when a relay is configured, else the computer's own ws:// address
  localUrl: string;       // ws://<computer on this Wi-Fi>:8766/ — tried first
  name: string;           // this phone's name on the computer ("iPhone", "Samsung Galaxy")
  computerName?: string;
};

export type AiConfig = {
  provider: "groq";
  apiKey: string;
  model: string;
  fallbackModel?: string;   // used when the main model is rate-limited (separate allowance)
  transcribeModel: string;
  userName?: string;
  /** Told by the computer along with the key, for the phone's own skills. */
  visionModel?: string;     // answers questions about pictures
  weatherCity?: string;     // the city from the computer's Settings
  spotify?: boolean;        // the computer can play on the phone's Spotify (the user's account is signed in there)
};

export type ChatMessage = { type: "chat"; sender: "user" | "ai"; text: string; ts?: number; image?: string };

export type SessionInfo = {
  type: "session_info";
  deviceName?: string;
  computerName?: string;
  history?: ChatMessage[];
  vapidKey?: string;
};

/** Connection states, as the UI presents them. */
export type ConnState =
  | "idle"         // not started
  | "connecting"   // first attempt
  | "waiting"      // retrying after a drop
  | "starting"     // Jarvis Wake answered: Jarvis is being opened on the computer
  | "ready"        // attached; computer actions available
  | "closed"       // Jarvis is closed on the computer (and wasn't asked to open)
  | "unreachable"  // nothing answered / computer off
  | "offline"      // this phone has no network
  | "stopped"      // user disconnected
  | "replaced"     // another device took the session
  | "ended"        // the computer ended it ("disconnect my phone")
  | "unpaired";    // credentials no longer valid

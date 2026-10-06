// Jarvis's visual identity on the phone: the desktop app's deep navy, cyan→violet orb, and HUD accents.
import { Platform } from "react-native";

export const colors = {
  bg: "#05070F",
  bgRaise: "#0A0E1B",
  surface: "#10162A",
  surface2: "#161D35",
  surface3: "#1D2542",
  line: "rgba(255,255,255,0.07)",
  line2: "rgba(255,255,255,0.12)",
  text: "#EEF2FB",
  text2: "#A5AFC8",
  text3: "#6B7592",
  cyan: "#4FD8FF",
  indigo: "#7D9DFF",
  violet: "#A58BFF",
  mint: "#3DF2C0",
  amber: "#FFC861",
  red: "#FF6B81",
  youText: "#050C1C",
};

export const brandGradient = ["#5EE0FF", "#7D9DFF", "#A58BFF"] as const;

export const radius = { sm: 12, md: 16, lg: 22, pill: 999 };

export const font = {
  // The system font on each platform (SF Pro on iPhone, the OEM's own on Samsung/Xiaomi) reads most native.
  family: Platform.select({ ios: undefined, android: undefined, default: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif" }),
  mono: Platform.select({ ios: "Menlo", android: "monospace", default: "ui-monospace, Menlo, monospace" }),
};

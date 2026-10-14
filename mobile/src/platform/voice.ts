// Speech to text for the mic button: recorded on the phone only while the user holds/taps it (never in the
// background), transcribed by the same Groq account (Whisper), then handled like typed text.
import type { AiConfig } from "../core/protocol.ts";

export async function transcribe(uri: string, config: AiConfig, mime = "audio/m4a"): Promise<string> {
  const form = new FormData();
  // React Native's FormData takes a {uri, name, type} file part directly.
  form.append("file", { uri, name: mime === "audio/webm" ? "voice.webm" : "voice.m4a", type: mime } as unknown as Blob);
  form.append("model", config.transcribeModel || "whisper-large-v3-turbo");
  form.append("response_format", "json");
  const res = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
    method: "POST",
    headers: { Authorization: `Bearer ${config.apiKey}` },
    body: form,
  });
  if (!res.ok) throw new Error(res.status === 401 ? "The AI key isn't valid anymore." : "I couldn't understand that recording.");
  const data = await res.json();
  return String(data.text || "").trim();
}

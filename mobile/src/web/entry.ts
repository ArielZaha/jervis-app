// The bundle the web app loads (/agent.js): the same Jarvis agent as the native app, with the web's phone tools.
// Built with `npm run build:web` into ../phone_agent.js.
import { JarvisAgent, type Mode, type Turn, type Activity } from "../core/agent.ts";
import { ToolRegistry, type Tool } from "../core/tools.ts";
import { webAnswerTool } from "../core/coreTools.ts";
import { explicitTarget } from "../core/intent.ts";
import type { AiConfig } from "../core/protocol.ts";
import { WEB_APP_NOTE, webPhoneTools } from "./webTools.ts";

export type AskComputer = (request: string) => Promise<{ ok: boolean; text: string }>;

export function createAgent(getConfig: () => AiConfig | null, askComputer: AskComputer) {
  const registry = new ToolRegistry();
  const computer: Tool = {
    name: "run_on_computer", where: "computer",
    description: "Have Jarvis on the user's computer do something there with all of its own abilities: desktop apps, " +
      "Spotify and YouTube on the computer, browser, files, take control of mouse and keyboard. Its answer comes back.",
    parameters: { type: "object", properties: { request: { type: "string", description: "The request as a clear command" } }, required: ["request"] },
    label: (a) => `On your computer: ${String(a.request || "").replace(/[.!?]+$/, "")}`,
    run: async (a) => {
      const answer = await askComputer(String(a.request || "").trim());
      return { ok: answer.ok, message: answer.text, final: true };
    },
  };
  const platform = /iPad|iPhone|iPod/.test(navigator.userAgent) ? "ios" : /Android/i.test(navigator.userAgent) ? "android" : "web";
  const agent = new JarvisAgent({ registry, platform, getConfig, fetch: (u, init) => fetch(u, init as RequestInit) as any, note: WEB_APP_NOTE });
  registry.register(...webPhoneTools(), computer, webAnswerTool((q) => agent.searchWeb(q)));
  return {
    respond: (req: { text: string; mode: Mode; history: Turn[]; computer: { online: boolean; name?: string; status: string };
                     confirm: (title: string, detail?: string) => Promise<boolean>; onActivity?: (a: Activity) => void }) =>
      agent.respond({ ...req, ctx: { platform, confirm: req.confirm } }),
  };
}

export async function transcribe(audio: Blob, config: AiConfig): Promise<string> {
  const form = new FormData();
  const ext = /mp4|m4a|aac/.test(audio.type) ? "m4a" : /ogg/.test(audio.type) ? "ogg" : "webm";
  form.append("file", audio, `voice.${ext}`);
  form.append("model", config.transcribeModel || "whisper-large-v3-turbo");
  const res = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
    method: "POST", headers: { Authorization: `Bearer ${config.apiKey}` }, body: form,
  });
  if (!res.ok) throw new Error(res.status === 401 ? "The AI key isn't valid anymore." : "I couldn't understand that recording.");
  return String((await res.json()).text || "").trim();
}

export { explicitTarget };

// Two small pieces of language understanding that must work without the AI:
//  - which device the user explicitly named ("…on my computer", "…on my phone"), so that always wins;
//  - a fallback for the most common phone requests when the AI can't be reached (no internet), so Phone Mode
//    is never useless offline. Everything else goes to the AI (agent.ts), which reads normal language.

export type Target = "phone" | "computer" | null;

const COMPUTER = /\b(?:on|from|with|using|in|to)\s+(?:my|the)\s+(?:computer|pc|mac|macbook|laptop|desktop)\b|\b(?:my|the)\s+(?:computer|pc|mac|laptop|desktop)(?:'s)?\s+(?:screen|spotify|browser|youtube)\b|\btake control\b|\buse my (?:computer|pc|mac|laptop)\b/i;
const PHONE = /\b(?:on|from|with|using|in|to)\s+(?:my|the|this)\s+(?:phone|iphone|mobile|cell|samsung|galaxy|xiaomi|android)\b|\bhere on (?:my|the) phone\b/i;

export function explicitTarget(text: string): Target {
  const c = COMPUTER.test(text), p = PHONE.test(text);
  if (c && !p) return "computer";
  if (p && !c) return "phone";
  return null;
}

export type ToolCall = { name: string; args: Record<string, unknown> };

function clean(s: string): string {
  let t = s.replace(/\s+(?:on|from|with|using|in)\s+(?:my|the|this)\s+(?:phone|iphone|mobile|android)\b/gi, "")
    .replace(/^(?:hey |ok |okay )?(?:jarvis|jervis)[,\s]+/i, "")
    .replace(/^(?:can|could|would|will) you (?:please )?|^please /i, "").trim();
  for (let previous = ""; previous !== t;) {   // "…for me please?" — peel trailing filler until nothing changes
    previous = t;
    t = t.replace(/[\s?.!,]+$/, "").replace(/\s+(?:please|for me|now|thanks)$/i, "");
  }
  return t;
}

/** A direct tool call for a plainly-worded common request, or null. Used only when the AI is unreachable. */
export function fallbackIntent(raw: string): ToolCall | null {
  const t = clean(raw);
  let m: RegExpExecArray | null;
  if ((m = /^(?:play|open|put on|find|search|look up|search for) (.+?) (?:on|in) spotify$/i.exec(t))) {
    return /^(?:it|them|that|this)$/i.test(m[1]) ? { name: "open_app", args: { app: "Spotify" } } : { name: "spotify", args: { query: m[1] } };
  }
  if ((m = /^(?:play|watch|search|find|look up) (.+?) on youtube$/i.exec(t)) || (m = /^search youtube for (.+)$/i.exec(t)))
    return { name: "youtube", args: { query: m[1] } };
  if ((m = /^(?:search (?:the web |google |online )?for|google|look up|search) (.+)$/i.exec(t)))
    return { name: "web_search", args: { query: m[1] } };
  if ((m = /^(?:navigate|take me|directions|drive|get me) (?:to )?(.+)$/i.exec(t)))
    return { name: "maps", args: { destination: m[1] } };
  if ((m = /^(?:find|show me) (?:the )?(?:nearest|closest) (.+)$/i.exec(t)) || (m = /^(?:find )?(.+?) near (?:me|here)$/i.exec(t)))
    return { name: "maps", args: { query: m[1] + " near me" } };
  if ((m = /^(?:call|phone|ring|dial) (.+)$/i.exec(t)))
    return { name: "call", args: { who: m[1] } };
  if ((m = /^(?:text|message|send a message to|send a text to|sms) (.+?)(?: (?:saying|that|to say)[: ]+(.+))?$/i.exec(t)))
    return { name: "message", args: { who: m[1], text: m[2] || "" } };
  if ((m = /^set (?:an |the )?alarm (?:for|at) (\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$/i.exec(t))) {
    let hour = Number(m[1]) % 12;
    if (/p/i.test(m[3] || "")) hour += 12; else if (!m[3] && Number(m[1]) === 12) hour = 12; else if (!m[3]) hour = Number(m[1]);
    return { name: "set_alarm", args: { hour, minute: Number(m[2] || 0) } };
  }
  if ((m = /^set (?:a |the )?timer (?:for )?(\d+)\s*(second|sec|minute|min|hour)s?$/i.exec(t))) {
    const unit = /^h/i.test(m[2]) ? 3600 : /^m/i.test(m[2]) ? 60 : 1;
    return { name: "set_timer", args: { seconds: Number(m[1]) * unit } };
  }
  if ((m = /^(?:turn|switch) (?:on|off) (?:the )?(wi-?fi|bluetooth|airplane mode|location|flashlight|hotspot)$/i.exec(t)))
    return { name: "settings", args: { section: m[1].toLowerCase().replace("-", "") } };
  if (/^(?:take a (?:photo|picture|selfie)|open (?:my |the )?camera)$/i.test(t)) return { name: "camera", args: {} };
  if ((m = /^(?:open|launch|start|show me|go to) (.+)$/i.exec(t))) {
    const what = m[1];
    if (/^https?:\/\/|^[\w-]+\.(?:com|org|net|io|co|il|dev|app)\b/i.test(what)) return { name: "open_url", args: { url: what } };
    return { name: "open_app", args: { app: what } };
  }
  return null;
}

// Jarvis on the phone: one agent that understands the request, picks the device and the tool, runs it (asking
// first when it matters), and says exactly what happened. The computer's own Jarvis is one of its tools
// (run_on_computer): requests for the computer go there verbatim and run through everything Jarvis already does
// on the computer — nothing about computer control is reimplemented here.
import type { AiConfig } from "./protocol.ts";
import type { Platform, ToolContext, ToolRegistry, ToolResult } from "./tools.ts";
import { explicitTarget, fallbackIntent, type ToolCall } from "./intent.ts";
import { findApp } from "./apps.ts";

export type Mode = "phone" | "computer";
export type Turn = { role: "user" | "assistant"; content: string };
export type Activity = { id: string; tool: string; label: string; where: "phone" | "computer" | "none";
                         status: "running" | "done" | "failed"; message?: string };

export type AgentRequest = {
  text: string;
  mode: Mode;
  history: Turn[];
  computer: { online: boolean; name?: string; status: string };
  ctx: ToolContext;
  onActivity?: (a: Activity) => void;
  signal?: AbortSignal;
};

export type AgentReply = { text: string; where: "phone" | "computer" | "none"; usedAI: boolean };

type Fetch = (url: string, init: Record<string, unknown>) => Promise<{ ok: boolean; status: number; json(): Promise<any>; text(): Promise<string> }>;

const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const MAX_ROUNDS = 4;

export type AgentOptions = {
  registry: ToolRegistry;
  platform: Platform;
  getConfig: () => AiConfig | null;
  fetch: Fetch;
  now?: () => Date;
  timeoutMs?: number;
};

export class JarvisAgent {
  private opts: AgentOptions;
  constructor(opts: AgentOptions) {
    this.opts = opts;
  }

  async respond(req: AgentRequest): Promise<AgentReply> {
    // Plain, unambiguous phone commands ("open Spotify", "call Mom", "set an alarm for 7") run instantly, without
    // a round trip to the AI — the same way Jarvis on the computer handles direct commands before asking the AI.
    const direct = req.mode === "phone" ? directCommand(req.text) : null;
    if (direct) {
      const result = await this.runTool(direct.name, direct.args as Record<string, any>, req);
      return { text: result.message, where: this.opts.registry.get(direct.name)?.where ?? "phone", usedAI: false };
    }
    const config = this.opts.getConfig();
    if (!config?.apiKey) return this.withoutAI(req, "I need to connect to your computer once to finish setting up.");
    try {
      return await this.withAI(req, config);
    } catch (e) {
      if (req.signal?.aborted) return { text: "Stopped.", where: "none", usedAI: true };
      return this.withoutAI(req, networkProblem(e));
    }
  }

  // ---------------------------------------------------------------- the AI path
  private async withAI(req: AgentRequest, config: AiConfig): Promise<AgentReply> {
    const { registry, platform } = this.opts;
    const tools = registry.schemas(platform);
    const messages: any[] = [
      { role: "system", content: this.systemPrompt(req, config) },
      ...req.history.slice(-12).map((t) => ({ role: t.role, content: t.content.slice(0, 600) })),
      { role: "user", content: req.text },
    ];
    let where: AgentReply["where"] = "none";
    for (let round = 0; round < MAX_ROUNDS; round++) {
      const body = { model: config.model, messages, tools, tool_choice: "auto", temperature: 0.2, reasoning_effort: "low",
                     max_completion_tokens: 700 };
      let response: any;
      try {
        response = await this.chat(config, body, req.signal);
      } catch (e) {
        if (!(e instanceof GroqError)) throw e;
        if (e.status === 429 && config.fallbackModel && config.fallbackModel !== config.model) {
          // Groq's free tier allows ~8k tokens a minute per model; the smaller model has its own allowance.
          response = await this.chat(config, { ...body, model: config.fallbackModel }, req.signal);
        } else if (e.status === 400 && /tool_use_failed|failed_generation|tool call/i.test(e.detail)) {
          // The model now and then writes a malformed tool call; Groq rejects it. A second try nearly always works.
          response = await this.chat(config, { ...body, temperature: 0.4 }, req.signal);
        } else {
          throw e;
        }
      }
      const msg = response.choices?.[0]?.message || {};
      const calls: any[] = msg.tool_calls || [];
      if (!calls.length) return { text: tidy(msg.content) || "Done.", where, usedAI: true };

      messages.push({ role: "assistant", content: msg.content || null, tool_calls: calls });
      const results: Array<{ tool: string; result: ToolResult }> = [];
      for (const call of calls) {
        let args: Record<string, any> = {};
        try { args = call.function?.arguments ? JSON.parse(call.function.arguments) : {}; } catch { /* empty args */ }
        const name = String(call.function?.name || "");
        const result = await this.runTool(name, args, req);
        const tool = registry.get(name);
        if (tool && tool.where !== "none") where = tool.where;
        results.push({ tool: name, result });
        messages.push({ role: "tool", tool_call_id: call.id,
                        content: JSON.stringify({ ok: result.ok, result: result.message, ...(result.data || {}) }) });
      }
      // A single action's own result is exactly what happened — say that, rather than have the AI retell it
      // (faster too: no second round trip). Failures are always said as-is: never dressed up as success.
      const finals = results.filter((r) => r.result.final || registry.get(r.tool)?.where !== "none");
      if (results.length && finals.length === results.length) {
        return { text: results.map((r) => r.result.message).join(" "), where, usedAI: true };
      }
    }
    return { text: "I got stuck working that out. Could you say it another way?", where, usedAI: true };
  }

  private async runTool(name: string, args: Record<string, any>, req: AgentRequest): Promise<ToolResult> {
    const { registry } = this.opts;
    const tool = registry.get(name);
    const id = `${name}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const label = tool ? safe(() => tool.label(args), name) : name;
    const where = tool?.where ?? "none";
    req.onActivity?.({ id, tool: name, label, where, status: "running" });
    const result = await registry.execute(name, args, req.ctx);
    req.onActivity?.({ id, tool: name, label, where, status: result.ok ? "done" : "failed", message: result.message });
    return result;
  }

  private async chat(config: AiConfig, body: Record<string, unknown>, signal?: AbortSignal): Promise<any> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.opts.timeoutMs ?? 30000);
    signal?.addEventListener?.("abort", () => controller.abort());
    try {
      const res = await this.opts.fetch(GROQ_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${config.apiKey}` },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new GroqError(res.status, detail);
      }
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /** The web, answered in the chat (Groq's built-in browser search) — used by the web_answer tool. */
  async searchWeb(question: string, signal?: AbortSignal): Promise<string> {
    const config = this.opts.getConfig();
    if (!config?.apiKey) throw new Error("I need to connect to your computer once before I can search the web.");
    const response = await this.chat(config, {
      model: config.model,
      messages: [
        { role: "system", content: `Today is ${this.today()}. Answer briefly (2-4 sentences, plain text, no tables), from current web results. Mention a source name when useful.` },
        { role: "user", content: question },
      ],
      tools: [{ type: "browser_search" }],
      temperature: 0.2,
      max_completion_tokens: 1200,
    }, signal);
    return tidy(response.choices?.[0]?.message?.content) || "I couldn't find anything on that.";
  }

  // ---------------------------------------------------------------- without the AI (offline / not set up)
  private async withoutAI(req: AgentRequest, why: string): Promise<AgentReply> {
    const call = fallbackIntent(req.text);
    if (!call) return { text: `${why} I can still open apps, search, call, text, navigate, and set alarms or timers on this phone.`, where: "none", usedAI: false };
    if (call.name === "open_app" && explicitTarget(req.text) === "computer") {
      return { text: "Your computer is offline right now, so I can't control it.", where: "none", usedAI: false };
    }
    const result = await this.runTool(call.name, call.args as Record<string, any>, req);
    return { text: result.message, where: this.opts.registry.get(call.name)?.where ?? "phone", usedAI: false };
  }

  // ---------------------------------------------------------------- prompt
  private today(): string {
    const now = (this.opts.now ?? (() => new Date()))();
    return `${now.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}, ` +
      `${now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })} (time zone ${Intl.DateTimeFormat().resolvedOptions().timeZone}, UTC offset ${-now.getTimezoneOffset() / 60}h)`;
  }

  private systemPrompt(req: AgentRequest, config: AiConfig): string {
    const phone = this.opts.platform === "ios" ? "iPhone" : this.opts.platform === "android" ? "Android phone" : "phone";
    const computer = req.computer.online ? `online${req.computer.name ? ` ("${req.computer.name}")` : ""}`
      : `OFFLINE (${req.computer.status}): computer actions are impossible now, say so`;
    const target = explicitTarget(req.text);
    return [
      `You are Jarvis, ${config.userName ? config.userName + "'s" : "the user's"} personal assistant: one Jarvis on their ${phone} (talking now) and their computer. ${this.today()}.`,
      `Computer: ${computer}. Mode: ${req.mode}; when no device is named, act on ${req.mode === "computer" ? "the computer" : "this phone"}.` +
        (target ? ` The user named the ${target} here.` : ""),
      "Rules: use a tool for every action; never claim success a tool didn't report; report failures plainly. " +
        "Computer actions (its apps, Spotify/YouTube there, browser, files, mouse/keyboard) → run_on_computer with the user's own words minus \"on my computer\" (keep phrases like \"take control\"); only rewrite to resolve \"it\"/\"them\"/\"the first one\" from the conversation. " +
        "News, current or uncertain facts → web_answer. General questions → just answer. " +
        "If the person, place or device is ambiguous and it matters (calling, messaging, the computer), ask briefly. " +
        "No app can switch Wi-Fi/Bluetooth on iPhone; on Android only the user can, from the panel.",
      "Reply in one or two warm, natural sentences (may be read aloud). No markdown tables. Never mention tool names.",
    ].join("\n");
  }
}

/** A plain phone command the local parser is sure about, or null (then the AI decides). */
function directCommand(text: string): ToolCall | null {
  if (/\b(?:it|them|that|this|these|those|one|him|her|there|same|again|instead|first|second|last)\b/i.test(text)) return null;   // needs the conversation
  if (explicitTarget(text) === "computer") {
    // Named the computer, nothing to resolve: the user's own words go to computer-Jarvis as they are (it has its
    // own command handling — "take control …" means something specific there), minus the "on my computer".
    const request = text.replace(/\s*\b(?:on|from|with|using|in)\s+(?:my|the)\s+(?:computer|pc|mac|macbook|laptop|desktop)\b/gi, "")
      .replace(/^\s*(?:hey |ok |okay )?(?:jarvis|jervis)[,\s]+/i, "").replace(/^\s*(?:please\s+|can you\s+|could you\s+)/i, "").trim();
    return request ? { name: "run_on_computer", args: { request } } : null;
  }
  const call = fallbackIntent(text);
  if (!call) return null;
  if (call.name === "open_app") return findApp(String(call.args.app)) ? call : null;
  if (call.name === "web_search") return null;   // "search for X" is better answered by the AI (web_answer)
  return call;
}

export class GroqError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(status === 401 ? "The AI key isn't valid anymore." : status === 429 ? "The AI is busy (rate limit)." : `The AI answered with an error (${status}).`);
    this.name = "GroqError";
    this.status = status;
    this.detail = detail;
    if (status === 400) console.warn("Groq rejected a request:", detail.slice(0, 500));
  }
}

function networkProblem(e: unknown): string {
  if (e instanceof GroqError) return e.message;
  return "I can't reach the AI right now (no internet?).";
}

function tidy(text: unknown): string {
  return String(text || "")
    .replace(/【[^】]*】/g, "")          // browser-search citation markers
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim();
}

function safe<T>(fn: () => T, fallback: T): T {
  try { return fn(); } catch { return fallback; }
}

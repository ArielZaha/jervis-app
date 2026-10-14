// The phone's tool architecture: every capability is a Tool — what it does (for the AI), where it acts, whether it
// needs the user's OK first, and how it runs. The agent (agent.ts) only ever sees this registry; platform code
// (src/platform/) supplies the implementations. Adding a capability = registering one more Tool, nothing else.

export type Platform = "ios" | "android" | "web";
export type Where = "phone" | "computer" | "none";

export type ToolResult = {
  ok: boolean;
  /** What happened, in plain words — shown to the user and given to the AI. Never claims more than happened. */
  message: string;
  /** Extra facts for the AI (e.g. the matched contact), not shown. */
  data?: Record<string, unknown>;
  /** true when this result is itself the answer (no need for the AI to reword it). */
  final?: boolean;
};

export type ToolContext = {
  platform: Platform;
  /** Ask the user to confirm a consequential action; resolves false if they cancel. */
  confirm: (title: string, detail?: string) => Promise<boolean>;
};

export type JsonSchema = { type: "object"; properties: Record<string, unknown>; required?: string[] };

export type Tool = {
  name: string;
  description: string;
  parameters: JsonSchema;
  where: Where;
  /** Shown while it runs, e.g. "Opening Spotify". */
  label: (args: Record<string, any>) => string;
  /** A confirmation question when this particular call needs one, else null. */
  confirm?: (args: Record<string, any>) => { title: string; detail?: string } | null;
  available?: (platform: Platform) => boolean;
  run: (args: Record<string, any>, ctx: ToolContext) => Promise<ToolResult>;
};

export class ToolRegistry {
  private tools = new Map<string, Tool>();

  register(...tools: Tool[]): this {
    for (const tool of tools) this.tools.set(tool.name, tool);
    return this;
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  list(platform: Platform, filter: (t: Tool) => boolean = () => true): Tool[] {
    return [...this.tools.values()].filter((t) => (t.available ? t.available(platform) : true) && filter(t));
  }

  /** OpenAI/Groq function-calling schemas. Optional parameters also accept null: the model often sends
   *  `"location": null` for "not given", and Groq rejects the whole call if the schema says plain "string". */
  schemas(platform: Platform, filter?: (t: Tool) => boolean) {
    return this.list(platform, filter).map((t) => ({
      type: "function" as const,
      function: { name: t.name, description: t.description, parameters: nullableOptionals(t.parameters) },
    }));
  }

  /** Runs one call with its confirmation step; never throws. */
  async execute(name: string, args: Record<string, any>, ctx: ToolContext): Promise<ToolResult> {
    const tool = this.tools.get(name);
    if (!tool || (tool.available && !tool.available(ctx.platform))) {
      return { ok: false, message: `That isn't something I can do on this ${ctx.platform === "ios" ? "iPhone" : "phone"}.` };
    }
    const ask = tool.confirm?.(args);
    if (ask && !(await ctx.confirm(ask.title, ask.detail))) return { ok: false, message: "Okay, I didn't do it.", final: true };
    try {
      return await tool.run(args, ctx);
    } catch (e) {
      return { ok: false, message: e instanceof Error ? e.message : "That didn't work." };
    }
  }
}

function nullableOptionals(schema: JsonSchema): JsonSchema {
  const required = new Set(schema.required ?? []);
  const properties: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(schema.properties)) {
    const prop = value as { type?: string | string[]; enum?: unknown[] };
    properties[key] = !required.has(key) && typeof prop.type === "string"
      ? { ...prop, type: [prop.type, "null"], ...(prop.enum ? { enum: [...prop.enum, null] } : {}) }
      : prop;
  }
  return { ...schema, properties };
}

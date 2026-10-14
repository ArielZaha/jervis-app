// The agent's decision loop with a scripted AI: device routing, verbatim results, honest failures, confirmation,
// and the no-AI fallback.
import { test } from "node:test";
import assert from "node:assert/strict";
import { JarvisAgent, type Activity } from "../src/core/agent.ts";
import { ToolRegistry, type Tool } from "../src/core/tools.ts";

const config = { provider: "groq" as const, apiKey: "k", model: "m", transcribeModel: "w" };

function fakeTool(name: string, where: Tool["where"], result: { ok: boolean; message: string }, calls: unknown[], confirm = false): Tool {
  return { name, description: name, where, parameters: { type: "object", properties: {} }, label: () => name,
           confirm: confirm ? () => ({ title: "Sure?" }) : undefined,
           run: async (args) => { calls.push([name, args]); return result; } };
}

function scripted(...replies: any[]) {
  const bodies: any[] = [];
  return { bodies, fetch: async (_url: string, init: any) => {
    bodies.push(JSON.parse(init.body));
    const next = replies.shift();
    if (next instanceof Error) throw next;
    return { ok: true, status: 200, json: async () => next, text: async () => "" };
  } };
}
const call = (name: string, args: object) => ({ choices: [{ message: { content: null, tool_calls: [{ id: "c1", type: "function", function: { name, arguments: JSON.stringify(args) } }] } }] });
const say = (content: string) => ({ choices: [{ message: { content } }] });
const ctx = (answer = true) => ({ platform: "ios" as const, confirm: async () => answer });
const base = { mode: "phone" as const, history: [], computer: { online: true, name: "Mac", status: "ready" } };

test("a plain command runs instantly, without the AI", async () => {
  const calls: unknown[] = [];
  const reg = new ToolRegistry().register(fakeTool("open_app", "phone", { ok: true, message: "Opened Spotify." }, calls));
  const ai = scripted();
  const agent = new JarvisAgent({ registry: reg, platform: "ios", getConfig: () => config, fetch: ai.fetch as any });
  const reply = await agent.respond({ ...base, text: "Could you open Spotify for me?", ctx: ctx() });
  assert.deepEqual(reply, { text: "Opened Spotify.", where: "phone", usedAI: false });
  assert.equal(ai.bodies.length, 0);
  // ...anything needing the conversation goes to the AI
  await agent.respond({ ...base, text: "Open them on Spotify", ctx: ctx() }).catch(() => {});
  assert.equal(ai.bodies.length, 1);
});

test("naming the computer sends the user's own words there, without an AI round trip", async () => {
  const calls: Array<[string, any]> = [];
  const reg = new ToolRegistry().register(fakeTool("run_on_computer", "computer", { ok: true, message: "Okay. Move the mouse to stop me." }, calls));
  const ai = scripted();
  const agent = new JarvisAgent({ registry: reg, platform: "android", getConfig: () => config, fetch: ai.fetch as any });
  const reply = await agent.respond({ ...base, text: "Take control of my computer and open Chrome", ctx: ctx() });
  assert.deepEqual(calls, [["run_on_computer", { request: "Take control of my computer and open Chrome" }]]);
  assert.equal(reply.where, "computer");
  await agent.respond({ ...base, text: "Jarvis, open Spotify and play Radiohead on my computer", ctx: ctx() });
  assert.deepEqual(calls[1], ["run_on_computer", { request: "open Spotify and play Radiohead" }]);
  assert.equal(ai.bodies.length, 0);
});

test("a phone action the AI picked runs once and its own result is the answer (no second AI call)", async () => {
  const calls: unknown[] = [];
  const reg = new ToolRegistry().register(fakeTool("open_app", "phone", { ok: true, message: "Opened Spotify." }, calls));
  const ai = scripted(call("open_app", { app: "Spotify" }));
  const activity: Activity[] = [];
  const agent = new JarvisAgent({ registry: reg, platform: "ios", getConfig: () => config, fetch: ai.fetch as any });
  const reply = await agent.respond({ ...base, text: "I'd love some music, get Spotify going", ctx: ctx(), onActivity: (a) => activity.push(a) });
  assert.deepEqual(reply, { text: "Opened Spotify.", where: "phone", usedAI: true });
  assert.deepEqual(calls, [["open_app", { app: "Spotify" }]]);
  assert.equal(ai.bodies.length, 1);
  assert.deepEqual(activity.map((a) => a.status), ["running", "done"]);
  assert.match(ai.bodies[0].messages[0].content, /act on this phone/);
});

test("rate-limited: retried once on the smaller model", async () => {
  const bodies: any[] = [];
  let n = 0;
  const fetch = async (_u: string, init: any) => {
    bodies.push(JSON.parse(init.body));
    if (n++ === 0) return { ok: false, status: 429, json: async () => ({}), text: async () => "rate limit" };
    return { ok: true, status: 200, json: async () => say("Sure."), text: async () => "" };
  };
  const agent = new JarvisAgent({ registry: new ToolRegistry(), platform: "ios", getConfig: () => ({ ...config, fallbackModel: "small" }), fetch: fetch as any });
  const reply = await agent.respond({ ...base, text: "tell me a joke", ctx: ctx() });
  assert.equal(reply.text, "Sure.");
  assert.deepEqual(bodies.map((b) => b.model), ["m", "small"]);
});

test("a failure is reported as a failure, never dressed up", async () => {
  const reg = new ToolRegistry().register(fakeTool("open_app", "phone", { ok: false, message: "Spotify isn't installed on this iPhone." }, []));
  const agent = new JarvisAgent({ registry: reg, platform: "ios", getConfig: () => config, fetch: scripted(call("open_app", { app: "Spotify" })).fetch as any });
  const reply = await agent.respond({ ...base, text: "Open Spotify", ctx: ctx() });
  assert.equal(reply.text, "Spotify isn't installed on this iPhone.");
});

test("the system prompt tells the AI where to act and whether the computer is reachable", async () => {
  const ai = scripted(say("Hi!"));
  const agent = new JarvisAgent({ registry: new ToolRegistry(), platform: "android", getConfig: () => config, fetch: ai.fetch as any });
  await agent.respond({ ...base, mode: "computer", computer: { online: false, status: "Jarvis is closed" }, text: "Get Spotify going on my phone", ctx: ctx() });
  const prompt = ai.bodies[0].messages[0].content;
  assert.match(prompt, /act on the computer/);
  assert.match(prompt, /OFFLINE \(Jarvis is closed\)/);
  assert.match(prompt, /named the phone here/);
  assert.match(prompt, /Android phone/);
});

test("conversation history goes along, so follow-ups like 'open them' have context", async () => {
  const ai = scripted(say("ok"));
  const agent = new JarvisAgent({ registry: new ToolRegistry(), platform: "ios", getConfig: () => config, fetch: ai.fetch as any });
  await agent.respond({ ...base, text: "Open them on Spotify", ctx: ctx(),
                        history: [{ role: "user", content: "Find Radiohead" }, { role: "assistant", content: "Radiohead are an English rock band." }] });
  const roles = ai.bodies[0].messages.map((m: any) => m.role);
  assert.deepEqual(roles, ["system", "user", "assistant", "user"]);
  // a leading message of Jarvis's own (no question before it) isn't sent: the model would answer it again
  const ai2 = scripted(say("ok"));
  const agent2 = new JarvisAgent({ registry: new ToolRegistry(), platform: "ios", getConfig: () => config, fetch: ai2.fetch as any });
  await agent2.respond({ ...base, text: "What's 15% of 80?", ctx: ctx(),
                         history: [{ role: "assistant", content: "Your iPhone is now paired." }, { role: "user", content: "open youtube" }, { role: "assistant", content: "Opened YouTube." }] });
  assert.deepEqual(ai2.bodies[0].messages.map((m: any) => m.role), ["system", "user", "assistant", "user"]);
});

test("a declined confirmation means nothing ran", async () => {
  const calls: unknown[] = [];
  const reg = new ToolRegistry().register(fakeTool("calendar_event", "phone", { ok: true, message: "Added." }, calls, true));
  const agent = new JarvisAgent({ registry: reg, platform: "ios", getConfig: () => config, fetch: scripted(call("calendar_event", {})).fetch as any });
  const reply = await agent.respond({ ...base, text: "add dinner tomorrow", ctx: ctx(false) });
  assert.deepEqual(calls, []);
  assert.equal(reply.text, "Okay, I didn't do it.");
});

test("no internet: plain phone requests still work through the fallback", async () => {
  const calls: unknown[] = [];
  const reg = new ToolRegistry().register(fakeTool("open_app", "phone", { ok: true, message: "Opened Maps." }, calls));
  const agent = new JarvisAgent({ registry: reg, platform: "android", getConfig: () => config,
                                  fetch: scripted(new TypeError("Network request failed")).fetch as any });
  const reply = await agent.respond({ ...base, text: "open maps", ctx: ctx() });
  assert.equal(reply.text, "Opened Maps.");
  assert.equal(reply.usedAI, false);
  const nothing = await agent.respond({ ...base, text: "what's the capital of France", ctx: ctx() });
  assert.match(nothing.text, /can't reach the AI/);
});

test("not set up yet (no key): still useful for simple requests", async () => {
  const calls: unknown[] = [];
  const reg = new ToolRegistry().register(fakeTool("call", "phone", { ok: true, message: "Calling Mom." }, calls));
  const agent = new JarvisAgent({ registry: reg, platform: "ios", getConfig: () => null, fetch: (async () => { throw new Error("no"); }) as any });
  assert.equal((await agent.respond({ ...base, text: "call mom", ctx: ctx() })).text, "Calling Mom.");
});

test("optional tool parameters accept null (the model sends null for 'not given')", () => {
  const reg = new ToolRegistry().register({ name: "calendar_event", description: "", where: "phone", label: () => "",
    parameters: { type: "object", properties: { title: { type: "string" }, end: { type: "string" }, mode: { type: "string", enum: ["a"] } }, required: ["title"] },
    run: async () => ({ ok: true, message: "" }) });
  const props = (reg.schemas("ios")[0].function.parameters as any).properties;
  assert.deepEqual(props.title.type, "string");
  assert.deepEqual(props.end.type, ["string", "null"]);
  assert.deepEqual(props.mode.type, ["string", "null"]);
  assert.deepEqual(props.mode.enum, ["a", null]);
});

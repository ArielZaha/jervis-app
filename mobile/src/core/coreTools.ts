// Tools that don't touch the phone's own APIs: the computer (through its own Jarvis) and the web.
import type { Tool } from "./tools.ts";
import type { ComputerConnection } from "./connection.ts";

export function computerTool(getConnection: () => ComputerConnection | null): Tool {
  return {
    name: "run_on_computer",
    description:
      "Have Jarvis on the user's computer do something there, with all of its own abilities: open or control desktop " +
      "apps, play music on the computer's Spotify, play YouTube on the computer, browse, files, documents, images, " +
      "take control of the mouse and keyboard, and more. Its answer comes back as the result.",
    parameters: {
      type: "object",
      properties: { request: { type: "string", description: "The request as a clear command, e.g. \"play Radiohead on Spotify\"." } },
      required: ["request"],
    },
    where: "computer",
    label: (a) => `On your computer: ${String(a.request || "").replace(/[.!?]+$/, "")}`,
    run: async (args) => {
      const connection = getConnection();
      if (!connection || !connection.ready) {
        return { ok: false, message: connection ? offlineSentence(connection.offlineReason()) : "Your computer isn't paired yet.", final: true };
      }
      try {
        const answer = await connection.askComputer(String(args.request || "").trim());
        return { ok: true, message: answer || "Done.", final: true };
      } catch (e) {
        return { ok: false, message: e instanceof Error ? e.message : "Your computer didn't answer.", final: true };
      }
    },
  };
}

function offlineSentence(reason: string): string {
  return /offline/i.test(reason) ? "Your computer is offline right now, so I can't control it." : `${reason} So I can't do that there right now.`;
}

export function webAnswerTool(search: (question: string) => Promise<string>): Tool {
  return {
    name: "web_answer",
    description: "Look something up on the web right now and answer in the chat: news, current events, prices, sports, " +
      "opening hours, anything recent or that you're unsure of.",
    parameters: { type: "object", properties: { question: { type: "string" } }, required: ["question"] },
    where: "none",
    label: (a) => `Searching the web for “${String(a.question || "").slice(0, 60)}”`,
    run: async (args) => ({ ok: true, message: await search(String(args.question || "")), final: true }),
  };
}

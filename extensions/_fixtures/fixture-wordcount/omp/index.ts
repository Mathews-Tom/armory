import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { countWords, formatCount } from "../core/index.ts";

export default function fixtureWordcount(pi: ExtensionAPI): void {
  pi.registerCommand("armory-fixture-wordcount", {
    description: "Count the words in the given text (packaging fixture)",
    handler: async (args, ctx) => {
      ctx.ui.notify(formatCount(countWords(args)), "info");
    },
  });
}

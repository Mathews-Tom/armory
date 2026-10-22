import { countWords, formatCount } from "../core/index.ts";

// The subset of the Claude Code mods API this hooks module touches.
interface ModApi {
  command: { register(spec: { name: string; description: string }): Promise<unknown> };
}
type Next<E> = (event: E) => Promise<unknown>;
interface CommandRun {
  command: string;
  args: string;
}
type On = {
  (event: "session.start", hook: ($: ModApi, e: unknown, next: Next<unknown>) => Promise<unknown>): unknown;
  (
    event: "command.run",
    matcher: { command: string },
    hook: ($: ModApi, e: CommandRun) => Promise<{ text: string }>,
  ): unknown;
};

export function register(on: On): void {
  on("session.start", async ($, e, next) => {
    await $.command.register({
      name: "armory-fixture-wordcount",
      description: "Count the words in the given text (packaging fixture)",
    });
    return next(e);
  });

  on("command.run", { command: "armory-fixture-wordcount" }, async ($, e) => {
    return { text: formatCount(countWords(e.args)) };
  });
}

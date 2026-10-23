/**
 * OMP factory probe: loads one extension entry exactly as OMP's loader does
 * (default export or module-level factory), calls it with a recording
 * ExtensionAPI, emits a recording session_start and prints command names.
 *
 * This is a test-kit check of the factory contract, not host proof: no OMP
 * session, model, UI or command handler runs.
 *
 * Usage: bun extensions/_tooling/omp-probe.ts <entry.ts|entry.js>
 */
import { pathToFileURL } from "node:url";
import type { ExtensionAPI, ExtensionFactory } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";

type LoadedModule = ExtensionFactory | { default?: unknown };

const entry = process.argv[2];
if (entry === undefined || process.argv.length !== 3) {
  process.stderr.write("usage: omp-probe.ts <extension entry>\n");
  process.exit(2);
}

const loaded = (await import(pathToFileURL(entry).href)) as LoadedModule;
const candidate = typeof loaded === "function" ? loaded : loaded.default;
if (typeof candidate !== "function") {
  process.stderr.write(`${entry}: no extension factory (default export function) found\n`);
  process.exit(1);
}

const commands: string[] = [];
const calls: string[] = [];
const startupHandlers: Array<(event: unknown, context: unknown) => unknown> = [];
const recorder = new Proxy(
  {},
  {
    get(_target, property) {
      const name = String(property);
      if (name === "getCommands") {
        return () => commands.map((command) => ({ name: command, source: "extension" }));
      }
      if (name === "on") {
        return (event: string, handler: (event: unknown, context: unknown) => unknown) => {
          if (event === "session_start") startupHandlers.push(handler);
          calls.push(`on:${event}`);
        };
      }
      if (name === "registerCommand") {
        return (commandName: string) => {
          commands.push(commandName);
        };
      }
      return () => {
        calls.push(name);
      };
    },
  },
) as ExtensionAPI;

await (candidate as ExtensionFactory)(recorder);
for (const handler of startupHandlers) {
  await handler({ type: "session_start" }, { mode: "print", hasUI: false });
}
process.stdout.write(`${JSON.stringify({ commands, calls })}\n`);

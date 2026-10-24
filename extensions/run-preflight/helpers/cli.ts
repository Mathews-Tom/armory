import { admit, check, refusal } from "../core/index.ts";
import type { ProbeResponse, Response } from "../core/index.ts";
import { renderPreflight } from "../core/render.ts";
import { runBridge } from "./bridge.ts";
import { observe, readSelected, sha256 } from "./filesystem.ts";
import { hasUnsafeCharacters } from "../core/text.ts";

const HELP = `Run Preflight standalone source-prefix CLI (core 1.0.0; protocol 1).
Usage: bun <selected-prefix>/helpers/cli.ts check --config PATH --declaration PATH
       bun <selected-prefix>/helpers/cli.ts admit --config PATH --declaration PATH --record PATH --invocation PATH
       bun <selected-prefix>/helpers/cli.ts probe --config PATH --declaration PATH
Optional: --format json|text (default json). All paths are explicit absolute JSON files.
The config selects this exact package root/helper, a project root, frozen contract,
and a trusted versioned bridge argv. No registered package or Armory checkout fallback.
check: read-only observations; no managed child, quota/auth probe or provider call.
admit: reobserve all prerequisites, consume a complete record and actual invocation.
probe: explicit SYNTHETIC-LOCAL-ONLY project bridge, bounded to 30s / 64KiB output;
       one harmless local child can yield terminal-receipt-unavailable, never a model receipt.
Unknown quota remains unknown; synthetic authority is not authenticated account authority.
No spend/call/worker/concurrency counter or universal bypass guard; existing study holds remain.
Exit 0: valid normalized report (inspect status/admitted, never a readiness boolean).
Exit 2: invalid input/observation/bridge failure. Exit 130/143: cancelled.
`;
interface Arguments {
  readonly action: "check" | "admit" | "probe";
  readonly config: string;
  readonly declaration: string;
  readonly record: string | null;
  readonly invocation: string | null;
  readonly format: "json" | "text";
}
function argumentsFor(args: readonly string[]): Arguments {
  const action = args[0];
  if (action !== "check" && action !== "admit" && action !== "probe") throw new Error("invalid action");
  const allowed = new Set(["--config", "--declaration", "--format"]);
  if (action === "admit") { allowed.add("--record"); allowed.add("--invocation"); }
  const values = new Map<string, string>();
  for (let index = 1; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (key === undefined || !allowed.has(key) || values.has(key) || value === undefined || value.length === 0 || value.length > 4096 || value.startsWith("--") || hasUnsafeCharacters(value)) throw new Error("invalid arguments");
    values.set(key, value);
  }
  const required = (key: string): string => {
    const value = values.get(key);
    if (value === undefined || !value.startsWith("/")) throw new Error("missing absolute path");
    return value;
  };
  const format = values.get("--format") ?? "json";
  if (format !== "json" && format !== "text") throw new Error("invalid format");
  return { action, config: required("--config"), declaration: required("--declaration"), record: action === "admit" ? required("--record") : null, invocation: action === "admit" ? required("--invocation") : null, format };
}
export async function main(args: readonly string[]): Promise<number> {
  if (args.length === 1 && (args[0] === "--help" || args[0] === "-h")) { process.stdout.write(HELP); return 0; }
  let options: Arguments;
  try { options = argumentsFor(args); } catch {
    const response = args[0] === "probe" ? { ...refusal(["invalid-arguments"]), probe: null } : refusal(["invalid-arguments"]);
    process.stdout.write(`${JSON.stringify(response)}\n`);
    return 2;
  }
  const controller = new AbortController();
  let cancellationCode = 0;
  const interrupt = (): void => { cancellationCode = 130; controller.abort(); };
  const terminate = (): void => { cancellationCode = 143; controller.abort(); };
  process.once("SIGINT", interrupt);
  process.once("SIGTERM", terminate);
  let response: Response | ProbeResponse;
  let exitCode = 0;
  try {
    if (options.action === "admit") {
      // Read untrusted record/invocation before taking the final state observation.
      if (options.record === null || options.invocation === null) throw new Error("missing admission paths");
      const record = await readSelected(options.record, true);
      const invocation = await readSelected(options.invocation, true);
      const current = await observe(options.config, options.declaration, import.meta.path);
      response = admit(current, record.document, invocation.document, Date.now(), sha256);
    } else {
      const observation = await observe(options.config, options.declaration, import.meta.path);
      if (controller.signal.aborted) return cancellationCode;
      response = check(observation, Date.now(), sha256);
      if (options.action === "probe") {
        if (observation.declaration.purpose !== "synthetic-local-sentinel" || response.admission === null) {
          response = { ...refusal(["probe-requires-bounded-synthetic-admission"]), quota: response.quota, probe: null };
        } else {
          const execution = await runBridge(observation.config, options.config, options.declaration, controller.signal);
          if (execution.result === null) {
            response = { ...refusal([execution.reason ?? "bridge-failed"]), quota: response.quota, probe: null };
            exitCode = 2;
          } else if (execution.result.status === "blocked") {
            response = { ...refusal(["bridge-admission-refused"]), quota: response.quota, probe: execution.result };
          } else {
            response = { ...response, reasons: [...response.reasons, "terminal-receipt-unavailable"], probe: execution.result };
          }
        }
      }
    }
    if (controller.signal.aborted) return cancellationCode;
  } catch {
    const failure = refusal(["prerequisites-unavailable-malformed-or-changed"]);
    response = options.action === "probe" ? { ...failure, probe: null } : failure;
    exitCode = 2;
  } finally {
    process.off("SIGINT", interrupt);
    process.off("SIGTERM", terminate);
  }
  process.stdout.write(options.format === "json" ? `${JSON.stringify(response)}\n` : `${renderPreflight(response)}\n`);
  return exitCode;
}
if (import.meta.main) process.exitCode = await main(process.argv.slice(2));

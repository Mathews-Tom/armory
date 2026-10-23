import { deriveRadar, renderRadar, validateSelection } from "../core/index.ts";
import type { Selection } from "../core/types.ts";
import { observe } from "./github.ts";

const HELP = `Delivery Radar standalone CLI.
Usage: bun extensions/delivery-radar/helpers/cli.ts refresh --repo <owner/name> --prs <n,n,...> [--format json|text]
  refresh              Explicit bounded read of only the selected repository and PRs.
  --repo owner/name    Required GitHub repository; uses existing gh read authentication.
  --prs n,n,...        Required unique positive PR numbers, at most 20.
  --format json|text   Default json: original observations plus the derived view.
No daemon, timer, model turn, GitHub mutation or persistent installation.
Unknown/partial/stale evidence is not success. Published artifacts are not inferred
from a merged PR or a successful workflow. Exit 0 means observation completed,
not merge readiness; exit 2 means invalid input/failure; 130/143 mean cancellation.
`;

interface Arguments {
  selection: Selection;
  format: "json" | "text";
}

function argumentsFor(args: readonly string[]): Arguments {
  if (args[0] !== "refresh") throw new Error("expected refresh");
  const values = new Map<string, string>();
  const allowed = new Set(["--repo", "--prs", "--format"]);
  for (let index = 1; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (key === undefined || !allowed.has(key) || values.has(key) || value === undefined || value.length === 0 || value.length > 4096 || value.startsWith("--")) {
      throw new Error("invalid or repeated argument");
    }
    values.set(key, value);
  }
  const repository = values.get("--repo");
  const numbers = values.get("--prs");
  if (repository === undefined || numbers === undefined || !/^[1-9][0-9]*(,[1-9][0-9]*)*$/.test(numbers)) {
    throw new Error("explicit repository and PR selection required");
  }
  const format = values.get("--format") ?? "json";
  if (format !== "json" && format !== "text") throw new Error("invalid output format");
  const selection = validateSelection({ repository, pullRequests: numbers.split(",").map(Number) });
  return { selection, format };
}

export async function main(args: readonly string[]): Promise<number> {
  if (args.length === 1 && (args[0] === "--help" || args[0] === "-h")) {
    process.stdout.write(HELP);
    return 0;
  }
  let options: Arguments;
  try {
    options = argumentsFor(args);
  } catch {
    process.stderr.write("delivery-radar: invalid arguments; use --help\n");
    return 2;
  }
  const controller = new AbortController();
  let cancellationCode = 0;
  const interrupt = (): void => { cancellationCode = 130; controller.abort(); };
  const terminate = (): void => { cancellationCode = 143; controller.abort(); };
  process.once("SIGINT", interrupt);
  process.once("SIGTERM", terminate);
  try {
    const observation = await observe(options.selection, { signal: controller.signal });
    if (controller.signal.aborted) return cancellationCode;
    const view = deriveRadar(observation, Date.now());
    process.stdout.write(options.format === "json"
      ? `${JSON.stringify({ observation, view })}\n`
      : `${renderRadar(view)}\n`);
    return 0;
  } catch {
    if (controller.signal.aborted) return cancellationCode;
    process.stderr.write("delivery-radar: observation failed; no readiness result\n");
    return 2;
  } finally {
    process.off("SIGINT", interrupt);
    process.off("SIGTERM", terminate);
  }
}

process.exitCode = await main(process.argv.slice(2));

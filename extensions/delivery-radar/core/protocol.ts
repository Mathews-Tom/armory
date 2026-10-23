import { deriveRadar } from "./derive.ts";
import type { Observation, RadarView, Selection } from "./types.ts";
import { record, validateSelection } from "./validation.ts";

export const COMMAND = "armory-delivery";
export const COMMAND_DESCRIPTION = "Read selected PR delivery evidence without remote actions";
export const ARGUMENT_HINT = "refresh <owner/repo> <n,n,...> [--json] | help";
export const MAX_HELPER_BYTES = 2 * 1024 * 1024;
export const HELP = `Delivery Radar: selected GitHub.com evidence, no remote actions.\n/armory-delivery refresh <owner/repo> <n,n,...> [--json]\n/armory-delivery help\nSelect 1–20 unique PR numbers explicitly. Existing gh authentication is used.\nImplementation, verification, review, merge and publication remain independent.\nUnknown is not readiness. Each command refreshes once; there is no background timer.\n`;

export type DeliveryCommand = { action: "help" } | { action: "refresh"; selection: Selection; json: boolean };
export type Failure = "invalid-arguments" | "operation-failed" | "cancelled" | "context-changed" | "session-unavailable";

/** An unsuccessful owned gh-group cleanup is not ordinary unavailable evidence. */
export function cleanupUnconfirmed(value: unknown): boolean {
  if (!record(value)) return false;
  const failed = (source: unknown): boolean => record(source) && source.diagnostic === "github-process-cleanup-unconfirmed";
  if (failed(value.viewerBefore) || failed(value.viewerAfter)) return true;
  return Array.isArray(value.pulls) && value.pulls.some((pull: unknown) => record(pull) &&
    ["before", "after", "reviews", "threads", "checks", "policy", "publication"].some((name) => failed(pull[name])));
}

/** Literal tokens only; no shell, repository inference or account selection. */
export function parseCommand(args: string): DeliveryCommand {
  if (args.length > 8192) throw new Error("arguments too long");
  const tokens = args.trim().split(/\s+/u).filter((token) => token.length > 0);
  if (tokens.length === 1 && (tokens[0] === "help" || tokens[0] === "--help")) return { action: "help" };
  const [action, repository, numbers, option] = tokens;
  if (action !== "refresh" || repository === undefined || numbers === undefined || !/^[1-9][0-9]*(,[1-9][0-9]*)*$/u.test(numbers)
    || (tokens.length !== 3 && !(tokens.length === 4 && option === "--json"))) throw new Error("explicit repository and PR selection required");
  return { action: "refresh", selection: validateSelection({ repository, pullRequests: numbers.split(",").map(Number) }), json: option === "--json" };
}

/** Re-derive from guarded source data; never trust the helper's claimed view. */
export function parseHelperAnswer(value: unknown, expected: Selection, now: number): RadarView {
  if (!record(value) || !record(value.observation)) throw new Error("helper observation missing");
  const selected = validateSelection(value.observation.selection);
  if (selected.repository !== expected.repository || selected.pullRequests.length !== expected.pullRequests.length
    || selected.pullRequests.some((number, index) => number !== expected.pullRequests[index])) throw new Error("helper selection changed");
  // deriveRadar validates schema, chronology and every source/value/binding before
  // using it. Malformed or unavailable nested evidence yields unknown, not green.
  return deriveRadar(value.observation as unknown as Observation, now);
}

/** Keep machine output inert in host-owned command text, including bidi controls. */
export function asciiJson(value: unknown): string {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

export function renderFailure(error: Failure, json = false): string {
  return json ? `${asciiJson({ error })}\n` : `Delivery Radar: ${error}; no readiness result.\n`;
}

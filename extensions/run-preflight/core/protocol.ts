import { CORE_VERSION, SCHEMA_VERSION } from "./types.ts";
import type { BridgeResult, ProbeResponse, Response } from "./types.ts";
import { freeze, parseProbeResponse, parseResponse, ValidationError } from "./validation.ts";
import { inert, renderPreflight } from "./render.ts";
import { parseTimestamp } from "./timestamp.ts";
import { hasUnsafeCharacters } from "./text.ts";

export const COMMAND = "armory-preflight";
export const COMMAND_DESCRIPTION = "Check explicitly declared managed-run prerequisites without a provider call";
export const ARGUMENT_HINT = 'check|probe {"config":"/absolute/project.json","declaration":"/absolute/declaration.json"} [--json] | help';
export const MAX_HELPER_BYTES = 2 * 1024 * 1024;
export const HELPER_TIMEOUT_MS = 65_000;
export const HELP = `Run Preflight: explicit local prerequisites, not campaign approval.
/armory-preflight check {"config":"/absolute/project.json","declaration":"/absolute/declaration.json"} [--json]
/armory-preflight probe {"config":"/absolute/project.json","declaration":"/absolute/declaration.json"} [--json]
/armory-preflight help
Select exactly two canonical absolute JSON paths; JSON strings support spaces.
check is read-only. probe explicitly invokes only bounded SYNTHETIC-LOCAL-ONLY authority.
Unknown quota is not capacity. No account query, hosted model call or native admit command.
The selected config must name this installed package and helpers/cli.js.
Project bridge code remains trusted. Existing runner limits and live-study holds remain.
Native output projects nonsecret observations, never the complete admission record.
There is no spend guard, signed/single-use authority, sandbox or protection of arbitrary bypasses.
`;

export interface Selection {
  readonly config: string;
  readonly declaration: string;
}
export type PreflightCommand = { readonly action: "help" } | {
  readonly action: "check" | "probe";
  readonly selection: Selection;
  readonly json: boolean;
};
export type RunCommand = Exclude<PreflightCommand, { action: "help" }>;
export type Failure = "invalid-arguments" | "operation-failed" | "cancelled" | "context-changed" | "session-unavailable";
export type HelperAnswer = Response | ProbeResponse;
export interface NativeView {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly coreVersion: typeof CORE_VERSION;
  readonly selection: Selection;
  readonly status: Response["status"];
  readonly reasons: readonly string[];
  readonly quota: { readonly status: "observed" | "unknown"; readonly observedAt: string; readonly expiresAt: string } | null;
  readonly run: { readonly id: string; readonly purpose: "synthetic-local-sentinel" | "managed"; readonly provider: string; readonly identityKind: "synthetic-local" | "managed"; readonly profile: string; readonly cell: string; readonly expiresAt: string } | null;
  readonly admitted: false;
  readonly probe: BridgeResult | null;
  readonly limitations: readonly string[];
}

function absolute(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length < 2 || value.length > 4096 || hasUnsafeCharacters(value)
    || !value.startsWith("/") || value.includes("//") || value.endsWith("/")
    || value.split("/").some((part) => part === "." || part === "..")) throw new ValidationError();
}
export function requestsJson(args: string): boolean { return /\s--json\s*$/u.test(args); }

/** JSON is data, not shell syntax; no cwd, checkout or account inference. */
export function parseCommand(args: string): PreflightCommand {
  if (args.length > 16_384) throw new ValidationError();
  const text = args.trim();
  if (text === "help" || text === "--help") return { action: "help" };
  const match = /^(check|probe)\s+([\s\S]+)$/u.exec(text);
  if (match === null) throw new ValidationError();
  const action = match[1];
  let document = match[2];
  if ((action !== "check" && action !== "probe") || document === undefined) throw new ValidationError();
  const json = requestsJson(text);
  if (json) document = document.replace(/\s--json\s*$/u, "");
  let selected: unknown;
  try { selected = JSON.parse(document); } catch { throw new ValidationError(); }
  if (selected === null || typeof selected !== "object" || Array.isArray(selected)) throw new ValidationError();
  const object = selected as Record<string, unknown>;
  const keys = Object.keys(object);
  if (keys.length !== 2 || !keys.includes("config") || !keys.includes("declaration")) throw new ValidationError();
  absolute(object.config);
  absolute(object.declaration);
  if (object.config === object.declaration) throw new ValidationError();
  return freeze({ action, selection: { config: object.config, declaration: object.declaration }, json });
}

/** Only the package's own built helper is executable; selection is literal argv. */
export function helperArgv(command: RunCommand, packageRoot: string): readonly string[] {
  absolute(packageRoot);
  return ["bun", `${packageRoot}/helpers/cli.js`, command.action, "--config", command.selection.config,
    "--declaration", command.selection.declaration, "--format", "json"];
}
function current(start: string, end: string, now: number): boolean {
  const issued = parseTimestamp(start);
  const expires = parseTimestamp(end);
  return issued !== null && expires !== null && issued <= now && now < expires;
}

/** Validate the trusted local helper's wire report before any host publication.
 * This is a freshness/selection boundary, not authentication or dispatch admission.
 */
export function parseHelperAnswer(value: unknown, command: RunCommand, packageRoot: string, now: number, exitCode: number): HelperAnswer {
  absolute(packageRoot);
  if (!Number.isSafeInteger(now) || now < 0 || (exitCode !== 0 && exitCode !== 2)) throw new ValidationError();
  const report = command.action === "probe" ? parseProbeResponse(value) : parseResponse(value);
  if (report.admitted || (exitCode === 2 && report.status !== "blocked")) throw new ValidationError();
  if (report.status !== "blocked" && (report.quota === null || !current(report.quota.observedAt, report.quota.expiresAt, now))) throw new ValidationError();
  const record = report.admission;
  if (record !== null) {
    if (!current(record.issuedAt, record.expiresAt, now)
      || !current(record.declaration.issuedAt, record.declaration.expiresAt, now)
      || !current(record.facts.identity.observedAt, record.facts.identity.expiresAt, now)
      || !current(record.scope.authorization.issuedAt, record.scope.authorization.expiresAt, now)
      || record.facts.config.path !== command.selection.config || record.facts.config.realPath !== command.selection.config
      || record.facts.declaration.path !== command.selection.declaration || record.facts.declaration.realPath !== command.selection.declaration
      || record.config.packageRoot !== packageRoot || record.config.helperPath !== "helpers/cli.js"
      || record.facts.packageRoot.path !== packageRoot || record.facts.packageRoot.realPath !== packageRoot
      || record.facts.helper.path !== `${packageRoot}/helpers/cli.js` || record.facts.helper.realPath !== `${packageRoot}/helpers/cli.js`) throw new ValidationError();
  }
  return report;
}

/** No declaration, bridge argv, account fingerprint, hashes, file facts or raw output. */
export function projectAnswer(report: HelperAnswer, selection: Selection): NativeView {
  const record = report.admission;
  return freeze({ schemaVersion: SCHEMA_VERSION, coreVersion: CORE_VERSION, selection: { ...selection },
    status: report.status, reasons: [...report.reasons],
    quota: report.quota === null ? null : { status: report.quota.status, observedAt: report.quota.observedAt, expiresAt: report.quota.expiresAt },
    run: record === null ? null : { id: record.scope.runId, purpose: record.scope.purpose,
      provider: record.facts.identity.provider, identityKind: record.facts.identity.kind,
      profile: record.scope.invocation.profile, cell: record.scope.invocation.cell.taskId, expiresAt: record.expiresAt },
    admitted: false, probe: "probe" in report ? report.probe : null,
    limitations: ["Selected invocation only; native output is not consumed admission, authenticated capacity or study approval.",
      "Existing runner owns timeouts; other caps are caller discipline or unsupported. No signed/single-use authority, spend guard or sandbox."],
  });
}
export function asciiJson(value: unknown): string {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
export function renderAnswer(report: HelperAnswer, view: NativeView, json: boolean): string {
  return json ? `${asciiJson(view)}\n`
    : `Selected config: ${inert(view.selection.config)}\nSelected declaration: ${inert(view.selection.declaration)}\n${view.run === null ? "" : `Declared provider: ${inert(view.run.provider)} (${view.run.identityKind}); not an account probe.\n`}${renderPreflight(report)}\n`;
}
export function renderFailure(error: Failure, json = false): string {
  return json ? `${asciiJson({ error })}\n` : `Run Preflight: ${error}; no readiness or admission result.\n`;
}

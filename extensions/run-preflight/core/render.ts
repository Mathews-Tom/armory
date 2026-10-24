import type { ProbeResponse, Response } from "./types.ts";

/** Escape every structural/control character; untrusted labels cannot create text rows. */
export function inert(value: string): string {
  return JSON.stringify(value).replace(/[^a-zA-Z0-9 _./:"\\-]/gu, (character) => [...character].map((part) => {
    const point = part.codePointAt(0) ?? 0;
    return point <= 0xffff ? `\\u${point.toString(16).padStart(4, "0")}` : `\\u{${point.toString(16)}}`;
  }).join(""));
}
/** Deterministic projection, never a dump of declarations, secrets or subprocess output. */
export function renderPreflight(report: Response | ProbeResponse): string {
  const lines = ["Run Preflight", `Status: ${report.status}`, `Managed admission consumed: ${report.admitted ? "yes" : "no"}`];
  if (report.quota === null) lines.push("Quota: unavailable");
  else {
    lines.push(`Quota: ${report.quota.status}`, `Quota observed: ${inert(report.quota.observedAt)}`, `Quota expires: ${inert(report.quota.expiresAt)}`);
    if (report.quota.status === "unknown") lines.push("Unknown quota is not capacity or account authority.");
  }
  if (report.admission !== null) {
    const scope = report.admission.scope;
    lines.push(`Run: ${inert(scope.runId)}`, `Purpose: ${scope.purpose}`, `Profile: ${inert(scope.invocation.profile)}`, `Cell: ${inert(scope.invocation.cell.taskId)}`, `Admission expires: ${inert(report.admission.expiresAt)}`);
  }
  for (const reason of report.reasons) lines.push(`Reason: ${inert(reason)}`);
  if ("probe" in report && report.probe !== null) {
    lines.push("Probe: SYNTHETIC-LOCAL-ONLY", `Terminal receipt: ${report.probe.status}`, `Managed local spawns: ${report.probe.managedSpawns}`, "Provider calls: 0");
  }
  lines.push("Scope: this invocation only; not signed or one-use authority, a spend guard, a sandbox, or study approval.", "Runner owns the 600-second max-time and 630-second outer timeout. Other caps are caller discipline or unsupported.");
  return lines.join("\n");
}

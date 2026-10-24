import { expect, test } from "claude-code/testing";

// Run with Claude Code 2.1.310's real command/stream test engine. Synthetic
// helper reports test SDK delivery, not authentication or real project dispatch;
// those belong to the separate opt-in actual-host driver.
const T = Date.parse("2026-10-24T12:00:00.000Z");
const selected = { config: "/selected project/config.json", declaration: "/selected project/declaration.json" };
const args = `check ${JSON.stringify(selected)} --json`;
function blocked() {
  return { schemaVersion: 1, coreVersion: "1.0.0", status: "blocked", reasons: ["identity-source-drift"], quota: null, admission: null, admitted: false };
}
function untilCancelled(signal: AbortSignal): Promise<undefined> {
  const completion = Promise.withResolvers<undefined>();
  if (signal.aborted) completion.resolve(undefined);
  else signal.addEventListener("abort", () => completion.resolve(undefined), { once: true });
  return completion.promise;
}

test("invalid selections, implicit probe and admit never reach the SDK process engine", async ($, on) => {
  let processes = 0;
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-preflight" } }));
  on("process.spawn", async function* () { processes++; yield { stream: "stderr", text: "must not execute" }; return { value: { code: 0, signal: null } }; });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  for (const value of ["probe", "", `admit ${JSON.stringify(selected)} --json`, 'check {"config":"relative","declaration":"/selected.json"} --json']) {
    expect((await $.command.run({ command: "armory-preflight", args: value })).text).toContain("invalid-arguments");
  }
  expect(processes).toBe(0);
});

test("real streamed exit2 may publish only a validated projected blocked report", async ($, on) => {
  on("session.id", () => ({ value: "kit-session" }));
  on("clock.now", () => ({ value: T }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-preflight" } }));
  on("process.spawn", async function* () {
    const payload = JSON.stringify(blocked());
    yield { stream: "stdout", text: payload.slice(0, 23) };
    yield { stream: "stderr", text: "PRIVATE-credential" };
    yield { stream: "stdout", text: payload.slice(23) };
    return { value: { code: 2, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const output = await $.command.run({ command: "armory-preflight", args });
  const view = JSON.parse(output.text ?? "");
  expect(view.selection).toEqual(selected); expect(view.status).toBe("blocked"); expect(view.admitted).toBe(false);
  expect(view.admission).toBeUndefined(); expect(output.text).not.toContain("PRIVATE-credential");
  expect(output.text).toContain("\\u0020");
});

test("actual nonzero and signalled stream results cannot be replaced by iterator return values", async ($, on) => {
  let code: number | null = 1;
  let signal: string | null = null;
  on("session.id", () => ({ value: "kit-session" }));
  on("clock.now", () => ({ value: T }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-preflight" } }));
  on("process.spawn", async function* () { yield { stream: "stdout", text: JSON.stringify(blocked()) }; return { value: { code, signal } }; });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  expect(JSON.parse((await $.command.run({ command: "armory-preflight", args })).text ?? "")).toEqual({ error: "operation-failed" });
  code = 0; signal = "SIGTERM";
  expect(JSON.parse((await $.command.run({ command: "armory-preflight", args })).text ?? "")).toEqual({ error: "operation-failed" });
});

test("clock freshness is enforced by the native consumer even on a successful process", async ($, on) => {
  on("session.id", () => ({ value: "kit-session" }));
  on("clock.now", () => ({ value: T }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-preflight" } }));
  on("process.spawn", async function* () {
    yield { stream: "stdout", text: JSON.stringify({ ...blocked(), status: "unknown", quota: { status: "unknown", observedAt: "2026-10-24T10:00:00.000Z", expiresAt: "2026-10-24T11:00:00.000Z", reason: "unobserved", source: "synthetic", remainingCalls: null } }) };
    return { value: { code: 0, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  expect(JSON.parse((await $.command.run({ command: "armory-preflight", args })).text ?? "")).toEqual({ error: "operation-failed" });
});

test("session change after helper completion suppresses native publication", async ($, on) => {
  let session = "kit-original";
  on("session.id", () => ({ value: session }));
  on("clock.now", () => ({ value: T }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-preflight" } }));
  on("process.spawn", async function* () { yield { stream: "stdout", text: JSON.stringify(blocked()) }; session = "kit-new"; return { value: { code: 2, signal: null } }; });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  expect(JSON.parse((await $.command.run({ command: "armory-preflight", args })).text ?? "")).toEqual({ error: "context-changed" });
});

test("actual SDK session disposal cancels in-flight stream before a subsequent session command", async ($, on) => {
  let session = "kit-original";
  let first = true;
  let cleaned = false;
  const entered = Promise.withResolvers<undefined>();
  on("session.id", () => ({ value: session }));
  on("clock.now", () => ({ value: T }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("session.end", (_$, event) => ({ sessionId: event.sessionId }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-preflight" } }));
  on("process.spawn", async function* (_$, _event, next) {
    if (first) {
      first = false;
      entered.resolve(undefined);
      try { await untilCancelled(next.signal); } finally { cleaned = true; }
    }
    yield { stream: "stdout", text: JSON.stringify(blocked()) };
    return { value: { code: 2, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const running = $.command.run({ command: "armory-preflight", args });
  await entered.promise;
  await $.session.end({ reason: "clear", sessionId: session, resume: { id: session } });
  expect(JSON.parse((await running).text ?? "")).toEqual({ error: "context-changed" });
  expect(cleaned).toBe(true);
  session = "kit-new";
  expect(JSON.parse((await $.command.run({ command: "armory-preflight", args })).text ?? "").status).toBe("blocked");
});

import { expect, test } from "claude-code/testing";
import type { Observation } from "../../core/index.ts";

// These cases run the actual pinned command/stream engine with synthetic source
// data beneath it. They do not qualify a signed-in host, GitHub or descendant
// process cleanup; the native read-only journey establishes those separately.
const T = 1_000_000;
function observation(viewer = "kit-viewer", at = T): Observation {
  return {
    schema: "armory.delivery-radar.observation/v1", selection: { repository: "owner/project", pullRequests: [7, 2] }, startedAt: at, finishedAt: at,
    viewerBefore: { status: "available", binding: null, observedAt: at, reference: "https://api.github.com/user", diagnostic: null, value: viewer },
    viewerAfter: { status: "available", binding: null, observedAt: at, reference: "https://api.github.com/user", diagnostic: null, value: viewer },
    pulls: [],
  };
}

function untilCancelled(signal: AbortSignal): Promise<undefined> {
  const completion = Promise.withResolvers<undefined>();
  if (signal.aborted) completion.resolve(undefined);
  else signal.addEventListener("abort", () => completion.resolve(undefined), { once: true });
  return completion.promise;
}

test("invalid explicit selections cannot dispatch helper work", async ($, on) => {
  let processes = 0;
  on("session.id", () => ({ value: "kit-session" }));
  on("clock.now", () => ({ value: T + 100 }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-delivery" } }));
  on("process.spawn", async function* () {
    processes++;
    yield { stream: "stderr", text: "invalid selection must never reach this helper" };
    return { value: { code: 0, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  for (const args of ["refresh owner/project 7,7", "refresh owner/project 7 --merge", "refresh owner/project 7 --json --watch"]) {
    const result = await $.command.run({ command: "armory-delivery", args });
    expect(result.text).toContain("invalid-arguments");
  }
  expect(processes).toBe(0);
});

test("streamed claimed readiness is re-derived into the actual unknown selected dimensions", async ($, on) => {
  on("session.id", () => ({ value: "kit-session" }));
  on("clock.now", () => ({ value: T + 100 }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-delivery" } }));
  on("process.spawn", async function* () {
    const value = JSON.stringify({ observation: observation(), view: { allReady: true, repository: "private/secret" }, credential: "PRIVATE-SECRET" });
    yield { stream: "stdout", text: value.slice(0, 19) };
    yield { stream: "stderr", text: "PRIVATE-SECRET" };
    yield { stream: "stdout", text: value.slice(19) };
    return { value: { code: 0, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const result = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  const answer = JSON.parse(result.text ?? "");
  expect(answer.view.repository).toBe("owner/project");
  expect(answer.view.pulls.map((pull: { number: number }) => pull.number)).toEqual([7, 2]);
  expect(answer.view.pulls.map((pull: { implementation: { state: string }; verification: { state: string }; review: { state: string }; merge: { state: string }; publication: { state: string } }) =>
    [pull.implementation.state, pull.verification.state, pull.review.state, pull.merge.state, pull.publication.state])).toEqual([
      ["unknown", "unknown", "unknown", "unknown", "unknown"], ["unknown", "unknown", "unknown", "unknown", "unknown"],
    ]);
  expect(answer.transition).toBe(false);
  expect(result.text).not.toContain("PRIVATE-SECRET");
  expect(result.text).not.toContain("private/secret");
});

test("a valid source payload is not a successful refresh before a zero unsignalled process exit", async ($, on) => {
  let code: number | null = 2;
  let signal: string | null = null;
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-delivery" } }));
  on("clock.now", () => ({ value: T + 100 }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("process.spawn", async function* () {
    yield { stream: "stdout", text: JSON.stringify({ observation: observation() }) };
    return { value: { code, signal } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const failed = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(failed.text ?? "")).toEqual({ error: "operation-failed" });
  code = null; signal = "SIGTERM";
  const killed = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(killed.text ?? "")).toEqual({ error: "operation-failed" });
});

test("a changed host session cannot receive a completed observation", async ($, on) => {
  let session = "kit-original";
  on("session.id", () => ({ value: session }));
  on("clock.now", () => ({ value: T + 100 }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-delivery" } }));
  on("process.spawn", async function* () {
    yield { stream: "stdout", text: JSON.stringify({ observation: observation() }) };
    session = "kit-replaced";
    return { value: { code: 0, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const result = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(result.text ?? "")).toEqual({ error: "context-changed" });
});

test("semantic transitions deduplicate independently of sample timestamps and reset for another session", async ($, on) => {
  let viewer = "kit-viewer-a";
  let session = "kit-session-a";
  let at = T;
  on("clock.now", () => ({ value: at + 100 }));
  on("clock.after", async (_$, _event, next) => { await untilCancelled(next.signal); return { value: undefined }; });
  on("session.id", () => ({ value: session }));
  on("session.start", (_$, event) => ({ cwd: event.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", () => ({ value: { command: "armory-delivery" } }));
  on("process.spawn", async function* () {
    yield { stream: "stdout", text: JSON.stringify({ observation: observation(viewer, at) }) };
    return { value: { code: 0, signal: null } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const baseline = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(baseline.text ?? "").transition).toBe(false);
  at += 100;
  const repeated = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(repeated.text ?? "").transition).toBe(false);
  viewer = "kit-viewer-b";
  const changed = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  const answer = JSON.parse(changed.text ?? "");
  expect(answer.transition).toBe(true);
  expect(answer.view.viewerId).toBe("kit-viewer-b");
  const same = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(same.text ?? "").transition).toBe(false);
  session = "kit-session-b";
  const fresh = await $.command.run({ command: "armory-delivery", args: "refresh owner/project 7,2 --json" });
  expect(JSON.parse(fresh.text ?? "").transition).toBe(false);
});

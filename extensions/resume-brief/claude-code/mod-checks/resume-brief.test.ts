import { expect, mock, test } from "claude-code/testing";

// Native-kit boundary tests deliberately provide the effects beneath the mod;
// real helper/Git/state behavior is covered by tests/claude.test.ts. The kit
// does not start a signed-in session and does not establish live compatibility.

const ENV = {
  ARMORY_BRIEF_REPO: "/synthetic", ARMORY_BRIEF_DATA_ROOT: "/synthetic-private",
  ARMORY_BRIEF_ACCOUNT: "kit-account", ARMORY_BRIEF_CONTEXT: "brief.json",
};
const ANSWER = { action: "list", snapshots: [] };


test("missing explicit account selection fails closed before any helper process", async ($, on) => {
  mock.env(on, { ARMORY_BRIEF_REPO: "/synthetic", ARMORY_BRIEF_DATA_ROOT: "/synthetic-private" });
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const answer = await $.command.run({ command: "armory-brief", args: "list --json" });
  expect(JSON.parse(answer.text ?? "")).toMatchObject({ error: "invalid-configuration" });
});


test("unsafe or truncated helper output is refused without exposing private fields", async ($, on) => {
  mock.env(on, ENV);
  let stdout = JSON.stringify({ ...ANSWER, privatePath: "/PRIVATE-SECRET" });
  let truncated = false;
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  on("process.run", () => ({ value: { exitCode: 0, stdout, stderr: "PRIVATE-SECRET", isStdoutTruncated: truncated, isStderrTruncated: false } }));
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const unsafe = await $.command.run({ command: "armory-brief", args: "list --json" });
  expect(JSON.parse(unsafe.text ?? "")).toEqual({ error: "operation-failed", detail: null });
  expect(unsafe.text).not.toContain("PRIVATE-SECRET");
  stdout = JSON.stringify(ANSWER);
  truncated = true;
  const cut = await $.command.run({ command: "armory-brief", args: "list --json" });
  expect(JSON.parse(cut.text ?? "")).toEqual({ error: "operation-failed", detail: null });
});

test("a session end during the helper run suppresses its answer", async ($, on) => {
  mock.env(on, ENV);
  let session = "kit-original";
  const entered = Promise.withResolvers<undefined>();
  const release = Promise.withResolvers<undefined>();
  on("session.id", () => ({ value: session }));
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("session.end", (_$, e) => ({ sessionId: e.sessionId }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  on("process.run", async () => {
    entered.resolve(undefined); await release.promise;
    return { value: { exitCode: 0, stdout: JSON.stringify(ANSWER), stderr: "", isStdoutTruncated: false, isStderrTruncated: false } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const reading = $.command.run({ command: "armory-brief", args: "list --json" });
  await entered.promise;
  // No session.start follows a real /clear. Test the same lifetime boundary.
  const ending = $.session.end({ reason: "clear", sessionId: session, resume: { id: session } });
  session = "kit-cleared"; release.resolve(undefined); await ending;
  const answer = await reading;
  expect(JSON.parse(answer.text ?? "")).toEqual({ error: "context-changed", detail: null });
});

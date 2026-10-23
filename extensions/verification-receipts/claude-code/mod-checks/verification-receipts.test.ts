import { expect, mock, test } from "claude-code/testing";

// Native-kit boundary tests deliberately provide the effects beneath the mod;
// real helper/process/store behavior is covered by tests/claude.test.ts. The kit
// does not implicitly start a session and does not establish live compatibility.

test("invalid gate text cannot become a process or model operation", async ($, on) => {
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const invalid = await $.command.run({ command: "armory-verify", args: "check; touch /unsafe" });
  expect(invalid.text).toBe('{"error":"invalid-arguments"}');
  const unknown = await $.command.run({ command: "armory-evidence", args: "all --raw" });
  expect(unknown.text).toBe('{"error":"invalid-arguments"}');
});

test("missing explicit account selection fails closed without process effects", async ($, on) => {
  mock.env(on, {
    ARMORY_RECEIPTS_REPO: "/synthetic", ARMORY_RECEIPTS_CONFIG: "receipts.json",
    ARMORY_RECEIPTS_DATA_ROOT: "/synthetic-private", ARMORY_RECEIPTS_WORK_CONTEXT: "kit-work",
  });
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const answer = await $.command.run({ command: "armory-verify", args: "check" });
  expect(answer.text).toBe('{"error":"operation-failed"}');
});

test("unsafe persisted projection is refused without exposing private fields", async ($, on) => {
  mock.env(on, {
    ARMORY_RECEIPTS_REPO: "/synthetic", ARMORY_RECEIPTS_CONFIG: "receipts.json",
    ARMORY_RECEIPTS_DATA_ROOT: "/synthetic-private", ARMORY_RECEIPTS_ACCOUNT: "kit-account",
    ARMORY_RECEIPTS_WORK_CONTEXT: "kit-work",
  });
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  on("process.run", () => ({ value: {
    exitCode: 0, stdout: JSON.stringify({ receipts: [], privatePath: "/PRIVATE-SECRET" }),
    stderr: "PRIVATE-SECRET", isStdoutTruncated: false, isStderrTruncated: false,
  } }));
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const answer = await $.command.run({ command: "armory-evidence", args: "" });
  expect(answer.text).toBe('{"error":"operation-failed"}');
});

test("truncated observations cannot masquerade as empty current evidence", async ($, on) => {
  mock.env(on, {
    ARMORY_RECEIPTS_REPO: "/synthetic", ARMORY_RECEIPTS_CONFIG: "receipts.json",
    ARMORY_RECEIPTS_DATA_ROOT: "/synthetic-private", ARMORY_RECEIPTS_ACCOUNT: "kit-account",
    ARMORY_RECEIPTS_WORK_CONTEXT: "kit-work",
  });
  on("session.id", () => ({ value: "kit-session" }));
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("command.list", () => ({ value: [] }));
  on("command.register", (_$, e) => ({ value: { command: e.name } }));
  on("process.run", () => ({ value: {
    exitCode: 0, stdout: '{"receipts":[]}', stderr: "PRIVATE-SECRET",
    isStdoutTruncated: true, isStderrTruncated: false,
  } }));
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const answer = await $.command.run({ command: "armory-evidence", args: "" });
  expect(answer.text).toBe('{"error":"operation-failed"}');
});

test("clear revokes an evidence read without registering commands in the new session", async ($, on) => {
  mock.env(on, {
    ARMORY_RECEIPTS_REPO: "/synthetic", ARMORY_RECEIPTS_CONFIG: "receipts.json",
    ARMORY_RECEIPTS_DATA_ROOT: "/synthetic-private", ARMORY_RECEIPTS_ACCOUNT: "kit-account",
    ARMORY_RECEIPTS_WORK_CONTEXT: "kit-work",
  });
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
    return { value: { exitCode: 0, stdout: '{"receipts":[]}', stderr: "", isStdoutTruncated: false, isStderrTruncated: false } };
  });
  await $.session.start({ cwd: "/synthetic", surface: null, isInteractive: false });
  const reading = $.command.run({ command: "armory-evidence", args: "" });
  await entered.promise;
  // No session.start follows a real /clear. Test the same lifetime boundary.
  const ending = $.session.end({ reason: "clear", sessionId: session, resume: { id: session } });
  session = "kit-cleared"; release.resolve(undefined); await ending;
  expect((await reading).text).toBe('{"error":"context-changed"}');
});

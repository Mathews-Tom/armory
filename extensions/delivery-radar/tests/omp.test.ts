import { expect, test } from "bun:test";
import type { Subprocess } from "bun";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { SCHEMA } from "../core/index.ts";
import type { Binding, Check, Observation, PullIdentity, PullObservation, RadarView, RequiredPolicy, Review, Source, State } from "../core/index.ts";
import { COMMAND } from "../core/protocol.ts";
import { createDeliveryRadar } from "../omp/index.ts";
import type { observe } from "../helpers/github.ts";

const T = 1_000_000;
const HEAD = "a".repeat(40);
const BASE = "b".repeat(40);
const OTHER = "c".repeat(40);
const REPOSITORY = "owner/project";
type Observe = typeof observe;
type Registered = Parameters<ExtensionAPI["registerCommand"]>[1];
type Lifecycle = (event: { type: string }, ctx: ExtensionContext) => unknown;
interface Message {
  customType: string;
  content: string;
  display: boolean;
  details: { view?: RadarView; transition?: boolean; error?: string; help?: boolean; correlation?: { host: string; sessionId: string; cwd?: string } };
}

function fixture(options: { at?: number; numbers?: number[]; repository?: string; head?: string; base?: string; viewer?: string; failed?: boolean } = {}): Observation {
  const at = options.at ?? T;
  const repository = options.repository ?? REPOSITORY;
  const numbers = options.numbers ?? [7];
  const head = options.head ?? HEAD;
  const base = options.base ?? BASE;
  const viewer = options.viewer ?? "viewer-1";
  const source = <V>(value: V, reference: string, binding: Binding | null, observedAt = at + 20): Source<V> =>
    ({ status: "available", value, reference, binding, observedAt, diagnostic: null });
  const pulls: PullObservation[] = numbers.map((number) => {
    const identity: PullIdentity = { number, url: `https://github.com/${repository}/pull/${number}`, title: `Change ${number}`,
      state: "OPEN", headOid: head, baseOid: base, headRef: `feature-${number}`, baseRef: "main", headRepository: repository,
      draft: false, mergeable: "MERGEABLE", mergeCommitOid: null };
    const binding: Binding = { repository, pullRequest: number, headOid: head, baseOid: base, viewerId: viewer };
    const reference = `github:${repository}#${number}`;
    return {
      before: source({ ...identity }, `${reference}:before`, binding, at + 10),
      after: source({ ...identity }, `${reference}:after`, binding, at + 30),
      reviews: source<readonly Review[]>([{ id: "review-1", reviewerId: "reviewer-1", state: "APPROVED", commitOid: head, submittedAt: at }], `${reference}:reviews`, binding),
      threads: source([], `${reference}:threads`, binding),
      checks: source<readonly Check[]>([{ id: "check-1", context: "test", publisherId: 1, state: options.failed ? "failed" : "passed", headOid: head,
        testedBaseOid: base, completedAt: at, url: "https://github.com/check/1" }], `${reference}:checks`, binding),
      policy: source<RequiredPolicy>({ checks: [{ context: "test", publisherId: 1 }], requiredApprovals: 1, requireCodeOwnerReview: false,
        requireLatestApproval: false, dismissStaleReviews: true, strict: true, unsupported: [] }, `${reference}:policy`, binding),
      publication: { ...source(null, `${reference}:publication`, binding), status: "not-selected" },
    };
  });
  return { schema: SCHEMA, selection: { repository, pullRequests: numbers }, startedAt: at, finishedAt: at + 50,
    viewerBefore: source(viewer, "github:viewer:before", null, at), viewerAfter: source(viewer, "github:viewer:after", null, at + 40), pulls };
}

function harness(observeEffect: Observe, options: { cwd?: string; foreign?: { name: string; source: string; description?: string }[]; now?: number } = {}) {
  const commands = new Map<string, Registered>();
  const events = new Map<string, Lifecycle>();
  const messages: Message[] = [];
  const deliveries: unknown[] = [];
  let id = "session-A";
  const ctx = { ...(options.cwd === undefined ? {} : { cwd: options.cwd }), sessionManager: { getSessionId: () => id } } as unknown as ExtensionCommandContext;
  const api = {
    getCommands: () => [...(options.foreign ?? []), ...[...commands].map(([name, command]) => ({ name, description: command.description, source: "extension" }))],
    registerCommand: (name: string, command: Registered) => { commands.set(name, command); },
    on: (name: string, listener: Lifecycle) => { events.set(name, listener); },
    sendMessage: (message: Message, delivery: unknown) => { messages.push(message); deliveries.push(delivery); },
  };
  createDeliveryRadar({ observe: observeEffect, now: () => options.now ?? T + 5_000 })(api as unknown as ExtensionAPI);
  return {
    commands, messages, deliveries,
    async start() { await events.get("session_start")?.({ type: "session_start" }, ctx); },
    async run(args = "refresh owner/project 7 --json") {
      const registered = commands.get(COMMAND);
      if (registered === undefined) throw new Error("native command is unavailable");
      await registered.handler(args, ctx);
    },
    async switchTo(next: string) { id = next; await events.get("session_switch")?.({ type: "session_switch" }, ctx); },
    async shutdown() { await events.get("session_shutdown")?.({ type: "session_shutdown" }, ctx); },
    moveWithoutEvent(next: string) { id = next; },
  };
}

function answer(host: { messages: Message[] }): { view: RadarView; transition: boolean } {
  const value = host.messages[host.messages.length - 1]?.details;
  if (value?.view === undefined || typeof value.transition !== "boolean") throw new Error("a current derived response was not published");
  return { view: value.view, transition: value.transition };
}

function firstPull(value: Observation): PullObservation {
  const pull = value.pulls[0];
  if (pull === undefined) throw new Error("fixture has no selected PR");
  return pull;
}

function states(view: RadarView): string[] {
  const pull = view.pulls[0];
  if (pull === undefined) throw new Error("response has no selected PR");
  return [pull.implementation.state, pull.verification.state, pull.review.state, pull.merge.state, pull.publication.state];
}

test("registers once across starts and refuses command collisions without observing", async () => {
  let reads = 0;
  const effect: Observe = async () => { reads++; return fixture(); };
  const host = harness(effect);
  await host.start();
  const registered = host.commands.get(COMMAND);
  await host.start();
  expect(host.commands.size).toBe(1);
  expect(host.commands.get(COMMAND)).toBe(registered);
  await host.run();
  expect(states(answer(host).view)).toEqual(["passed", "passed", "passed", "passed", "unknown"]);
  for (const source of ["prompt", "extension"]) {
    const foreign = harness(effect, { foreign: [{ name: COMMAND, source }] });
    await expect(foreign.start()).rejects.toThrow();
    expect(foreign.commands.size).toBe(0);
    expect(foreign.messages).toEqual([]);
  }
  expect(reads).toBe(1);
});

test("requires explicit valid selection and help has no provider or model effect", async () => {
  let reads = 0;
  const host = harness(async () => { reads++; return fixture(); }, { cwd: "/unrelated/worktree" });
  await host.start();
  for (const input of ["refresh", "refresh owner/project 7,7", "refresh owner/project 0", "refresh owner/project 7 --merge", "refresh owner/project;id 7", "refresh owner/project 7 --json extra"]) {
    await host.run(input);
    expect(host.messages[host.messages.length - 1]?.details.error).toBe("invalid-arguments");
  }
  await host.run("help");
  expect(host.messages[host.messages.length - 1]?.details.help).toBe(true);
  expect(reads).toBe(0);
  expect(host.deliveries.every((delivery) => JSON.stringify(delivery) === JSON.stringify({ triggerTurn: false }))).toBe(true);
});

test("renders all independent dimensions with actual host correlation, not cwd selection", async () => {
  const value = fixture();
  const checks = firstPull(value).checks.value?.[0];
  if (checks === undefined) throw new Error("fixture has no check");
  checks.testedBaseOid = null;
  const host = harness(async () => value, { cwd: "/worktrees/unrelated-repository" });
  await host.start();
  await host.run();
  expect(states(answer(host).view)).toEqual(["passed", "unknown", "passed", "unknown", "unknown"]);
  expect(answer(host).view.repository).toBe(REPOSITORY);
  expect(answer(host).view.viewerId).toBe("viewer-1");
  expect(answer(host).view.pulls[0]).toMatchObject({ headOid: HEAD, baseOid: BASE, action: "owner-decision" });
  expect(host.messages[0]?.details.correlation).toEqual({ host: "omp", sessionId: "session-A", cwd: "/worktrees/unrelated-repository" });
  expect(JSON.parse(host.messages[0]?.content ?? "")).toEqual(answer(host));
  expect(host.deliveries).toEqual([{ triggerTurn: false }]);
  const noCwd = harness(async () => fixture());
  await noCwd.start();
  await noCwd.run();
  expect(noCwd.messages[0]?.details.correlation).toEqual({ host: "omp", sessionId: "session-A" });
});

test("host clock, source visibility and identity drift prevent false-green native results", async () => {
  const cases: { value: Observation; now?: number; verification: State; review?: State }[] = [];
  const partial = fixture();
  firstPull(partial).checks.status = "partial";
  cases.push({ value: partial, verification: "unknown" });
  const oldBase = fixture();
  const oldBinding = firstPull(oldBase).checks.binding;
  if (oldBinding === null) throw new Error("fixture binding missing");
  firstPull(oldBase).checks.binding = { ...oldBinding, baseOid: OTHER };
  cases.push({ value: oldBase, verification: "unknown" });
  const viewer = fixture();
  viewer.viewerAfter.value = "viewer-2";
  cases.push({ value: viewer, verification: "unknown", review: "unknown" });
  cases.push({ value: fixture(), now: T + 400_000, verification: "unknown", review: "unknown" });
  for (const scenario of cases) {
    const host = harness(async () => scenario.value, { now: scenario.now });
    await host.start();
    await host.run();
    const pull = answer(host).view.pulls[0];
    expect(pull?.verification.state).toBe(scenario.verification);
    if (scenario.review !== undefined) expect(pull?.review.state).toBe(scenario.review);
    expect(pull?.merge.state).toBe("unknown");
    expect(pull?.publication.state).toBe("unknown");
  }
});

test("provider selection changes fail closed and errors never expose provider secrets", async () => {
  for (const value of [fixture({ repository: "other/project" }), fixture({ numbers: [8, 7] })]) {
    const host = harness(async () => value);
    await host.start();
    await host.run("refresh owner/project 7,8 --json");
    expect(JSON.parse(host.messages[0]?.content ?? "")).toEqual({ error: "operation-failed" });
    expect(host.messages[0]?.details.view).toBeUndefined();
  }
  const host = harness(async () => { throw new Error("provider token=private-auth-secret"); });
  await host.start();
  await host.run();
  expect(JSON.parse(host.messages[0]?.content ?? "")).toEqual({ error: "operation-failed" });
  expect(host.messages[0]?.details).toEqual({ error: "operation-failed", correlation: { host: "omp", sessionId: "session-A" } });
});

test("explicit replies continue while semantic notices deduplicate and reset per session", async () => {
  let value = fixture();
  const host = harness(async () => value);
  await host.start();
  await host.run();
  expect(answer(host).transition).toBe(false);
  value = fixture({ at: T + 1_000 });
  await host.run();
  expect(answer(host).transition).toBe(false);
  value = fixture({ failed: true });
  await host.run();
  expect(answer(host).transition).toBe(true);
  expect(answer(host).view.pulls[0]?.verification.state).toBe("failed");
  await host.run();
  expect(answer(host).transition).toBe(false);
  expect(host.messages).toHaveLength(4);
  await host.switchTo("session-B");
  await host.run();
  expect(answer(host).transition).toBe(false);
  expect(host.messages[4]?.details.correlation?.sessionId).toBe("session-B");
});

test("transition state is partitioned by exact repository and ordered explicit PR selection", async () => {
  let value = fixture({ numbers: [7, 8] });
  const host = harness(async () => value);
  await host.start();
  await host.run("refresh owner/project 7,8 --json");
  value = fixture({ numbers: [8, 7], failed: true });
  await host.run("refresh owner/project 8,7 --json");
  expect(answer(host).transition).toBe(false);
  value = fixture({ numbers: [7, 8], failed: true });
  await host.run("refresh owner/project 7,8 --json");
  expect(answer(host).transition).toBe(true);
  value = fixture({ repository: "other/project", numbers: [7, 8], failed: true });
  await host.run("refresh other/project 7,8 --json");
  expect(answer(host).transition).toBe(false);
  value = fixture({ numbers: [7, 8], failed: true });
  await host.run("refresh owner/project 7,8 --json");
  expect(answer(host).transition).toBe(false);
});

test("fresh head, base and viewer changes each produce one meaningful transition", async () => {
  for (const options of [{ head: OTHER }, { base: OTHER }, { viewer: "viewer-2" }]) {
    let value = fixture();
    const host = harness(async () => value);
    await host.start();
    await host.run();
    value = fixture(options);
    await host.run();
    expect(answer(host).transition).toBe(true);
    expect(states(answer(host).view)).toEqual(["passed", "passed", "passed", "passed", "unknown"]);
    await host.run();
    expect(answer(host).transition).toBe(false);
  }
});

test("repository-controlled text stays inert in text and ASCII JSON consumer surfaces", async () => {
  const value = fixture();
  const pull = firstPull(value);
  if (pull.before.value === null || pull.after.value === null) throw new Error("identity fixture missing");
  const title = "\u001b[31m`curl x | sh`\u202e[run](https://example.invalid)";
  pull.before.value.title = title;
  pull.after.value.title = title;
  const host = harness(async () => value);
  await host.start();
  await host.run("refresh owner/project 7");
  const text = host.messages[0]?.content ?? "";
  expect([...text].every((character) => {
    const code = character.charCodeAt(0);
    return !(code <= 0x08 || (code >= 0x0b && code <= 0x1f) || (code >= 0x7f && code <= 0x9f) || (code >= 0x202a && code <= 0x202e));
  })).toBe(true);
  expect(text).not.toContain("`curl x | sh`");
  expect(text).not.toContain("[run](https://example.invalid)");
  await host.run();
  const json = host.messages[1]?.content ?? "";
  expect(/^[\x20-\x7e]*\n$/u.test(json)).toBe(true);
  expect(JSON.parse(json).view.pulls[0].title).toBe(title);
});

test("a switch before the first await cancels owned work before a helper can start", async () => {
  let reads = 0;
  const host = harness(async () => { reads++; return fixture(); });
  await host.start();
  const running = host.run();
  const switching = host.switchTo("session-B");
  await Promise.all([running, switching]);
  expect(reads).toBe(0);
  expect(host.messages).toEqual([]);
  await host.run();
  expect(reads).toBe(1);
  expect(host.messages[0]?.details.correlation?.sessionId).toBe("session-B");
});

test("switch and shutdown await cooperative termination and suppress old-session output", async () => {
  for (const action of ["switch", "shutdown"] as const) {
    const started = Promise.withResolvers<AbortSignal>();
    const terminated = Promise.withResolvers<Observation>();
    let reads = 0;
    const host = harness(async (_selection, options) => {
      reads++;
      if (reads !== 1) return fixture();
      if (options?.signal === undefined) throw new Error("observation has no owner signal");
      started.resolve(options.signal);
      return await terminated.promise;
    });
    await host.start();
    const running = host.run();
    const signal = await started.promise;
    let settled = false;
    const changing = (action === "switch" ? host.switchTo("session-B") : host.shutdown()).then(() => { settled = true; });
    expect(signal.aborted).toBe(true);
    await Promise.resolve();
    expect(settled).toBe(false);
    terminated.resolve(fixture());
    await Promise.all([running, changing]);
    expect(host.messages).toEqual([]);
    await host.run();
    expect(reads).toBe(action === "switch" ? 2 : 1);
    if (action === "switch") expect(host.messages[0]?.details.correlation?.sessionId).toBe("session-B");
  }
});

test("superseding refreshes await previous termination and never start a cancelled queued refresh", async () => {
  const started = Promise.withResolvers<AbortSignal>();
  const terminated = Promise.withResolvers<Observation>();
  let reads = 0;
  const host = harness(async (_selection, options) => {
    reads++;
    if (reads !== 1) return fixture({ failed: true });
    if (options?.signal === undefined) throw new Error("observation has no owner signal");
    started.resolve(options.signal);
    return await terminated.promise;
  });
  await host.start();
  const first = host.run();
  const signal = await started.promise;
  const second = host.run();
  const third = host.run();
  expect(signal.aborted).toBe(true);
  await Promise.resolve();
  expect(reads).toBe(1);
  expect(host.messages).toEqual([]);
  terminated.resolve(fixture());
  await Promise.all([first, second, third]);
  expect(reads).toBe(2);
  expect(host.messages).toHaveLength(1);
  expect(answer(host).view.pulls[0]?.verification.state).toBe("failed");
  expect(answer(host).transition).toBe(false);
});

test("session identity is re-observed before publication even without a lifecycle callback", async () => {
  const started = Promise.withResolvers<undefined>();
  const complete = Promise.withResolvers<Observation>();
  const host = harness(async () => { started.resolve(undefined); return await complete.promise; });
  await host.start();
  const running = host.run();
  await started.promise;
  host.moveWithoutEvent("session-B");
  complete.resolve(fixture());
  await running;
  expect(host.messages).toEqual([]);
});

test("unconfirmed helper cleanup rejects cancellation, refuses new work and never reports a view", async () => {
  const started = Promise.withResolvers<undefined>();
  const complete = Promise.withResolvers<Observation>();
  let reads = 0;
  const host = harness(async () => { reads++; started.resolve(undefined); return await complete.promise; });
  await host.start();
  const running = host.run();
  await started.promise;
  const switching = host.switchTo("session-B");
  const results = Promise.allSettled([running, switching]);
  const value = fixture();
  firstPull(value).reviews.status = "unavailable";
  firstPull(value).reviews.diagnostic = "github-process-cleanup-unconfirmed";
  complete.resolve(value);
  expect((await results).map((result) => result.status)).toEqual(["rejected", "rejected"]);
  expect(host.messages).toEqual([]);
  await host.run();
  expect(reads).toBe(1);
  await expect(host.start()).rejects.toThrow();
});

// The production factory invokes its real feature-owned gh helper in a fresh
// process. Only that process gets the synthetic gh executable and isolated PATH.
// A provider-side handshake gates cancellation; no sleeps race process startup.
test("production factory transition awaits actual gh process-tree termination", async () => {
  const directory = await mkdtemp(join(tmpdir(), "armory-radar-omp-"));
  const root = Promise.withResolvers<number>();
  const descendant = Promise.withResolvers<number>();
  const pids: number[] = [];
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/ready") {
      await Promise.all([root.promise, descendant.promise]);
      return new Response("ready");
    }
    const body = await request.json() as { pid: number };
    if (!Number.isSafeInteger(body.pid) || body.pid <= 0) return new Response("invalid", { status: 400 });
    pids.push(body.pid);
    if (path === "/gh") root.resolve(body.pid);
    else if (path === "/descendant") descendant.resolve(body.pid);
    else return new Response("unknown", { status: 404 });
    return new Response("owned");
  } });
  const executable = join(directory, "gh");
  const driver = join(directory, "driver.ts");
  const adapter = fileURLToPath(new URL("../omp/index.ts", import.meta.url));
  let child: Subprocess<"ignore", "pipe", "pipe"> | undefined;
  let timer: Timer | undefined;
  const failures: unknown[] = [];
  try {
    await writeFile(executable, `#!${process.execPath}
import {spawn} from "node:child_process";
await fetch(process.env.RADAR_OMP_FIXTURE+"/gh",{method:"POST",body:JSON.stringify({pid:process.pid})});
process.on("SIGTERM",()=>{});
spawn(process.execPath,["-e",'await fetch(process.env.RADAR_OMP_FIXTURE+"/descendant",{method:"POST",body:JSON.stringify({pid:process.pid})});setInterval(()=>{},1000);'],{stdio:"ignore"});
setInterval(()=>{},1000);
`);
    await chmod(executable, 0o700);
    await writeFile(driver, `import delivery from ${JSON.stringify(adapter)};
const events=new Map();const commands=new Map();const messages=[];let id="session-A";
const ctx={sessionManager:{getSessionId:()=>id}};
const pi={on:(name,handler)=>events.set(name,handler),getCommands:()=>[...commands].map(([name,command])=>({name,description:command.description,source:"extension"})),registerCommand:(name,command)=>commands.set(name,command),sendMessage:(message)=>messages.push(message)};
delivery(pi);
await events.get("session_start")({type:"session_start"},ctx);
const running=commands.get("armory-delivery").handler("refresh owner/project 7 --json",ctx);
await fetch(process.env.RADAR_OMP_FIXTURE+"/ready");
id="session-B";
await events.get("session_switch")({type:"session_switch"},ctx);
await running;
await events.get("session_shutdown")({type:"session_shutdown"},ctx);
process.stdout.write(JSON.stringify({messages}));
`);
    child = Bun.spawn([process.execPath, driver], { env: { ...process.env, PATH: `${directory}:${process.env.PATH ?? ""}`, RADAR_OMP_FIXTURE: server.url.toString().replace(/\/$/u, "") },
      stdin: "ignore", stdout: "pipe", stderr: "pipe" });
    const expired = Promise.withResolvers<never>();
    // This deadline bounds real OS processes; fake timers cannot reap groups.
    timer = setTimeout(() => expired.reject(new Error("isolated native cancellation deadline exceeded")), 15_000);
    const result = await Promise.race([Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]), expired.promise]);
    expect(result[0]).toBe(0);
    expect(JSON.parse(result[1])).toEqual({ messages: [] });
    expect(pids).toHaveLength(2);
    for (const pid of pids) {
      let exists = true;
      try { process.kill(pid, 0); } catch (error) {
        if (error instanceof Error && "code" in error && error.code === "ESRCH") exists = false;
        else throw error;
      }
      expect(exists).toBe(false);
    }
  } catch (error) {
    failures.push(error);
  } finally {
    clearTimeout(timer);
    try {
      if (child !== undefined && child.exitCode === null) { child.kill("SIGKILL"); await child.exited; }
    } catch (error) { failures.push(error); }
    for (const pid of pids) {
      try { process.kill(-pid, "SIGKILL"); } catch (error) {
        if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) failures.push(error);
      }
    }
    try { server.stop(true); } catch (error) { failures.push(error); }
    try { await rm(directory, { recursive: true, force: true }); } catch (error) { failures.push(error); }
  }
  if (failures.length > 0) throw new AggregateError(failures, "native process-tree cancellation or cleanup failed");
}, 20_000);

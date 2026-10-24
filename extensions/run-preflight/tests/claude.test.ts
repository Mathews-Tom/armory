import { describe, expect, test } from "bun:test";
import { register } from "../claude-code/register.ts";
import type { Api, On, Stream } from "../claude-code/register.ts";
import { HELP, HELPER_TIMEOUT_MS, MAX_HELPER_BYTES } from "../core/protocol.ts";

interface Exit { code: number | null; signal: string | null }
interface Chunk { stream: "stdout" | "stderr"; text: string }
interface Plan {
  chunks?: Chunk[];
  exit?: Exit;
  hold?: boolean;
  closeFailure?: boolean;
  resultFailure?: boolean;
  resultGate?: Promise<unknown>;
  closeGate?: Promise<unknown>;
  onDone?: () => void;
}
interface Child { stream: Stream; readonly closed: boolean; readonly returns: number }
const ROOT = "/detached package/run-preflight";
const SELECTION = { config: "/selected project/project config.json", declaration: "/selected project/run declaration.json" };
const ARGS = `check ${JSON.stringify(SELECTION)} --json`;
const SECRET = "PRIVATE-provider-credential";
const T = Date.parse("2026-10-24T12:00:00.000Z");
function report(status: "unknown" | "blocked" = "unknown") {
  return { schemaVersion: 1, coreVersion: "1.0.0", status, reasons: status === "blocked" ? ["identity-source-drift"] : ["quota-unknown"],
    quota: status === "blocked" ? null : { status: "unknown", observedAt: "2026-10-24T11:59:00.000Z", expiresAt: "2026-10-24T12:05:00.000Z", reason: "no-provider-observation", source: "local declaration", remainingCalls: null },
    admission: null, admitted: false };
}
function answer(value: unknown = report(), exit: Exit = { code: 0, signal: null }): Plan {
  const text = JSON.stringify(value);
  return { chunks: [{ stream: "stdout", text: text.slice(0, 23) }, { stream: "stderr", text: SECRET }, { stream: "stdout", text: text.slice(23) }], exit };
}
// This recording boundary deliberately gives iterator completion and process
// completion different clocks/statuses. return(undefined) never supplies a fake
// process exit, and failed cleanup may not prevent observing other owners.
function child(plan: Plan): Child {
  const result = Promise.withResolvers<Exit>();
  const pending = Promise.withResolvers<IteratorResult<Chunk, Exit>>();
  let index = 0;
  let closed = false;
  let ended = false;
  let returns = 0;
  const exit = plan.exit ?? { code: 0, signal: null };
  const stream: Stream = {
    result: result.promise,
    async next() {
      if (closed || ended) return { done: true, value: { code: 0, signal: null } };
      const chunk = plan.chunks?.[index++];
      if (chunk !== undefined) return { done: false, value: chunk };
      if (plan.hold) return pending.promise;
      ended = true;
      plan.onDone?.();
      void Promise.resolve(plan.resultGate).then(() => {
        if (plan.resultFailure) result.reject(new Error(SECRET));
        else result.resolve(exit);
      });
      // A fabricated iterator code MUST NOT override the process result.
      return { done: true, value: { code: 0, signal: null } };
    },
    async return(value) {
      expect(value).toBeUndefined();
      returns++;
      closed = true;
      await plan.closeGate;
      result.reject(new Error(SECRET));
      pending.resolve({ done: true, value: { code: null, signal: "SIGTERM" } });
      if (plan.closeFailure) throw new Error(SECRET);
      return { done: true, value: undefined as never };
    },
    async throw(error) { result.reject(error); pending.reject(error); throw error; },
    [Symbol.asyncIterator]() { return this; },
    async [Symbol.asyncDispose]() { await stream.return(undefined as never); },
  };
  return { stream, get closed() { return closed; }, get returns() { return returns; } };
}
function harness(collision = false) {
  type Hook = ($: Api, event: never, next: never) => Promise<unknown>;
  const hooks = new Map<string, Hook>();
  const plans: Plan[] = [];
  const children: Child[] = [];
  const argv: string[][] = [];
  const timers: { ms: number; active: boolean; fire(): void }[] = [];
  let session = "session-a";
  let read: (() => Promise<string>) | undefined;
  let registrations = 0;
  let now = T;
  const api: Api = {
    plugin: { root: ROOT },
    session: { id: async () => read ? read() : session },
    command: { list: async () => collision ? [{ name: "armory-preflight" }] : [], register: async () => { registrations++; } },
    process: { spawn(request) {
      argv.push([...request.argv]);
      const plan = plans.shift();
      if (plan === undefined) throw new Error("unexpected spawn");
      const item = child(plan);
      children.push(item);
      return item.stream;
    } },
    clock: { now: async () => now, after(ms, fn) {
      const timer = { ms, active: true, fire() { if (timer.active) fn(); } };
      timers.push(timer);
      return { cancel() { timer.active = false; } };
    } },
  };
  register(((event: string, ...parts: unknown[]) => hooks.set(event, parts.at(-1) as Hook)) as On);
  async function invoke(event: string, value: unknown, controller = new AbortController()) {
    const hook = hooks.get(event);
    if (hook === undefined) throw new Error("missing hook");
    const next = Object.assign(async (input: unknown) => input, { signal: controller.signal });
    return hook(api, value as never, next as never);
  }
  return { api, plans, children, argv, timers, invoke,
    start: () => invoke("session.start", {}), end: () => invoke("session.end", { sessionId: session, reason: "clear" }),
    async run(args = ARGS, controller?: AbortController): Promise<{ text: string }> { return await invoke("command.run", { command: "armory-preflight", args }, controller) as { text: string }; },
    setSession(value: string) { session = value; }, setRead(value?: () => Promise<string>) { read = value; }, setNow(value: number) { now = value; },
    get registrations() { return registrations; },
    frame(text: string) { const hook = hooks.get("ui.render"); if (!hook) throw new Error("missing render hook"); return hook(undefined as never, { props: { text } } as never, undefined as never); },
  };
}
async function until(predicate: () => boolean) {
  for (let turn = 0; turn < 100; turn++) { if (predicate()) return; await Promise.resolve(); }
  throw new Error("recording host boundary did not settle");
}

describe("Claude Run Preflight command boundary", () => {
  test("collision rejects registration and concurrent starts register once", async () => {
    const occupied = harness(true);
    await expect(occupied.start()).rejects.toThrow("collision");
    expect(occupied.registrations).toBe(0);
    const h = harness();
    await Promise.all([h.start(), h.start()]);
    expect(h.registrations).toBe(1);
  });
  test("help, invalid/admit/implicit invocations and unstarted commands never spawn", async () => {
    const h = harness();
    expect((await h.run("help")).text).toBe(HELP);
    expect(JSON.parse((await h.run()).text)).toEqual({ error: "session-unavailable" });
    await h.start();
    for (const args of ["", "probe", `admit ${JSON.stringify(SELECTION)} --json`, `check ${JSON.stringify({ ...SELECTION, extra: SECRET })} --json`, 'check {"config":"relative","declaration":"/run.json"} --json']) {
      expect((await h.run(args)).text).toContain("invalid-arguments");
    }
    expect(h.argv).toHaveLength(0);
  });
  test("literal own bundled helper, paths with spaces, projected JSON and full native frame", async () => {
    const h = harness(); await h.start(); h.plans.push(answer());
    const output = await h.run();
    const view = JSON.parse(output.text);
    expect(h.argv).toEqual([["bun", `${ROOT}/helpers/cli.js`, "check", "--config", SELECTION.config, "--declaration", SELECTION.declaration, "--format", "json"]]);
    expect(view.selection).toEqual(SELECTION);
    expect(view.status).toBe("unknown"); expect(view.quota.status).toBe("unknown"); expect(view.admitted).toBe(false);
    expect(view).not.toHaveProperty("admission"); expect(output.text).not.toContain(SECRET); expect(output.text).not.toContain("local declaration");
    expect(output.text).toContain("\\u0020");
    const frame = h.frame(output.text) as unknown as { children: { children: string[] }[] };
    expect(frame.children[0]?.children).toEqual([output.text]);
    expect(h.timers[0]?.ms).toBe(HELPER_TIMEOUT_MS); expect(h.timers.every((timer) => !timer.active)).toBe(true);
  });
  test("complete text contains the selected paths and scope limits, without raw facts", async () => {
    const h = harness(); await h.start(); h.plans.push(answer());
    const text = (await h.run(ARGS.replace(/ --json$/, ""))).text;
    expect(text).toContain("Selected config:"); expect(text).toContain("Selected declaration:"); expect(text).toContain("unknown");
    expect(text).not.toContain(SECRET); expect(text).not.toContain('"admission"');
  });
  test("only a validated blocked report may use normalized exit2", async () => {
    const h = harness(); await h.start();
    h.plans.push(answer(report("blocked"), { code: 2, signal: null }));
    expect(JSON.parse((await h.run()).text).status).toBe("blocked");
    for (const plan of [answer(report(), { code: 2, signal: null }), answer(report("blocked"), { code: 1, signal: null }), answer(report("blocked"), { code: 0, signal: "SIGTERM" }), answer(report(), { code: null, signal: null }), answer({ status: "ready" }), answer({ ...report(), admitted: true }), answer({ ...report(), credential: SECRET })]) {
      h.plans.push(plan); expect(JSON.parse((await h.run()).text)).toEqual({ error: "operation-failed" });
    }
  });
  test("EOF is not a process exit and cannot publish before real result", async () => {
    const h = harness(); await h.start(); const gate = Promise.withResolvers<undefined>();
    h.plans.push({ ...answer(), resultGate: gate.promise, exit: { code: 1, signal: null } });
    let settled = false; const running = h.run().then((value) => { settled = true; return value; });
    await until(() => h.children.length === 1); await Promise.resolve(); expect(settled).toBe(false);
    gate.resolve(undefined); expect(JSON.parse((await running).text)).toEqual({ error: "operation-failed" });
  });
  test("expired observations, malformed output and rejected real result fail closed", async () => {
    const h = harness(); await h.start(); h.setNow(T + 600_000);
    h.plans.push(answer()); expect(JSON.parse((await h.run()).text)).toEqual({ error: "operation-failed" });
    h.setNow(T);
    h.plans.push({ chunks: [{ stream: "stdout", text: SECRET }] }, { ...answer(), resultFailure: true });
    for (let index = 0; index < 2; index++) expect(JSON.parse((await h.run()).text)).toEqual({ error: "operation-failed" });
  });
  test("bounds combined UTF8 bytes on both pipes and cleans the owner", async () => {
    for (const chunks of [[{ stream: "stderr" as const, text: "é".repeat(MAX_HELPER_BYTES / 2 + 1) }], [{ stream: "stdout" as const, text: " ".repeat(MAX_HELPER_BYTES) }, { stream: "stderr" as const, text: "x" }]]) {
      const h = harness(); await h.start(); h.plans.push({ chunks, hold: true });
      expect(JSON.parse((await h.run()).text)).toEqual({ error: "operation-failed" }); expect(h.children[0]?.closed).toBe(true);
    }
  });
  test("explicit probe uses the same owned helper and projects validated refusal", async () => {
    const h = harness(); await h.start(); h.plans.push(answer({ ...report("blocked"), probe: { schemaVersion: 1, coreVersion: "1.0.0", status: "blocked", managedSpawns: 0, providerCalls: 0, reasons: ["identity-source-drift"] } }, { code: 2, signal: null }));
    const value = JSON.parse((await h.run(ARGS.replace(/^check/, "probe"))).text);
    expect(h.argv[0]?.[2]).toBe("probe"); expect(value.probe.managedSpawns).toBe(0);
  });
});

describe("Claude owner lifecycle", () => {
  test("abort before the first session read returns cannot start work", async () => {
    const h = harness(); await h.start(); const read = Promise.withResolvers<string>(); h.setRead(() => read.promise);
    const controller = new AbortController(); const running = h.run(ARGS, controller); controller.abort(); read.resolve("session-a");
    expect(JSON.parse((await running).text)).toEqual({ error: "cancelled" }); expect(h.argv).toHaveLength(0);
  });
  test("SDK abort awaits owned return and result, then a fresh invocation succeeds", async () => {
    const h = harness(); await h.start(); const gate = Promise.withResolvers<undefined>();
    h.plans.push({ hold: true, closeGate: gate.promise }); const controller = new AbortController(); const running = h.run(ARGS, controller);
    await until(() => h.children.length === 1); controller.abort();
    let settled = false; void running.then(() => { settled = true; }); await Promise.resolve(); expect(settled).toBe(false);
    gate.resolve(undefined); expect(JSON.parse((await running).text)).toEqual({ error: "cancelled" }); expect(h.children[0]?.closed).toBe(true);
    h.plans.push(answer()); expect(JSON.parse((await h.run()).text).status).toBe("unknown");
  });
  test("owned timeout cancels instead of publishing buffered readiness", async () => {
    const h = harness(); await h.start(); h.plans.push({ ...answer(), hold: true }); const running = h.run();
    await until(() => h.timers.length === 1); h.timers[0]?.fire();
    expect(JSON.parse((await running).text)).toEqual({ error: "operation-failed" }); expect(h.children[0]?.closed).toBe(true);
  });
  test("host session drift after real completion suppresses the old answer", async () => {
    const h = harness(); await h.start(); h.plans.push({ ...answer(), onDone: () => h.setSession("session-b") });
    expect(JSON.parse((await h.run()).text)).toEqual({ error: "context-changed" });
  });
  test("session end revokes in-flight work and rejects the ended session", async () => {
    const h = harness(); await h.start(); h.plans.push({ hold: true }); const running = h.run(); await until(() => h.children.length === 1);
    await h.end(); expect(JSON.parse((await running).text)).toEqual({ error: "context-changed" });
    expect(JSON.parse((await h.run()).text)).toEqual({ error: "session-unavailable" });
    h.setSession("session-b"); h.plans.push(answer()); expect(JSON.parse((await h.run()).text).status).toBe("unknown");
  });
  test("replacement waits for the previous owner; failed cleanup permanently blocks respawn", async () => {
    const h = harness(); await h.start(); const gate = Promise.withResolvers<undefined>();
    h.plans.push({ hold: true, closeGate: gate.promise, closeFailure: true }); const first = h.run(); await until(() => h.children.length === 1);
    const second = h.run(); await until(() => h.children[0]?.closed === true); expect(h.argv).toHaveLength(1);
    gate.resolve(undefined);
    expect(JSON.parse((await first).text)).toEqual({ error: "operation-failed" }); expect(JSON.parse((await second).text)).toEqual({ error: "operation-failed" });
    expect(JSON.parse((await h.run()).text)).toEqual({ error: "operation-failed" }); expect(h.argv).toHaveLength(1);
  });
  test("session revocation waits every overlapping owner even when one return fails", async () => {
    const h = harness(); await h.start(); const gate = Promise.withResolvers<undefined>();
    h.plans.push({ hold: true, closeGate: gate.promise, closeFailure: true }); const first = h.run(); await until(() => h.children.length === 1);
    const read = Promise.withResolvers<string>(); h.setRead(() => read.promise);
    const second = h.run(); const ending = h.end();
    let ended = false; void ending.catch(() => { ended = true; }); await Promise.resolve(); expect(ended).toBe(false);
    gate.resolve(undefined); await expect(ending).rejects.toThrow("cleanup unconfirmed"); read.resolve("session-a"); await Promise.all([first, second]);
    expect(h.argv).toHaveLength(1); expect(h.children[0]?.closed).toBe(true);
  });
});

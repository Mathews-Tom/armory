import { describe, expect, test } from "bun:test";
import { register } from "../claude-code/register.ts";
import type { Api, On as Registrar, Stream } from "../claude-code/register.ts";
import { SCHEMA } from "../core/index.ts";
import type { Binding, Check, Observation, PullIdentity, PullObservation, RadarView, RequiredPolicy, Review, Selection, Source } from "../core/index.ts";
import { MAX_HELPER_BYTES } from "../core/protocol.ts";

type Chunk = { stream: "stdout" | "stderr"; text: string };
type Exit = { code: number | null; signal: string | null };
type Hook = ($: Api, event: never, next: never) => Promise<unknown>;
interface Plan {
  chunks?: Chunk[];
  exit?: Exit;
  hold?: boolean;
  startFailure?: boolean;
  resultFailure?: boolean;
  closeFailure?: boolean;
  closeGate?: Promise<unknown>;
  onDone?: () => void;
}
interface Child {
  stream: Stream;
  readonly closed: boolean;
}
const T = 1_000_000;
const HEAD = "a".repeat(40);
const BASE = "b".repeat(40);
const SELECTED: Selection = { repository: "owner/project", pullRequests: [7, 2] };
const ARGS = "refresh owner/project 7,2 --json";
const SECRET = "PRIVATE-provider-credential";

function source<V>(value: V, name: string, binding: Binding | null, at: number): Source<V> {
  return { status: "available", binding, observedAt: at, reference: `https://api.github.com/repos/owner/project/${name}`, diagnostic: null, value };
}
function observation(selection = SELECTED, at = T): Observation {
  const pulls: PullObservation[] = selection.pullRequests.map((number) => {
    const identity: PullIdentity = { number, url: `https://github.com/owner/project/pull/${number}`, title: `Selected ${number}`, state: "OPEN", headOid: HEAD, baseOid: BASE,
      headRef: `feature-${number}`, baseRef: "main", headRepository: selection.repository, draft: false, mergeable: "MERGEABLE", mergeCommitOid: null };
    const binding: Binding = { repository: selection.repository, pullRequest: number, headOid: HEAD, baseOid: BASE, viewerId: "viewer-1" };
    return {
      before: source({ ...identity }, `pulls/${number}/before`, binding, at + 10), after: source({ ...identity }, `pulls/${number}/after`, binding, at + 30),
      reviews: source<readonly Review[]>([{ id: `review-${number}`, reviewerId: "reviewer-1", state: "APPROVED", commitOid: HEAD, submittedAt: at }], `pulls/${number}/reviews`, binding, at + 20),
      threads: source([], `pulls/${number}/threads`, binding, at + 20),
      checks: source<readonly Check[]>([{ id: `check-${number}`, context: "test", publisherId: 1, state: "passed", headOid: HEAD, testedBaseOid: BASE, url: "https://github.com/check/1", completedAt: at }], `pulls/${number}/checks`, binding, at + 20),
      policy: source<RequiredPolicy>({ checks: [{ context: "test", publisherId: 1 }], requiredApprovals: 1, requireCodeOwnerReview: false, requireLatestApproval: false, dismissStaleReviews: true, strict: true, unsupported: [] }, `pulls/${number}/policy`, binding, at + 20),
      publication: { ...source(null, `pulls/${number}/publication`, binding, at + 20), status: "not-selected" },
    };
  });
  return { schema: SCHEMA, selection, startedAt: at, finishedAt: at + 50, viewerBefore: source("viewer-1", "viewer/before", null, at), viewerAfter: source("viewer-1", "viewer/after", null, at + 40), pulls };
}
function answer(value = observation(), extra: Record<string, unknown> = {}): Plan {
  return { chunks: [{ stream: "stdout", text: JSON.stringify({ observation: value, ...extra }) }] };
}

function required<V>(value: V | null | undefined, description: string): V {
  if (value === null || value === undefined) throw new Error(`missing ${description}`);
  return value;
}

// An isolated recording host boundary, not a module mock. Its return() and
// async disposal model the pinned host's immediate child close, including a
// rejected result promise.
// Synthetic evidence never requires authentication, GitHub, PATH or a model.
function streamFor(plan: Plan): Child {
  const result = Promise.withResolvers<Exit>();
  const pending = Promise.withResolvers<IteratorResult<Chunk, Exit>>();
  let index = 0;
  let done = false;
  let closed = false;
  const exit = plan.exit ?? { code: 0, signal: null };
  const stream: Stream = {
    result: result.promise,
    async next(): Promise<IteratorResult<Chunk, Exit>> {
      if (closed || done) return { done: true, value: exit };
      if (plan.startFailure) {
        done = true;
        result.reject(new Error(SECRET));
        throw new Error(SECRET);
      }
      const chunk = plan.chunks?.[index++];
      if (chunk !== undefined) return { done: false, value: chunk };
      if (plan.hold) return pending.promise;
      done = true;
      plan.onDone?.();
      if (plan.resultFailure) result.reject(new Error(SECRET));
      else result.resolve(exit);
      return { done: true, value: exit };
    },
    async return(): Promise<IteratorResult<Chunk, Exit>> {
      if (done || closed) return { done: true, value: exit };
      closed = true;
      await plan.closeGate;
      result.reject(new Error(SECRET));
      pending.resolve({ done: true, value: { code: null, signal: "SIGTERM" } });
      if (plan.closeFailure) throw new Error(SECRET);
      return { done: true, value: { code: null, signal: "SIGTERM" } };
    },
    async throw(error: unknown): Promise<IteratorResult<Chunk, Exit>> {
      result.reject(error);
      pending.reject(error);
      throw error;
    },
    [Symbol.asyncIterator]() { return this; },
    async [Symbol.asyncDispose](): Promise<void> {
      await stream.return(exit);
    },
  };
  return { stream, get closed() { return closed; } };
}

function harness(options: { collision?: boolean; session?: string } = {}) {
  const hooks = new Map<string, Hook>();
  const plans: Plan[] = [];
  const streams: Child[] = [];
  const spawned = Promise.withResolvers<Child>();
  const timers: { active: boolean; fire(): void }[] = [];
  let session = options.session ?? "session-a";
  let sessionRead: (() => Promise<string>) | null = null;
  let registrations = 0;
  let now = T + 100;
  let clockRead: (() => Promise<number>) | null = null;
  const api: Api = {
    plugin: { root: "/detached/synthetic-plugin" },
    session: { async id() { return sessionRead === null ? session : sessionRead(); } },
    command: {
      async list() { return options.collision ? [{ name: "armory-delivery" }] : []; },
      async register() { registrations++; return {}; },
    },
    process: {
      spawn() {
        const plan = plans.shift();
        if (plan === undefined) throw new Error("unexpected helper work");
        const child = streamFor(plan);
        streams.push(child);
        spawned.resolve(child);
        return child.stream;
      },
    },
    clock: {
      async now() { return clockRead === null ? now : clockRead(); },
      after(_ms, callback) {
        const timer = { active: true, fire() { if (this.active) { this.active = false; callback(); } } };
        timers.push(timer);
        return { cancel() { timer.active = false; } };
      },
    },
  };
  register(((name: string, ...rest: unknown[]) => {
    hooks.set(name, rest.at(-1) as Hook);
  }) as Registrar);
  async function emit(name: string, event: unknown = {}, signal = new AbortController().signal) {
    const hook = hooks.get(name);
    if (hook === undefined) throw new Error(`missing ${name} hook`);
    const next = Object.assign(async () => ({}), { signal });
    return hook(api, event as never, next as never);
  }
  return {
    plans, streams, timers, spawned: spawned.promise,
    start: () => emit("session.start"),
    end: () => emit("session.end", { sessionId: session, reason: "clear" }),
    async run(args = ARGS, signal?: AbortSignal): Promise<string> {
      const reply = await emit("command.run", { command: "armory-delivery", args }, signal);
      if (reply === null || typeof reply !== "object" || !("text" in reply) || typeof reply.text !== "string") throw new Error("command did not return host text");
      return reply.text;
    },
    setSession(value: string) { session = value; },
    readSession(fn: (() => Promise<string>) | null) { sessionRead = fn; },
    setNow(value: number) { now = value; },
    readClock(fn: (() => Promise<number>) | null) { clockRead = fn; },
    get registrations() { return registrations; },
  };
}

function parsed(text: string): { view: RadarView; transition: boolean } {
  const result = JSON.parse(text);
  if (result === null || typeof result !== "object" || typeof result.transition !== "boolean" || result.view?.schema !== "armory.delivery-radar.view/v1" || !Array.isArray(result.view.pulls)) {
    throw new Error("command did not return a native view envelope");
  }
  return result;
}

describe("Claude native Delivery Radar consumer boundary", () => {
  test("preserves the explicit ordered selection and independent dimensions, ignoring a claimed view", async () => {
    const native = harness();
    await native.start();
    const value = observation();
    required(value.pulls[0], "selected fixture PR").checks.status = "unavailable";
    native.plans.push(answer(value, { view: { repository: "other/private", pulls: [{ merge: { state: "passed" }, publication: { state: "passed" } }] }, credential: SECRET }));
    const response = await native.run();
    const result = parsed(response);
    expect(result.view.repository).toBe(SELECTED.repository);
    expect(result.view.pulls.map((pull) => pull.number)).toEqual([7, 2]);
    expect(result.view.pulls.map((pull) => [pull.implementation.state, pull.verification.state, pull.review.state, pull.merge.state, pull.publication.state])).toEqual([
      ["passed", "unknown", "passed", "unknown", "unknown"], ["passed", "passed", "passed", "passed", "unknown"],
    ]);
    expect(result.transition).toBe(false);
    expect(response).not.toContain(SECRET);
    expect(response).not.toContain("other/private");
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("help and invalid selections never start a helper", async () => {
    const native = harness();
    await native.start();
    await native.run("help");
    for (const args of ["refresh", "refresh owner/project 7,7", "refresh owner/project 7 --json --watch", "refresh owner/project;id 7", "refresh owner/project 7 --merge", "refresh owner/project 0", "refresh owner/project 7 --json extra"]) {
      expect(await native.run(args)).toContain("invalid-arguments");
    }
    expect(native.streams).toHaveLength(0);
    expect(native.timers).toHaveLength(0);
  });

  test("registration is single-flight and a collision never replaces the other command", async () => {
    const native = harness();
    await Promise.all([native.start(), native.start()]);
    await native.start();
    expect(native.registrations).toBe(1);
    const collision = harness({ collision: true });
    await expect(collision.start()).rejects.toThrow("collision");
    await expect(collision.start()).rejects.toThrow("collision");
    expect(collision.registrations).toBe(0);
    expect(JSON.parse(await collision.run())).toEqual({ error: "session-unavailable" });
    expect(collision.streams).toHaveLength(0);
  });

  test("rejects output from another repository, reordered PRs, invalid JSON and a missing observation", async () => {
    const native = harness();
    await native.start();
    for (const plan of [answer(observation({ repository: "other/repository", pullRequests: [7, 2] })), answer(observation({ ...SELECTED, pullRequests: [2, 7] })),
      { chunks: [{ stream: "stdout" as const, text: `not-json ${SECRET}` }] }, { chunks: [{ stream: "stdout" as const, text: JSON.stringify({ view: { merge: "passed" }, credential: SECRET }) }] }]) {
      native.plans.push(plan);
      const text = await native.run();
      expect(JSON.parse(text)).toEqual({ error: "operation-failed" });
      expect(text).not.toContain(SECRET);
    }
  });

  test("waits for actual process completion and never accepts nonzero, signalled or rejected completion", async () => {
    const native = harness();
    await native.start();
    native.plans.push({ ...answer(), hold: true });
    const interrupted = new AbortController();
    let answered = false;
    const command = native.run(ARGS, interrupted.signal).then((value) => { answered = true; return value; });
    await native.spawned;
    expect(answered).toBe(false);
    interrupted.abort();
    expect(JSON.parse(await command)).toEqual({ error: "cancelled" });
    for (const change of [{ exit: { code: 2, signal: null } }, { exit: { code: null, signal: "SIGTERM" } }, { resultFailure: true }, { startFailure: true }]) {
      native.plans.push({ ...answer(), ...change });
      const response = await native.run();
      expect(JSON.parse(response)).toEqual({ error: "operation-failed" });
      expect(response).not.toContain(SECRET);
    }
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("bounds both output pipes by UTF-8 bytes before parsing and closes oversized helpers", async () => {
    for (const stream of ["stdout", "stderr"] as const) {
      const native = harness();
      await native.start();
      native.plans.push({ chunks: [{ stream, text: "é".repeat(MAX_HELPER_BYTES / 2 + 1) }], hold: true });
      expect(JSON.parse(await native.run())).toEqual({ error: "operation-failed" });
      expect(required(native.streams[0], "spawned helper").closed).toBe(true);
      expect(native.timers.every((timer) => !timer.active)).toBe(true);
    }
  });

  test("head/base/viewer changes remain unknown even behind a helper's optimistic view", async () => {
    const native = harness();
    await native.start();
    for (const field of ["headOid", "baseOid", "viewerId"] as const) {
      const value = observation();
      if (field === "viewerId") value.viewerAfter.value = "viewer-2";
      else required(required(value.pulls[0], "selected fixture PR").after.value, "fixture after identity")[field] = "c".repeat(40);
      native.plans.push(answer(value, { view: { allReady: true } }));
      const pull = required(parsed(await native.run()).view.pulls[0], "selected response PR");
      expect([pull.implementation.state, pull.verification.state, pull.review.state, pull.merge.state, pull.publication.state]).toEqual(["unknown", "unknown", "unknown", "unknown", "unknown"]);
    }
  });

  test("does not emit active Markdown, terminal controls or bidi in host command text", async () => {
    const native = harness();
    await native.start();
    const value = observation();
    for (const pull of value.pulls) {
      const before = required(pull.before.value, "fixture before identity");
      const after = required(pull.after.value, "fixture after identity");
      before.title = "[click](https://evil.invalid)\u001b[31m\u202e";
      after.title = before.title;
    }
    native.plans.push(answer(value), answer(value));
    const text = await native.run("refresh owner/project 7,2");
    expect(text).not.toContain("[click](https://evil.invalid)");
    expect(text).not.toContain("\u001b");
    expect(text).not.toContain("\u202e");
    const json = await native.run();
    expect(json).not.toContain("\u202e");
    expect(required(parsed(json).view.pulls[0], "selected response PR").title).toBe(
      required(required(value.pulls[0], "selected fixture PR").after.value, "fixture after identity").title,
    );
  });
});

describe("Claude native command ownership and transition state", () => {
  test("abort before session preflight completes cannot create helper work", async () => {
    const native = harness();
    await native.start();
    const selected = Promise.withResolvers<string>();
    native.readSession(() => selected.promise);
    const interrupt = new AbortController();
    const running = native.run(ARGS, interrupt.signal);
    interrupt.abort();
    selected.resolve("session-a");
    expect(JSON.parse(await running)).toEqual({ error: "cancelled" });
    expect(native.streams).toHaveLength(0);
  });

  test("an interrupt while the host clock is pending cannot publish a derived view", async () => {
    const native = harness();
    await native.start();
    const sampled = Promise.withResolvers<undefined>();
    const clock = Promise.withResolvers<number>();
    native.readClock(() => { sampled.resolve(undefined); return clock.promise; });
    native.plans.push(answer());
    const interrupt = new AbortController();
    const running = native.run(ARGS, interrupt.signal);
    await sampled.promise;
    interrupt.abort();
    clock.resolve(T + 100);
    expect(JSON.parse(await running)).toEqual({ error: "cancelled" });
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("an unavailable host clock fails closed without substituting ordinary runtime time", async () => {
    const native = harness();
    await native.start();
    native.readClock(async () => { throw new Error(SECRET); });
    native.plans.push(answer());
    const response = await native.run();
    expect(JSON.parse(response)).toEqual({ error: "operation-failed" });
    expect(response).not.toContain(SECRET);
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("an interrupt during final ownership revalidation suppresses a completed answer", async () => {
    const native = harness();
    await native.start();
    const finalRead = Promise.withResolvers<undefined>();
    const finalSession = Promise.withResolvers<string>();
    let reads = 0;
    native.readSession(async () => {
      if (++reads === 1) return "session-a";
      finalRead.resolve(undefined);
      return finalSession.promise;
    });
    native.plans.push(answer());
    const interrupt = new AbortController();
    const running = native.run(ARGS, interrupt.signal);
    await finalRead.promise;
    interrupt.abort();
    finalSession.resolve("session-a");
    expect(JSON.parse(await running)).toEqual({ error: "cancelled" });
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("session.end closes and awaits the active child and consumes expected result rejection", async () => {
    const native = harness();
    await native.start();
    const gate = Promise.withResolvers<undefined>();
    native.plans.push({ ...answer(), hold: true, closeGate: gate.promise });
    const running = native.run();
    await native.spawned;
    let ended = false;
    const ending = native.end().then(() => { ended = true; });
    expect(required(native.streams[0], "spawned helper").closed).toBe(true);
    expect(ended).toBe(false);
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
    gate.resolve(undefined);
    await ending;
    expect(JSON.parse(await running)).toEqual({ error: "context-changed" });
    expect(JSON.parse(await native.run())).toEqual({ error: "session-unavailable" });
  });

  test("new sessions without session.start reset dedup and old answers are refused", async () => {
    const native = harness();
    await native.start();
    native.plans.push({ ...answer(), onDone: () => native.setSession("session-b") });
    expect(JSON.parse(await native.run())).toEqual({ error: "context-changed" });
    native.plans.push(answer());
    expect(parsed(await native.run()).transition).toBe(false);
    await native.end();
    native.setSession("session-c");
    native.plans.push(answer());
    expect(parsed(await native.run()).transition).toBe(false);
    expect(native.registrations).toBe(1);
  });

  test("superseding refresh closes old work before a new helper can publish", async () => {
    const native = harness();
    await native.start();
    const gate = Promise.withResolvers<undefined>();
    native.plans.push({ ...answer(), hold: true, closeGate: gate.promise });
    const old = native.run();
    await native.spawned;
    native.plans.push(answer());
    const latest = native.run();
    expect(required(native.streams[0], "spawned helper").closed).toBe(true);
    expect(native.streams).toHaveLength(1);
    gate.resolve(undefined);
    expect(JSON.parse(await old)).toEqual({ error: "context-changed" });
    expect(parsed(await latest).view.pulls.map((pull) => pull.number)).toEqual([7, 2]);
    expect(native.streams).toHaveLength(2);
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  for (const closeFailure of [false, true]) {
    test(`three refreshes wait for every older cleanup, close failure=${closeFailure}`, async () => {
      const native = harness();
      await native.start();
      const gate = Promise.withResolvers<undefined>();
      native.plans.push({ ...answer(), hold: true, closeGate: gate.promise, closeFailure });
      const first = native.run();
      await native.spawned;
      native.plans.push(answer());
      const second = native.run();
      let released = false;
      let publishedBeforeCleanup = false;
      const third = native.run().then((reply) => {
        publishedBeforeCleanup = !released;
        return reply;
      });
      // Flush ready microtasks through one event-loop turn, not a wall-time race.
      await Bun.sleep(0);
      const admittedBeforeCleanup = native.streams.length > 1;
      released = true;
      gate.resolve(undefined);
      const [oldest, middle, latest] = await Promise.all([first, second, third]);
      expect(admittedBeforeCleanup).toBe(false);
      expect(publishedBeforeCleanup).toBe(false);
      expect(JSON.parse(oldest)).toHaveProperty("error");
      expect(JSON.parse(middle)).toHaveProperty("error");
      if (closeFailure) {
        expect(JSON.parse(latest)).toEqual({ error: "operation-failed" });
        expect(JSON.parse(await native.run())).toEqual({ error: "operation-failed" });
        expect(native.streams).toHaveLength(1);
      } else {
        expect(parsed(latest).view.pulls.map((pull) => pull.number)).toEqual([7, 2]);
        expect(native.streams).toHaveLength(2);
      }
    });
  }

  test("a command timeout stops the child, clears timers and cannot masquerade as a current view", async () => {
    const native = harness();
    await native.start();
    native.plans.push({ ...answer(), hold: true });
    const running = native.run();
    await native.spawned;
    required(native.timers[0], "helper timeout").fire();
    expect(JSON.parse(await running)).toEqual({ error: "operation-failed" });
    expect(required(native.streams[0], "spawned helper").closed).toBe(true);
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("failed child close refuses further work rather than treating cancellation as clean", async () => {
    const native = harness();
    await native.start();
    native.plans.push({ ...answer(), hold: true, closeFailure: true });
    const running = native.run();
    await native.spawned;
    await expect(native.end()).rejects.toThrow("cleanup failed");
    expect(JSON.parse(await running)).toEqual({ error: "operation-failed" });
    native.setSession("session-b");
    expect(JSON.parse(await native.run())).toEqual({ error: "operation-failed" });
    expect(native.streams).toHaveLength(1);
  });

  test("unconfirmed detached gh cleanup blocks publication and every subsequent helper", async () => {
    const native = harness();
    await native.start();
    const unsafe = observation();
    const pull = required(unsafe.pulls[0], "selected pull");
    pull.checks = { ...pull.checks, status: "unavailable", value: null, diagnostic: "github-process-cleanup-unconfirmed" };
    native.plans.push(answer(unsafe));
    expect(JSON.parse(await native.run())).toEqual({ error: "operation-failed" });
    native.plans.push(answer());
    expect(JSON.parse(await native.run())).toEqual({ error: "operation-failed" });
    expect(native.streams).toHaveLength(1);
    expect(native.timers.every((timer) => !timer.active)).toBe(true);
  });

  test("deduplicates semantic transitions per session and ordered selection, not sampling time", async () => {
    const native = harness();
    await native.start();
    native.plans.push(answer());
    expect(parsed(await native.run()).transition).toBe(false);
    native.setNow(T + 200);
    native.plans.push(answer(observation(SELECTED, T + 100)));
    expect(parsed(await native.run()).transition).toBe(false);
    const changed = observation(SELECTED, T + 100);
    const checks = required(required(changed.pulls[0], "selected fixture PR").checks.value, "fixture checks");
    required(checks[0], "fixture check").state = "failed";
    native.plans.push(answer(changed), answer(changed));
    const transition = parsed(await native.run());
    expect(transition.transition).toBe(true);
    expect(required(transition.view.pulls[0], "selected response PR").verification.state).toBe("failed");
    expect(parsed(await native.run()).transition).toBe(false);
    const reordered: Selection = { ...SELECTED, pullRequests: [2, 7] };
    native.plans.push(answer(observation(reordered, T + 100)));
    expect(parsed(await native.run("refresh owner/project 2,7 --json")).transition).toBe(false);
    native.plans.push(answer(changed));
    expect(parsed(await native.run()).transition).toBe(false);
    native.setSession("session-b");
    native.plans.push(answer());
    expect(parsed(await native.run()).transition).toBe(false);
  });
});

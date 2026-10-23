import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Observation, PullObservation, Selection } from "../core/types.ts";
import { observe } from "../helpers/github.ts";

const HEAD = "a".repeat(40);
const BASE = "b".repeat(40);
const NEXT = "c".repeat(40);
const API_DATE = "2026-01-01T00:00:00Z";
const HELPER = fileURLToPath(new URL("../helpers/github.ts", import.meta.url));
interface Reply { body?: unknown; code?: number; stderr?: string; hang?: boolean; raw?: string; }
interface Request { args: string[]; pid: number; }
interface Scenario {
  drift?: "head" | "base" | "viewer";
  policy?: "missing" | "none" | "unsupported" | "rules-unavailable" | "malformed" | "paginated" | "requirements" | "signatures";
  checks?: "pending" | "rate-limited" | "unavailable" | "malformed" | "paginated";
  checkUrl?: string;
  statusUrl?: string;
  pagination?: "reviews" | "threads" | "statuses" | "budget" | "broken";
  graphql?: "rate-limited" | "permission" | "malformed-review";
  cancel?: boolean;
  overflow?: boolean;
}

function firstPull(observation: Observation): PullObservation {
  const pull = observation.pulls[0];
  if (pull === undefined) throw new Error("selected PR observation missing");
  return pull;
}
async function deadline<T>(promise: Promise<T>, milliseconds = 15_000): Promise<T> {
  // These deadlines bound real OS processes and IPC; fake timers cannot reap
  // children. Readiness/cancellation below await provider signals, never sleeps.
  const expired = Promise.withResolvers<T>();
  const timer = setTimeout(() => expired.reject(new Error("local protocol scenario deadline exceeded")), milliseconds);
  try { return await Promise.race([promise, expired.promise]); } finally { clearTimeout(timer); }
}
function pageInfo(hasNextPage = false, endCursor: string | null = null) { return { hasNextPage, endCursor }; }
function review(index: number) {
  return { id: `review-${index}`, author: { id: `reviewer-${index}` }, state: index === 101 ? "DISMISSED" : "APPROVED", commit: { oid: HEAD }, submittedAt: API_DATE };
}
function thread(index: number) { return { id: `thread-${index}`, isResolved: index !== 101, isOutdated: index === 101 }; }
function check(index: number, pending = false) {
  return { id: index, name: `check-${index}`, app: { id: 15368 }, head_sha: HEAD, status: pending ? "in_progress" : "completed", conclusion: pending ? null : "success", html_url: `https://github.com/acme/widget/actions/runs/${index}`, completed_at: pending ? null : API_DATE,
    // This intentionally tempting mutable association must never become testedBaseOid.
    check_suite: { pull_requests: [{ number: 7, head: { sha: HEAD }, base: { sha: BASE } }] } };
}
function protection() {
  return { url: "https://api.github.com/repos/acme/widget/branches/main/protection", required_signatures: { enabled: false }, required_status_checks: { strict: true, contexts: ["check-1"], checks: [{ context: "check-1", app_id: 15368 }] }, required_pull_request_reviews: { required_approving_review_count: 1, require_code_owner_reviews: false, require_last_push_approval: false, dismiss_stale_reviews: true } };
}

// The executable speaks gh's argv protocol and streams real child stdout/stderr.
// Responses come from a stateful provider fixture that validates route, method,
// cursor and page independently; it does not echo caller-requested result values.
const FAKE_GH = `#!${process.execPath}
import { spawn } from "node:child_process";
const args = process.argv.slice(2);
const endpoint = process.env.RADAR_FIXTURE_URL;
const response = await fetch(endpoint, {method:"POST",body:JSON.stringify({args,pid:process.pid})});
const reply = await response.json();
if(reply.hang){
  const child=spawn(process.execPath,["-e", "await fetch(process.env.RADAR_FIXTURE_URL+'/descendant',{method:'POST',body:JSON.stringify({pid:process.pid})});setInterval(()=>{},1000)"],{stdio:"ignore"});
  process.on('SIGTERM',()=>{});
  setInterval(()=>{},1000);
}else{
  if(reply.stderr)process.stderr.write(reply.stderr);
  if(reply.raw!==undefined||reply.body!==undefined)process.stdout.write(reply.raw ?? JSON.stringify(reply.body));
  process.exitCode=reply.code ?? 0;
}
`;
const HARNESS = `import {observe} from ${JSON.stringify(HELPER)};
const controller=new AbortController();
process.on("SIGTERM",()=>controller.abort());
process.on("SIGINT",()=>controller.abort());
const result=await observe({repository:"acme/widget",pullRequests:[7]},{signal:controller.signal});
process.stdout.write(JSON.stringify(result));`;

async function scenario(config: Scenario = {}) {
  const directory = await mkdtemp("/tmp/armory-radar-gh-");
  const requests: Request[] = [];
  const violations: string[] = [];
  let identities = 0;
  let viewers = 0;
  let descendantPid: number | null = null;
  let hangingProviderPid: number | null = null;
  const hanging = Promise.withResolvers<number>();
  const root = Promise.withResolvers<number>();
  function respond(request: Request): Reply {
    requests.push(request);
    const args = [...request.args];
    if (args.splice(0, 3).join(" ") !== "api --hostname github.com") { violations.push("api hostname prefix"); return { code: 1 }; }
    if (args[0] === "graphql") {
      const fields = new Map<string, string>();
      for (let index = 1; index < args.length; index += 2) {
        if (!["-f", "-F"].includes(args[index] ?? "")) violations.push("GraphQL argv field flag");
        const field = args[index + 1] ?? "";
        const equals = field.indexOf("=");
        fields.set(field.slice(0, equals), field.slice(equals + 1));
      }
      const query = fields.get("query") ?? "";
      if (!query.startsWith("query ") || /\bmutation\b/u.test(query) || fields.get("owner") !== "acme" || fields.get("name") !== "widget" || fields.get("number") !== "7") violations.push("read-only GraphQL variables");
      if (query.includes("RadarIdentity")) {
        identities++;
        const identity = { number: 7, url: "https://github.com/acme/widget/pull/7", title: "Local fixture PR", state: "OPEN", headRefOid: config.drift === "head" && identities > 1 ? NEXT : HEAD, baseRefOid: config.drift === "base" && identities > 1 ? NEXT : BASE, headRefName: "feature", baseRefName: "main", headRepository: { nameWithOwner: "acme/widget" }, isDraft: false, mergeable: "MERGEABLE", mergeCommit: null };
        return { body: { data: { repository: { nameWithOwner: "acme/widget", pullRequest: identity } } } };
      }
      const kind = query.includes("RadarReviews") ? "reviews" : query.includes("RadarThreads") ? "reviewThreads" : null;
      if (!kind) { violations.push("known GraphQL document"); return { code: 1 }; }
      if (config.cancel && kind === "reviews") { hangingProviderPid = request.pid; root.resolve(request.pid); return { hang: true }; }
      if (kind === "reviews" && config.graphql) {
        if (config.graphql === "malformed-review") return { body: { data: { repository: { nameWithOwner: "acme/widget", pullRequest: { reviews: { nodes: [{ ...review(1), author: null }], pageInfo: pageInfo() } } } } } };
        return { body: { data: { repository: { nameWithOwner: "acme/widget", pullRequest: { reviews: { nodes: [], pageInfo: pageInfo() } } } }, errors: [{ type: config.graphql === "rate-limited" ? "RATE_LIMITED" : "FORBIDDEN", message: "private provider explanation token=NEVER_COPY_THIS" }] } };
      }
      const pagination = config.pagination === "budget" || config.pagination === "broken" || config.pagination === (kind === "reviews" ? "reviews" : "threads");
      const cursor = fields.get("cursor");
      let nodes: (ReturnType<typeof review> | ReturnType<typeof thread>)[] = kind === "reviews" ? [review(1)] : [thread(1)];
      let info = pageInfo();
      if (pagination) {
        if (!cursor) { nodes = Array.from({ length: 100 }, (_, index) => kind === "reviews" ? review(index + 1) : thread(index + 1)); info = pageInfo(true, "page-2"); }
        else if (config.pagination === "budget") {
          const page = Number(cursor.slice(5));
          nodes = Array.from({ length: 100 }, (_, index) => kind === "reviews" ? review(page * 100 + index) : thread(page * 100 + index));
          info = pageInfo(true, `page-${page + 1}`);
        } else if (config.pagination === "broken") { nodes = []; info = pageInfo(true, "page-2"); }
        else if (cursor === "page-2") { nodes = [kind === "reviews" ? review(101) : thread(101)]; }
        else { violations.push("cursor continuation"); return { code: 1 }; }
      }
      return { body: { data: { repository: { nameWithOwner: "acme/widget", pullRequest: { [kind]: { nodes, pageInfo: info } } } } } };
    }
    if (args[0] !== "--method" || args[1] !== "GET" || args.length !== 3) { violations.push("REST GET argv"); return { code: 1 }; }
    const route = args[2] ?? "";
    const path = new URL(`https://api.github.com/${route}`);
    if (path.pathname === "/user") { viewers++; return { body: { node_id: config.drift === "viewer" && viewers > 1 ? "VIEWER_OTHER" : "VIEWER_ONE" } }; }
    if (path.pathname.includes("/check-runs")) {
      if (config.overflow) return { raw: "x".repeat(2 * 1024 * 1024 + 1) };
      if (config.checks === "rate-limited") return { code: 1, stderr: "gh: HTTP 429 rate limit token=NEVER_COPY_THIS" };
      if (config.checks === "unavailable") return { code: 1, stderr: "private service failure token=NEVER_COPY_THIS" };
      if (config.checks === "malformed") return { body: { total_count: 0 } };
      if (path.searchParams.get("per_page") !== "100" || path.searchParams.get("filter") !== "latest") violations.push("check query");
      if (config.checks === "paginated") {
        const second = path.searchParams.get("page") === "2";
        return { body: { total_count: 101, check_runs: second ? [check(101)] : Array.from({ length: 100 }, (_, index) => check(index + 1)) } };
      }
      return { body: { total_count: 1, check_runs: [{ ...check(1, config.checks === "pending"), html_url: config.checkUrl ?? check(1).html_url }] } };
    }
    if (path.pathname.endsWith("/statuses")) {
      if (config.pagination === "statuses") {
        const first = path.searchParams.get("page") === "1";
        return { body: first ? Array.from({ length: 100 }, (_, index) => ({ id: 900 + index, context: `legacy-${index}`, state: "success", updated_at: API_DATE, target_url: null })) : [{ id: 1001, context: "last-status", state: "pending", updated_at: API_DATE, target_url: null }] };
      }
      return { body: [{ id: 900, context: "legacy", state: "success", updated_at: API_DATE, target_url: config.statusUrl ?? null, creator: { id: 15368 } }] };
    }
    if (path.pathname === "/repos/acme/widget/branches/main") return { body: { protected: config.policy !== "none" } };
    if (path.pathname.endsWith("/protection")) {
      if (config.policy === "missing" || config.policy === "none") return { code: 1, stderr: "gh: Not Found (HTTP 404) token=NEVER_COPY_THIS" };
      if (config.policy === "malformed") return { body: { required_status_checks: [] } };
      if (config.policy === "signatures") return { body: { url: "https://api.github.com/repos/acme/widget/branches/main/protection" } };
      return { body: protection() };
    }
    if (path.pathname.endsWith("/protection/required_signatures")) return { body: { enabled: true } };
    if (path.pathname.includes("/rules/branches/")) {
      if (config.policy === "rules-unavailable") return { code: 1, stderr: "gh: Forbidden HTTP 403 token=NEVER_COPY_THIS" };
      if (config.policy === "paginated") {
        const first = path.searchParams.get("page") === "1";
        return { body: first ? Array.from({ length: 100 }, (_, index) => ({ type: "required_signatures", ruleset_id: index + 1, parameters: {} })) : [{ type: "merge_queue", ruleset_id: 101, parameters: {} }] };
      }
      if (config.policy === "requirements") return { body: [
        { type: "required_status_checks", parameters: { strict_required_status_checks_policy: true, required_status_checks: [{ context: "rules-check", integration_id: 42 }, { context: "any-app-check" }] } },
        { type: "pull_request", parameters: { required_approving_review_count: 2, require_code_owner_review: true, require_last_push_approval: true, dismiss_stale_reviews_on_push: true, required_review_thread_resolution: false } },
      ] };
      return { body: config.policy === "unsupported" ? [{ type: "merge_queue", parameters: {} }] : [] };
    }
    violations.push(`unexpected route ${path.pathname}`);
    return { code: 1 };
  }
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    if (new URL(request.url).pathname === "/descendant") {
      const data = await request.json() as { pid: number };
      descendantPid = data.pid; hanging.resolve(data.pid);
      return Response.json({});
    }
    return Response.json(respond(await request.json() as Request));
  } });
  let child: ChildProcess | null = null;
  let completedNormally = false;
  try {
    const executable = join(directory, "gh");
    await writeFile(executable, FAKE_GH); await chmod(executable, 0o700);
    const script = join(directory, "observe.ts"); await writeFile(script, HARNESS);
    child = spawn(process.execPath, [script], { env: { ...process.env, PATH: `${directory}:${process.env.PATH ?? ""}`, RADAR_FIXTURE_URL: `http://127.0.0.1:${server.port}` }, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = ""; let stderr = "";
    const { stdout: output, stderr: errors } = child;
    if (output === null || errors === null) throw new Error("fixture process pipes missing");
    output.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
    errors.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    const completed = Promise.withResolvers<number | null>();
    child.once("error", completed.reject); child.once("close", completed.resolve);
    let rootPid: number | null = null;
    if (config.cancel) {
      [rootPid] = await deadline(Promise.all([root.promise, hanging.promise]));
      child.kill("SIGTERM");
    }
    expect(await deadline(completed.promise)).toBe(0);
    expect(stderr).toBe("");
    expect(violations).toEqual([]);
    const observation = JSON.parse(stdout) as Observation;
    expect(JSON.stringify(observation)).not.toContain("NEVER_COPY_THIS");
    if (config.cancel) {
      // Assert before fixture cleanup, so teardown cannot make this guard pass.
      for (const pid of [rootPid, descendantPid]) {
        if (pid === null) throw new Error("owned cancellation process identity missing");
        expect(() => process.kill(pid, 0)).toThrow();
      }
    }
    completedNormally = true;
    return { observation, requests, rootPid, descendantPid };
  } finally {
    if (child && child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    if (!completedNormally && hangingProviderPid) { try { process.kill(-hangingProviderPid, "SIGKILL"); } catch { /* Already stopped. */ } }
    if (!completedNormally && descendantPid) { try { process.kill(descendantPid, "SIGKILL"); } catch { /* Already stopped. */ } }
    server.stop(true);
    await rm(directory, { recursive: true, force: true });
  }
}

test("observes through argv-only real processes with exact publisher and honest tested-base provenance", async () => {
  const { observation, requests } = await scenario();
  const pull = firstPull(observation);
  expect(observation.viewerBefore.value).toBe("VIEWER_ONE");
  expect(observation.viewerAfter.value).toBe("VIEWER_ONE");
  expect(pull.before.binding).toEqual({ repository: "acme/widget", pullRequest: 7, headOid: HEAD, baseOid: BASE, viewerId: "VIEWER_ONE" });
  expect(pull.checks.status).toBe("available");
  expect(pull.checks.value?.[0]?.publisherId).toBe(15368);
  expect(pull.checks.value?.[0]?.testedBaseOid).toBeNull();
  expect(pull.checks.value?.[1]?.publisherId).toBeNull();
  expect(pull.checks.diagnostic).toBe("head-only-checks-do-not-establish-tested-base");
  expect(pull.policy.value?.checks).toEqual([{ context: "check-1", publisherId: 15368 }]);
  expect(pull.publication.status).toBe("not-selected");
  expect(pull.before.observedAt).toBeGreaterThanOrEqual(observation.startedAt);
  expect(pull.after.observedAt).toBeLessThanOrEqual(observation.finishedAt);
  expect(requests.filter(({ args }) => args.some((arg) => arg.includes("RadarIdentity")))).toHaveLength(2);
});

for (const pagination of ["reviews", "threads"] as const) {
  test(`fully paginates ${pagination} without hiding dismissed or unresolved old threads`, async () => {
    const { observation } = await scenario({ pagination });
    const value = firstPull(observation)[pagination === "reviews" ? "reviews" : "threads"];
    expect(value.status).toBe("available"); expect(value.value).toHaveLength(101);
    if (pagination === "reviews") expect(firstPull(observation).reviews.value?.[100]?.state).toBe("DISMISSED");
    else { expect(firstPull(observation).threads.value?.[100]?.resolved).toBe(false); expect(firstPull(observation).threads.value?.[100]?.outdated).toBe(true); }
  });
}
test("fully paginates check runs with stable total count", async () => {
  const { observation } = await scenario({ checks: "paginated" });
  expect(firstPull(observation).checks.status).toBe("available");
  expect(firstPull(observation).checks.value).toHaveLength(102);
});
for (const drift of ["head", "base", "viewer"] as const) {
  test(`preserves before/after ${drift} drift instead of rebinding old evidence`, async () => {
    const { observation } = await scenario({ drift }); const pull = firstPull(observation);
    if (drift === "viewer") expect(observation.viewerBefore.value).not.toBe(observation.viewerAfter.value);
    else {
      expect(pull.before.value?.[drift === "head" ? "headOid" : "baseOid"]).not.toBe(pull.after.value?.[drift === "head" ? "headOid" : "baseOid"]);
      expect(pull.reviews.binding).toEqual(pull.before.binding);
      expect(pull.reviews.binding).not.toEqual(pull.after.binding);
    }
  });
}
for (const policy of ["missing", "rules-unavailable", "malformed"] as const) {
  test(`never treats ${policy} required policy as an empty successful policy`, async () => {
    const { observation } = await scenario({ policy });
    expect(firstPull(observation).policy.status).toBe(policy === "malformed" ? "malformed" : "unavailable");
    expect(firstPull(observation).policy.value).toBeNull();
  });
}
test("distinguishes visible unprotected policy from unsupported merge-queue policy", async () => {
  const none = await scenario({ policy: "none" });
  expect(firstPull(none.observation).policy.status).toBe("available");
  expect(firstPull(none.observation).policy.value?.checks).toEqual([]);
  const unsupported = await scenario({ policy: "unsupported" });
  expect(firstPull(unsupported.observation).policy.value?.unsupported).toContain("ruleset:merge_queue");
});
test("fully paginates effective branch rules and does not hide the final unsupported policy", async () => {
  const { observation, requests } = await scenario({ policy: "paginated" });
  expect(firstPull(observation).policy.status).toBe("available");
  expect(firstPull(observation).policy.value?.unsupported).toContain("ruleset:merge_queue");
  expect(requests.filter(({ args }) => args.some((arg) => arg.includes("/rules/branches/")))).toHaveLength(2);
});
test("combines traditional and ruleset requirements without inventing eligibility", async () => {
  const { observation } = await scenario({ policy: "requirements" });
  const policy = firstPull(observation).policy.value;
  expect(policy?.checks).toEqual([{ context: "check-1", publisherId: 15368 }, { context: "rules-check", publisherId: 42 }, { context: "any-app-check", publisherId: null }]);
  expect(policy?.requiredApprovals).toBe(2);
  expect(policy?.unsupported).toContain("code-owner-eligibility-not-observed");
  expect(policy?.unsupported).toContain("latest-push-approver-eligibility-not-observed");
});
test("reads the separate signature requirement when it is omitted from traditional protection", async () => {
  const { observation, requests } = await scenario({ policy: "signatures" });
  expect(firstPull(observation).policy.status).toBe("available");
  expect(firstPull(observation).policy.value?.unsupported).toContain("branch-protection:required_signatures");
  expect(requests.some(({ args }) => args.some((arg) => arg.endsWith("/protection/required_signatures")))).toBe(true);
});
test("fully paginates legacy statuses and preserves a final pending context", async () => {
  const { observation } = await scenario({ pagination: "statuses" });
  const checks = firstPull(observation).checks;
  expect(checks.status).toBe("available");
  expect(checks.value).toHaveLength(102);
  expect(checks.value?.at(-1)?.context).toBe("last-status");
  expect(checks.value?.at(-1)?.state).toBe("pending");
});
for (const unsafe of ["not a URL", "http://ci.example/run/7", "https://user:private@ci.example/run/7"]) {
  test(`display-only URLs do not discard independent check evidence: ${unsafe.split(":")[0]}`, async () => {
    const { observation } = await scenario({ checkUrl: unsafe, statusUrl: unsafe });
    const checks = firstPull(observation).checks;
    expect(checks.status).toBe("available");
    expect(checks.value?.map(({ id, state, url }) => ({ id, state, url }))).toEqual([
      { id: "check:1", state: "passed", url: null },
      { id: "status:900", state: "passed", url: null },
    ]);
    expect(checks.value?.[0]?.publisherId).toBe(15368);
    expect(checks.value?.[1]?.publisherId).toBeNull();
  });
}
for (const checks of ["pending", "rate-limited", "unavailable", "malformed"] as const) {
  test(`retains ${checks} check evidence without fabricated success`, async () => {
    const { observation } = await scenario({ checks }); const value = firstPull(observation).checks;
    if (checks === "pending") { expect(value.status).toBe("available"); expect(value.value?.[0]?.state).toBe("pending"); }
    else { expect(value.status).toBe(checks); expect(value.value).toBeNull(); }
  });
}
for (const pagination of ["budget", "broken"] as const) {
  test(`bounds ${pagination} pagination and does not return a successful prefix`, async () => {
    const { observation, requests } = await scenario({ pagination });
    expect(firstPull(observation).reviews.status).toBe(pagination === "budget" ? "partial" : "malformed");
    expect(firstPull(observation).reviews.value).toBeNull();
    expect(requests.filter(({ args }) => args.some((arg) => arg.includes("RadarReviews"))).length).toBeLessThanOrEqual(10);
  });
}
test("bounds process output before parsing and suppresses raw diagnostics", async () => {
  const { observation } = await scenario({ overflow: true });
  expect(firstPull(observation).checks.status).toBe("partial");
  expect(firstPull(observation).checks.diagnostic).toBe("github-output-budget-exhausted");
});
test("cancellation waits for the owned gh process group, including an ignoring parent and descendant", async () => {
  const started = performance.now();
  const { observation, requests, rootPid, descendantPid } = await scenario({ cancel: true });
  expect(performance.now() - started).toBeLessThan(10_000);
  expect(firstPull(observation).reviews.status).toBe("unavailable");
  expect(firstPull(observation).reviews.diagnostic).toBe("observation-cancelled");
  expect(observation.viewerAfter.diagnostic).toBe("observation-cancelled");
  expect(requests).toHaveLength(3);
  for (const pid of [rootPid, descendantPid]) {
    if (pid === null) throw new Error("owned cancellation process identity missing");
    expect(() => process.kill(pid, 0)).toThrow();
  }
});
test("pre-aborted observation launches no provider reads", async () => {
  const controller = new AbortController(); controller.abort();
  const value = await observe({ repository: "acme/widget", pullRequests: [7] }, { signal: controller.signal });
  expect(value.viewerBefore.diagnostic).toBe("observation-cancelled");
  expect(firstPull(value).before.diagnostic).toBe("observation-cancelled");
});
test("public selection boundary rejects injection, duplicate and unbounded PR lists", async () => {
  for (const selection of [
    { repository: "acme/widget;echo BAD", pullRequests: [7] },
    { repository: "acme/../widget", pullRequests: [7] },
    { repository: "acme/widget", pullRequests: [7, 7] },
    { repository: "acme/widget", pullRequests: [0] },
    { repository: "acme/widget", pullRequests: Array.from({ length: 21 }, (_, index) => index + 1) },
    { repository: "acme/widget", pullRequests: ["7"] },
  ]) await expect(observe(selection as Selection)).rejects.toThrow();
});
for (const graphql of ["rate-limited", "permission", "malformed-review"] as const) {
  test(`rejects ${graphql} GraphQL data rather than manufacturing successful empty reviews`, async () => {
    const { observation } = await scenario({ graphql });
    const value = firstPull(observation).reviews;
    expect(value.status).toBe(graphql === "permission" ? "unavailable" : graphql === "malformed-review" ? "malformed" : "rate-limited");
    expect(value.value).toBeNull();
  });
}
test("public options boundary rejects a fabricated cancellation signal before spawning", async () => {
  await expect(observe({ repository: "acme/widget", pullRequests: [7] }, { signal: {} as AbortSignal })).rejects.toThrow();
});

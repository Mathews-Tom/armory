import { spawn } from "node:child_process";
import { performance } from "node:perf_hooks";
import { SCHEMA } from "../core/types.ts";
import type { Binding, Check, Observation, Publication, PullIdentity, PullObservation, RequiredPolicy, Review, ReviewThread, Selection, Source, SourceStatus } from "../core/types.ts";
import { validateSelection } from "../core/validation.ts";

// No implicit polling or retries: each refresh has one finite observation budget.
const MAX_REQUESTS = 320;
const MAX_PAGES = 10;
const MAX_ELAPSED_MS = 60_000;
const MAX_REQUEST_MS = 10_000;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_TOTAL_BYTES = 12 * 1024 * 1024;
const PAGE_SIZE = 100;
const OID = /^[a-f0-9]{40}$/u;
type ObjectValue = Record<string, unknown>;
class ReadFailure extends Error {
  constructor(readonly status: SourceStatus, readonly diagnostic: string) { super(diagnostic); }
}
function malformed(): never { throw new ReadFailure("malformed", "github-response-malformed"); }
function object(value: unknown): ObjectValue {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return malformed();
  return value as ObjectValue;
}
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : malformed(); }
function text(value: unknown): string { return typeof value === "string" && value.length > 0 && value.length <= 16_384 ? value : malformed(); }
function bool(value: unknown): boolean { return typeof value === "boolean" ? value : malformed(); }
function integer(value: unknown): number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : malformed(); }
function oid(value: unknown): string { const result = text(value); return OID.test(result) ? result : malformed(); }
function timestamp(value: unknown): number | null {
  if (value === null) return null;
  const iso = text(value);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/u.test(iso)) return malformed();
  const parsed = Date.parse(iso);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString() !== (iso.includes(".") ? iso : iso.replace("Z", ".000Z"))) return malformed();
  return parsed;
}
function url(value: unknown): string | null {
  if (value === null) return null;
  const result = text(value);
  try { const parsed = new URL(result); return parsed.protocol === "https:" && !parsed.username && !parsed.password ? result : malformed(); } catch { return malformed(); }
}
function displayUrl(value: unknown): string | null {
  try { return url(value); } catch (error) {
    if (error instanceof ReadFailure && error.status === "malformed") return null;
    throw error;
  }
}
function member<T extends string>(value: unknown, values: readonly T[]): T { return typeof value === "string" && values.includes(value as T) ? value as T : malformed(); }
function source<T>(reference: string, binding: Binding | null, status: SourceStatus, value: T | null, diagnostic: string | null = null): Source<T> {
  return { reference, binding, status, value, diagnostic, observedAt: Date.now() };
}
function groupExists(pid: number): boolean {
  try { process.kill(-pid, 0); return true; } catch (error) { return !(error instanceof Error && "code" in error && error.code === "ESRCH"); }
}
function signalGroup(pid: number, signal: NodeJS.Signals): void { try { process.kill(-pid, signal); } catch { /* The group may already have exited. */ } }
async function stopGroup(pid: number): Promise<boolean> {
  if (!groupExists(pid)) return true;
  signalGroup(pid, "SIGTERM");
  const start = performance.now();
  const { promise, resolve } = Promise.withResolvers<boolean>();
  const timer = setInterval(() => {
    const elapsed = performance.now() - start;
    if (elapsed >= 100) signalGroup(pid, "SIGKILL");
    if (!groupExists(pid) || elapsed >= 1_000) { clearInterval(timer); resolve(!groupExists(pid)); }
  }, 10);
  return await promise;
}

class Reader {
  private requests = 0;
  private bytes = 0;
  private readonly started = performance.now();
  constructor(private readonly signal?: AbortSignal) {}
  async read(args: readonly string[]): Promise<unknown> {
    if (this.signal?.aborted) throw new ReadFailure("unavailable", "observation-cancelled");
    if (process.platform === "win32") throw new ReadFailure("unavailable", "process-tree-cleanup-unsupported-platform");
    const remaining = MAX_ELAPSED_MS - (performance.now() - this.started);
    if (++this.requests > MAX_REQUESTS || remaining <= 0 || this.bytes >= MAX_TOTAL_BYTES) throw new ReadFailure("partial", "observation-budget-exhausted");
    const pending = Promise.withResolvers<{ output: string; diagnostic: string | null; status: SourceStatus }>();
    const { resolve } = pending;
      const child = spawn("gh", ["api", "--hostname", "github.com", ...args], { detached: true, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, GH_PROMPT_DISABLED: "1", GH_PAGER: "cat", PAGER: "cat" } });
      const chunks: Buffer[] = [];
      let stderr = "";
      let size = 0;
      let cause: string | null = null;
      let settled = false;
      let cleanup: Promise<boolean> | null = null;
      let finishTimer: NodeJS.Timeout | undefined;
      const stop = (reason: string) => {
        cause ??= reason;
        if (child.pid && !cleanup) cleanup = stopGroup(child.pid);
        finishTimer ??= setTimeout(() => { void finish(null); }, 1_100);
      };
      const abort = () => stop("observation-cancelled");
      const timer = setTimeout(() => stop("github-request-timeout"), Math.min(MAX_REQUEST_MS, remaining));
      const finish = async (code: number | null) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.signal?.removeEventListener("abort", abort);
        if (child.pid && !cleanup && groupExists(child.pid)) cleanup = stopGroup(child.pid);
        const stopped = cleanup ? await cleanup : true;
        clearTimeout(finishTimer);
        child.stdout.destroy(); child.stderr.destroy();
        child.unref();
        if (!stopped) { resolve({ output: "", status: "unavailable", diagnostic: "github-process-cleanup-unconfirmed" }); return; }
        if (cause) { resolve({ output: "", status: cause.includes("budget") || cause.includes("output") ? "partial" : "unavailable", diagnostic: cause }); return; }
        if (code !== 0) {
          const rateLimited = /rate.?limit|HTTP 429|secondary rate/iu.test(stderr);
          const missing = /HTTP 404/iu.test(stderr);
          resolve({ output: "", status: rateLimited ? "rate-limited" : "unavailable", diagnostic: rateLimited ? "github-rate-limited" : missing ? "github-not-found-or-not-visible" : "github-read-unavailable" });
          return;
        }
        resolve({ output: Buffer.concat(chunks).toString("utf8"), status: "available", diagnostic: null });
      };
      child.stdout.on("data", (chunk: Buffer) => {
        size += chunk.length; this.bytes += chunk.length;
        if (size > MAX_RESPONSE_BYTES || this.bytes > MAX_TOTAL_BYTES) stop("github-output-budget-exhausted");
        else chunks.push(chunk);
      });
      child.stderr.on("data", (chunk: Buffer) => {
        size += chunk.length; this.bytes += chunk.length;
        if (size > MAX_RESPONSE_BYTES || this.bytes > MAX_TOTAL_BYTES) stop("github-output-budget-exhausted");
        else if (stderr.length < 16_384) stderr += chunk.toString("utf8").slice(0, 16_384 - stderr.length);
      });
      child.once("error", () => { cause ??= "github-process-unavailable"; void finish(null); });
      child.once("close", (code) => { void finish(code); });
      this.signal?.addEventListener("abort", abort, { once: true });
      if (this.signal?.aborted) abort();
    const result = await pending.promise;
    if (result.diagnostic) throw new ReadFailure(result.status, result.diagnostic);
    try { return JSON.parse(result.output) as unknown; } catch { return malformed(); }
  }
  rest(path: string): Promise<unknown> { return this.read(["--method", "GET", path]); }
  async graphql(query: string, selection: Selection, number: number, cursor: string | null = null): Promise<ObjectValue> {
    const [owner, name] = selection.repository.split("/");
    const args = ["graphql", "-f", `query=${query}`, "-f", `owner=${owner}`, "-f", `name=${name}`, "-F", `number=${number}`];
    if (cursor !== null) args.push("-f", `cursor=${cursor}`);
    const response = object(await this.read(args));
    if (response.errors !== undefined) {
      const errors = array(response.errors);
      if (errors.length > 0) {
        const limited = errors.some((error) => object(error).type === "RATE_LIMITED");
        throw new ReadFailure(limited ? "rate-limited" : "unavailable", limited ? "github-rate-limited" : "github-graphql-unavailable");
      }
    }
    const data = object(response.data);
    if (text(object(data.repository).nameWithOwner).toLowerCase() !== selection.repository.toLowerCase()) return malformed();
    return data;
  }
}

const IDENTITY_QUERY = `query RadarIdentity($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$number){number url title state headRefOid baseRefOid headRefName baseRefName headRepository{nameWithOwner} isDraft mergeable mergeCommit{oid}}}}`;
const REVIEWS_QUERY = `query RadarReviews($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$number){reviews(first:100,after:$cursor){nodes{id author{... on Node{id}} state commit{oid} submittedAt} pageInfo{hasNextPage endCursor}}}}}`;
const THREADS_QUERY = `query RadarThreads($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$number){reviewThreads(first:100,after:$cursor){nodes{id isResolved isOutdated} pageInfo{hasNextPage endCursor}}}}}`;
function pull(data: ObjectValue): ObjectValue { return object(object(data.repository).pullRequest); }
function identity(value: ObjectValue, number: number): PullIdentity {
  if (integer(value.number) !== number) return malformed();
  const parsedUrl = url(value.url);
  if (!parsedUrl) return malformed();
  return { number, url: parsedUrl, title: text(value.title), state: member(value.state, ["OPEN", "CLOSED", "MERGED"]), headOid: oid(value.headRefOid), baseOid: oid(value.baseRefOid), headRef: text(value.headRefName), baseRef: text(value.baseRefName), headRepository: value.headRepository === null ? null : text(object(value.headRepository).nameWithOwner), draft: bool(value.isDraft), mergeable: member(value.mergeable, ["MERGEABLE", "CONFLICTING", "UNKNOWN"]), mergeCommitOid: value.mergeCommit === null ? null : oid(object(value.mergeCommit).oid) };
}
async function capture<T>(reference: string, binding: Binding | null, read: () => Promise<T>): Promise<Source<T>> {
  try { return source(reference, binding, "available", await read()); } catch (error) {
    if (error instanceof ReadFailure) return source<T>(reference, binding, error.status, null, error.diagnostic);
    return source<T>(reference, binding, "malformed", null, "github-response-malformed");
  }
}
async function connection<T>(reader: Reader, selection: Selection, number: number, kind: "reviews" | "reviewThreads", parse: (value: ObjectValue) => T): Promise<T[]> {
  const results: T[] = [];
  const ids = new Set<string>();
  const cursors = new Set<string>();
  let cursor: string | null = null;
  for (let page = 0; page < MAX_PAGES; page++) {
    const data = pull(await reader.graphql(kind === "reviews" ? REVIEWS_QUERY : THREADS_QUERY, selection, number, cursor));
    const connection = object(data[kind]);
    const nodes = array(connection.nodes);
    if (nodes.length > PAGE_SIZE) return malformed();
    for (const node of nodes) {
      const value = object(node); const id = text(value.id);
      if (ids.has(id)) return malformed();
      ids.add(id); results.push(parse(value));
    }
    const info = object(connection.pageInfo);
    if (!bool(info.hasNextPage)) return results;
    cursor = text(info.endCursor);
    if (nodes.length === 0 || cursors.has(cursor)) return malformed();
    cursors.add(cursor);
  }
  throw new ReadFailure("partial", "github-pagination-budget-exhausted");
}
async function restPages(reader: Reader, path: string, field?: string): Promise<unknown[]> {
  const result: unknown[] = [];
  let total: number | null = null;
  for (let page = 1; page <= MAX_PAGES; page++) {
    const value = await reader.rest(`${path}${path.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
    const values = field ? array(object(value)[field]) : array(value);
    if (values.length > PAGE_SIZE) return malformed();
    if (field) {
      const count = integer(object(value).total_count);
      if (total !== null && count !== total) throw new ReadFailure("partial", "github-pagination-changed");
      total = count;
    }
    result.push(...values);
    if (values.length < PAGE_SIZE) {
      if (total !== null && total !== result.length) throw new ReadFailure("partial", "github-pagination-incomplete");
      return result;
    }
  }
  throw new ReadFailure("partial", "github-pagination-budget-exhausted");
}
function checkState(status: unknown, conclusion: unknown): Check["state"] {
  const current = member(status, ["queued", "in_progress", "completed", "waiting", "requested", "pending"]);
  if (current !== "completed") { if (conclusion !== null) return malformed(); return "pending"; }
  switch (member(conclusion, ["success", "neutral", "skipped", "failure", "timed_out", "action_required", "cancelled", "stale", "startup_failure"])) {
    case "success": case "neutral": case "skipped": return "passed";
    case "cancelled": return "cancelled";
    default: return "failed";
  }
}
async function checks(reader: Reader, repository: string, headOid: string): Promise<Check[]> {
  const runs = await restPages(reader, `repos/${repository}/commits/${headOid}/check-runs?filter=latest`, "check_runs");
  const statuses = await restPages(reader, `repos/${repository}/commits/${headOid}/statuses`);
  const results = runs.map((item): Check => {
    const value = object(item);
    // A check-suite's PR base association is mutable; it is not an attestation
    // that this run actually tested that base. Never promote it to testedBaseOid.
    if (oid(value.head_sha) !== headOid) return malformed();
    return { id: `check:${integer(value.id)}`, context: text(value.name), publisherId: integer(object(value.app).id), state: checkState(value.status, value.conclusion), headOid, testedBaseOid: null, url: displayUrl(value.html_url), completedAt: timestamp(value.completed_at) };
  });
  // The REST status list is newest-first. Keep the current value of each legacy
  // context; a status creator's user id is NOT a GitHub App publisher id.
  const contexts = new Set<string>();
  for (const item of statuses) {
    const value = object(item);
    const context = text(value.context);
    const state = member(value.state, ["error", "failure", "pending", "success"]);
    const id = integer(value.id);
    const completedAt = timestamp(value.updated_at);
    const target = displayUrl(value.target_url);
    if (!contexts.has(context)) {
      contexts.add(context);
      results.push({ id: `status:${id}`, context, publisherId: null, state: state === "success" ? "passed" : state === "pending" ? "pending" : "failed", headOid, testedBaseOid: null, url: target, completedAt });
    }
  }
  if (new Set(results.map((value) => value.id)).size !== results.length) return malformed();
  return results;
}
function checkRequirement(context: unknown, app: unknown): { context: string; publisherId: number | null } {
  const id = app === null || app === -1 ? null : integer(app);
  return { context: text(context), publisherId: id };
}
async function policy(reader: Reader, repository: string, baseRef: string): Promise<RequiredPolicy> {
  const branchPath = `repos/${repository}/branches/${encodeURIComponent(baseRef)}`;
  const branch = object(await reader.rest(branchPath));
  const protectedBranch = bool(branch.protected);
  let protection: ObjectValue | null = null;
  try { protection = object(await reader.rest(`${branchPath}/protection`)); } catch (error) {
    // A 404 alone does not establish absence: it also conceals permissions.
    if (!(error instanceof ReadFailure && error.diagnostic === "github-not-found-or-not-visible" && !protectedBranch)) throw error;
  }
  const rules = await restPages(reader, `repos/${repository}/rules/branches/${encodeURIComponent(baseRef)}`);
  const result: RequiredPolicy = { checks: [], requiredApprovals: 0, requireCodeOwnerReview: false, requireLatestApproval: false, dismissStaleReviews: false, strict: false, unsupported: [] };
  const requiredChecks: { context: string; publisherId: number | null }[] = [];
  const unsupported: string[] = [];
  if (protection) {
    if (!url(protection.url)) return malformed();
    // GitHub omits disabled traditional requirements from a visible protection
    // document. Missing documents/permissions are never treated as empty.
    if (protection.required_status_checks !== undefined && protection.required_status_checks !== null) {
      const status = object(protection.required_status_checks);
      result.strict = bool(status.strict);
      for (const item of array(status.checks)) { const value = object(item); requiredChecks.push(checkRequirement(value.context, value.app_id)); }
      // Older API responses without app-aware checks cannot establish publisher identity.
      for (const context of array(status.contexts)) {
        const name = text(context);
        if (!requiredChecks.some((check) => check.context === name)) unsupported.push("legacy-required-check-publisher-unavailable");
      }
    }
    if (protection.required_pull_request_reviews !== undefined && protection.required_pull_request_reviews !== null) {
      const reviews = object(protection.required_pull_request_reviews);
      result.requiredApprovals = integer(reviews.required_approving_review_count);
      result.requireCodeOwnerReview = bool(reviews.require_code_owner_reviews);
      result.requireLatestApproval = bool(reviews.require_last_push_approval);
      result.dismissStaleReviews = bool(reviews.dismiss_stale_reviews);
    }
    if (protection.required_signatures === undefined) {
      protection.required_signatures = object(await reader.rest(`${branchPath}/protection/required_signatures`));
    }
    for (const key of ["required_signatures", "required_linear_history", "required_conversation_resolution", "lock_branch"]) {
      if (protection[key] !== undefined && bool(object(protection[key]).enabled)) unsupported.push(`branch-protection:${key}`);
    }
    if (protection.restrictions !== undefined && protection.restrictions !== null) unsupported.push("branch-protection:push-restrictions");
  }
  for (const item of rules) {
    const rule = object(item);
    const type = text(rule.type);
    if (type === "required_status_checks") {
      const parameters = object(rule.parameters);
      result.strict = bool(parameters.strict_required_status_checks_policy) || result.strict;
      for (const item of array(parameters.required_status_checks)) {
        const check = object(item); requiredChecks.push(checkRequirement(check.context, check.integration_id === undefined ? null : check.integration_id));
      }
      if (parameters.do_not_enforce_on_create === true) unsupported.push("ruleset:do-not-enforce-on-create");
    } else if (type === "pull_request") {
      const parameters = object(rule.parameters);
      result.requiredApprovals = Math.max(result.requiredApprovals, integer(parameters.required_approving_review_count));
      result.requireCodeOwnerReview = bool(parameters.require_code_owner_review) || result.requireCodeOwnerReview;
      result.requireLatestApproval = bool(parameters.require_last_push_approval) || result.requireLatestApproval;
      result.dismissStaleReviews = bool(parameters.dismiss_stale_reviews_on_push) || result.dismissStaleReviews;
      if (bool(parameters.required_review_thread_resolution)) unsupported.push("ruleset:required-review-thread-resolution");
      if (parameters.allowed_merge_methods !== undefined) unsupported.push("ruleset:allowed-merge-methods");
    } else unsupported.push(`ruleset:${type.replace(/[^a-z0-9_]/gu, "_").slice(0, 80)}`);
  }
  if (result.requireCodeOwnerReview) unsupported.push("code-owner-eligibility-not-observed");
  if (result.requireLatestApproval) unsupported.push("latest-push-approver-eligibility-not-observed");
  result.checks = requiredChecks.filter((value, index) => requiredChecks.findIndex((other) => other.context === value.context && other.publisherId === value.publisherId) === index);
  result.unsupported = [...new Set(unsupported)];
  return result;
}

/** Observe explicitly selected PRs through existing gh authentication. Never writes provider state. */
export async function observe(input: Selection, options: { signal?: AbortSignal } = {}): Promise<Observation> {
  const selection = validateSelection(input);
  if (options === null || typeof options !== "object" || (options.signal !== undefined && !(options.signal instanceof AbortSignal))) throw new Error("invalid-delivery-radar-options");
  const startedAt = Date.now();
  const reader = new Reader(options.signal);
  const viewer = () => capture("github:viewer", null, async () => text(object(await reader.rest("user")).node_id));
  const viewerBefore = await viewer();
  const pulls: PullObservation[] = [];
  for (const number of selection.pullRequests) {
    const reference = `github:${selection.repository}#${number}`;
    const readIdentity = () => capture(`${reference}:identity`, null, async () => identity(pull(await reader.graphql(IDENTITY_QUERY, selection, number)), number));
    const before = await readIdentity();
    const binding: Binding | null = before.value && viewerBefore.value ? { repository: selection.repository, pullRequest: number, headOid: before.value.headOid, baseOid: before.value.baseOid, viewerId: viewerBefore.value } : null;
    before.binding = binding;
    const unavailable = <T>(kind: string) => source<T>(`${reference}:${kind}`, binding, "unavailable", null, "pr-or-viewer-identity-unavailable");
    const reviews = binding ? await capture(`${reference}:reviews`, binding, () => connection<Review>(reader, selection, number, "reviews", (value) => ({ id: text(value.id), reviewerId: text(object(value.author).id), state: member(value.state, ["APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"]), commitOid: value.commit === null ? null : oid(object(value.commit).oid), submittedAt: timestamp(value.submittedAt) }))) : unavailable<Review[]>("reviews");
    const threads = binding ? await capture(`${reference}:threads`, binding, () => connection<ReviewThread>(reader, selection, number, "reviewThreads", (value) => ({ id: text(value.id), resolved: bool(value.isResolved), outdated: bool(value.isOutdated) }))) : unavailable<ReviewThread[]>("threads");
    const checkSource = binding ? await capture(`${reference}:checks@${binding.headOid}`, binding, () => checks(reader, selection.repository, binding.headOid)) : unavailable<Check[]>("checks");
    if (checkSource.status === "available") checkSource.diagnostic = "head-only-checks-do-not-establish-tested-base";
    const baseRef = before.value?.baseRef;
    const policySource = binding && baseRef !== undefined ? await capture(`${reference}:policy@${baseRef}`, binding, () => policy(reader, selection.repository, baseRef)) : unavailable<RequiredPolicy>("policy");
    const publication = source<Publication>(`${reference}:publication`, binding, "not-selected", null, "artifact-provenance-source-not-selected");
    const after = await readIdentity();
    if (after.value && viewerBefore.value) after.binding = { repository: selection.repository, pullRequest: number, headOid: after.value.headOid, baseOid: after.value.baseOid, viewerId: viewerBefore.value };
    pulls.push({ before, after, reviews, threads, checks: checkSource, policy: policySource, publication });
  }
  const viewerAfter = await viewer();
  return { schema: SCHEMA, selection, viewerBefore, viewerAfter, startedAt, finishedAt: Date.now(), pulls };
}

import type { Check, Publication, PullIdentity, RequiredPolicy, Review, ReviewThread, Selection } from "./types.ts";

export const MAX_SELECTED_PULLS = 20;
export const DEFAULT_MAX_AGE_MS = 300_000;
const REPOSITORY = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9_.-]{1,100}$/;
const OID = /^[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$/;

export function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= 4096;
}

export function repository(value: unknown): value is string {
  return typeof value === "string" && REPOSITORY.test(value) && !/\s/.test(value) && !value.split("/").some((part) => part === "." || part === "..");
}

export function oid(value: unknown): value is string {
  return typeof value === "string" && (value.length === 40 || value.length === 64) && OID.test(value);
}

export function timestamp(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= 8_640_000_000_000_000 ? value : null;
}

export function validateSelection(value: unknown): Selection {
  if (!record(value) || Object.keys(value).some((key) => key !== "repository" && key !== "pullRequests") || !repository(value.repository)) {
    throw new TypeError("selection requires an explicit owner/repository and pullRequests");
  }
  const numbers = value.pullRequests;
  if (!Array.isArray(numbers) || numbers.length === 0 || numbers.length > MAX_SELECTED_PULLS || numbers.some((number) => !Number.isSafeInteger(number) || number <= 0) || new Set(numbers).size !== numbers.length) {
    throw new TypeError(`select 1–${MAX_SELECTED_PULLS} unique positive PR numbers`);
  }
  return { repository: value.repository, pullRequests: [...numbers] };
}

function nullableText(value: unknown): boolean { return value === null || text(value); }
function nullableOid(value: unknown): boolean { return value === null || oid(value); }
function dateOrNull(value: unknown): boolean { return value === null || timestamp(value) !== null; }
function publisher(value: unknown): boolean { return value === null || (Number.isSafeInteger(value) && (value as number) > 0); }
export function validUrl(value: unknown): boolean { return typeof value === "string" && /^https:\/\/[^\s/?#]+(?:\/[^\s]*)?$/.test(value) && provenance(value); }

export function identity(value: unknown): value is PullIdentity {
  return record(value) && Number.isSafeInteger(value.number) && (value.number as number) > 0 && validUrl(value.url) && typeof value.title === "string" && value.title.length <= 4096 &&
    ["OPEN", "CLOSED", "MERGED"].includes(value.state as string) && oid(value.headOid) && oid(value.baseOid) && text(value.headRef) && text(value.baseRef) &&
    (value.headRepository === null || repository(value.headRepository)) && typeof value.draft === "boolean" && ["MERGEABLE", "CONFLICTING", "UNKNOWN"].includes(value.mergeable as string) && nullableOid(value.mergeCommitOid);
}

function list<T extends { id: string }>(value: unknown, valid: (item: unknown) => item is T): value is T[] {
  return Array.isArray(value) && value.length <= 10_000 && value.every(valid) && new Set(value.map((item) => item.id)).size === value.length;
}

export function reviews(value: unknown): value is readonly Review[] {
  return list(value, (item): item is Review => record(item) && text(item.id) && text(item.reviewerId) &&
    ["APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"].includes(item.state as string) && nullableOid(item.commitOid) && dateOrNull(item.submittedAt) &&
    (item.state === "PENDING" || item.submittedAt !== null));
}

export function threads(value: unknown): value is readonly ReviewThread[] {
  return list(value, (item): item is ReviewThread => record(item) && text(item.id) && typeof item.resolved === "boolean" && typeof item.outdated === "boolean");
}

export function checks(value: unknown): value is readonly Check[] {
  return list(value, (item): item is Check => record(item) && text(item.id) && text(item.context) && publisher(item.publisherId) &&
    ["pending", "passed", "failed", "cancelled", "unknown"].includes(item.state as string) && oid(item.headOid) && nullableOid(item.testedBaseOid) &&
    (item.url === null || validUrl(item.url)) && dateOrNull(item.completedAt) && (item.state !== "passed" || item.completedAt !== null));
}

export function policy(value: unknown): value is RequiredPolicy {
  if (!record(value) || !Array.isArray(value.checks) || value.checks.length > 1000 || !value.checks.every((item) => record(item) && text(item.context) && publisher(item.publisherId)) ||
    !Number.isSafeInteger(value.requiredApprovals) || (value.requiredApprovals as number) < 0 || (value.requiredApprovals as number) > 1000 ||
    ![value.requireCodeOwnerReview, value.requireLatestApproval, value.dismissStaleReviews, value.strict].every((item) => typeof item === "boolean") ||
    !Array.isArray(value.unsupported) || value.unsupported.length > 1000 || !value.unsupported.every(text)) return false;
  return new Set(value.checks.map((item) => JSON.stringify([item.context, item.publisherId]))).size === value.checks.length;
}

export function publication(value: unknown): value is Publication {
  return record(value) && ["published", "pending", "failed", "unknown"].includes(value.state as string) && nullableOid(value.commitOid) &&
    Array.isArray(value.artifactIds) && value.artifactIds.length <= 1000 && value.artifactIds.every(text) && new Set(value.artifactIds).size === value.artifactIds.length &&
    (value.url === null || validUrl(value.url));
}

export function provenance(value: unknown): boolean {
  return text(value) && [...value].every((character) => {
    const code = character.charCodeAt(0);
    return code > 31 && (code < 127 || code > 159);
  });
}

export function diagnostic(value: unknown): boolean { return nullableText(value); }

import type { Applicability, Artifact, ExecutionStatus } from "./index.ts";
import { assertExecutionId } from "./validation.ts";

export interface NativeReceiptProjection {
  executionId: string;
  status: ExecutionStatus;
  applicability: Applicability;
  proof: boolean;
  output: Pick<Artifact, "sha256" | "capturedBytes" | "totalBytes" | "truncated">;
}

export type NativeObservation = NativeReceiptProjection
  | { receipts: NativeReceiptProjection[] }
  | { error: "invalid-arguments" | "operation-failed" };

// Match the private store's record limit. Refuse overflow rather than silently
// omit historical evidence; each projection contains only fixed-size metadata.
const MAX_RECEIPTS = 10_000;
const MAX_CAPTURED_BYTES = 16 * 1024 * 1024;

function reject(): never {
  throw new Error("invalid native receipt observation");
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) reject();
  const prototype: unknown = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) reject();
  return value as Record<string, unknown>;
}

function exact(value: Record<string, unknown>, keys: readonly string[]): Record<string, unknown> {
  const names = Reflect.ownKeys(value);
  if (names.length !== keys.length || names.some((key) => typeof key !== "string" || !keys.includes(key))) reject();
  const result: Record<string, unknown> = {};
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (descriptor === undefined || !("value" in descriptor)) reject();
    result[key] = descriptor.value as unknown;
  }
  return result;
}

function integer(value: unknown, maximum = Number.MAX_SAFE_INTEGER): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > maximum) reject();
}

function projection(value: unknown): NativeReceiptProjection {
  const item = exact(object(value), ["executionId", "status", "applicability", "proof", "output"]);
  if (typeof item.executionId !== "string") reject();
  assertExecutionId(item.executionId);
  if (item.status !== "passed" && item.status !== "failed" && item.status !== "cancelled" && item.status !== "incomplete") reject();
  if (item.applicability !== "current" && item.applicability !== "stale" && item.applicability !== "unknown") reject();
  if (typeof item.proof !== "boolean" || (item.proof && (item.status !== "passed" || item.applicability !== "current"))) reject();
  const output = exact(object(item.output), ["sha256", "capturedBytes", "totalBytes", "truncated"]);
  if (typeof output.sha256 !== "string" || !/^[a-f0-9]{64}$/u.test(output.sha256)) reject();
  integer(output.capturedBytes, MAX_CAPTURED_BYTES);
  if (output.totalBytes === null || output.truncated === null) {
    // Only interrupted-owner reconciliation has unknown output completeness.
    if (output.totalBytes !== null || output.truncated !== null || item.status !== "incomplete" || item.applicability !== "unknown" || item.proof) reject();
  } else {
    integer(output.totalBytes);
    if (output.totalBytes < output.capturedBytes || typeof output.truncated !== "boolean" || output.truncated !== (output.totalBytes > output.capturedBytes)) reject();
  }
  return {
    executionId: item.executionId, status: item.status, applicability: item.applicability, proof: item.proof,
    output: { sha256: output.sha256, capturedBytes: output.capturedBytes, totalBytes: output.totalBytes, truncated: output.truncated },
  };
}

/** Validate both sides of the private-helper boundary, never forwarding input. */
export function parseNativeObservation(value: unknown): NativeObservation {
  try {
    const item = object(value);
    if (Object.hasOwn(item, "error")) {
      const error = exact(item, ["error"]).error;
      if (error !== "invalid-arguments" && error !== "operation-failed") reject();
      return { error };
    }
    if (Object.hasOwn(item, "receipts")) {
      const values = exact(item, ["receipts"]).receipts;
      if (!Array.isArray(values)) reject();
      const length = values.length;
      integer(length, MAX_RECEIPTS);
      const receipts: NativeReceiptProjection[] = [];
      for (let index = 0; index < length; index++) receipts.push(projection(values[index] as unknown));
      return { receipts };
    }
    return projection(item);
  } catch {
    // Even accessors/proxies and foreign errors cannot disclose private values.
    return reject();
  }
}

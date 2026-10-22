import { afterEach, expect, test } from "bun:test";
import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { chmod, link, lstat, mkdir, mkdtemp, readFile, realpath, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { CORE_VERSION, FEATURE, FEATURE_VERSION } from "../core/index.ts";
import type { Configuration, Context, Receipt, RepositoryIdentity, RunPlan } from "../core/index.ts";
import { captureSnapshot, loadConfiguration, resolveRepository } from "../helpers/scope.ts";
import { createStore } from "../helpers/storage.ts";
import type { ReceiptStore } from "../helpers/storage.ts";

const exec = promisify(execFile);
const temporary: string[] = [];
afterEach(async () => {
  for (const path of temporary.splice(0)) await rm(path, { recursive: true, force: true });
});

interface Fixture {
  base: string;
  dataRoot: string;
  repository: RepositoryIdentity;
  context: Context;
  store: ReceiptStore;
  plan: RunPlan;
}

async function fixture(): Promise<Fixture> {
  const base = await realpath(await mkdtemp(join(tmpdir(), "receipt-storage-")));
  temporary.push(base);
  const repositoryRoot = join(base, "repository");
  await mkdir(repositoryRoot);
  await exec("git", ["init", "--quiet", repositoryRoot], { timeout: 5000 });
  const config: Configuration = { schemaVersion: 1, configId: "storage-tests", gates: {
    check: { criterionId: "private-persistence", kind: "unit", executable: process.execPath, args: ["--version"], cwd: ".", timeoutMs: 5000, maxOutputBytes: 1024, requiresCompleteOutput: true, scope: { paths: ["input.txt"], configPaths: [], environmentNames: [], datasetIdentity: null } },
  } };
  await writeFile(join(repositoryRoot, "receipts.json"), JSON.stringify(config));
  await writeFile(join(repositoryRoot, "input.txt"), "input");
  const repository = await resolveRepository(repositoryRoot);
  const context: Context = { host: "standalone", sessionId: "storage-test-session", accountId: "test-account", workContext: "test-work" };
  const dataRoot = join(base, "private-state");
  const store = await createStore(dataRoot, repository, context);
  const loaded = await loadConfiguration(repositoryRoot, "receipts.json");
  const gate = config.gates.check;
  if (!gate) throw new Error("test fixture gate missing");
  const before = await captureSnapshot(repositoryRoot, gate.scope, "receipts.json", store.key);
  const plan: RunPlan = {
    schemaVersion: 1, feature: FEATURE, featureVersion: FEATURE_VERSION, coreVersion: CORE_VERSION,
    executionId: randomUUID(), repository, context, gateId: "check", gate, configId: config.configId,
    configPath: loaded.configPath, configDigest: loaded.configDigest, before, startedAtMs: Date.now(),
  };
  return { base, dataRoot, repository, context, store, plan };
}

async function finalized(fixture: Fixture, output = "private output\n"): Promise<Receipt> {
  const lease = await fixture.store.reserve(fixture.plan);
  const bytes = Buffer.from(output);
  await writeFile(lease.outputPath, bytes, { mode: 0o600, flag: "wx" });
  const finishedAtMs = Math.max(Date.now(), fixture.plan.startedAtMs);
  const receipt: Receipt = {
    schemaVersion: 1, plan: fixture.plan,
    result: { status: "passed", exitCode: 0, signal: null, reason: null, descendantsStopped: true },
    after: fixture.plan.before,
    artifact: { file: "output.bin", sha256: createHash("sha256").update(bytes).digest("hex"), capturedBytes: bytes.byteLength, totalBytes: bytes.byteLength, truncated: false },
    finishedAtMs, durationMs: finishedAtMs - fixture.plan.startedAtMs, applicability: "current", applicabilityReason: null,
  };
  await fixture.store.finalize(lease, receipt);
  return receipt;
}

test("finalized receipts and private key reload across sessions without losing records or artifact integrity", async () => {
  const f = await fixture();
  const receipt = await finalized(f);
  const reopened = await createStore(f.dataRoot, f.repository, { ...f.context, sessionId: "next-session" });
  expect(Buffer.from(reopened.key)).toEqual(Buffer.from(f.store.key));
  expect(await reopened.read(f.plan.executionId)).toEqual(receipt);
  expect(await reopened.list()).toEqual([receipt]);
  expect(await reopened.reconcile()).toEqual([]);
  expect((await lstat(reopened.root)).mode & 0o777).toBe(0o700);
  expect((await lstat(join(reopened.root, "receipts", `${f.plan.executionId}.json`))).mode & 0o777).toBe(0o600);
  const other = await createStore(f.dataRoot, f.repository, { ...f.context, accountId: "different-account" });
  expect(other.root).not.toBe(reopened.root);
  expect(await other.list()).toEqual([]);
  await expect(reopened.read("../escape")).rejects.toThrow();
  const artifact = join(reopened.root, "runs", f.plan.executionId, "artifacts", "output.bin");
  await writeFile(artifact, "altered");
  await expect(reopened.read(f.plan.executionId)).rejects.toThrow();
  await expect(reopened.reconcile()).rejects.toThrow();
});

test("concurrent reservations enforce exclusive IDs and finalization cannot overwrite a receipt", async () => {
  const f = await fixture();
  const second = await createStore(f.dataRoot, f.repository, f.context);
  const attempts = await Promise.allSettled([f.store.reserve(f.plan), second.reserve(f.plan)]);
  const winners = attempts.filter((result) => result.status === "fulfilled");
  expect(winners).toHaveLength(1);
  expect(attempts.filter((result) => result.status === "rejected")).toHaveLength(1);
  const winner = winners[0];
  if (!winner || winner.status !== "fulfilled") throw new Error("exclusive reservation missing");
  const lease = winner.value;
  await writeFile(lease.outputPath, "captured", { mode: 0o600, flag: "wx" });
  const finishedAtMs = Math.max(Date.now(), f.plan.startedAtMs);
  const receipt: Receipt = {
    schemaVersion: 1, plan: f.plan, result: { status: "passed", exitCode: 0, signal: null, reason: null, descendantsStopped: true }, after: f.plan.before,
    artifact: { file: "output.bin", sha256: createHash("sha256").update("captured").digest("hex"), capturedBytes: 8, totalBytes: 8, truncated: false },
    finishedAtMs, durationMs: finishedAtMs - f.plan.startedAtMs, applicability: "current", applicabilityReason: null,
  };
  await expect(f.store.finalize(lease, { ...receipt, artifact: { ...receipt.artifact, sha256: "0".repeat(64) } })).rejects.toThrow();
  await f.store.finalize(lease, receipt);
  const record = join(f.store.root, "receipts", `${f.plan.executionId}.json`);
  const saved = await readFile(record);
  await expect(second.finalize(lease, { ...receipt, result: { ...receipt.result, status: "failed", exitCode: 1 } })).rejects.toThrow();
  expect(await readFile(record)).toEqual(saved);
  expect(await second.read(f.plan.executionId)).toEqual(receipt);
});

test("publication aliases are readable before unlink while unrelated hard links remain rejected", async () => {
  const f = await fixture();
  const receipt = await finalized(f);
  const record = join(f.store.root, "receipts", `${f.plan.executionId}.json`);
  const artifact = join(f.store.root, "runs", f.plan.executionId, "artifacts", "output.bin");
  const key = join(f.store.root, "key.bin");
  // Hold the exact real post-link/pre-unlink state deterministically. No sleeps
  // or scheduling assumptions are needed to exercise this publication boundary.
  const aliases = [
    [key, join(f.store.root, `.pending-key.bin-${randomUUID()}`)],
    [record, join(f.store.root, "receipts", `.pending-${f.plan.executionId}.json-${randomUUID()}`)],
    [artifact, join(f.store.root, "runs", f.plan.executionId, "artifacts", `.pending-output.bin-${randomUUID()}`)],
  ] as const;
  for (const [target, alias] of aliases) await link(target, alias);
  const reopened = await createStore(f.dataRoot, f.repository, f.context);
  expect(await reopened.read(f.plan.executionId)).toEqual(receipt);
  expect(await reopened.list()).toEqual([receipt]);
  for (const [, alias] of aliases) await unlink(alias);
  expect(await reopened.read(f.plan.executionId)).toEqual(receipt);
  const foreignAlias = join(f.base, "foreign-record-alias");
  await link(record, foreignAlias);
  await expect(reopened.read(f.plan.executionId)).rejects.toThrow("foreign hard links");
  expect(await readFile(foreignAlias)).toEqual(await readFile(record));
  await unlink(foreignAlias);
  const wrongDestinationAlias = join(f.store.root, "receipts", `.pending-other.json-${randomUUID()}`);
  await link(record, wrongDestinationAlias);
  await expect(reopened.read(f.plan.executionId)).rejects.toThrow("foreign hard links");
});

test("foreign files, symlinks, permissive directories, and in-repository roots are never repaired or overwritten", async () => {
  const f = await fixture();
  await expect(createStore(join(f.repository.worktreeRoot, "state"), f.repository, f.context)).rejects.toThrow();
  const publicRoot = join(f.base, "public-state");
  await mkdir(publicRoot, { mode: 0o755 });
  await chmod(publicRoot, 0o755);
  await expect(createStore(publicRoot, f.repository, f.context)).rejects.toThrow();
  expect((await lstat(publicRoot)).mode & 0o777).toBe(0o755);
  const foreign = join(f.base, "foreign.txt");
  await writeFile(foreign, "must remain unchanged", { mode: 0o600 });
  const keyPath = join(f.store.root, "key.bin");
  await unlink(keyPath);
  await symlink(foreign, keyPath);
  await expect(createStore(f.dataRoot, f.repository, f.context)).rejects.toThrow();
  expect(await readFile(foreign, "utf8")).toBe("must remain unchanged");
  expect((await lstat(keyPath)).isSymbolicLink()).toBe(true);
  await unlink(keyPath);
  await writeFile(keyPath, "foreign key bytes", { mode: 0o644 });
  await chmod(keyPath, 0o644);
  await expect(createStore(f.dataRoot, f.repository, f.context)).rejects.toThrow();
  expect(await readFile(keyPath, "utf8")).toBe("foreign key bytes");
  expect((await lstat(keyPath)).mode & 0o777).toBe(0o644);
});

test("invalid persisted schemas are rejected without mutation", async () => {
  const f = await fixture();
  await finalized(f);
  const path = join(f.store.root, "receipts", `${f.plan.executionId}.json`);
  const invalid = Buffer.from('{"schemaVersion":999}');
  await writeFile(path, invalid);
  await expect(f.store.read(f.plan.executionId)).rejects.toThrow();
  await expect(f.store.reconcile()).rejects.toThrow();
  expect(await readFile(path)).toEqual(invalid);
});

test("reconcile skips live and uncommitted owners, and durably recovers a real dead owner without claiming output completeness", async () => {
  const f = await fixture();
  await f.store.reserve(f.plan);
  const uncommitted = join(f.store.root, "runs", randomUUID());
  await mkdir(uncommitted, { mode: 0o700 });
  expect(await f.store.reconcile()).toEqual([]);
  const interruptedPlan = { ...f.plan, executionId: randomUUID() };
  const source = `
    import { createStore } from ${JSON.stringify(new URL("../helpers/storage.ts", import.meta.url).href)};
    import { writeFile } from "node:fs/promises";
    const store = await createStore(${JSON.stringify(f.dataRoot)}, ${JSON.stringify(f.repository)}, ${JSON.stringify(f.context)});
    const lease = await store.reserve(${JSON.stringify(interruptedPlan)});
    await writeFile(lease.outputPath, "partial-output", { mode: 0o600, flag: "wx" });
    console.log("reservation-durable");
  `;
  const child = Bun.spawn([process.execPath, "--eval", source], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  const [code, stdout, stderr] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
  expect({ code, stdout: stdout.trim(), stderr }).toEqual({ code: 0, stdout: "reservation-durable", stderr: "" });
  const reopened = await createStore(f.dataRoot, f.repository, f.context);
  const recovered = await reopened.reconcile();
  expect(recovered).toHaveLength(1);
  const receipt = recovered[0];
  if (!receipt) throw new Error("dead-owner receipt missing");
  expect(receipt.plan.executionId).toBe(interruptedPlan.executionId);
  expect(receipt.result).toEqual({ status: "incomplete", exitCode: null, signal: null, reason: "owner-interrupted", descendantsStopped: false });
  expect(receipt.applicability).toBe("unknown");
  expect(receipt.artifact).toEqual({ file: "output.bin", sha256: createHash("sha256").update("partial-output").digest("hex"), capturedBytes: 14, totalBytes: null, truncated: null });
  expect(await reopened.read(interruptedPlan.executionId)).toEqual(receipt);
  expect(await reopened.reconcile()).toEqual([]);
  await expect(reopened.read(f.plan.executionId)).rejects.toThrow();
  expect((await lstat(uncommitted)).isDirectory()).toBe(true);
});

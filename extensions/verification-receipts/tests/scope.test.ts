import { afterEach, expect, test } from "bun:test";
import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, realpath, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { compareSnapshots } from "../core/index.ts";
import type { Configuration, Scope } from "../core/index.ts";
import { captureSnapshot, loadConfiguration, resolveRepository } from "../helpers/scope.ts";

const exec = promisify(execFile);
const temporary: string[] = [];
afterEach(async () => {
  for (const path of temporary.splice(0)) await rm(path, { recursive: true, force: true });
});

async function fixture(): Promise<{ root: string; base: string; scope: Scope; config: Configuration; key: Uint8Array }> {
  const base = await realpath(await mkdtemp(join(tmpdir(), "receipt-scope-")));
  temporary.push(base);
  const root = join(base, "repository");
  await mkdir(root);
  await exec("git", ["init", "--quiet", root], { timeout: 5000 });
  await mkdir(join(root, "source"));
  await writeFile(join(root, "source", "input.txt"), "initial\n", { mode: 0o600 });
  const scope: Scope = { paths: ["source", "missing.txt"], configPaths: ["settings.json"], environmentNames: [], datasetIdentity: "dataset-v1" };
  const config: Configuration = {
    schemaVersion: 1, configId: "scope-tests", gates: {
      check: { criterionId: "scoped-inputs", kind: "unit", executable: process.execPath, args: ["--version"], cwd: ".", timeoutMs: 5000, maxOutputBytes: 1024, requiresCompleteOutput: true, scope },
    },
  };
  await writeFile(join(root, "receipts.json"), JSON.stringify(config));
  await writeFile(join(root, "settings.json"), "{}\n");
  return { root, base, scope, config, key: randomBytes(32) };
}

test("scoped snapshots distinguish content, untracked membership, absence, mode, config, and dataset but ignore unrelated edits", async () => {
  const { root, scope, key } = await fixture();
  const capture = () => captureSnapshot(root, scope, "receipts.json", key);
  const before = await capture();
  expect(before.entries.find((entry) => entry.path === "missing.txt")?.kind).toBe("absent");
  await writeFile(join(root, "unrelated.txt"), "outside declared scope");
  expect(compareSnapshots(before, await capture())).toBe("current");
  await writeFile(join(root, "source", "input.txt"), "changed\n");
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await writeFile(join(root, "source", "input.txt"), "initial\n");
  expect(compareSnapshots(before, await capture())).toBe("current");
  await writeFile(join(root, "source", "new.txt"), "untracked member");
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await unlink(join(root, "source", "new.txt"));
  await chmod(join(root, "source", "input.txt"), 0o700);
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await chmod(join(root, "source", "input.txt"), 0o600);
  await writeFile(join(root, "missing.txt"), "now present");
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await unlink(join(root, "missing.txt"));
  await unlink(join(root, "source", "input.txt"));
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await writeFile(join(root, "source", "input.txt"), "initial\n", { mode: 0o600 });
  await writeFile(join(root, "settings.json"), "{\"changed\":true}\n");
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await writeFile(join(root, "settings.json"), "{}\n");
  const configuration = await readFile(join(root, "receipts.json"), "utf8");
  await writeFile(join(root, "receipts.json"), `${configuration}\n`);
  expect(compareSnapshots(before, await capture())).toBe("stale");
  await writeFile(join(root, "receipts.json"), configuration);
  expect(compareSnapshots(before, await captureSnapshot(root, { ...scope, datasetIdentity: "dataset-v2" }, "receipts.json", key))).toBe("stale");
  expect(compareSnapshots(before, await capture())).toBe("current");
});

test("selected environment values are keyed, absent values explicit, and __proto__ remains an own digest", async () => {
  const { root, scope, key } = await fixture();
  const selected = "ARMORY_RECEIPT_SCOPE_TEST_SELECTED";
  const unrelated = "ARMORY_RECEIPT_SCOPE_TEST_UNRELATED";
  const names = [selected, unrelated, "__proto__"];
  const saved = names.map((name) => process.env[name]);
  try {
    delete process.env.ARMORY_RECEIPT_SCOPE_TEST_SELECTED;
    process.env.__proto__ = "private-prototype-value";
    const declared = { ...scope, environmentNames: [selected, "__proto__"] };
    const before = await captureSnapshot(root, declared, "receipts.json", key);
    expect(before.environment[selected]).toBeNull();
    expect(Object.hasOwn(before.environment, "__proto__")).toBe(true);
    expect(before.environment.__proto__).toMatch(/^[a-f0-9]{64}$/);
    process.env[unrelated] = "outside-scope";
    expect(compareSnapshots(before, await captureSnapshot(root, declared, "receipts.json", key))).toBe("current");
    process.env[selected] = "private-selected-value";
    const after = await captureSnapshot(root, declared, "receipts.json", key);
    expect(compareSnapshots(before, after)).toBe("stale");
    expect(JSON.stringify(after)).not.toContain("private-selected-value");
    expect(JSON.stringify(after)).not.toContain("private-prototype-value");
    expect((await captureSnapshot(root, declared, "receipts.json", randomBytes(32))).environment[selected]).not.toBe(after.environment[selected]);
  } finally {
    names.forEach((name, index) => { const value = saved[index]; if (value === undefined) Reflect.deleteProperty(process.env, name); else process.env[name] = value; });
  }
});

test("paths, symlinked ancestors, configuration links, and special files are rejected", async () => {
  const { root, base, scope, key } = await fixture();
  await expect(captureSnapshot(root, { ...scope, paths: ["../escape"] }, "receipts.json", key)).rejects.toThrow();
  await symlink(base, join(root, "outside"));
  await expect(captureSnapshot(root, { ...scope, paths: ["outside/anything"] }, "receipts.json", key)).rejects.toThrow();
  await symlink(join(root, "receipts.json"), join(root, "linked.json"));
  await expect(loadConfiguration(root, "linked.json")).rejects.toThrow();
  await exec("mkfifo", [join(root, "source", "fifo")]);
  await expect(captureSnapshot(root, scope, "receipts.json", key)).rejects.toThrow();
});

test("linked worktrees share repository identity but retain distinct canonical worktree identity", async () => {
  const { root, base } = await fixture();
  await exec("git", ["-C", root, "add", "."]);
  await exec("git", ["-C", root, "-c", "user.name=Receipt Test", "-c", "user.email=receipt@example.invalid", "commit", "--quiet", "-m", "fixture"], { timeout: 5000 });
  const linked = join(base, "linked");
  await exec("git", ["-C", root, "worktree", "add", "--quiet", "--detach", linked, "HEAD"], { timeout: 5000 });
  const primary = await resolveRepository(root);
  const secondary = await resolveRepository(linked);
  expect(primary.repositoryId).toBe(secondary.repositoryId);
  expect(primary.repositoryRoot).toBe(secondary.repositoryRoot);
  expect(primary.worktreeId).not.toBe(secondary.worktreeId);
  expect(primary.worktreeRoot).toBe(await realpath(root));
  expect(secondary.worktreeRoot).toBe(await realpath(linked));
  expect(primary.revision).toBe(secondary.revision);
  expect(primary.dirty).toBe(false);
  await writeFile(join(linked, "source", "input.txt"), "dirty only here");
  expect((await resolveRepository(linked)).dirty).toBe(true);
  expect((await resolveRepository(root)).dirty).toBe(false);
});

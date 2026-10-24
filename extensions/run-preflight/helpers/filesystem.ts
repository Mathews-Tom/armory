import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { access, lstat, open, realpath } from "node:fs/promises";
import type { BigIntStats } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
import { canonicalJson, MAX_JSON_BYTES, parseConfig, parseDeclaration, parseIdentity, ValidationError } from "../core/index.ts";
import type { DirectoryFact, FileFact, Observation } from "../core/index.ts";
import { hasUnsafeCharacters } from "../core/text.ts";

export class ObservationError extends Error {
  constructor() { super("selected preflight prerequisites are unavailable or changed"); }
}
export function sha256(text: string): string { return createHash("sha256").update(text, "utf8").digest("hex"); }
function sameStat(left: BigIntStats, right: BigIntStats): boolean {
  return left.dev === right.dev && left.ino === right.ino && left.size === right.size && left.mtimeNs === right.mtimeNs && left.ctimeNs === right.ctimeNs && left.mode === right.mode;
}
function selectedPath(path: string): void {
  if (!isAbsolute(path) || resolve(path) !== path || path.length > 4096 || hasUnsafeCharacters(path)) throw new ObservationError();
}
/** Open only explicitly selected regular files; reject a final symlink and mutation during read. */
export async function readSelected(path: string, json = false): Promise<{ fact: FileFact; document: unknown }> {
  selectedPath(path);
  const initial = await lstat(path, { bigint: true });
  if (!initial.isFile() || initial.isSymbolicLink()) throw new ObservationError();
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const before = await handle.stat({ bigint: true });
    if (!sameStat(initial, before) || before.size > BigInt(Number.MAX_SAFE_INTEGER) || (json && before.size > BigInt(MAX_JSON_BYTES))) throw new ObservationError();
    const resolved = await realpath(path);
    const hash = createHash("sha256");
    const buffer = Buffer.allocUnsafe(64 * 1024);
    const chunks: Buffer[] = [];
    let count = 0;
    while (true) {
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, null);
      if (bytesRead === 0) break;
      count += bytesRead;
      if (count > Number(before.size) || (json && count > MAX_JSON_BYTES)) throw new ObservationError();
      hash.update(buffer.subarray(0, bytesRead));
      if (json) chunks.push(Buffer.from(buffer.subarray(0, bytesRead)));
    }
    const after = await handle.stat({ bigint: true });
    const pathAfter = await lstat(path, { bigint: true });
    if (!sameStat(before, after) || !sameStat(after, pathAfter) || count !== Number(before.size) || resolved !== await realpath(path)) throw new ObservationError();
    let document: unknown = null;
    if (json) {
      try { document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks, count))); } catch { throw new ValidationError(); }
    }
    return { fact: { path, realPath: resolved, sha256: hash.digest("hex"), device: before.dev.toString(), inode: before.ino.toString(), size: count, modifiedNs: before.mtimeNs.toString() }, document };
  } finally { await handle.close(); }
}
async function directory(path: string, needsWrite: boolean): Promise<DirectoryFact> {
  selectedPath(path);
  const info = await lstat(path, { bigint: true });
  if (!info.isDirectory() || info.isSymbolicLink()) throw new ObservationError();
  const resolved = await realpath(path);
  const permissions = constants.R_OK | constants.X_OK | (needsWrite ? constants.W_OK : 0);
  await access(path, permissions);
  // No probe files: access plus a nonzero writable mode is only a readiness observation,
  // not a guarantee that later writes cannot fail (ACL/disk state may change).
  const writable = (Number(info.mode) & 0o222) !== 0;
  if (needsWrite && !writable) throw new ObservationError();
  return { path, realPath: resolved, device: info.dev.toString(), inode: info.ino.toString(), mode: Number(info.mode), uid: Number(info.uid), gid: Number(info.gid), writable };
}
function contained(root: string, child: string): boolean {
  const path = relative(root, child);
  return path.length > 0 && path !== ".." && !path.startsWith("../") && !isAbsolute(path);
}
/** Reobserve selected state. No discovery, subprocess, auth, quota or owner-state writes. */
export async function observe(configPath: string, declarationPath: string, helperEntry: string): Promise<Observation> {
  const selectedConfig = await readSelected(configPath, true);
  const selectedDeclaration = await readSelected(declarationPath, true);
  const config = parseConfig(selectedConfig.document);
  const declaration = parseDeclaration(selectedDeclaration.document);
  if (declaration.configSha256 !== selectedConfig.fact.sha256) throw new ObservationError();
  const packageRoot = await directory(config.packageRoot, false);
  const projectRoot = await directory(config.projectRoot, false);
  const configuredHelper = resolve(config.packageRoot, config.helperPath);
  if (await realpath(helperEntry) !== await realpath(configuredHelper) || !contained(packageRoot.realPath, await realpath(configuredHelper))) throw new ObservationError();
  const helper = await readSelected(configuredHelper);
  const source = [];
  const configs = [];
  const data = [];
  for (const binding of declaration.inputs.source) source.push((await readSelected(binding.path)).fact);
  for (const binding of declaration.inputs.config) configs.push((await readSelected(binding.path)).fact);
  for (const binding of declaration.inputs.data) data.push((await readSelected(binding.path)).fact);
  const identityFile = await readSelected(declaration.inputs.identity.path, true);
  const identity = parseIdentity(identityFile.document);
  const checkpoint = await directory(declaration.checkpoint.path, true);
  if (!source.some((file) => file.path === config.bridgeArgv[1]) || !configs.some((file) => file.path === config.contractPath) || !configs.some((file) => canonicalJson(file) === canonicalJson(selectedConfig.fact))) throw new ObservationError();
  const executable = config.bridgeArgv[0];
  if (executable === undefined) throw new ObservationError();
  await access(executable, constants.X_OK);
  const facts = { config: selectedConfig.fact, declaration: selectedDeclaration.fact, helper: helper.fact, source, configs, data, identityFile: identityFile.fact, identity, checkpoint, projectRoot, packageRoot };
  // Detect replacements after earlier observations. This narrows, but cannot erase,
  // the unavoidable filesystem-to-spawn race; the managed boundary re-runs admit.
  const files = [facts.config, facts.declaration, facts.helper, ...source, ...configs, ...data, facts.identityFile];
  for (const file of files) {
    const current = await lstat(file.path, { bigint: true });
    if (!current.isFile() || current.dev.toString() !== file.device || current.ino.toString() !== file.inode || current.size !== BigInt(file.size) || current.mtimeNs.toString() !== file.modifiedNs || await realpath(file.path) !== file.realPath) throw new ObservationError();
  }
  if (canonicalJson(await directory(declaration.checkpoint.path, true)) !== canonicalJson(checkpoint)
    || canonicalJson(await directory(config.projectRoot, false)) !== canonicalJson(projectRoot)
    || canonicalJson(await directory(config.packageRoot, false)) !== canonicalJson(packageRoot)) throw new ObservationError();
  return { config, declaration, facts };
}

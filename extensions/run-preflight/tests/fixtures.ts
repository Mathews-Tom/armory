import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { canonicalJson, parseDeclaration } from "../core/index.ts";
import type { AdmissionRecord, Declaration, FileBinding, ProjectConfig, Response } from "../core/index.ts";
import { sha256 } from "../helpers/filesystem.ts";

export const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url)).replace(/\/$/, "");
export const HELPER = join(PACKAGE_ROOT, "helpers/cli.ts");
export function requireAdmission(response: Response): AdmissionRecord {
  if (response.admission === null) throw new Error(`expected complete test admission: ${response.reasons.join(",")}`);
  return response.admission;
}
export interface Fixture {
  readonly root: string;
  readonly configPath: string;
  readonly declarationPath: string;
  readonly marker: string;
  readonly sourcePath: string;
  readonly dataPath: string;
  readonly identityPath: string;
  readonly contractPath: string;
  readonly checkpoint: string;
  readonly config: ProjectConfig;
  readonly declaration: Declaration;
  readonly now: number;
  dispose(): Promise<void>;
}
export async function fixture(bridgeBody?: string): Promise<Fixture> {
  const root = await realpath(await mkdtemp(join(tmpdir(), "armory-preflight-")));
  const configPath = join(root, "project.json");
  const declarationPath = join(root, "declaration.json");
  const sourcePath = join(root, "bridge.ts");
  const dataPath = join(root, "input.txt");
  const identityPath = join(root, "identity.json");
  const contractPath = join(root, "frozen-contract.yaml");
  const checkpoint = join(root, "checkpoint");
  const marker = join(root, "spawn-count.txt");
  const now = Date.now();
  const issuedAt = new Date(now - 1000).toISOString();
  const expiresAt = new Date(now + 600_000).toISOString();
  await mkdir(checkpoint);
  // Transport fixture, not a model receipt or dispatch integration substitute. The
  // Python consumer tests exercise its actual dispatch_cell bridge separately.
  await writeFile(sourcePath, bridgeBody ?? `
import { appendFileSync } from "node:fs";
const child = Bun.spawnSync([process.execPath, "-e", "void 0"], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
if (child.exitCode !== 0 || child.stdout.length !== 0) process.exit(1);
appendFileSync(${JSON.stringify(marker)}, "local-child\\n");
process.stdout.write(JSON.stringify({ schemaVersion: 1, coreVersion: "1.0.0", status: "terminal-receipt-unavailable", managedSpawns: 1, providerCalls: 0, reasons: ["terminal-receipt-unavailable"] }));
`);
  await writeFile(dataPath, "explicit selected input\n");
  await writeFile(contractPath, "max_time_seconds: 600\n");
  await writeFile(identityPath, JSON.stringify({ schemaVersion: 1, provider: "synthetic-local", profile: "fixture-profile", accountFingerprint: "synthetic-no-account", kind: "synthetic-local", auth: "not-applicable", observedAt: issuedAt, expiresAt }));
  const config: ProjectConfig = { schemaVersion: 1, adapterId: "omp-skillsbench", adapterVersion: 1, coreVersion: "1.0.0", packageRoot: PACKAGE_ROOT, helperPath: "helpers/cli.ts", projectRoot: root, contractPath, bridgeArgv: [process.execPath, sourcePath] };
  await writeFile(configPath, JSON.stringify(config));
  const bind = async (path: string): Promise<FileBinding> => ({ path, sha256: sha256(await readFile(path, "utf8")) });
  const invocation = { adapterId: "omp-skillsbench", adapterVersion: 1, targetId: "fixture-target", targetModel: "fixture/model", targetThinking: "high", profile: "fixture-profile", cell: { taskId: "task-1", condition: "control", targetId: "fixture-target", repetition: 1, conditionHash: "a".repeat(64) }, wallSeconds: 630, checkpointRoot: checkpoint };
  const declaration = parseDeclaration({ schemaVersion: 1, runId: "fixture-run", purpose: "synthetic-local-sentinel", issuedAt, expiresAt, configSha256: sha256(await readFile(configPath, "utf8")), invocation,
    inputs: { source: [await bind(sourcePath)], config: [await bind(configPath), await bind(contractPath)], data: [await bind(dataPath)], identity: await bind(identityPath) }, checkpoint: { path: checkpoint },
    limits: { calls: { value: 1, required: false }, workers: { value: 1, required: false }, concurrency: { value: 1, required: false }, wallSeconds: { value: 630, required: true }, tokens: null, currency: null },
    quota: { status: "unknown", observedAt: issuedAt, expiresAt, reason: "no-provider-observation", source: "synthetic-fixture", remainingCalls: null },
    authorizations: [{ runId: "fixture-run", purpose: "synthetic-local-sentinel", accountFingerprint: "synthetic-no-account", scope: "local-sentinel-only", invocationSha256: sha256(canonicalJson(invocation)), acknowledgeUnknownQuota: true, issuedAt, expiresAt }],
  });
  await writeFile(declarationPath, JSON.stringify(declaration));
  return { root, configPath, declarationPath, marker, sourcePath, dataPath, identityPath, contractPath, checkpoint, config, declaration, now, dispose: () => rm(root, { recursive: true, force: true }) };
}

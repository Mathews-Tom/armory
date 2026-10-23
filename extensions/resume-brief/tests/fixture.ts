import { execFile } from "node:child_process";
import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);

export interface Project {
  base: string;
  root: string;
  dataRoot: string;
  external: string;
  git(...args: string[]): Promise<string>;
  write(relative: string, content: string): Promise<void>;
  cleanup(): Promise<void>;
}

export const CONTEXT = {
  schema: "armory.resume-brief.context/v1",
  objective: "Ship the parser rewrite",
  plan: { path: "docs/PLAN.md" },
  blockers: { path: "docs/blockers.json" },
  pullRequest: { number: 7, url: "https://github.com/example/project/pull/7" },
  approvals: [
    { id: "deploy-staging", scope: "deploy to staging", origin: { host: "omp", accountId: "acct-a", sessionId: "omp-1" }, grantedAt: "2026-01-01T00:00:00Z", expiresAt: "2026-01-02T00:00:00Z" },
  ],
};

export const BLOCKERS = {
  schema: "armory.resume-brief.blockers/v1",
  blockers: [{ id: "flaky-ci", summary: "CI job times out", status: "open" }],
  nextAction: "Rerun the integration suite",
};

/** A real temporary Git repository with a committed context, plan and blockers file. */
export async function project(): Promise<Project> {
  const base = await realpath(await mkdtemp(join(tmpdir(), "resume-brief-")));
  const root = join(base, "repository");
  const external = join(base, "external");
  await mkdir(root);
  await mkdir(external);
  const git = async (...args: string[]): Promise<string> => (await exec("git", ["-C", root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", ...args], { timeout: 10_000 })).stdout.trim();
  const write = async (relative: string, content: string): Promise<void> => {
    await mkdir(dirname(join(root, relative)), { recursive: true });
    await writeFile(join(root, relative), content);
  };
  await git("init", "--quiet", "--initial-branch=main");
  await write("brief.json", JSON.stringify(CONTEXT));
  await write("docs/PLAN.md", "# Plan\n\n1. Parse\n");
  await write("docs/blockers.json", JSON.stringify(BLOCKERS));
  await git("add", ".");
  await git("commit", "--quiet", "-m", "initial");
  return { base, root, dataRoot: join(base, "state"), external, git, write, cleanup: () => rm(base, { recursive: true, force: true }) };
}

export function ompSession(cwd: string, extra: object[] = []): string {
  const header = { type: "session", version: 3, id: "omp-session-1", timestamp: "2026-01-01T00:00:00.000Z", cwd };
  const message = { type: "message", id: "e1", parentId: null, timestamp: "2026-01-01T00:00:01.000Z", message: { role: "user", content: "SECRET TRANSCRIPT BODY" } };
  return [header, message, ...extra].map((item) => JSON.stringify(item)).join("\n") + "\n";
}

export function receipt(repositoryId: string, status = "passed"): string {
  return JSON.stringify({
    schemaVersion: 1,
    plan: { feature: "verification-receipts", executionId: "11111111-2222-4333-8444-555555555555", gateId: "unit", repository: { repositoryId }, context: { host: "standalone" } },
    result: { status },
    finishedAtMs: 1_767_225_600_000,
    artifact: { file: "output.bin" },
  });
}

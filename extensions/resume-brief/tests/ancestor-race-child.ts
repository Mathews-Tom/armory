// Separate process: interception must not mutate the test suite's module state.
import { mock } from "bun:test";
import * as contained from "../helpers/contained-open.ts";
import * as fs from "node:fs/promises";
import { renameSync, symlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import type * as Sources from "../helpers/sources.ts";

const [root, outside, source] = process.argv.slice(2);
if (root === undefined || outside === undefined || source === undefined) throw new Error("missing race fixture paths");
const sourceDirectory = join(root, "docs");
const originalDirectory = join(root, "docs-original");
const outsideDirectory = outside;
let swapped = false;
function swap(): void {
  if (swapped) return;
  swapped = true;
  renameSync(sourceDirectory, originalDirectory);
  symlinkSync(outsideDirectory, sourceDirectory);
}
const originalOpen = fs.open;
mock.module("node:fs/promises", () => ({
  ...fs,
  open: async (...args: Parameters<typeof fs.open>) => {
    if (String(args[0]).endsWith("/docs/PLAN.md")) swap();
    return originalOpen(...args);
  },
}));
const originalContainedOpen = contained.openRepositoryFile;
mock.module(join(dirname(source), "contained-open.ts"), () => ({
  ...contained,
  openRepositoryFile: async (selectedRoot: string, relative: string) => {
    if (relative === "docs/PLAN.md") swap();
    return originalContainedOpen(selectedRoot, relative);
  },
}));
// Load only after interception: this child intentionally exercises the open boundary.
const { observe, resolveRepository } = await import(source) as typeof Sources;
const observed = await observe(await resolveRepository(root), { contextPath: "brief.json", ompSessionPath: null, ompHandoffPath: null, receiptPath: null }, Date.now);
console.log(JSON.stringify({ swapped, plan: observed.plan, source: observed.sources.find((item) => item.role === "plan") }));

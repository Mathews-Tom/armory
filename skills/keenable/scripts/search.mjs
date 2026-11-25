#!/usr/bin/env node

function usage() {
  console.error(`Usage: search.mjs "query" [-n 5] [--days 7] [--keyless]`);
  process.exit(2);
}

function positiveInt(flag, value) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    console.error(`${flag} requires a positive integer, got: ${value ?? "(missing)"}`);
    usage();
  }
  return parsed;
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "-h" || args[0] === "--help") usage();

const query = args[0];
let n = 5;
let days = null;
let keyless = false;

for (let i = 1; i < args.length; i++) {
  const a = args[i];
  if (a === "-n") {
    n = positiveInt("-n", args[i + 1]);
    i++;
    continue;
  }
  if (a === "--days") {
    days = positiveInt("--days", args[i + 1]);
    i++;
    continue;
  }
  if (a === "--keyless") {
    keyless = true;
    continue;
  }
  console.error(`Unknown arg: ${a}`);
  usage();
}

// --keyless always uses the public endpoint and never sends KEENABLE_API_KEY.
const apiKey = keyless ? "" : (process.env.KEENABLE_API_KEY ?? "").trim();
const url = apiKey
  ? "https://api.keenable.ai/v1/search"
  : "https://api.keenable.ai/v1/search/public";
const headers = {
  "Content-Type": "application/json",
  Accept: "application/json",
  "X-Keenable-Title": "armory",
};
if (apiKey) headers["X-API-Key"] = apiKey;

const body = {
  query,
  max_results: Math.max(1, Math.min(n, 50)),
};
if (days) {
  body.published_after = `${Math.trunc(days)}d`;
}

const resp = await fetch(url, {
  method: "POST",
  headers,
  body: JSON.stringify(body),
});

if (!resp.ok) {
  const text = await resp.text().catch(() => "");
  throw new Error(`Keenable Search failed (${resp.status}): ${text}`);
}

const data = await resp.json();
const results = (data.results ?? []).slice(0, n);
console.log("## Sources\n");

for (const r of results) {
  const title = String(r?.title ?? "").trim();
  const pageUrl = String(r?.url ?? "").trim();
  const content = String(r?.snippet ?? "").trim() || String(r?.description ?? "").trim();
  if (!title || !pageUrl) continue;
  console.log(`- **${title}**`);
  console.log(`  ${pageUrl}`);
  if (content) {
    console.log(`  ${content.slice(0, 300)}${content.length > 300 ? "..." : ""}`);
  }
  console.log();
}

#!/usr/bin/env node

function usage() {
  console.error(`Usage: fetch.mjs "url"`);
  process.exit(2);
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "-h" || args[0] === "--help") usage();

for (const a of args) {
  if (a.startsWith("-")) {
    console.error(`Unknown arg: ${a}`);
    usage();
  }
}

if (args.length !== 1) {
  console.error("Expected exactly one URL");
  usage();
}

const pageUrl = args[0];

const apiKey = (process.env.KEENABLE_API_KEY ?? "").trim();
const endpoint = new URL(
  apiKey ? "https://api.keenable.ai/v1/fetch" : "https://api.keenable.ai/v1/fetch/public",
);
endpoint.searchParams.set("url", pageUrl);

const headers = { Accept: "application/json", "X-Keenable-Title": "armory" };
if (apiKey) headers["X-API-Key"] = apiKey;

const resp = await fetch(endpoint, { method: "GET", headers });
if (!resp.ok) {
  const text = await resp.text().catch(() => "");
  throw new Error(`Keenable Fetch failed (${resp.status}): ${text}`);
}

const data = await resp.json();
const content = String(data?.content ?? "").trim();
console.log(`# ${data?.title || pageUrl}\n`);
console.log(`Source: ${data?.url || pageUrl}\n`);
console.log(content || "(no content extracted)");

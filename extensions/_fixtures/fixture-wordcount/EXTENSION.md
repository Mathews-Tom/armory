---
name: fixture-wordcount
description: Fictional packaging fixture that counts words through a native OMP command and a Claude Code mod command; it exercises extension build, check and lifecycle infrastructure only.
metadata:
  version: 1.0.0
extension:
  schema_version: 1
  runtime: bun
  core:
    version: 1.0.0
  hosts:
    omp:
      entry: omp/index.ts
    claude:
      entry: claude-code/register.ts
  commands:
    - armory-fixture-wordcount
  helpers:
    - helpers/wordcount.ts
  storage: none
  permissions: []
---

# fixture-wordcount

Test fixture for the native extension infrastructure. It lives under
`extensions/_fixtures/`, outside registered feature discovery, and is never
cataloged, installed by default or released.

`/armory-fixture-wordcount <text>` reports how many words the text contains.
`bun helpers/wordcount.js <text>` prints the same count as JSON.

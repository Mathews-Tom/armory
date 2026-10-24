---
name: delivery-radar
description: Observe an explicitly selected GitHub pull-request graph in OMP and Claude Code, separating implementation, verification, review, merge and publication with head/base/viewer/time provenance and honest unknowns, without remote actions.
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
    - armory-delivery
  helpers:
    - helpers/cli.ts
  storage: none
  permissions:
    - fs.read
    - process.spawn
    - network
  tested:
    omp:
      - version: 18.12.6
        surfaces:
          - rpc-macos-arm64
    claude:
      - version: 2.1.310
        surfaces:
          - interactive-macos-arm64
          - headless-macos-arm64
---

# Delivery Radar

Observe only explicitly selected GitHub.com pull requests through the already configured GitHub CLI account. Package and shared core versions are 1.0.0. Implementation, verification, review, merge and publication are independent dimensions, each with source visibility and current head/base/viewer/time bindings. Actions distinguish agent work, external wait and owner decision; they are suggestions, never permission or executed actions. A merged PR is not proof of verified integration or published artifacts.

## Command

`/armory-delivery refresh <owner/repo> <n,n,...> [--json]`

Select one repository and 1–20 unique positive pull-request numbers explicitly. `/armory-delivery help` prints usage without reading GitHub. Every refresh is one bounded observation, not a watch command. Native JSON returns `{view, transition}`; text returns the same five dimensions. The first sample establishes a session-local baseline; only a meaningful change for the same ordered selection marks a transition. Sampling timestamps alone do not create a notice. Session changes revoke pending publication and reset this derived state.

## Source boundaries

Identity reads bracket each selected PR and the whole viewer observation. Incomplete pagination, changed head/base/viewer, stale or malformed evidence, inaccessible required policy, dismissed or old-head reviews, unresolved threads and unavailable checks cannot produce current readiness. Required check publishers remain exact. Head-only checks do not prove which base was tested. Publication stays unknown without independent applicable artifact provenance. Selected graph edges never expand into unrelated repositories or PRs.

The reader uses bounded argument-vector `gh api` GraphQL queries and REST GET operations. It performs no merge, review solicitation or mention, thread resolution, branch cleanup, publication, OAuth, account switch or model request. It creates no feature data store, daemon or background timer. Titles, source strings and diagnostics are untrusted data and are rendered inert. Owned installation/update/disable/removal preserves foreign configuration and data.

## Qualification

The listed native surfaces require detached-artifact qualification with normal HOME/default authentication, genuine user/managed enforcement, disposable test roots and reviewed containment of optional writers. Missing tools, trust or supported interfaces fail closed. Credential-free CI exercises deterministic behavior, pinned adapter contracts, offline host validation/test kits, reproducible contained builds and owned lifecycle operations; it does not certify authenticated native compatibility. See [README.md](README.md) for commands, limits, lifecycle and exact observed compatibility boundaries.

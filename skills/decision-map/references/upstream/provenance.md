# Upstream Provenance

## Source

- Repository: https://github.com/mattpocock/skills
- Pinned commit: `068b6e0c62393147daf03530149cdce209c93da8`, obtained with `git rev-parse HEAD` from a fresh clone on 2026-08-16.
- License: MIT.
- Copyright holder: Copyright (c) 2026 Matt Pocock.

## What was vendored

- `skills/engineering/wayfinder/SKILL.md`.
- The GitHub and local tracker-operation sections from `skills/engineering/setup-matt-pocock-skills/issue-tracker-github.md` and `skills/engineering/setup-matt-pocock-skills/issue-tracker-local.md`.

## What was adapted

- Renamed the package from `wayfinder` to `decision-map` because armory package names and descriptions must expose the triggerable outcome.
- Replaced the `wayfinder:*` label namespace with `decision-map:*` to avoid importing an upstream-specific namespace.
- Renamed `grilling` to `discussion` and `task` to `unblock` because the target catalog has no corresponding sibling and task decomposition is a distinct downstream concern.
- Promoted interaction mode to authoritative labels so the tracker can query it without a second body-metadata source of truth.
- Replaced assignee-as-claim with visible ownership plus arbitrated session claims because shared GitHub identities cannot provide exclusive ownership.
- Moved research dispatch out of charting so charting changes topology without resolving tickets.
- Added a five-state map model to prevent empty-frontier false completion.
- Rejected GraphQL in favour of native `gh` relationship flags available in the verified CLI.
- Rewrote frontmatter for armory metadata and trigger routing.
- Split operational detail into local references so the package is self-contained.
- Replaced absent sibling pointers with in-package elicitation and research guidance, an inlined prototype instruction, and `project-context-setup` guidance.
- Added explicit trigger boundaries against `plan-prompts`, `task-decomposer`, and `milestone-runner` to prevent planning-surface collisions.

## What was skipped

- `agents/openai.yaml` because it is upstream harness metadata.
- The GitLab adapter because armory has no GitLab operating surface.
- `grill-with-docs`, `triage-labels.md`, `to-tickets`, and `to-spec` because they are not required for this package's self-contained contract.
- Newsletter, donation, installer, and marketing content because it is not operational guidance.

## Re-sync policy

Do not auto-sync. Compare future upstream changes against the pinned commit, preserve the license, and re-run armory validation before adopting any change.

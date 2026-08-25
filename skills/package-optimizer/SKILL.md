---
name: package-optimizer
description: 'Evaluate one existing package or bounded package family from recorded evaluator evidence and a capability profile, then propose retain, simplify, strengthen, retire, or inconclusive without editing. Use when optimizing a skill, agent, hook, rule, command, utility, or preset; evaluating whether package detail is justified; reviewing a model-refresh impact; or preparing an approval-gated package improvement. Refuses missing, stale, or incomparable evidence and never edits without explicit approval. Not for scoring static package conformance or rubric dimensions; use package-evaluator.'
metadata:
  version: 1.0.0
  category: development
  phase: review
  tags: [package, optimization, evaluation, evidence, approval]
  difficulty: advanced
---

# Package Optimizer

Turn existing package evidence into one bounded, reviewable proposal. The
optimizer is proposal-only: it never edits a package, changes a profile, or
starts a benchmark run.

## Scope

| Situation | Action |
| --- | --- |
| One package has current evaluator evidence | Propose one disposition. |
| A bounded family shares the same evidence/profile | Propose one family plan with a per-package row. |
| Evidence is missing, stale, structurally invalid, or from another profile | Return `inconclusive`; name the unresolved package decision and request the smallest recertification needed. |
| User asks to apply a proposal | Require explicit approval, preserve before artifacts, then hand the edit to the normal package workflow. |
| User asks for a broad benchmark before identifying a package decision | Refuse the expansion; identify the package decision first. |

## Required inputs

1. **Package scope** — one `type/name` package or an explicitly bounded family.
2. **Current evidence** — static conformance and relevant eval-case result or a
   recorded behavioral result. Cite exact commands, artifacts, or case IDs.
3. **Capability profile** — model/client/tool-surface identity when behavioral
   evidence depends on one. Structural-only evidence is labelled as such.
4. **Decision question** — what behavior should be retained, simplified, or
   strengthened.

Do not infer effectiveness from package length, heading count, or static score.

## Evidence validity

Reject evidence when any condition holds:

- package path, version, or evaluator case differs from the proposed scope;
- a behavioral result has no model/client/tool-surface identity;
- a profile is older than a recorded package change or cannot be compared to the
  requested profile;
- the evidence omits a failure, safety outcome, or relevant evaluator result;
- an M4 recertification report pools model targets or lacks complete cells.

A rejection uses the single output format below with `Disposition: inconclusive`,
`Proposed change: none`, and `Approval required: yes`. Its `Unresolved package
decision` must name the package scope and decision question. A recertification
request repeats that exact field; do not request a benchmark without it.

## Procedure

1. Resolve the package scope and read its definition, evaluator cases, and
   current conformance output.
2. State the decision question and evidence class: `structural`, `behavioral`,
   or `profile-scoped behavioral`.
3. Verify evidence validity. Stop with `inconclusive` on any invalid input.
4. Select exactly one disposition:
   - `retain` — evidence supports the current contract.
   - `simplify` — evidence identifies redundant detail and the retained
     contract/evaluator proves the smaller scope.
   - `strengthen` — a documented failure requires a concrete contract addition.
   - `retire` — explicit deprecation or replacement evidence supports removal.
   - `inconclusive` — evidence cannot support a safe change.
5. Produce a proposal. For non-`retain` dispositions, name exact sections or
   files to change and the evaluator behavior that must remain true.
6. Stop. Do not edit. Require the user to explicitly approve the proposal.

## Approval handoff

An approval must name the package, disposition, and proposal ID. The downstream
applying workflow—not this skill—must:

1. Save the original package artifact and evaluator evidence.
2. Apply only the approved package/family change.
3. Run static conformance and relevant eval cases.
4. Record before/after artifacts, verification output, profile identity, and any
   regression.
5. Revert the bounded package change on regression. Do not broaden the scope.

## Output format

```text
## Package Optimization Proposal

Scope: <type/name or bounded family>
Decision question: <question>
Evidence class: <structural | behavioral | profile-scoped behavioral>
Evidence:
- <command/artifact/case and observed result>
Capability profile: <identity | not applicable>

Disposition: <retain | simplify | strengthen | retire | inconclusive>
Rationale: <evidence-backed explanation>
Unresolved package decision: <scope + decision question | not applicable>

Proposal ID: <stable scope + evidence identifier>
Proposed change: <none | exact files/sections and intended behavior>
Preservation check: <existing evaluator/eval case>
Approval required: yes

Smallest next action: <concrete action>
```

## Guardrails

- Never edit without explicit approval.
- Never optimize all packages at once.
- Never turn missing evidence into a simplification recommendation.
- Never claim token, cost, or quality improvement without recorded evidence.
- Prefer `retain` or `inconclusive` over speculative change.

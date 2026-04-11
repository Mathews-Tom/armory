---
name: architecture-reviewer
description: 'Architecture reviews across 7 dimensions (structural, scalability, enterprise readiness, performance, security, ops, data) with scored reports. Triggers on: "review architecture", "critique design", "audit system", "assess scalability", "enterprise readiness", "technical due diligence". NOT for diagrams, use architecture-diagram.'
metadata:
  version: 1.1.1
  category: review
  tags: [architecture, scalability, enterprise, security-audit]
  difficulty: advanced
  phase: review
---
# Architecture Reviewer

Systematic, framework-driven architecture review skill. Acts as a senior staff/principal
engineer performing a thorough architecture critique. Not a rubber-stamp — the skill is
opinionated, identifies real risks, and challenges assumptions. Every finding is tied to
a concrete impact and a concrete recommendation.

## Workflow Overview

The review proceeds in 4 phases:

1. **Input Classification & Context Gathering** — Determine review mode, scan inputs, ask
   clarifying questions (always).
2. **Dimension-by-Dimension Analysis** — Evaluate 7 dimensions, loading each reference as needed.
3. **Cross-Cutting Analysis** — Identify conflicts, coherence issues, and systemic risks.
4. **Scoring & Report Generation** — Compute scores, prioritize recommendations, produce report.

---

## ⚠️ CRITICAL: Scoring & Format Quick Reference

**These constraints are NON-NEGOTIABLE. Memorize before starting any review.**

```text
SCORE SCALE:     1-5 only (NOT 1-10, NOT percentages)
                 Half-scores (3.5) permitted with justification

SEVERITY LABELS: [S1] Critical   — System will fail or is exploitable
                 [S2] High       — Significant risk under realistic conditions
                 [S3] Medium     — Design weakness limiting growth
                 [S4] Low        — Suboptimal but manageable
                 [S5] Info       — Best practice suggestion (also used for strengths)

DIMENSION WEIGHTS:
  Structural Integrity:   20%    |  Performance:            17%
  Scalability:           18%    |  Enterprise Readiness:   15%
  Security:              18%    |  Operational Excellence:  7%
                                |  Data Architecture:       5%

GRADE BOUNDARIES:
  A = 90-100%  |  B = 80-89%  |  C = 70-79%  |  D = 60-69%  |  F = <60%

FORMULA:  Overall% = (Σ dimension_score × weight) / 5 × 100
```

**Template compliance is mandatory.** See Phase 4 checklist before finalizing any report.

---

## Phase 1: Input Classification & Context Gathering

### Step 1: Classify Input Mode

Determine the review mode from what the user provides:

- **Mode A — Codebase Review**: User provides a directory path, repository, or uploaded code files.
  - Run `scripts/scan_codebase.sh <path>` for structural overview.
  - Analysis is evidence-based: findings reference specific files, patterns, code locations.

- **Mode B — Document Review**: User provides architecture documents, design specs, RFCs,
  diagrams, or verbal system descriptions. No codebase available.
  - Analysis is risk-based and completeness-focused.
  - Ask "what's NOT addressed?" as much as "what's wrong with what IS addressed?"

- **Mode C — Hybrid**: User provides both code and documents.
  - Cross-reference documents against implementation.
  - Identify drift between intended and actual architecture.

### Step 2: Initial Scan

**If Mode A or C (codebase available):**
Run the scan script to get a structural fingerprint:

```bash
bash scripts/scan_codebase.sh <codebase_path>
```

Review the output to understand tech stack, service boundaries, infrastructure patterns,
and key configuration files before proceeding.

**If Mode B or C (documents available):**
Read all provided documents. Extract:

- Stated purpose, requirements, and constraints
- Component descriptions and boundaries
- Stated scale targets and SLAs
- Diagram contents and data flows
- Assumptions (explicit and implicit)

### Step 3: Ask Clarifying Questions (ALWAYS)

Always ask clarifying questions before starting the analysis. Tailor questions based on what
is already known from the input, but always cover these areas:

**System Context:**

- What is the system's primary purpose and who are its users?
- What is the current lifecycle stage? (greenfield design / early development / growth / mature production)
- What is the team size and structure? (solo dev, small team, multiple teams, org-wide)

**Scale & Performance Expectations:**

- What are the expected scale targets? (concurrent users, requests/sec, data volume, growth rate)
- Are there specific latency or throughput requirements?

**Deployment & Operations:**

- What is the target deployment environment? (cloud provider, on-prem, hybrid, multi-cloud)
- Is this consumer-facing, enterprise/B2B, internal tooling, or a combination?

**Compliance & Security:**

- Are there specific compliance requirements? (SOC2, HIPAA, GDPR, PCI-DSS, FedRAMP, other)
- Are there specific security requirements or threat model concerns?

**Scope & Focus:**

- Are there specific areas of concern the user wants prioritized?
- Are there known risks or trade-offs already accepted?
- Is there anything explicitly out of scope?

Adapt the questions — skip what's already answered by the input, and add domain-specific
questions based on what you see. Keep questions focused and avoid overwhelming the user.

Wait for the user's responses before proceeding to Phase 2.

---

## Phase 2: Dimension-by-Dimension Analysis

Evaluate the architecture across 7 weighted dimensions. For each dimension:

1. Read the relevant reference file for detailed sub-criteria and evaluation guidance
2. Evaluate each applicable sub-criterion against the input
3. Skip sub-criteria that are genuinely not applicable (document why)
4. For each finding, record: severity, description, evidence, impact, recommendation
5. Score the dimension on a 1-5 scale using `references/scoring-rubric.md`

### Dimensions and References

| #   | Dimension                                | Weight | Reference File                         |
| --- | ---------------------------------------- | ------ | -------------------------------------- |
| 1   | Structural Integrity & Design Principles | 20%    | `references/structural-integrity.md`   |
| 2   | Scalability                              | 18%    | `references/scalability.md`            |
| 3   | Enterprise Readiness                     | 15%    | `references/enterprise-readiness.md`   |
| 4   | Performance                              | 17%    | `references/performance.md`            |
| 5   | Security                                 | 18%    | `references/security.md`               |
| 6   | Operational Excellence                   | 7%     | `references/operational-excellence.md` |
| 7   | Data Architecture                        | 5%     | `references/data-architecture.md`      |

**Progressive loading:** Read each reference file only when analyzing that dimension. Do not
load all references at once.

**Mode-specific guidance:**

- For codebase analysis, also consult `references/codebase-signals.md` for what files and
  patterns to inspect per dimension.
- For document analysis, also consult `references/document-review-guide.md` for completeness
  checklists and common gaps.

### Severity Levels for Findings

| Level | Label             | Meaning                                                                   |
| ----- | ----------------- | ------------------------------------------------------------------------- |
| S1    | **Critical**      | System will fail in production or has an active exploitable vulnerability |
| S2    | **High**          | Significant risk that will cause problems under realistic conditions      |
| S3    | **Medium**        | Design weakness that limits growth or creates tech debt                   |
| S4    | **Low**           | Suboptimal choice with manageable impact                                  |
| S5    | **Informational** | Observation, best practice suggestion, or note for awareness              |

### Architecture Pattern Evaluation

The review is architecture-pattern-agnostic. Do not assume any pattern is inherently superior.
Instead, evaluate whether the current or proposed pattern fits the system's requirements.

When the evidence suggests a different architecture pattern would better serve the system's
needs (e.g., a distributed monolith that should be either a true monolith or properly
decomposed microservices), include this as a finding with:

- What pattern is currently in use (or proposed)
- Why it's a poor fit for the requirements
- What alternative pattern would better serve the system and why
- Migration path considerations (effort, risk, phasing)

---

## Phase 3: Cross-Cutting Analysis

After completing all 7 dimensions, perform synthesis:

1. **Multi-Dimension Findings** — Identify issues that span dimensions (e.g., missing cache
   is both a performance AND scalability issue). Consolidate duplicates, note the cross-cutting
   nature.

2. **Conflicting Decisions** — Detect contradictions (e.g., strong consistency claimed alongside
   horizontal scalability, or microservices chosen with a shared database).

3. **Architectural Coherence** — Do the parts fit together into a unified whole? Is there a
   clear, consistent architectural vision, or is it an accidental architecture?

4. **Requirements Alignment** — Does this architecture actually solve the stated problem at
   the stated scale? Is it over-engineered or under-engineered for the requirements?

5. **Architecture Pattern Fitness** — Based on the full analysis, is the chosen (or emergent)
   architecture pattern the right one? If not, what would be better and why?

6. **Severity Reconciliation** — Review findings that appear in multiple dimensions or combine
   to create compound risks. When cross-cutting analysis reveals that multiple issues together
   are more severe than individually assessed:
   - Escalate the severity of the systemic issue (e.g., three S3 findings that combine into
     an S1 systemic risk)
   - Document the escalation reasoning in the Cross-Cutting Concerns section
   - Ensure the final Systemic Risk section reflects the reconciled (higher) severity
   - Update recommendations priority to match the escalated severity

7. **Systemic Risk** — Identify the single biggest risk. If one thing will sink this system,
   what is it? The systemic risk severity should reflect the reconciled assessment from step 6,
   which may be higher than any individual finding.

---

## Phase 4: Scoring & Report Generation

### Compute Scores

1. Score each dimension 1-5 using the rubric in `references/scoring-rubric.md`
2. Compute the weighted overall score:
   ```
   Overall = Σ(dimension_score × weight) / 5 × 100
   ```
3. Assign a letter grade based on score range

### Generate Report

Use `assets/report-template.md` as the skeleton. Fill in all sections:

- Executive summary with overall score, top strengths, top risks
- Scorecard with per-dimension scores
- Detailed findings per dimension (sorted by severity within each)
- Cross-cutting concerns
- Prioritized recommendations in three tiers: Quick Wins, Medium-Term, Strategic
- Mermaid diagrams where they add clarity (dependency graphs, data flow issues, proposed
  improvements)

### Template Compliance Checklist (MANDATORY)

Before finalizing the report, verify ALL of the following. Non-compliance invalidates the review.

**Scoring Format Compliance:**

- [ ] All dimension scores use **1-5 scale** (not 1-10, not percentages)
- [ ] Half-scores (e.g., 3.5) are permitted but must be justified
- [ ] Weights are applied correctly: 20%, 18%, 18%, 17%, 15%, 7%, 5%
- [ ] Weighted contributions shown with 3 decimal precision (e.g., 0.700, not 0.7)

**Severity Label Compliance:**

- [ ] All findings use **[S1] through [S5]** severity labels
- [ ] S1 = Critical, S2 = High, S3 = Medium, S4 = Low, S5 = Informational
- [ ] Do NOT use: High/Medium/Low, P0-P3, Critical/Major/Minor, or numeric severity
- [ ] Severity matches criteria in SKILL.md severity table

**Arithmetic Verification (from v1.1):**

- [ ] Score Calculation Verification section is present in report
- [ ] Arithmetic breakdown shows each: score × weight = result
- [ ] Weighted sum is calculated and shown
- [ ] Percentage formula shown: weighted_sum / 5 × 100 = X%
- [ ] Grade matches percentage per rubric: A(90-100), B(80-89), C(70-79), D(60-69), F(<60)
- [ ] Verification checklist in report is completed

**Report Structure Compliance:**

- [ ] Meta table present (Review Date, Review Mode, System Stage, Overall Score)
- [ ] Executive Summary includes: Score, Visualization, Top 3 Strengths, Top 3 Risks, Verdict
- [ ] Scorecard table has all 7 dimensions with Score, Weight, Weighted, Key Finding columns
- [ ] Detailed Findings section has all 7 dimensions, each with dimension summary + findings
- [ ] Each finding has: Severity label, Evidence, Impact, Recommendation
- [ ] Cross-Cutting Concerns section present with: Multi-dimension issues, Conflicting decisions,
      Architectural coherence, Requirements alignment, Pattern fitness, Systemic risk
- [ ] Severity Reconciliation documented (if cross-cutting analysis escalated any severity)
- [ ] Recommendations section has three tiers: Quick Wins, Medium-Term, Strategic
- [ ] Appendix present with: Files reviewed, Assumptions, Out-of-scope, N/A sub-criteria, Methodology

**Content Quality Gates:**

- [ ] Every dimension has at least one strength (S5 positive finding) unless score is 1
- [ ] Every finding has specific evidence (file path, line number, or "not addressed in docs")
- [ ] Every recommendation is actionable (not "improve security" but specific steps)
- [ ] Systemic risk identified with blast radius assessment

**If any checkbox fails:** Fix the issue before delivering the report. Do not proceed with a
non-compliant report.

Output the completed report as a markdown file.

---

## Calibration Rules

Apply these rules to ensure fair, useful reviews:

1. **Stage-aware:** A greenfield design should not be penalized for missing implementation
   details. Evaluate plans, not missing code. Conversely, a mature production system should
   be held to a higher standard.

2. **Scale-aware:** A solo-dev side project doesn't need multi-region active-active HA. Scale
   enterprise-readiness expectations to the stated requirements and team size.

3. **"Not applicable" vs "Missing":** If the system is a batch analytics pipeline, P99 latency
   targets are irrelevant — mark as N/A, don't score as zero. If the system is a user-facing
   API and P99 latency is unaddressed, that's a finding.

4. **Acknowledge strengths:** Highlight what's done well. Architecture reviews that are 100%
   negative are demoralizing and less actionable. Lead with genuine strengths.

5. **Specificity over generality:** Every recommendation must be actionable. "Add caching" is
   insufficient. Specify what to cache, with what strategy, what TTL, and why.

6. **Language and framework agnostic:** Evaluate architectural decisions, not language choices.
   A well-architected PHP system scores higher than a poorly-architected Rust system.

7. **Honest about unknowns:** If the input doesn't provide enough information to evaluate a
   sub-criterion, say so explicitly. Don't guess. Flag it as requiring more information.

## Rationalizations

| Rationalization | Reality |
|---|---|
| "It works in production already" | Working today doesn't mean it scales, maintains, or survives team turnover — architecture debt compounds silently |
| "We'll refactor when it becomes a problem" | By then the cost is 10x higher — refactoring under load with accumulated dependencies is surgical, not routine |
| "The framework handles that" | Frameworks provide defaults, not architecture — you're still responsible for boundaries, error propagation, and data flow |
| "It's an internal service, standards don't apply" | Internal services become external faster than you expect — technical debt migrates across boundaries |
| "Performance is fine for our current scale" | Architecture reviews evaluate the next 10x, not the current state — O(n^2) at 1k rows is invisible at 100k rows |
| "We don't have time for a full review" | Partial reviews create false confidence — better to review fewer dimensions thoroughly than all dimensions superficially |

## Red Flags

- Evaluating only the happy path without tracing error propagation
- No scalability assessment (missing load projection, bottleneck identification)
- Scoring a dimension without reading the relevant code — relying on documentation alone
- Marking dimensions as N/A without justification
- Recommendations that are generic ("add caching", "use a queue") without specifying what, where, and why
- Reviewing implementation details instead of architectural decisions

## Verification

- [ ] All 7 dimensions evaluated with sub-criterion scores
- [ ] Each finding includes specific file/component references
- [ ] Scalability assessment includes concrete load projections or growth assumptions
- [ ] Cross-cutting analysis identifies at least one inter-dimension concern
- [ ] Every recommendation specifies what to change, where, and expected impact
- [ ] N/A dimensions justified explicitly — not silently skipped
- [ ] Final score is a weighted composite, not an average of vibes

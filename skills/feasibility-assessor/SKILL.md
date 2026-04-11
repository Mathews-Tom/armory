---
name: feasibility-assessor
description: 'Evaluates whether a business idea is technically buildable and financially viable. Covers unit economics (CAC, LTV), revenue modeling, break-even, and go/no-go verdicts. Triggers on: "feasibility assessment", "viability analysis", "unit economics", "build vs buy", "go/no-go decision", "ROI projection".'
metadata:
  version: 1.0.1
  category: review
  tags: [feasibility, unit-economics, viability, business-case]
  difficulty: advanced
  phase: define
---

# Feasibility Assessor

Evaluate business ideas and features across two tracks: financial viability and technical feasibility. Produce an integrated verdict with actionable de-risking recommendations.

## Phase 1: Input Classification

Determine the input type:

- **Idea pitch**: informal description of a concept
- **Feature spec**: defined requirements for a product addition
- **Repo/codebase**: existing code to evaluate for extension or pivot
- **Business plan**: structured document with financials

Extract from the input:

1. Value proposition (what problem it solves, for whom)
2. Target customer segment
3. Pricing intent or revenue model
4. Technology stack (stated or implied)
5. Competitive landscape awareness

If critical inputs are missing, ask targeted clarifying questions before proceeding. Minimum viable inputs: value proposition and target customer.

## Phase 2: Financial Analysis

Reference: `references/unit-economics.md`, `references/financial-viability.md`

Skip this phase only when the request is purely technical (e.g., "can we build X with Y stack").

### Unit Economics

1. Calculate **Customer Acquisition Cost (CAC)** — fully loaded: marketing spend + sales cost + overhead allocation per acquired customer
2. Calculate **Customer Lifetime Value (LTV)** — ARPU multiplied by average customer lifetime, adjusted for gross margin
3. Compute **LTV:CAC ratio** — minimum viable: 3:1
4. Determine **contribution margin** per unit sold or per customer served
5. Calculate **payback period** — months until cumulative gross profit from a customer exceeds CAC

State every assumption explicitly. Flag assumptions with high sensitivity (small change flips the outcome).

### Revenue Modeling

1. Identify all revenue streams and size each one
2. Assess pricing strategy fit: cost-plus, value-based, competitive, freemium-to-paid
3. Apply conversion rate assumptions — use industry benchmarks from reference material
4. Model churn and retention — apply cohort decay curves where possible

### Break-Even Analysis

1. Separate fixed costs (rent, salaries, infrastructure baseline) from variable costs (COGS, transaction fees, support per user)
2. Calculate break-even point in units, customers, or revenue
3. Model three scenarios:
   - **Pessimistic**: 50th percentile conversion, high churn, slow growth
   - **Base**: industry-average assumptions
   - **Optimistic**: top-quartile performance

### Path to Profitability

1. Project gross margin trajectory over 12-24 months
2. Model operating expense scaling (linear vs step-function vs economies of scale)
3. Estimate funding requirements and runway at current burn
4. Compare against industry benchmarks for time-to-profitability

## Phase 3: Technical Analysis

Reference: `references/technical-risk.md`

Skip this phase only when the request is purely financial (e.g., "are the unit economics viable for a SaaS at $29/mo").

### Architecture Assessment

Classify complexity:

| Level        | Description                                       | Examples                                             |
| ------------ | ------------------------------------------------- | ---------------------------------------------------- |
| 1 — Simple   | Standard CRUD, single service                     | Landing page, basic CMS, form-based app              |
| 2 — Moderate | Multi-service integration, auth, payments         | E-commerce, SaaS dashboard, API platform             |
| 3 — Complex  | Distributed systems, real-time, high availability | Marketplace, streaming platform, fintech             |
| 4 — Novel    | R&D required, unproven at scale                   | ML-driven product, novel protocol, hardware+software |

Evaluate:

- Technology stack maturity and ecosystem support
- Infrastructure requirements and cost scaling curve
- Third-party dependency count and criticality

### Build Estimation

1. Define MVP scope — the minimum feature set that tests the core value proposition
2. Estimate development timelines:
   - **Optimistic**: experienced team, known stack, minimal unknowns
   - **Realistic**: standard team, some learning curve, normal blockers
   - **Pessimistic**: new domain, integration challenges, regulatory overhead
3. Identify required team skills and availability
4. Run build vs buy vs partner analysis for each major component

### Risk Scoring

Score each dimension 1-5 (1 = low risk, 5 = critical risk):

| Dimension              | What It Measures                                                                  |
| ---------------------- | --------------------------------------------------------------------------------- |
| Technical novelty      | Proven tech (1) vs active R&D required (5)                                        |
| Integration complexity | Self-contained (1) vs many external APIs (5)                                      |
| Scale readiness        | Architecture handles 100x with config changes (1) vs requires re-architecture (5) |
| Data risk              | Public/owned data, no regulation (1) vs restricted data, heavy compliance (5)     |
| Security/compliance    | No sensitive data (1) vs PCI/HIPAA/SOC2 required (5)                              |

Composite technical risk = weighted average. Flag any dimension scoring 4+ as a blocker requiring mitigation plan.

## Phase 4: Integrated Feasibility Score

### Financial Viability

- **Viable**: LTV:CAC > 3:1, payback < 18 months, clear path to positive unit economics
- **Risky**: LTV:CAC 1.5-3:1, payback 18-36 months, unit economics depend on scale
- **Not viable**: LTV:CAC < 1.5:1, payback > 36 months, negative contribution margin

### Technical Feasibility

- **Straightforward**: complexity level 1-2, all risk dimensions < 3
- **Challenging**: complexity level 2-3, one or two dimensions at 3-4
- **High-risk**: complexity level 3-4, multiple dimensions at 4+
- **Research-grade**: complexity level 4, any dimension at 5

### Overall Verdict

| Financial  | Technical          | Verdict                                                |
| ---------- | ------------------ | ------------------------------------------------------ |
| Viable     | Straightforward    | **Green** — proceed                                    |
| Viable     | Challenging        | **Yellow** — proceed with caution, mitigate tech risks |
| Risky      | Straightforward    | **Yellow** — validate financial assumptions first      |
| Risky      | Challenging        | **Yellow** — high uncertainty, run cheap experiments   |
| Not viable | Any                | **Red** — reconsider fundamentals                      |
| Any        | High-risk/Research | **Red** — reduce technical unknowns before committing  |

### Assumption Sensitivity

Identify the top 3-5 assumptions that most influence the verdict. For each, state:

- Current assumed value
- Threshold value that would flip the assessment
- How to validate cheaply

### De-risking Recommendations

Rank experiments by cost-to-run vs information-value. Prioritize experiments that validate the riskiest assumptions at the lowest cost.

## Phase 5: Report Generation

Structure the output as:

### Executive Summary

- One-paragraph verdict with go/no-go signal
- Top 3 risks and top 3 strengths

### Financial Dashboard (if applicable)

- Unit economics table: CAC, LTV, LTV:CAC, contribution margin, payback period
- Revenue projection under 3 scenarios (table or description)
- Break-even point and timeline

### Technical Scorecard (if applicable)

- Complexity classification
- Risk dimension scores (table)
- MVP scope and timeline estimate
- Critical dependencies and mitigation

### Sensitivity Analysis

- Which assumptions, if wrong, flip the verdict
- Threshold values for each critical assumption

### Recommended Next Steps

- Ordered list of actions, cheapest validation first
- Clear owners or skill requirements for each step
- Decision gates: what evidence triggers proceed vs pivot vs stop

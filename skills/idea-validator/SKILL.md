---
name: idea-validator
description: 'Orchestrates business idea validation via parallel sub-agents: Lean Canvas, JTBD, market/competitive/feasibility research, SWOT/PESTLE, and a weighted scorecard with verdict. Triggers on: "validate this idea", "evaluate my startup idea", "is this idea worth pursuing", "score this business idea", "validate my pitch".'
metadata:
  version: 1.0.1
  complements: [market-analyzer, competitive-analyzer, feasibility-assessor]
  category: review
  tags: [idea-validation, lean-canvas, jtbd, swot]
  difficulty: advanced
  phase: define
---

# Business Idea Validator

## Purpose

Perform rigorous, multi-dimensional validation of business ideas by orchestrating parallel research and synthesizing findings into a scored, actionable report. The goal is honest assessment — surfacing what holds up under scrutiny and what does not — rather than cheerleading or reflexive dismissal.

## Phase 1: Input Intake & Classification

Classify the input:

| Input Type       | Indicators                                  | Adaptation                                  |
| ---------------- | ------------------------------------------- | ------------------------------------------- |
| Elevator pitch   | 1-3 sentences, informal                     | Extract hypothesis, ask for missing details |
| Business plan    | Structured, multiple sections               | Validate claims against research            |
| Feature proposal | Technical focus, existing product context   | Narrow scope to feature viability           |
| Repo/codebase    | File paths, code references                 | Technical feasibility + market fit          |
| Pivot assessment | "Should we pivot to...", comparison context | Compare current vs proposed direction       |

Extract core elements from the input:

- **Problem statement** — what pain point exists
- **Proposed solution** — how it addresses the pain
- **Target customer** — who experiences this problem
- **Value proposition** — why this solution over alternatives
- **Revenue model** — how it generates money

If any core element is missing or ambiguous, ask clarifying questions. Cap at 5 questions. Do not proceed with fabricated assumptions for missing elements — get real answers.

## Phase 2: Lean Canvas Construction

Build a complete Lean Canvas using `references/lean-canvas.md` as the framework guide.

Populate all 9 boxes:

1. **Problem** — top 3 problems the customer faces
2. **Customer Segments** — target market + early adopter profile
3. **Unique Value Proposition** — single clear compelling message
4. **Solution** — top 3 features addressing the top 3 problems
5. **Channels** — path to reaching customers
6. **Revenue Streams** — pricing model and revenue mechanics
7. **Cost Structure** — fixed and variable costs
8. **Key Metrics** — what to measure for progress
9. **Unfair Advantage** — what cannot be easily copied or bought

For each box:

- Assess completeness and specificity
- Flag vague entries ("everyone" as a segment, "best product" as UVP)
- Check cross-box coherence (solution must address stated problems, channels must reach stated segments)

## Phase 3: Jobs-to-be-Done Analysis

Apply the JTBD framework from `references/jtbd-framework.md`:

- **Functional job** — what is the customer trying to accomplish?
- **Emotional job** — how do they want to feel?
- **Social job** — how do they want to be perceived?
- **Current solutions** — what do they use today? (hiring/firing decisions)
- **Switching triggers** — what would cause adoption of a new solution?

Assess whether the proposed solution addresses the core job better than current alternatives. Identify the four forces of progress: push of current situation, pull of new solution, anxiety of change, habit of status quo.

## Phase 4: Parallel Research Delegation

Use the Agent tool to spawn three research agents in parallel. Each agent receives a focused research brief derived from the idea context established in Phases 1-3. These agents perform the same analysis covered by the complementary skills (`market-analyzer`, `competitive-analyzer`, `feasibility-assessor`) — when those skills are installed, their reference frameworks inform the analysis depth; when running standalone, the agents use the inline briefs below.

### Agent 1 — Market Research

Prompt the agent:

> Analyze the market opportunity for [idea summary with target customer and problem context]. Research TAM/SAM/SOM estimates, market growth trends, customer segment sizing, and timing signals. Use WebSearch to find industry reports, market data, analyst projections, and trend indicators. Produce a structured market analysis with quantified estimates and cited sources. Include: market size estimates with methodology, growth rate and trajectory, key market drivers, timing assessment (too early, right time, too late), and customer willingness to pay signals.

### Agent 2 — Competitive Analysis

Prompt the agent:

> Analyze the competitive landscape for [idea summary with solution and value proposition context]. Discover direct competitors (same solution, same customer), indirect competitors (different solution, same job-to-be-done), and potential competitors (adjacent players who could enter). Compare features, pricing, and positioning across competitors. Assess Porter's Five Forces for this industry. Identify moats and defensibility factors. Use WebSearch for competitor data from Product Hunt, G2, Capterra, Crunchbase, and company sites. Produce a structured competitive analysis with competitor matrix, force scores, and positioning assessment.

### Agent 3 — Feasibility Assessment

Prompt the agent:

> Assess the financial and technical feasibility of [idea summary with solution details and revenue model]. Calculate unit economics using industry benchmarks: customer acquisition cost (CAC), lifetime value (LTV), LTV:CAC ratio, gross margins, payback period. Evaluate technical complexity: architecture requirements, key technical risks, build vs buy decisions, infrastructure needs. Estimate build timeline and team composition for MVP and v1. Use WebSearch for comparable company benchmarks, SaaS metrics benchmarks, and technical stack assessments. Produce a structured feasibility report with financial projections, technical risk matrix, and resource requirements.

Wait for all three agents to return results before proceeding.

## Phase 5: SWOT/PESTLE Integration

Using the combined outputs from Phases 2-4, construct both analyses per `references/swot-pestle.md`.

### SWOT Analysis

- **Strengths** — internal advantages, unique capabilities, resource advantages
- **Weaknesses** — internal gaps, resource constraints, skill deficiencies
- **Opportunities** — external factors favoring success (market trends, regulatory changes, technology shifts)
- **Threats** — external factors risking failure (competitive moves, market shifts, regulatory risks)

Derive strategy implications: SO strategies (use strengths to capture opportunities), WO strategies (address weaknesses to unlock opportunities), ST strategies (use strengths to counter threats), WT strategies (minimize weaknesses and avoid threats).

### PESTLE Scan

Assess macro-environment factors:

- **Political** — regulation, government policy, trade restrictions, political stability
- **Economic** — market conditions, funding environment, consumer spending, interest rates
- **Social** — demographic trends, cultural shifts, consumer behavior changes
- **Technological** — tech maturity, disruption potential, infrastructure readiness
- **Legal** — IP protection, compliance requirements, liability exposure, licensing
- **Environmental** — sustainability pressures, resource constraints, ESG expectations

Prioritize factors by impact and likelihood. Feed high-impact factors into SWOT external quadrants.

## Phase 6: Integrated Validation Scoring

Score across 6 dimensions using `references/validation-scoring.md`:

| Dimension             | Weight | Score Range | Primary Sources            |
| --------------------- | ------ | ----------- | -------------------------- |
| Problem-Solution Fit  | 25%    | 1-5         | Lean Canvas, JTBD          |
| Market Opportunity    | 20%    | 1-5         | Market Research Agent      |
| Competitive Position  | 15%    | 1-5         | Competitive Analysis Agent |
| Financial Viability   | 20%    | 1-5         | Feasibility Agent          |
| Technical Feasibility | 10%    | 1-5         | Feasibility Agent          |
| Timing & Environment  | 10%    | 1-5         | PESTLE, Market Research    |

Compute weighted overall score. Map to verdict:

- **4.0-5.0: Strong** — pursue aggressively, competitive advantage is clear
- **3.0-3.9: Promising** — proceed with targeted validation of key assumptions
- **2.0-2.9: Risky** — significant concerns must be addressed before investment
- **1.0-1.9: Weak** — fundamental issues present, consider pivot or abandon

Identify any red flags that override scores (legal impossibility, ethical concerns, physical impossibility). A single critical red flag can downgrade the verdict regardless of score.

Assess confidence level: how certain are the inputs driving each score? Flag dimensions where data is thin or speculative.

## Phase 7: Report Generation

Produce the final validation report in this structure:

```markdown
# Business Idea Validation Report

## Meta

| Field         | Value                                                     |
| ------------- | --------------------------------------------------------- |
| Date          | YYYY-MM-DD                                                |
| Input Type    | [elevator pitch / business plan / feature / repo / pivot] |
| Overall Score | X.X / 5.0                                                 |
| Verdict       | [Strong / Promising / Risky / Weak]                       |

## Executive Summary

[3-5 sentences: what the idea is, the key finding, the main risk, the recommendation]

## Lean Canvas

[Completed canvas with assessment notes per box]

## Problem-Solution Fit

[JTBD analysis, switching triggers, current alternatives, fit assessment]

## Market Opportunity

[TAM/SAM/SOM, growth trends, timing assessment — from market research agent]

## Competitive Landscape

[Competitor matrix, Porter's Five Forces, positioning — from competitive agent]

## Financial & Technical Feasibility

[Unit economics, build estimate, risk scores — from feasibility agent]

## SWOT Analysis

[4-quadrant analysis with strategy implications]

## PESTLE Scan

[Macro environment factors prioritized by impact]

## Validation Scorecard

[6 dimensions with scores, weights, justification, confidence levels]

## Red Flags

[Ranked list of critical concerns that could invalidate the idea]

## Recommended Validation Experiments

[Ordered by: cheapest test of riskiest assumption]

1. [Experiment] — tests [assumption] — cost: [effort/money] — timeline: [days]
2. ...

## What Survives Scrutiny

[Honest assessment of what holds up after thorough analysis]
```

## Constraints

- Do not fabricate market data. If research agents cannot find reliable data, state the gap and assign lower confidence to affected scores.
- Do not inflate scores to be encouraging. The value of this analysis is honesty.
- Do not present opinions as facts. Distinguish between data-backed findings and analytical judgments.
- When the idea addresses a real problem with a defensible solution and favorable timing, say so clearly. Honest assessment works in both directions.
- Keep the report actionable. Every section should inform a decision or an experiment.

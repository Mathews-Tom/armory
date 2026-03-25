---
name: biz-validation
description: "DEPRECATED: Superseded by the idea-scout agent, which orchestrates the same skills (market-analyzer, competitive-analyzer, feasibility-assessor, idea-validator) with parallel research delegation, weighted scoring, and GO/CAUTION/NO-GO verdicts. Use idea-scout agent instead."
type: preset
metadata:
  version: 1.1.0
  status: deprecated
preset:
  packages:
    skills:
      - name: market-analyzer
      - name: competitive-analyzer
      - name: feasibility-assessor
      - name: idea-validator
  compatibility:
    platforms: [darwin, linux]
---

# Biz Validation

> **DEPRECATED** — The `idea-scout` agent supersedes this preset. It orchestrates the
> same four skills with parallel Agent tool spawning, cross-referencing, weighted
> validation scorecards, and GO/CAUTION/NO-GO verdicts. Install `idea-scout` instead.

A curated bundle of four skills for comprehensive business idea validation.

## Included Skills

| Skill                  | Purpose                                 | Key Frameworks                                              |
| ---------------------- | --------------------------------------- | ----------------------------------------------------------- |
| `market-analyzer`      | Market sizing and trend analysis        | TAM/SAM/SOM, Rogers adoption curve, trend identification    |
| `competitive-analyzer` | Competitive landscape assessment        | Porter's Five Forces, feature matrices, positioning maps    |
| `feasibility-assessor` | Financial and technical viability       | Unit economics, technical risk scoring, break-even analysis |
| `idea-validator`       | Full business validation (orchestrator) | Lean Canvas, JTBD, SWOT/PESTLE, integrated scoring          |

## Usage Patterns

### Full Validation

Ask Claude to "validate this business idea" — triggers `idea-validator`, which orchestrates the other three skills via sub-agents.

### Focused Analysis

- "Analyze the market for X" — triggers `market-analyzer` directly
- "Who are the competitors for X" — triggers `competitive-analyzer` directly
- "Is X financially viable" — triggers `feasibility-assessor` directly

### Incremental Validation

Run individual skills in sequence, building up a complete picture:

1. Start with market analysis to confirm opportunity exists
2. Add competitive analysis to understand the landscape
3. Run feasibility to check if it can be built and sustained
4. Use idea-validator for the integrated synthesis

## Data Flow

When `idea-validator` orchestrates the full suite, the data flows as follows:

```text
User Input (idea/pitch/plan)
    │
    ▼
┌─────────────────────┐
│  idea-validator      │  Phase 1-3: Intake, Lean Canvas, JTBD
│  (orchestrator)      │
└────────┬────────────┘
         │ Phase 4: Spawns 3 parallel agents
         ├──────────────────┬──────────────────┐
         ▼                  ▼                  ▼
┌─────────────────┐ ┌────────────────┐ ┌─────────────────┐
│ market-analyzer │ │ competitive-   │ │ feasibility-    │
│                 │ │ analyzer       │ │ assessor        │
│ → TAM/SAM/SOM   │ │ → Competitors  │ │ → Unit economics│
│ → Trends        │ │ → Five Forces  │ │ → Tech risk     │
│ → Timing        │ │ → Positioning  │ │ → Break-even    │
└────────┬────────┘ └───────┬────────┘ └────────┬────────┘
         │                  │                    │
         └──────────────────┴────────────────────┘
                            │
                            ▼
                ┌─────────────────────┐
                │  idea-validator      │  Phase 5-7: SWOT/PESTLE,
                │  (synthesis)         │  Scoring, Report
                └─────────────────────┘
                            │
                            ▼
                  Validation Report
                  (6-dimension scorecard,
                   verdict, experiments)
```

Each sub-agent returns structured findings. The orchestrator synthesizes them with SWOT/PESTLE analysis and produces a weighted validation scorecard.

## Installation

Install the complete suite:

```bash
npx skills add biz-validation
```

Or install individual skills:

```bash
npx skills add market-analyzer
npx skills add competitive-analyzer
npx skills add feasibility-assessor
npx skills add idea-validator
```

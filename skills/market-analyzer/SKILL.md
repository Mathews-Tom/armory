---
name: market-analyzer
description: 'Structured market analysis with TAM/SAM/SOM sizing, trends, and competitive landscape via WebSearch, producing investor-grade cited reports. Triggers on: "market size", "TAM SAM SOM", "market opportunity", "industry analysis", "how big is the market", "market trends". NOT for financial modeling or pricing.'
metadata:
  version: 1.0.1
  category: research
  tags: [market-sizing, tam-sam-som, trends, industry]
  difficulty: intermediate
  phase: define
---

# Market Analyzer

Produces structured market analysis reports: sizes the addressable market using top-down
and bottom-up methods, identifies growth trajectories and adoption stages, segments
customers, and assesses timing. Every estimate cites a data source or states its
assumption explicitly.

## Reference Files

| File                           | Contents                                                           | Load When |
| ------------------------------ | ------------------------------------------------------------------ | --------- |
| `references/tam-sam-som.md`    | TAM/SAM/SOM definitions, calculation formulas, common mistakes     | Always    |
| `references/trend-analysis.md` | Trend categorization framework, adoption lifecycle, timing signals | Always    |
| `references/market-sizing.md`  | Data sources, estimation techniques, confidence framework          | Always    |

## Prerequisites

- Product, feature, or business idea description
- Target geography (default: global)
- Target customer segment (if known)

## Workflow

### Phase 1: Input Understanding

1. **Classify the input** — Determine whether the subject is a product idea, feature,
   market category, or industry vertical.
2. **Extract key attributes:**
   - Target customer profile
   - Value proposition or core problem solved
   - Geography and regulatory jurisdiction
   - Price range or monetization model (if known)
   - Competitive alternatives
3. **Clarify gaps** — If critical context is missing (target customer, geography, or
   value proposition), ask 3-5 targeted clarifying questions before proceeding.

### Phase 2: Market Research

Use WebSearch to gather quantitative market data:

1. **Industry reports** — Search for market size reports from Statista, Grand View Research,
   Fortune Business Insights, IBISWorld, and similar aggregators.
2. **Growth rates** — Identify CAGR (Compound Annual Growth Rate) for the relevant
   market and adjacent segments.
3. **Funding signals** — Search Crunchbase, PitchBook coverage, and venture capital
   trends in the space.
4. **Consumer trends** — Google Trends data, social media volume, and news sentiment.
5. **Academic research** — Search Semantic Scholar for relevant market studies, adoption
   research, and behavioral economics papers.
6. **Government/public data** — Census Bureau, BLS, World Bank, OECD datasets for
   demographic and economic baselines.

For each data point, record the source, publication date, and methodology (if available).

### Phase 3: TAM/SAM/SOM Calculation

Apply both estimation approaches and cross-validate:

**Top-down (from total industry):**

```
TAM = Total industry revenue or total potential buyers x average revenue per buyer
SAM = TAM x % addressable by geography, segment, and channel
SOM = SAM x realistic capture rate (year 1-3)
```

**Bottom-up (from unit economics):**

```
Reachable customers = Identified target accounts or users in reachable channels
SOM = Reachable customers x conversion rate x average revenue per customer
SAM = SOM scaled to full serviceable segment (remove channel constraints)
TAM = SAM scaled to total market (remove geographic/segment constraints)
```

Cross-validate the two approaches. If they diverge by more than 3x, investigate the
discrepancy and document the reason.

### Phase 4: Trend and Timing Assessment

Evaluate four dimensions:

1. **Market growth trajectory** — Classify as emerging (pre-revenue), growing (CAGR > 10%),
   mature (CAGR 0-5%), or declining (negative CAGR).
2. **Technology adoption stage** — Map to Rogers curve: innovators (< 2.5%), early
   adopters (2.5-16%), early majority (16-50%), late majority (50-84%), laggards (> 84%).
3. **Regulatory environment** — Identify tailwinds (subsidies, mandates) and headwinds
   (restrictions, compliance costs).
4. **Macro trends** — Economic conditions, demographic shifts, technological enablers
   that accelerate or hinder the market.

### Phase 5: Customer Segmentation

Identify 2-5 distinct customer segments:

- **Demographics** — Age, income, geography, company size (B2B)
- **Behavioral** — Usage patterns, purchase triggers, switching costs
- **Willingness to pay** — Price sensitivity signals, competitive pricing data
- **Segment sizing** — Estimated size and growth rate per segment

### Phase 6: Report Generation

Produce the structured output below.

## Output Format

```text
## Market Analysis: {Subject}

### Executive Summary
**Market Opportunity Score: {1-5}/5**
{2-3 sentence summary of the opportunity, key market size, and timing assessment.}

### TAM / SAM / SOM

| Level | Value | Methodology | Confidence |
|-------|-------|-------------|------------|
| TAM | ${amount} | {Top-down / Bottom-up / Both} | {High/Medium/Low} |
| SAM | ${amount} | {methodology summary} | {High/Medium/Low} |
| SOM (Year 1) | ${amount} | {methodology summary} | {High/Medium/Low} |
| SOM (Year 3) | ${amount} | {methodology summary} | {High/Medium/Low} |

**Top-down calculation:**
{Step-by-step derivation with sources}

**Bottom-up calculation:**
{Step-by-step derivation with sources}

**Cross-validation:**
{Comparison of approaches, explanation of any divergence}

### Market Trends

| Dimension | Assessment | Evidence |
|-----------|-----------|----------|
| Growth trajectory | {Emerging/Growing/Mature/Declining} | {CAGR, data source} |
| Adoption stage | {Innovators/Early Adopters/Early Majority/Late Majority} | {penetration %, signal} |
| Regulatory | {Tailwind/Neutral/Headwind} | {specific regulation or policy} |
| Macro trends | {Favorable/Mixed/Unfavorable} | {key trend} |

### Customer Segments

| Segment | Size | Growth | WTP Signal | Priority |
|---------|------|--------|------------|----------|
| {name} | {size} | {rate} | {signal} | {Primary/Secondary/Tertiary} |

### Key Risks and Assumptions

| # | Assumption | Impact if Wrong | Confidence |
|---|-----------|-----------------|------------|
| 1 | {assumption} | {impact} | {High/Medium/Low} |

### Data Quality Assessment

| Data Point | Source | Date | Quality |
|-----------|--------|------|---------|
| {metric} | {source} | {date} | {Verified/Estimated/Extrapolated} |

### Recommendation
{1-2 paragraphs: proceed/pivot/investigate further, with specific next steps.}
```

## Scoring Criteria: Market Opportunity Score

| Score | Meaning     | Criteria                                                                             |
| ----- | ----------- | ------------------------------------------------------------------------------------ |
| 5     | Exceptional | Large TAM (> $10B), growing (> 15% CAGR), early adoption stage, regulatory tailwinds |
| 4     | Strong      | Large TAM or high growth, favorable timing, manageable competition                   |
| 3     | Moderate    | Mid-size market, moderate growth, competitive but differentiation possible           |
| 2     | Challenging | Small or saturated market, mature stage, significant headwinds                       |
| 1     | Unfavorable | Declining market, regulatory barriers, limited differentiation                       |

## Quality Rules

1. **Every number needs a source.** Cite the report, database, or methodology used.
   If no source exists, label the estimate as "Author extrapolation" and state the
   assumption chain.
2. **Distinguish data from extrapolation.** Use the Data Quality Assessment table to
   make this explicit for every key metric.
3. **Confidence levels are mandatory.** Each TAM/SAM/SOM figure carries a confidence
   rating with rationale.
4. **Cross-validate estimates.** Run both top-down and bottom-up. If only one approach
   is feasible, state why and reduce confidence.
5. **Date your data.** Market data older than 3 years gets a lower confidence rating.
   Flag any pre-2022 data explicitly.
6. **No vanity TAMs.** The TAM must be genuinely addressable by the product category,
   not inflated by including tangential markets.

## Error Handling

| Problem                             | Resolution                                                                             |
| ----------------------------------- | -------------------------------------------------------------------------------------- |
| No market data available            | Use proxy markets and analogies. State the proxy explicitly. Reduce confidence to Low. |
| Input too vague to size             | Ask clarifying questions (target customer, geography, price point) before proceeding.  |
| Conflicting data sources            | Present both figures, explain the discrepancy, use the more conservative estimate.     |
| Market is too new for reliable data | Size the adjacent market the product displaces. Note the nascent stage.                |
| User wants a single TAM number      | Provide the range (conservative to optimistic) with the methodology behind each bound. |

## When NOT to Analyze

Push back if:

- The request is for financial projections or revenue forecasting (different skill domain)
- The request is for pricing strategy or competitive positioning (strategy, not analysis)
- The market definition is so broad it has no analytical value ("the internet economy")
- The user has not defined what the product or idea actually does

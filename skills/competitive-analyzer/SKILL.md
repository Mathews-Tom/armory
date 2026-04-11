---
name: competitive-analyzer
description: 'Competitive landscape analysis: Porter''s Five Forces, competitor discovery, feature/pricing matrices, positioning maps, moat assessment via WebSearch. Triggers on: "competitive analysis", "competitor comparison", "competitive landscape", "Porter''s Five Forces", "market positioning", "moat assessment", "defensibility analysis".'
metadata:
  version: 1.0.1
  complements: [market-analyzer, tavily, web-fetch]
  category: business
  tags: [competitive-analysis, market, porters-five-forces, positioning]
  difficulty: advanced
  phase: define
---

# Competitive Analyzer

Systematic competitive landscape analysis: discovery, force analysis, feature comparison, pricing, positioning, and defensibility assessment.

## When to use this skill vs. others

| Need                                                | Skill                                 |
| --------------------------------------------------- | ------------------------------------- |
| Analyze competitors, compare features, assess moats | **competitive-analyzer** (this skill) |
| Market sizing, TAM/SAM/SOM, demand signals          | market-analyzer                       |
| General web research and data gathering             | tavily / web-fetch                    |

## Workflow

### Phase 1: Competitor Discovery

Identify competitors across three tiers using WebSearch.

**Tier classification:**

- **Direct competitors** — Same solution to the same customer segment. Search: `"[product category] alternatives"`, `"[product] vs"`, `"best [category] tools 2024"`
- **Indirect competitors** — Different solution to the same underlying problem. Search: `"how to [solve problem] without [category]"`, adjacent category leaders
- **Potential competitors** — Adjacent players with capability and incentive to enter. Search: recent funding rounds, platform expansion announcements, acqui-hires

**Discovery sources:**

- Product Hunt: `site:producthunt.com [category]`
- G2: `site:g2.com [category] reviews`
- Capterra: `site:capterra.com [category]`
- Crunchbase: `site:crunchbase.com [category] funding`
- Industry reports and analyst coverage

**Output:** A competitor roster table:

| Competitor | Tier | Founded | Funding | HQ  | Est. Revenue | Target Segment |
| ---------- | ---- | ------- | ------- | --- | ------------ | -------------- |

Include 5-15 competitors. Fewer than 5 suggests the search was too narrow; more than 15 suggests the scope needs tightening.

### Phase 2: Porter's Five Forces Assessment

Score each force 1-5 with supporting evidence. Reference `references/porters-five-forces.md` for scoring rubric and sub-criteria.

**1. Threat of New Entrants (1-5)**

- Capital requirements and startup costs
- Regulatory and compliance barriers
- Technology and IP barriers
- Brand loyalty and switching costs of incumbents
- Access to distribution channels
- Economies of scale advantages

**2. Supplier Power (1-5)**

- Number of available suppliers
- Uniqueness of supplier inputs
- Switching costs between suppliers
- Forward integration threat
- Dependence on key vendors (cloud, APIs, data)

**3. Buyer Power (1-5)**

- Buyer concentration relative to sellers
- Price sensitivity and transparency
- Switching costs for buyers
- Backward integration threat
- Availability of substitute information

**4. Threat of Substitutes (1-5)**

- Availability of alternative solutions
- Performance-to-price ratio of substitutes
- Buyer propensity to switch
- Switching costs to substitutes

**5. Competitive Rivalry (1-5)**

- Number and size distribution of competitors
- Industry growth rate
- Product differentiation level
- Exit barriers
- Fixed cost structure and capacity

**Synthesis:** Calculate overall industry attractiveness (weighted average of forces). Higher scores mean more competitive pressure, lower attractiveness.

### Phase 3: Feature & Pricing Matrix

Build a comprehensive comparison. Reference `references/competitive-matrix.md` for structuring methodology.

**Feature comparison table:**

| Feature Category | Feature   | Competitor A | Competitor B | Competitor C | Our Product  |
| ---------------- | --------- | ------------ | ------------ | ------------ | ------------ |
| Core             | Feature 1 | Full         | Partial      | None         | Full         |
| Integration      | API       | REST         | GraphQL      | None         | REST+GraphQL |
| Support          | SLA       | 99.9%        | 99.5%        | None         | 99.95%       |

Use: Full / Partial / None / Superior (exceeds category standard)

**Feature analysis:**

- **Table stakes** — Features every competitor offers. Missing any = disqualifier.
- **Differentiators** — Features only 1-2 competitors offer. Potential positioning angles.
- **Gaps** — Features no competitor offers. Potential innovation opportunities.
- **Over-served** — Features with extensive investment but low customer value signal.

**Pricing comparison table:**

| Competitor | Model        | Free Tier | Entry Price | Mid Tier        | Enterprise | Billing        |
| ---------- | ------------ | --------- | ----------- | --------------- | ---------- | -------------- |
| A          | Subscription | Yes       | $29/mo      | $99/mo          | Custom     | Monthly/Annual |
| B          | Usage-based  | Trial     | $0.01/unit  | Volume discount | Custom     | Monthly        |

**Pricing analysis:**

- Price-to-feature ratio positioning (value vs. premium)
- Pricing model trends in the category
- Customer segment alignment by price point

### Phase 4: Positioning Map

Reference `references/positioning-analysis.md` for dimension selection and mapping methodology.

**Step 1: Dimension selection**
Select the two dimensions most important to target customers. Common pairs:

- Price vs. Feature richness
- Ease of use vs. Power/flexibility
- SMB-focused vs. Enterprise-focused
- Vertical-specific vs. Horizontal/general

Validate dimension selection against customer research or publicly available review themes.

**Step 2: Plot competitors**
Position each competitor on the 2D map using evidence from Phase 3.

```
High [Dimension Y]
    |
    |   [Comp A]        [Comp C]
    |
    |        [Comp B]
    |                    [Our Product]
    |
    |   [Comp D]
    |
Low  ────────────────────────────── High [Dimension X]
```

**Step 3: White space identification**

- Quadrants with no or few competitors = potential positioning opportunities
- Assess whether white space is genuinely underserved or intentionally avoided (no demand)
- Evaluate feasibility of occupying the white space

### Phase 5: Moat & Defensibility Assessment

Evaluate each moat type. Reference `references/positioning-analysis.md` for the moat taxonomy.

| Moat Type       | Present? | Strength             | Evidence    |
| --------------- | -------- | -------------------- | ----------- |
| Network effects | Yes/No   | Weak/Moderate/Strong | Description |
| Switching costs | Yes/No   | Weak/Moderate/Strong | Description |
| IP / Technology | Yes/No   | Weak/Moderate/Strong | Description |
| Brand           | Yes/No   | Weak/Moderate/Strong | Description |
| Data advantage  | Yes/No   | Weak/Moderate/Strong | Description |
| Cost advantage  | Yes/No   | Weak/Moderate/Strong | Description |
| Regulatory      | Yes/No   | Weak/Moderate/Strong | Description |

**Overall moat rating:**

- **Weak** — No meaningful barriers. Competitors can replicate within 6 months.
- **Moderate** — 1-2 barriers provide temporary advantage. Replication takes 1-2 years.
- **Strong** — Multiple reinforcing barriers. Replication takes 2-5 years.
- **Very Strong** — Compounding barriers with flywheel effects. Extremely difficult to replicate.

### Phase 6: Report Generation

Produce the final competitive analysis report with these sections:

1. **Executive Summary** — Competitive landscape threat level (Low / Moderate / High / Critical), top 3 competitive risks, top 3 competitive advantages
2. **Competitor Roster** — Discovery table from Phase 1
3. **Porter's Five Forces Scorecard** — Force-by-force scoring with evidence from Phase 2
4. **Feature Comparison Matrix** — Full feature table with gap analysis from Phase 3
5. **Pricing Analysis** — Pricing table and positioning from Phase 3
6. **Positioning Map** — 2D map with white space analysis from Phase 4
7. **Moat Assessment** — Defensibility table and rating from Phase 5
8. **Strategic Recommendations**
   - Immediate actions (0-3 months): address critical gaps or threats
   - Medium-term plays (3-12 months): build differentiators and strengthen moats
   - Long-term positioning (1-3 years): sustainable competitive advantage strategy
9. **Risks & Mitigation** — Top competitive risks with specific mitigation strategies

## Quality Checks

Before delivering the report, verify:

- [ ] Competitor roster covers all three tiers (direct, indirect, potential)
- [ ] Every Five Forces score has supporting evidence, not just a number
- [ ] Feature matrix uses consistent scoring across competitors
- [ ] Pricing data is sourced and dated (pricing changes frequently)
- [ ] Positioning map dimensions are customer-relevant, not internal metrics
- [ ] Moat assessment distinguishes between current moats and aspirational moats
- [ ] Strategic recommendations are specific and actionable, not generic advice
- [ ] All claims about competitors are sourced via WebSearch, not assumed

## Edge Cases

| Situation                                     | Adaptation                                                                                                                                                                                   |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pre-launch product with no direct competitors | Focus on indirect competitors and substitutes. Emphasize the "potential entrants" tier. The absence of direct competitors is itself a signal worth analyzing (nascent market vs. no market). |
| Highly fragmented market (50+ competitors)    | Segment competitors into strategic groups. Analyze 2-3 representative competitors per group rather than every player.                                                                        |
| Monopoly or duopoly market                    | Five Forces analysis becomes more important. Focus on substitute threats and potential entrants. Analyze the dominant player's moats in detail.                                              |
| B2B enterprise with opaque pricing            | Note pricing opacity as a finding. Use job postings, case studies, and review sites for indirect pricing signals.                                                                            |
| User provides a competitor list               | Skip discovery in Phase 1. Validate the list for completeness (are there missing tiers?) and proceed to Phase 2.                                                                             |
| Rapidly changing market                       | Date-stamp all findings. Flag data older than 6 months as potentially stale. Emphasize monitoring recommendations.                                                                           |

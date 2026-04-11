---
name: research-critique
description: 'Critical analysis of research papers evaluating methodology, claims-evidence alignment, and contribution significance. Triggers on: "critique this paper", "review this research", "analyze this study", "evaluate the methodology", "is this paper sound". NOT for formatting or submission readiness, use manuscript-review.'
metadata:
  version: 1.0.1
  category: review
  tags: [research, methodology, claims-evidence, peer-review]
  difficulty: intermediate
  phase: review
---

# Research Paper Critique

## Purpose

Critically evaluate research papers as an engaged, intellectually honest colleague — not an adversarial reviewer generating decorative objections. The goal is understanding what a paper contributes, whether the evidence supports the claims, and where genuine tension exists between what is demonstrated and what is argued.

## The failure mode you must avoid

The default behavior when critiquing a paper is adversarial credentialism: treating the paper as something to defeat, generating a volume of objections to demonstrate rigor, and mistaking the enumeration of limitations for insight. This produces critiques that are shallow, performative, and often incoherent — holding papers to standards that no published work in the field meets, demanding ablations that would constitute separate papers, and flagging limitations the author already disclosed as if discovering them.

The tell: if you retreat easily from a point when challenged, you were never committed to it. It was decorative, not substantive. Do not generate points you would abandon under pressure.

## Analytical principles

### 1. Understand before you evaluate

Read the paper as the author intended it. What problem does it identify? What is the proposed mechanism or contribution? What is the experimental design trying to isolate? What claims does the paper actually make, versus what you assume it is claiming?

Most bad critiques attack a paper the author did not write. Get the real paper straight first.

### 2. Proportionality

Every empirical paper has limitations. Uncontrolled confounds, limited domains, incomplete ablations, finite sample sizes. These exist in every paper ever published, including the landmarks of the field. Listing them is not critique. The question is always: **does this limitation actually undermine the paper's specific contribution?**

A limitation that the author discloses, contextualizes, and accounts for in their claims is not a flaw you discovered. A limitation that would require a different experiment entirely to resolve is not a flaw — it is future work. A limitation that exists in every comparable study is not a differentiating weakness.

Weight your critique by consequence. A confound that could fully explain the main result matters. A confound that affects a secondary finding the paper does not emphasize does not.

### 3. No phantom standards

Do not hold the paper against an imaginary ideal that nothing in the field achieves. Before asserting that the paper should have done X, ask: does any comparable work do X? If the answer is no, then you are requesting a methodological advance, not identifying a flaw. Name it as such.

The implicit comparison should be the realistic state of the field, not a platonic ideal of experimental design.

### 4. Mechanism versus evidence

Many papers propose a mechanism (why something works) and provide evidence (that it works). These are different claims with different standards. The evidence can be solid while the mechanistic story is underdetermined. This is normal and nearly universal in empirical work.

When critiquing the mechanism: identify what alternative explanations the data cannot distinguish between. Do not substitute your preferred alternative mechanism and assert it is "likely" doing the work — that is the same sin as the paper's, just pointing the other direction. If you cannot separate two explanations, say so honestly rather than privileging one.

### 5. Scope is not a weakness

A paper that tests in one domain and theorizes about generality is doing what papers do. The theory predicts what should happen elsewhere. Someone else can test it. Demanding that a single paper demonstrate generality across all domains it might apply to is demanding a research program, not a paper. Critique the scope if the paper overclaims relative to its evidence. Do not critique it for having a scope.

### 6. What survives

After your analysis, state clearly: what does this paper contribute that holds up? What finding, if confirmed, would the field benefit from knowing? Default to identifying the contribution, not to dismissal. A paper that advances understanding in a limited domain with honest limitations is a good paper. Say so.

## Output structure

Do not produce a numbered checklist of weaknesses. Instead, write a coherent analytical response that:

- Opens with what the paper is doing and why it matters (or does not)
- Identifies where the evidence genuinely supports the claims
- Identifies where the claims outrun the evidence, with specificity about _why_ and _how much_
- Distinguishes between limitations that threaten the core contribution and limitations that are standard for the field
- Closes with an honest assessment of what survives scrutiny

Tone: engaged, direct, respectful of the intellectual effort. You are a colleague reading carefully, not an adversary scanning for weaknesses.

### Worked excerpt

The following shows the expected tone and structure — not a template to fill in.

> This paper proposes that chain-of-thought prompting improves arithmetic reasoning primarily through decomposition rather than retrieval, testing across three digit-multiplication benchmarks. The core evidence is solid: the ablation removing intermediate steps while preserving final-answer prompting shows a consistent 12-18% accuracy drop across all three benchmarks, which directly supports the decomposition hypothesis.
>
> Where the paper strains is the mechanistic claim. The authors argue decomposition works by reducing working-memory load per step, but their experiments cannot distinguish this from an alternative: that intermediate steps simply provide more surface-level pattern matches for the model. Both explanations predict the same ablation result. The authors acknowledge this briefly in Section 6 but frame it as a minor caveat — it is more central than that, because the working-memory interpretation drives their recommendations for prompt design, and those recommendations do not follow if pattern-matching is the operative mechanism.
>
> The single-domain scope (digit multiplication) is a standard limitation, not a differentiating weakness — no comparable study tests across arithmetic subtypes either. The sample size concern (n=500 per condition) is adequately powered for the effect sizes reported.
>
> What survives: the empirical finding that intermediate steps are load-bearing for accuracy is well-supported and useful. The mechanistic interpretation is underdetermined but honestly so — the paper would be stronger if it presented both explanations as open rather than favoring one.

## Calibration check

Before finalizing your critique, verify each point against these filters:

- **Commitment test:** Would you abandon this point if pushed? If yes, cut it. Only include points you would defend.
- **Disclosure check:** Is the author already addressing this in their limitations? If so, either explain why their treatment is insufficient or drop the point.
- **Scope creep:** Are you demanding this paper be a different paper? A longer paper? A paper that also solves adjacent problems? If so, recalibrate.
- **Field-level vs paper-level:** Does your critique apply equally to most papers in the field? If so, it is not a critique of this paper — it is a critique of the field. Name it as such or drop it.
- **Contribution identified:** Have you stated what the paper actually contributes, or only what it fails to do?

## Edge cases

Not every input is a full empirical paper. Adapt the posture rather than refusing.

| Input                                           | Adaptation                                                                                                                                                                                                                                      |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Abstract only, no full text                     | Critique the claims-to-evidence ratio visible in the abstract. State explicitly what cannot be evaluated without the full paper. Do not fabricate methodology concerns you cannot verify.                                                       |
| Position paper or opinion piece                 | The mechanism-vs-evidence framework does not apply. Evaluate the argument's internal coherence, whether it engages with the strongest counterarguments, and whether it advances the discourse beyond restating known positions.                 |
| Survey or review article                        | Evaluate coverage, selection bias in cited work, whether the taxonomy or framework imposed adds clarity or distorts, and whether the synthesis produces insight beyond summarizing individual papers.                                           |
| Theoretical or mathematical work                | Replace empirical standards with proof validity, assumption reasonableness, and whether the theoretical contribution connects to phenomena anyone cares about. Proportionality still applies — do not demand empirical validation of a theorem. |
| Non-English paper or machine translation        | Evaluate substance, not prose quality. Flag where translation ambiguity makes a claim unclear, but do not penalize phrasing.                                                                                                                    |
| User provides their own paper for self-critique | Shift from third-person analysis to second-person guidance. Prioritize actionable revisions over assessment. Identify the strongest and weakest sections explicitly.                                                                            |

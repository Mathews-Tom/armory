---
name: rag-auditor
description: 'Evaluates RAG pipeline quality across retrieval (precision, recall, MRR) and generation (groundedness, hallucination rate). Triggers on: "audit RAG pipeline", "RAG quality", "hallucination detection", "why is RAG failing", "grounding check". NOT for general architecture audits, use architecture-reviewer.'
metadata:
  version: 1.1.1
  category: review
  tags: [rag, retrieval, hallucination, grounding]
  difficulty: advanced
  phase: build
---

# RAG Auditor

Systematic RAG pipeline evaluation across the full retrieval-generation chain: designs
evaluation query sets, measures retrieval metrics (Precision@K, Recall@K, MRR), evaluates
generation quality (groundedness, completeness, hallucination rate), diagnoses component-level
failures, and recommends targeted improvements.

## Reference Files

| File                               | Contents                                                                   | Load When                    |
| ---------------------------------- | -------------------------------------------------------------------------- | ---------------------------- |
| `references/retrieval-metrics.md`  | Precision@K, Recall@K, MRR, NDCG definitions and calculation               | Always                       |
| `references/generation-metrics.md` | Groundedness, completeness, hallucination detection methods                | Generation evaluation needed |
| `references/failure-taxonomy.md`   | RAG failure categories: retrieval, generation, chunking, embedding         | Failure diagnosis needed     |
| `references/diagnostic-queries.md` | Designing evaluation query sets, known-answer questions, difficulty levels | Evaluation setup             |

## Prerequisites

- Access to the RAG pipeline (or its outputs for post-hoc evaluation)
- A set of test queries with known-correct answers
- Understanding of the pipeline components (embedding model, retriever, generator)

## Workflow

### Phase 1: Pipeline Inventory

Document the RAG pipeline configuration:

1. **Document source** — What documents are indexed? Format, count, size.
2. **Chunking** — Strategy (fixed-size, semantic, paragraph), chunk size, overlap.
3. **Embedding** — Model name and version, dimensionality.
4. **Vector store** — Type (FAISS, Pinecone, Chroma, pgvector), index type.
5. **Retrieval** — Method (similarity, hybrid, reranking), top-K parameter.
6. **Generation** — Model, prompt template, context window usage.

### Phase 2: Design Evaluation Queries

Create a diverse set of test queries:

| Query Type             | Purpose                                     | Count |
| ---------------------- | ------------------------------------------- | ----- |
| Known-answer (factoid) | Measure retrieval + generation accuracy     | 10+   |
| Multi-hop              | Require combining info from multiple chunks | 5+    |
| Unanswerable           | Not in the corpus — should abstain          | 3+    |
| Ambiguous              | Multiple valid interpretations              | 3+    |
| Recent/updated         | Test freshness                              | 2+    |

For each query, document the expected answer and the source chunk(s).

### Phase 3: Evaluate Retrieval

For each test query, measure:

1. **Precision@K** — Of the K retrieved chunks, how many are relevant?
2. **Recall@K** — Of all relevant chunks in the corpus, how many were retrieved?
3. **MRR (Mean Reciprocal Rank)** — How high is the first relevant chunk ranked?
4. **Chunk relevance** — Score each retrieved chunk: Relevant, Partially Relevant, Irrelevant.

### Phase 4: Evaluate Generation

For each test query with retrieved context:

1. **Groundedness** — Is every claim in the response supported by the retrieved context?
   Score: 0 (hallucinated) to 1 (fully grounded).
2. **Completeness** — Does the response use all relevant information from the context?
   Score: 0 (ignored context) to 1 (complete).
3. **Hallucination detection** — Identify specific claims not supported by context.
4. **Abstention** — For unanswerable queries, does the model correctly say "I don't know"?

### Phase 5: Diagnose Failures

For every incorrect or low-quality response, classify the root cause:

| Failure Type         | Diagnosis                                          | Indicator                                |
| -------------------- | -------------------------------------------------- | ---------------------------------------- |
| Retrieval failure    | Relevant chunks not retrieved                      | Low Recall@K                             |
| Ranking failure      | Relevant chunk retrieved but ranked low            | Low MRR, high Recall                     |
| Chunk boundary issue | Answer split across chunk boundaries               | Partial matches in multiple chunks       |
| Embedding mismatch   | Query semantics don't match chunk embeddings       | Relevant chunk has low similarity score  |
| Generation failure   | Correct context but wrong answer                   | High retrieval scores, low groundedness  |
| Hallucination        | Model invents facts not in context                 | Claims not traceable to any chunk        |
| Over-abstention      | Model refuses to answer when context is sufficient | Unanswered with relevant context present |

### Phase 6: Recommendations

Based on failure analysis, recommend specific improvements:

| Failure Pattern       | Recommendation                                                 |
| --------------------- | -------------------------------------------------------------- |
| Chunk boundary issues | Increase overlap, try semantic chunking                        |
| Low Precision@K       | Reduce K, add reranking stage                                  |
| Low Recall@K          | Increase K, try hybrid search                                  |
| Embedding mismatch    | Try different embedding model, add query expansion             |
| Hallucination         | Strengthen grounding instruction in prompt, reduce temperature |
| Over-abstention       | Soften abstention criteria in prompt                           |

## Output Format

```text
## RAG Audit Report

### Pipeline Configuration
| Component | Value |
|-----------|-------|
| Documents | {N} ({format}) |
| Chunking | {strategy}, {size} tokens, {overlap}% overlap |
| Embedding | {model} ({dimensions}d) |
| Retrieval | {method}, K={N} |
| Generation | {model}, temperature={T} |

### Evaluation Dataset
- **Total queries:** {N}
- **Known-answer:** {N}
- **Multi-hop:** {N}
- **Unanswerable:** {N}

### Retrieval Quality

| Metric | Score | Target | Status |
|--------|-------|--------|--------|
| Precision@{K} | {score} | {target} | {Pass/Fail} |
| Recall@{K} | {score} | {target} | {Pass/Fail} |
| MRR | {score} | {target} | {Pass/Fail} |

### Generation Quality

| Metric | Score | Target | Status |
|--------|-------|--------|--------|
| Groundedness | {score} | {target} | {Pass/Fail} |
| Completeness | {score} | {target} | {Pass/Fail} |
| Hallucination rate | {score} | {target} | {Pass/Fail} |
| Abstention accuracy | {score} | {target} | {Pass/Fail} |

### Failure Analysis

| # | Query | Failure Type | Root Cause | Recommendation |
|---|-------|-------------|------------|----------------|
| 1 | {query} | {type} | {cause} | {fix} |

### Recommendations (Priority Order)
1. **{Recommendation}** — addresses {N} failures, expected impact: {description}
2. **{Recommendation}** — addresses {N} failures, expected impact: {description}

### Sample Failures

#### Query: "{query}"
- **Expected:** {answer}
- **Retrieved chunks:** {chunk summaries with relevance scores}
- **Generated:** {response}
- **Issue:** {diagnosis}
```

## Calibration Rules

1. **Component isolation.** Evaluate retrieval and generation independently. A great
   retriever with a bad generator looks like retrieval failure if you only check end output.
2. **Known answers first.** Start with factoid questions where the correct answer is
   unambiguous. Multi-hop and ambiguous queries are harder to evaluate.
3. **Quantify, don't qualify.** "Retrieval is bad" is not a finding. "Precision@5 is
   0.3 (target: 0.8) with 70% of failures due to chunk boundary splits" is actionable.
4. **Sample failures deeply.** Aggregate metrics identify WHERE the problem is. Individual
   failure analysis identifies WHY.

## Error Handling

| Problem                           | Resolution                                                                                              |
| --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| No known-answer queries available | Help design them from the document corpus. Pick 10 facts and formulate questions.                       |
| Pipeline access not available     | Work from recorded inputs/outputs. Post-hoc evaluation is possible with query-context-response triples. |
| Corpus is too large to review     | Sample-based evaluation. Select representative documents and generate queries from them.                |
| Multiple failure types co-exist   | Address retrieval failures first. Generation quality cannot exceed retrieval quality.                   |

## When NOT to Audit

Push back if:

- The pipeline hasn't been built yet — design it first, audit after
- The corpus has fewer than 10 documents — too small for meaningful retrieval evaluation
- The user wants to compare embedding models — that's a benchmark task, not an audit

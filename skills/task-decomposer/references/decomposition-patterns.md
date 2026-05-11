# Decomposition Patterns

Strategies for breaking features into implementable tasks at the right granularity.

---

## Decomposition Strategies

### By Capability (Vertical Slicing)

Break by user-visible capability, implementing thin tracer bullets:

```text
Feature: User search
├── Slice 1: Basic exact-match search (all layers, minimal)
├── Slice 2: Add fuzzy matching
├── Slice 3: Add filters (date, category)
└── Slice 4: Add pagination
```

**When to use:** Default for feature implementation. Each slice is deployable,
demoable, or independently verifiable.

### By Layer (Horizontal Slicing)

Break by architectural layer only when a shared contract or infrastructure step
genuinely unblocks later vertical slices:

```text
Feature: User search
├── Data layer: Add search index, write query function
├── Logic layer: Search ranking, filtering, pagination
├── API layer: GET /search endpoint, query params
└── UI layer: Search bar, results list, loading state
```

**When to use:** Pure infrastructure, migrations, or contract setup. Avoid using this
as the main plan for user-facing features because it creates non-demoable work queues.

### By Component

Break by independent system components:

```text
Feature: Notification system
├── Component: Email provider integration
├── Component: SMS provider integration
├── Component: Notification preferences storage
├── Component: Notification dispatch service
└── Component: Delivery tracking
```

**When to use:** Multiple independent components that connect together.

### By Data Flow

Follow the data through the system:

```text
Feature: CSV import
├── Step 1: File upload and validation
├── Step 2: CSV parsing and schema detection
├── Step 3: Data transformation and mapping
├── Step 4: Batch database insertion
├── Step 5: Import result reporting
└── Step 6: Error handling and retry
```

**When to use:** Data processing pipelines, ETL features.

---

## Granularity Guide

### Right-Sized Tasks

Each task should be:

- **Completable in 1-3 days** (not weeks, not hours)
- **Independently testable** (can verify it works alone)
- **Single PR** (one review, one merge)
- **Describable in one sentence** (clear scope)
- **Vertically meaningful** when user-facing behavior is involved

### Size Indicators

| Size             | Description                | Task Count                  |
| ---------------- | -------------------------- | --------------------------- |
| S (Small)        | < 4 hours, straightforward | Combined with other S tasks |
| M (Medium)       | 4-16 hours, some decisions | Ideal task size             |
| L (Large)        | 16-40 hours, complex       | Break down further          |
| XL (Extra Large) | > 40 hours                 | Must break down further     |

### When to Break Down Further

A task needs decomposition if:

- It touches more than 3 files
- It requires more than one design decision
- You can't explain it in one sentence
- It has sub-tasks with different dependencies
- Different people could work on different parts

### When to Merge

Tasks should be merged if:

- Both take < 2 hours
- They modify the same file(s)
- One is meaningless without the other
- Testing them separately is artificial

---

## Phase Organization

### Preferred Vertical-Slice Model

| Phase | Purpose | Characteristics |
| ----- | ------- | --------------- |
| Setup | Shared contract work that unblocks slices | Minimal schema/types/fixtures only |
| Slice 1 | First narrow end-to-end behavior | Demoable tracer bullet |
| Slice N | Additional capabilities | Each adds one observable behavior |
| Hardening | Cross-slice quality gates | Performance, security, docs, cleanup |

### When to Collapse Phases

For small features (< 5 tasks), 2 phases are sufficient:

1. **Build** — All implementation
2. **Polish** — Edge cases, error handling, tests

### When to Expand Phases

For large features (> 15 tasks), add phases:

1. **Research / Spike** — Investigate unknowns
2. **Foundation** — Data layer
3. **Core** — Business logic
4. **Integration** — API + connectivity
5. **Testing** — Integration tests, load tests
6. **Polish** — UX, error handling, documentation

---

## Dependency Rules

### Hard Dependencies (Must Respect)

- Database table must exist before queries can be written
- API contract must be defined before frontend integration
- Authentication must work before authorization logic
- Data model must be stable before business logic

### Soft Dependencies (Can Work Around)

- Backend API not ready → frontend can use mocks/stubs
- Design not finalized → implement with placeholder UI
- External API not available → use recorded responses

### No Dependency (Parallel)

Tasks with no shared state, files, or contracts can be done simultaneously:

- Two independent API endpoints
- Backend and frontend working against a defined contract
- Documentation and implementation (if spec is stable)

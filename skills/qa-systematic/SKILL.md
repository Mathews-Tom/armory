---
name: qa-systematic
description: 'Systematic web application QA testing with issue taxonomy, health scoring, and regression tracking. Triggers on: "QA this", "test the app", "smoke test", "run QA", "systematic test", "regression test", "full QA", "/qa-systematic".'
metadata:
  version: 1.0.1
  category: development
  tags: [qa, testing, browser, regression]
  difficulty: advanced
  phase: verify
---

# Systematic QA Testing

## Modes

### Full (default)

Systematic page-by-page testing, 8-category health score, full issue documentation.

### Quick

30-second smoke test of critical paths only: login, main nav, primary action.

### Regression

Diff current state against saved baseline, report new/resolved issues.

## Browser Automation Detection

Detect available automation in priority order:

1. **Playwright MCP server** — check if Playwright tools are available in the current tool list
2. **`agent-browser` skill** — check if the agent-browser skill is loaded
3. **Direct CLI tools** — check for `playwright`, `puppeteer`, or `cypress` binaries on PATH
4. **Manual fallback** — instruct the user to navigate and report observations

Use the highest-priority method available. State which method is in use at the start of the report.

## Workflow

### Phase 1: Initialize

1. Detect mode from user prompt. Default to **full** if unspecified.
2. Detect application URL:
   - Check `references/project-detection.md` for framework port conventions (e.g., Next.js → 3000, Vite → 5173, Django → 8000).
   - If not detectable, ask the user.
3. Detect available browser automation method (priority list above).
4. If regression mode: load previous baseline from `.qa-reports/`.

### Phase 2: Authenticate (if needed)

1. Navigate to root URL and check if a login wall is present.
2. If credentials were provided: authenticate and store session.
3. If not: ask the user for test credentials, or skip auth-gated pages and note the gap in the report.

### Phase 3: Orient

1. Navigate to root URL.
2. Map the primary navigation structure — collect all top-level nav links.
3. Classify each page: static, form, list, detail, dashboard.
4. Build a test plan ordered by page category (forms and dashboards first — highest defect density).

### Phase 4: Explore (Full mode)

For each page, run the per-page checklist below. In quick mode, run only the items marked with (Q).

#### Visual Scan

- (Q) Layout renders correctly — no overlap, no overflow
- Images load — no broken `<img>` tags
- Typography consistent — no visible font fallbacks
- Responsive: check at desktop (1280px) and mobile (375px) widths

#### Interactive Elements

- (Q) All buttons and links are clickable and responsive
- Hover states present where expected
- Focus indicators visible for keyboard navigation
- Disabled states visually distinct

#### Forms

- (Q) Required field validation fires on empty submit
- Error messages display on invalid input
- Success feedback on valid submission
- Form resubmission handled — no duplicate submissions on double-click

#### Navigation

- (Q) All nav links resolve — no 404s
- Back button works as expected
- Deep links work — direct URL access returns correct page
- Breadcrumbs accurate (if present)

#### State Management

- Loading states displayed during async operations
- Empty states handled — no blank pages when data is absent
- Error states recoverable — retry or back options present
- Data persists across navigation — no lost form data on back/forward

#### Console

- (Q) No JavaScript errors in console
- No failed network requests (4xx/5xx)
- No mixed content warnings
- No deprecation warnings in hot paths

#### Responsiveness

- Mobile layout usable — no horizontal scroll at 375px
- Touch targets >= 44px
- Text readable without zoom (>= 16px body text)

### Phase 5: Document

For each issue found, classify using `references/issue-taxonomy.md`:

- **Severity**: critical (blocks usage), major (degrades experience), minor (cosmetic/polish)
- **Category**: functional, visual, accessibility, performance, content, navigation, security, console
- **Evidence**: screenshot description or reproduction steps

Assign a unique ID: `QA-001`, `QA-002`, etc.

Compute health score using the weights defined below and detailed in `references/report-template.md`.

### Phase 6: Wrap Up

1. Generate structured report following `references/report-template.md`.
2. Save to `.qa-reports/<YYYY-MM-DD>-<mode>.json`.
3. If full mode: save baseline for future regression comparison.
4. Present summary: health score, critical/major/minor counts, top 3 priority fixes.

## Health Score

Weighted average across 8 categories, scored 0-100.

| Category       | Weight |
| -------------- | ------ |
| Console errors | 15%    |
| Broken links   | 10%    |
| Functional     | 20%    |
| UX/Usability   | 15%    |
| Accessibility  | 15%    |
| Visual         | 10%    |
| Performance    | 10%    |
| Content        | 5%     |

**Scoring per category**: start at 100, deduct per issue by severity:

- Critical: -30
- Major: -15
- Minor: -5

Floor at 0. Final health score = weighted sum of category scores.

## Quick Mode Behavior

Run only items marked (Q) in the Phase 4 checklist. Skip health score computation — report pass/fail per critical path. Target completion: 30 seconds of actual testing time.

## Regression Mode Behavior

1. Load the most recent baseline from `.qa-reports/`.
2. Run full mode.
3. Diff issues by ID and description similarity.
4. Report: new issues, resolved issues, persistent issues.
5. Save updated baseline.

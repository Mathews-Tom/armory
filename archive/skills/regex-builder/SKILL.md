---
name: regex-builder
description:
  "DEPRECATED: The base model generates, explains, and tests regex patterns
  natively with high accuracy. This skill no longer provides meaningful uplift. Retained
  for reference only.

  "
metadata:
  version: 1.1.1
  status: deprecated
  category: development
  tags: [regex, pattern-matching, testing, validation]
  difficulty: beginner
---

> **DEPRECATED** — Modern Claude models produce accurate, well-explained regex patterns
> with edge-case test suites natively, including multi-language usage examples. The uplift
> delta from this skill approaches zero. Retained for archival reference only.

# Regex Builder

Transforms matching requirements (positive and negative examples) into tested regex
patterns with component-by-component explanations, capture group documentation, edge
case identification, and ready-to-use code in Python and JavaScript.

## Reference Files

| File                               | Contents                                                        | Load When                   |
| ---------------------------------- | --------------------------------------------------------------- | --------------------------- |
| `references/character-classes.md`  | Character class reference, Unicode categories, POSIX classes    | Always                      |
| `references/quantifiers.md`        | Quantifier behavior, greedy vs lazy vs possessive, backtracking | Pattern needs repetition    |
| `references/common-patterns.md`    | Validated patterns for email, URL, phone, IP, date, UUID, etc.  | Common validation requested |
| `references/flavor-differences.md` | Syntax differences between Python, JavaScript, PCRE, POSIX      | Multi-language usage needed |

## Prerequisites

- Clear specification: what should match and what should not
- Target regex flavor (Python `re`, JavaScript, PCRE) — defaults to Python

## Workflow

### Phase 1: Collect Examples

Gather positive (should match) and negative (should not match) examples:

1. **From user** — Explicit examples provided
2. **From context** — If the user says "match email addresses," infer standard positive
   and negative examples
3. **From data** — If sample data is provided, identify the pattern within it

Minimum: 3 positive examples and 3 negative examples. Fewer examples risk overfitting
the pattern to specific cases.

### Phase 2: Infer Pattern

Analyze the examples to build a pattern:

1. **Identify fixed literals** — Characters that appear in the same position across all
   positive examples
2. **Identify character classes** — Positions where different characters appear but follow
   a pattern (digits, letters, alphanumeric)
3. **Identify repetition** — Elements that appear a variable number of times
4. **Identify optional elements** — Parts present in some positive examples but not others
5. **Identify anchoring** — Must the pattern match the entire string or can it be a substring?

### Phase 3: Explain Pattern

Break down the pattern into a component table:

| Component  | Meaning                     |
| ---------- | --------------------------- |
| `^`        | Start of string             |
| `[A-Za-z]` | One letter (upper or lower) |
| `\d{3,5}`  | 3 to 5 digits               |
| `$`        | End of string               |

Document capture groups separately if the pattern uses them.

### Phase 4: Generate Edge Cases

For every pattern, identify inputs that are likely to cause problems:

1. **Empty string** — Does the pattern handle it correctly?
2. **Almost-matching strings** — One character off from a valid match
3. **Boundary lengths** — Minimum and maximum valid lengths
4. **Special characters** — Dots, brackets, backslashes in the input
5. **Unicode** — Multi-byte characters, emoji, diacritics
6. **Catastrophic backtracking** — Inputs that cause exponential matching time

### Phase 5: Output

Produce the pattern, explanation, test cases, and usage examples.

## Output Format

````
## Regex Pattern: {Brief Description}

### Requirements
- **Must match:** {description of valid inputs}
- **Must reject:** {description of invalid inputs}
- **Flavor:** {Python re | JavaScript | PCRE}

### Pattern
```regex
{pattern}
````

### Explanation

| Component     | Meaning                   |
| ------------- | ------------------------- |
| `{component}` | {what it matches and why} |

### Capture Groups

| Group | Name   | Captures | Example         |
| ----- | ------ | -------- | --------------- |
| 1     | {name} | {what}   | {example value} |

### Test Cases

| #   | Input      | Should Match | Reason             |
| --- | ---------- | ------------ | ------------------ |
| 1   | `{input}`  | Yes          | {why — happy path} |
| 2   | `{input}`  | Yes          | {why — boundary}   |
| 3   | `{input}`  | No           | {why — invalid}    |
| 4   | `{input}`  | No           | {why — near-miss}  |
| 5   | `` (empty) | No           | Empty input        |

### Edge Cases

- {Edge case 1}: {what to watch for}
- {Edge case 2}: {what to watch for}

### Usage

**Python:**

```python
import re

pattern = re.compile(r'{pattern}')

# Match entire string
if pattern.fullmatch(text):
    ...

# Search within string
match = pattern.search(text)
if match:
    captured = match.group(1)

# Find all matches
matches = pattern.findall(text)
```

**JavaScript:**

```javascript
const pattern = /{pattern}/;

// Test
if (pattern.test(text)) { ... }

// Match
const match = text.match(pattern);
if (match) {
    const captured = match[1];
}

// Find all
const matches = [...text.matchAll(/{pattern}/g)];
```

```text

## Calibration Rules

1. **Correctness over cleverness.** A readable, slightly longer pattern is better than
   a cryptic short one. `[A-Za-z0-9]` is clearer than `\w` when you specifically mean
   alphanumeric without underscores.
2. **Test negatives as rigorously as positives.** A pattern that matches everything
   technically matches all positive examples. Negative examples prevent over-matching.
3. **Anchor when appropriate.** `^\d{3}$` matches exactly 3 digits. `\d{3}` matches
   3 digits anywhere in the string. State the anchoring intent explicitly.
4. **Avoid catastrophic backtracking.** Nested quantifiers like `(a+)+` cause exponential
   time on non-matching input. Test with adversarial inputs.
5. **Named groups over numbered groups.** `(?P<year>\d{4})` (Python) or `(?<year>\d{4})`
   (JS) is self-documenting. Use numbered groups only for simple patterns.
6. **Specify the flavor.** Python `re`, JavaScript, and PCRE have different feature sets.
   Lookaheads, lookbehinds, and Unicode support vary.

## Error Handling

| Problem | Resolution |
|---------|------------|
| Insufficient examples | Ask for more. Minimum 3 positive, 3 negative. |
| Contradictory examples | Flag the contradiction. Ask which examples are correct. |
| Requirements too complex for regex | Suggest a parser instead. Regex cannot handle recursive structures (nested brackets, HTML). |
| Pattern causes backtracking | Rewrite with atomic groups or possessive quantifiers. Test with worst-case input. |
| Unicode requirements unclear | Ask if the pattern needs to handle non-ASCII. Default to ASCII unless specified. |
| Multiple valid patterns | Present the simplest one. Mention alternatives if they have meaningful tradeoffs (performance vs readability). |

## When NOT to Build Regex

Push back if:
- The input requires parsing a recursive grammar (HTML, JSON, nested expressions) — use a parser
- The validation is for a standard format with a library (email validation, URL parsing) — use the standard library
- The pattern is for security-critical input validation as the sole defense — regex is a first filter, not a security boundary
- The user wants to modify matched content in complex ways — regex replacement has limits; suggest code instead
```

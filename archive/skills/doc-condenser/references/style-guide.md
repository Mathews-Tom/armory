# Style Guide Reference

Detailed formatting rules for document condensation. Load when applying specific patterns.

## Path Formatting

```markdown
# Always include as first line of output file:

# C:\project\path\to\filename.md

# In tables:

| Path                   | Description      |
| ---------------------- | ---------------- |
| `scripts/validator.py` | Main entry point |
| `data/lexicons/*.json` | Runtime lexicons |

# In prose:

The validator (`scripts/word_validator_v3.py`) uses...
```

## Table Patterns

### Status/Metrics Table

```markdown
| Metric | Value         |
| ------ | ------------- |
| Accept | 3,936 (87.8%) |
| Reject | 396 (8.8%)    |
| Manual | 153 (3.4%)    |
```

### File Listing Table

```markdown
### Category Name (`parent/dir/`)

| File       | Purpose              |
| ---------- | -------------------- |
| `name.ext` | One-line description |
```

### Coverage/Capability Matrix

```markdown
| Feature    | Status | Method          |
| ---------- | ------ | --------------- |
| Base verbs | 100%   | Kosha lookup    |
| Compounds  | ~90%   | Recursive split |
```

### Comparison Table

```markdown
| Aspect | Option A | Option B | Winner |
| ------ | -------- | -------- | ------ |
| Speed  | Fast     | Slow     | A      |
```

## Code Sample Guidelines

### Include When

- Shows a pattern Claude generated that we refined
- Illustrates data structure/schema
- Demonstrates API usage
- Under 15 lines

### Format

```python
# Brief comment explaining what this shows
def example_function(param: str) -> Result:
    """Docstring only if essential."""
    return lookup(param)  # Inline comment for non-obvious line
```

### Exclude When

- Full implementation (link instead)
- Boilerplate/setup code
- Test code unless testing is the topic
- Multiple similar examples (pick best one)

## Commentary Style

### Good

```markdown
The validator uses pure lookup - no heuristics.
```

### Bad

```markdown
The validator has been designed to use a pure lookup-based approach,
which means that instead of using heuristics or guessing, it performs
direct lookups against the complete index. This was chosen because...
```

## Section Headers

```markdown
## Major Section # Top-level grouping

### Subsection # Category within section

#### Detail (rare) # Only if necessary
```

Avoid deep nesting. If you need `####`, consider restructuring.

## Quick Reference Block

Always end with scannable summary:

````markdown
## Quick Reference

| Key   | Value      |
| ----- | ---------- |
| Index | 287K forms |
| Speed | 6-7ms/word |
| Roots | 2,162      |

Or as code block:

```text

```
````

## Word Budget Guidelines

| Section                | Target                          |
| ---------------------- | ------------------------------- |
| Purpose                | 2-3 sentences                   |
| Architecture           | 5-10 lines or diagram           |
| File tables            | No limit (tables are scannable) |
| Commentary per section | 1-2 sentences                   |
| History reference      | 1 line                          |
| Quick reference        | 5-10 lines                      |

**Total document**: Aim for 70-80% reduction from verbose original while preserving all technical substance.

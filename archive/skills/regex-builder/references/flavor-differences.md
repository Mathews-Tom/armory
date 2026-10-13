# Flavor Differences

Syntax and feature differences between Python `re`, JavaScript, PCRE, and POSIX
regex implementations.

---

## Feature Comparison

| Feature                | Python `re`                              | JavaScript                            | PCRE                              | POSIX      |
| ---------------------- | ---------------------------------------- | ------------------------------------- | --------------------------------- | ---------- |
| Named groups           | `(?P<name>...)`                          | `(?<name>...)`                        | `(?P<name>...)` or `(?<name>...)` | No         |
| Lookahead              | `(?=...)`, `(?!...)`                     | `(?=...)`, `(?!...)`                  | `(?=...)`, `(?!...)`              | No         |
| Lookbehind             | `(?<=...)`, `(?<!...)` (variable length) | `(?<=...)` (limited in older engines) | `(?<=...)` (fixed length)         | No         |
| Atomic groups          | No (use `regex` module)                  | No                                    | `(?>...)`                         | No         |
| Possessive quantifiers | No (use `regex` module)                  | No                                    | `*+`, `++`, `?+`                  | No         |
| Unicode categories     | Limited (`\w` is Unicode-aware)          | `\p{L}` with `u` flag                 | `\p{L}`                           | No         |
| Backreferences         | `\1`, `(?P=name)`                        | `\1`, `\k<name>`                      | `\1`, `\k<name>`                  | `\1` (BRE) |
| Conditional            | No                                       | No                                    | `(?(cond)yes\|no)`                | No         |
| Comments               | `(?#comment)`, `re.VERBOSE`              | No                                    | `(?#comment)`, `x` flag           | No         |
| Recursion              | No                                       | No                                    | `(?R)`, `(?1)`                    | No         |

---

## Named Group Syntax

### Python

```python
import re
pattern = re.compile(r'(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})')
match = pattern.match('2026-02-25')
match.group('year')  # '2026'
match.groupdict()    # {'year': '2026', 'month': '02', 'day': '25'}
```

### JavaScript

```javascript
const pattern = /(?<year>\d{4})-(?<month>\d{2})-(?<day>\d{2})/;
const match = "2026-02-25".match(pattern);
match.groups.year; // '2026'
```

### Conversion

| Python          | JavaScript     | Meaning             |
| --------------- | -------------- | ------------------- |
| `(?P<name>...)` | `(?<name>...)` | Named capture group |
| `(?P=name)`     | `\k<name>`     | Named backreference |

---

## Flag Differences

| Purpose                                | Python                             | JavaScript    | PCRE                |
| -------------------------------------- | ---------------------------------- | ------------- | ------------------- |
| Case insensitive                       | `re.IGNORECASE` or `(?i)`          | `/i`          | `(?i)` or `i` flag  |
| Multiline (`^$` match line boundaries) | `re.MULTILINE` or `(?m)`           | `/m`          | `(?m)` or `m` flag  |
| Dot matches newline                    | `re.DOTALL` or `(?s)`              | `/s`          | `(?s)` or `s` flag  |
| Verbose/comments                       | `re.VERBOSE` or `(?x)`             | Not supported | `(?x)` or `x` flag  |
| Unicode                                | `re.UNICODE` (default in Python 3) | `/u`          | Default             |
| Global (find all)                      | `re.findall()` or `re.finditer()`  | `/g`          | N/A (API-dependent) |

---

## Escape Differences

### String Escaping vs Regex Escaping

**Python:** Use raw strings to avoid double escaping:

```python
# BAD: Backslash needs double escaping
pattern = '\\d+\\.\\d+'

# GOOD: Raw string
pattern = r'\d+\.\d+'
```

**JavaScript:** No raw string equivalent. Regex literals avoid the issue:

```javascript
// Regex literal — no extra escaping
const pattern = /\d+\.\d+/;

// String constructor — needs escaping
const pattern = new RegExp("\\d+\\.\\d+");
```

---

## Method Differences

### Python

```python
import re

# Compile once, use many times
pattern = re.compile(r'\d+')

pattern.match(string)       # Match at start of string
pattern.search(string)      # Search anywhere in string
pattern.fullmatch(string)   # Match entire string
pattern.findall(string)     # List of all matches
pattern.finditer(string)    # Iterator of match objects
pattern.sub(repl, string)   # Replace matches
pattern.split(string)       # Split on matches
```

### JavaScript

```javascript
const pattern = /\d+/g;

string.match(pattern); // Array of matches (with /g)
string.matchAll(pattern); // Iterator of match objects (with /g)
string.search(pattern); // Index of first match (-1 if none)
string.replace(pattern, rep); // Replace matches
string.split(pattern); // Split on matches
pattern.test(string); // Boolean: matches or not
pattern.exec(string); // Next match object (stateful with /g)
```

---

## Portability Guidelines

When writing patterns that must work across languages:

1. **Use basic syntax only:** `[...]`, `\d`, `\w`, `\s`, `*`, `+`, `?`, `{n,m}`
2. **Avoid named groups** or use the target language's syntax
3. **Avoid lookbehinds** — not universally supported
4. **Avoid possessive quantifiers** — Python and JavaScript don't support them
5. **Avoid `\b` in JavaScript** — works differently in some contexts
6. **Test in each target language** — subtle differences can cause mismatches

### Safest Subset

These features work identically across Python, JavaScript, and PCRE:

- Character classes: `[a-z]`, `[^0-9]`
- Shorthand classes: `\d`, `\w`, `\s` (with ASCII flag)
- Quantifiers: `*`, `+`, `?`, `{n,m}` (greedy and lazy)
- Alternation: `|`
- Grouping: `(...)`
- Anchors: `^`, `$`
- Lookahead: `(?=...)`, `(?!...)`
- Non-capturing group: `(?:...)`

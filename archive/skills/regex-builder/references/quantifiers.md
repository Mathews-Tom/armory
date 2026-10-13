# Quantifiers

Quantifier behavior, greedy vs lazy vs possessive matching, and backtracking.

---

## Basic Quantifiers

| Quantifier | Meaning         | Example                              |
| ---------- | --------------- | ------------------------------------ |
| `*`        | 0 or more       | `a*` matches "", "a", "aaa"          |
| `+`        | 1 or more       | `a+` matches "a", "aaa" (not "")     |
| `?`        | 0 or 1          | `a?` matches "" or "a"               |
| `{n}`      | Exactly n       | `a{3}` matches "aaa" only            |
| `{n,}`     | n or more       | `a{2,}` matches "aa", "aaa", ...     |
| `{n,m}`    | Between n and m | `a{2,4}` matches "aa", "aaa", "aaaa" |

---

## Greedy vs Lazy

### Greedy (Default)

Greedy quantifiers match as much as possible, then backtrack if needed:

```regex
".*"    applied to: He said "hello" and "goodbye"
        matches:    "hello" and "goodbye"  ← greedy grabs everything between first " and last "
```

### Lazy (Non-Greedy)

Lazy quantifiers match as little as possible:

```regex
".*?"   applied to: He said "hello" and "goodbye"
        matches:    "hello"  then  "goodbye"  ← lazy stops at first closing "
```

| Greedy  | Lazy     | Behavior                       |
| ------- | -------- | ------------------------------ |
| `*`     | `*?`     | Match minimum (prefer shorter) |
| `+`     | `+?`     | Match minimum but at least 1   |
| `?`     | `??`     | Prefer not matching (0)        |
| `{n,m}` | `{n,m}?` | Prefer n over m                |

### When to Use Lazy

- Parsing delimited content: `".*?"` for quoted strings
- Extracting the first match: `<tag>.*?</tag>` for XML-like content
- Avoiding over-matching in repetitive patterns

### When to Use Greedy

- When the pattern has a clear terminator: `[^"]*` (everything except quote)
- When you want the longest match
- Default — change to lazy only when greedy over-matches

---

## Possessive Quantifiers

Possessive quantifiers match as much as possible and **never backtrack**:

| Greedy | Possessive | Available In                               |
| ------ | ---------- | ------------------------------------------ |
| `*`    | `*+`       | PCRE, Java (NOT Python re, NOT JavaScript) |
| `+`    | `++`       | PCRE, Java                                 |
| `?`    | `?+`       | PCRE, Java                                 |

```regex
# Possessive: fails fast on non-matching input
\d++\.?\d*+

# Equivalent in Python using atomic group (regex module)
(?>\\d+)\\.?\\d*
```

Possessive quantifiers prevent catastrophic backtracking by eliminating retry paths.

---

## Backtracking

### How Backtracking Works

```text
Pattern: a+b
Input:   aaac

Step 1: a+ matches "aaa" (greedy)
Step 2: b doesn't match "c"
Step 3: a+ backtracks to "aa"
Step 4: b doesn't match "a"
Step 5: a+ backtracks to "a"
Step 6: b doesn't match "a"
Step 7: a+ backtracks to "" — but + requires at least 1
Step 8: FAIL — no match
```

For simple patterns, backtracking is fast. For pathological patterns, it's catastrophic.

### Catastrophic Backtracking

```regex
# DANGEROUS: nested quantifiers
(a+)+b

# Input: "aaaaaaaaaaaaaac" (14 a's followed by c)
# The engine tries 2^14 = 16,384 combinations before failing
# Each additional 'a' doubles the time
```

**Detection:** Nested quantifiers where the inner and outer pattern overlap:

- `(a+)+` — a+ repeats, then the group repeats
- `(a*)*` — similar nesting
- `(a|aa)+` — alternation creates similar branching

**Fix:**

1. Remove nesting: `(a+)+b` → `a+b`
2. Use possessive quantifier: `(a++)b`
3. Use atomic group: `(?>a+)b`
4. Rewrite the pattern to be more specific

### Backtracking Performance

| Pattern   | Input Length N | Time Complexity      |
| --------- | -------------- | -------------------- |
| `a+b`     | N              | O(N) — linear        |
| `(a+)+b`  | N (no match)   | O(2^N) — exponential |
| `a*a*a*b` | N (no match)   | O(N^3) — polynomial  |

---

## Practical Quantifier Patterns

### Match a Specific Range

```regex
# IP octet: 0-255
(25[0-5]|2[0-4]\d|[01]?\d\d?)

# Port number: 1-65535
([1-9]\d{0,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5])
```

### Optional Section

```regex
# Optional area code: (123) 456-7890 or 456-7890
(\(\d{3}\)\s?)?\d{3}-\d{4}
```

### Alternation with Quantifiers

```regex
# Match "color" or "colour"
colou?r

# Match "gray" or "grey"
gr[ae]y

# Match "http" or "https"
https?
```

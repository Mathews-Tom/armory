# Character Classes

Reference for regex character classes, shorthand notations, Unicode categories,
and POSIX classes.

---

## Basic Character Classes

| Syntax        | Matches          | Example                         |
| ------------- | ---------------- | ------------------------------- |
| `[abc]`       | a, b, or c       | `[aeiou]` matches vowels        |
| `[^abc]`      | NOT a, b, or c   | `[^0-9]` matches non-digits     |
| `[a-z]`       | Lowercase letter | Range within brackets           |
| `[A-Z]`       | Uppercase letter | Range within brackets           |
| `[0-9]`       | Digit            | Range within brackets           |
| `[a-zA-Z]`    | Any letter       | Combined ranges                 |
| `[a-zA-Z0-9]` | Alphanumeric     | Combined ranges                 |
| `[-]`         | Literal hyphen   | Place at start or end: `[-a-z]` |

---

## Shorthand Classes

| Shorthand | Equivalent        | Matches                              |
| --------- | ----------------- | ------------------------------------ |
| `\d`      | `[0-9]`           | Digit                                |
| `\D`      | `[^0-9]`          | Non-digit                            |
| `\w`      | `[a-zA-Z0-9_]`    | Word character (includes underscore) |
| `\W`      | `[^a-zA-Z0-9_]`   | Non-word character                   |
| `\s`      | `[ \t\n\r\f\v]`   | Whitespace                           |
| `\S`      | `[^ \t\n\r\f\v]`  | Non-whitespace                       |
| `.`       | `[^\n]` (default) | Any character except newline         |

### Important: `\w` Includes Underscore

`\w` matches `[a-zA-Z0-9_]`, not `[a-zA-Z0-9]`. If you want alphanumeric without
underscore, use `[a-zA-Z0-9]` or `[^\W_]`.

### Important: `.` Does NOT Match Newline

By default, `.` matches any character except `\n`. To match newlines too:

- Python: `re.DOTALL` flag or `(?s)` inline
- JavaScript: `s` flag (`/./s`)

---

## Unicode Categories (Python, PCRE)

| Category         | Syntax   | Matches                |
| ---------------- | -------- | ---------------------- |
| Letter           | `\p{L}`  | Any Unicode letter     |
| Uppercase letter | `\p{Lu}` | Uppercase letters      |
| Lowercase letter | `\p{Ll}` | Lowercase letters      |
| Digit            | `\p{Nd}` | Numeric digits         |
| Punctuation      | `\p{P}`  | Punctuation characters |
| Symbol           | `\p{S}`  | Symbols                |
| Whitespace       | `\p{Z}`  | Separators/whitespace  |

**Python support:** Requires `regex` module (not `re`) for `\p{...}` syntax. The
built-in `re` module supports Unicode matching with `re.UNICODE` flag but not
category syntax.

**JavaScript support:** `\p{...}` available with `u` flag (`/\p{L}/u`).

---

## Special Characters (Need Escaping)

These characters have special meaning in regex and must be escaped with `\` to
match literally:

```text
. ^ $ * + ? { } [ ] \ | ( )
```

| To Match | Use  |
| -------- | ---- |
| `.`      | `\.` |
| `*`      | `\*` |
| `(`      | `\(` |
| `[`      | `\[` |
| `\`      | `\\` |
| `$`      | `\$` |

### Inside Character Classes

Inside `[...]`, most special characters are literal. Only these need escaping:

- `]` → `\]`
- `\` → `\\`
- `^` → `\^` (only at the start)
- `-` → `\-` (or place at start/end: `[-a-z]`)

---

## Anchors

| Anchor | Matches                                     | Notes                 |
| ------ | ------------------------------------------- | --------------------- |
| `^`    | Start of string (or line with MULTILINE)    |                       |
| `$`    | End of string (or line with MULTILINE)      |                       |
| `\b`   | Word boundary                               | Between `\w` and `\W` |
| `\B`   | Non-word boundary                           |                       |
| `\A`   | Start of string (always, ignores MULTILINE) | Python, PCRE          |
| `\Z`   | End of string (always)                      | Python                |
| `\z`   | End of string (always)                      | PCRE, Java            |

### Word Boundary Examples

```regex
\bcat\b     matches "cat" in "the cat sat"
            does NOT match "cat" in "concatenate"

\Bcat\B     matches "cat" in "concatenate"
            does NOT match "cat" in "the cat sat"
```

---

## Lookaround (Zero-Width Assertions)

| Syntax     | Name                | Matches                 |
| ---------- | ------------------- | ----------------------- |
| `(?=...)`  | Positive lookahead  | Followed by pattern     |
| `(?!...)`  | Negative lookahead  | NOT followed by pattern |
| `(?<=...)` | Positive lookbehind | Preceded by pattern     |
| `(?<!...)` | Negative lookbehind | NOT preceded by pattern |

```regex
# Password: at least one digit, one uppercase, one lowercase
^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{8,}$

# Match "foo" not followed by "bar"
foo(?!bar)

# Match number preceded by "$"
(?<=\$)\d+\.?\d*
```

**JavaScript limitation:** Lookbehinds must be fixed-length in older engines.
Modern V8 (Chrome, Node.js) supports variable-length lookbehinds.

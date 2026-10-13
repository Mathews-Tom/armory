# Common Patterns

Validated regex patterns for common data formats. Each pattern includes the regex,
explanation, test cases, and known limitations.

---

## Email Address (Simplified)

```regex
^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$
```

| Component           | Meaning                                              |
| ------------------- | ---------------------------------------------------- |
| `^`                 | Start of string                                      |
| `[a-zA-Z0-9._%+-]+` | Local part: letters, digits, dots, underscores, etc. |
| `@`                 | Literal @                                            |
| `[a-zA-Z0-9.-]+`    | Domain: letters, digits, dots, hyphens               |
| `\.`                | Literal dot                                          |
| `[a-zA-Z]{2,}`      | TLD: 2+ letters                                      |
| `$`                 | End of string                                        |

**Limitation:** Does not cover all RFC 5322 valid addresses (quoted strings, IP
literals). For production email validation, use a library.

---

## URL

```regex
^https?://[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*(/[^\s]*)?$
```

**Simplified version for common URLs:**

```regex
^https?://[\w.-]+(/[\w./?%&=-]*)?$
```

**Limitation:** Does not validate all valid URLs. For production, use `urllib.parse`.

---

## IPv4 Address

```regex
^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$
```

| Component    | Meaning                      |
| ------------ | ---------------------------- |
| `25[0-5]`    | 250-255                      |
| `2[0-4]\d`   | 200-249                      |
| `[01]?\d\d?` | 0-199                        |
| `\.`         | Literal dot                  |
| `{3}`        | First three octets with dots |

**Test cases:**

- `192.168.1.1` ✅
- `0.0.0.0` ✅
- `255.255.255.255` ✅
- `256.1.1.1` ❌
- `192.168.1` ❌
- `192.168.1.1.1` ❌

---

## UUID (v4)

```regex
^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$
```

| Component           | Meaning             |
| ------------------- | ------------------- |
| `[0-9a-f]{8}`       | 8 hex chars         |
| `4[0-9a-f]{3}`      | Version 4 indicator |
| `[89ab][0-9a-f]{3}` | Variant bits        |

Add `i` flag for case-insensitive matching (`A-F` included).

---

## Date (YYYY-MM-DD)

```regex
^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$
```

| Component               | Meaning      |
| ----------------------- | ------------ |
| `\d{4}`                 | 4-digit year |
| `0[1-9]\|1[0-2]`        | Month 01-12  |
| `0[1-9]\|[12]\d\|3[01]` | Day 01-31    |

**Limitation:** Allows invalid dates like 2026-02-31. For date validation, parse
with a date library after regex filtering.

---

## Phone Number (US)

```regex
^(\+1[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}$
```

**Matches:**

- `555-123-4567` ✅
- `(555) 123-4567` ✅
- `+1-555-123-4567` ✅
- `5551234567` ✅

**Limitation:** US-centric. International phone validation requires a library like
`phonenumbers`.

---

## Semantic Version

```regex
^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-([a-zA-Z\d][-a-zA-Z.\d]*))?(\+([a-zA-Z\d][-a-zA-Z.\d]*))?$
```

**Matches:**

- `1.0.0` ✅
- `1.2.3-beta.1` ✅
- `1.2.3+build.123` ✅
- `01.0.0` ❌ (leading zero)

---

## Hex Color

```regex
^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$
```

**Matches:**

- `#fff` ✅ (shorthand)
- `#FF5733` ✅ (full)
- `#FF573380` ✅ (with alpha)
- `#gggggg` ❌

---

## Password Strength

```regex
^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*]).{8,}$
```

| Component          | Meaning                   |
| ------------------ | ------------------------- |
| `(?=.*[a-z])`      | At least one lowercase    |
| `(?=.*[A-Z])`      | At least one uppercase    |
| `(?=.*\d)`         | At least one digit        |
| `(?=.*[!@#$%^&*])` | At least one special char |
| `.{8,}`            | Minimum 8 characters      |

**Note:** Password strength is better assessed by entropy/length than character
class rules. This pattern is provided because it's commonly requested.

---

## Whitespace Normalization

```regex
\s+
```

Replace with a single space to normalize whitespace:

```python
re.sub(r'\s+', ' ', text).strip()
```

---

## File Extension

```regex
\.([a-zA-Z0-9]+)$
```

Captures the extension without the dot. For specific extensions:

```regex
\.(py|js|ts|rs|go)$
```

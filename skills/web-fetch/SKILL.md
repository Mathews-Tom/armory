---
name: web-fetch
description: 'Web content fetching via curl and WebFetch when a specific URL is provided. Covers HTTP GET/POST, JSON APIs, HTML, auth, cookies. Triggers on: "fetch this URL", "download HTML", "call this API", "curl this endpoint". NOT for search, use tavily.'
metadata:
  version: 1.1.1
  category: content
  tags: [http, curl, api, web-content]
  difficulty: beginner
---

# Web Fetch

All web content retrieval uses `curl` (Bash) or the built-in `WebFetch` tool. No MCP
server needed — Claude Code's native tools cover every Fetch MCP operation with more
control.

## Quick Reference

| Fetch MCP Tool   | Replacement                 | When to Use                                        |
| ---------------- | --------------------------- | -------------------------------------------------- |
| `fetch_html`     | `curl -s URL`               | Raw HTML needed for parsing                        |
| `fetch_json`     | `curl -s URL \| jq '.'`     | API responses, structured data                     |
| `fetch_markdown` | `WebFetch`                  | Readable page content (default output is markdown) |
| `fetch_txt`      | `curl -s URL` or `WebFetch` | Plain text extraction                              |

**Default choice:** Use `WebFetch` for general page content. Use `curl` when you need
headers, authentication, POST bodies, or raw format control.

---

## WebFetch (Built-in Tool)

The `WebFetch` tool fetches a URL and returns clean markdown content. It handles
JavaScript-rendered pages, strips navigation and boilerplate, and returns readable text.

Best for: documentation pages, articles, blog posts, README files — any content where
you want readable text rather than raw HTML.

Limitations: no custom headers, no POST bodies, no cookie management. Use `curl` for
those.

---

## curl Patterns

### Fetch HTML

```bash
curl -sL "https://example.com/page"
```

| Flag           | Purpose                               |
| -------------- | ------------------------------------- |
| `-s`           | Silent mode — suppress progress meter |
| `-L`           | Follow redirects (3xx)                |
| `-o file.html` | Save to file instead of stdout        |
| `-I`           | Headers only (HEAD request)           |
| `-i`           | Include response headers in output    |

Fetch and extract specific elements with `xmllint` or `python3`:

```bash
curl -sL "https://example.com" | python3 -c "
from html.parser import HTMLParser
import sys

class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ''
    def handle_starttag(self, tag, attrs):
        self.in_title = tag == 'title'
    def handle_data(self, data):
        if self.in_title:
            self.title += data
    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

p = TitleParser()
p.feed(sys.stdin.read())
print(p.title)
"
```

### Fetch JSON

```bash
curl -s "https://api.example.com/v1/data" \
  -H "Accept: application/json" | jq '.'
```

Filter and reshape JSON responses:

```bash
# Extract specific fields
curl -s "https://api.example.com/users" | jq '.[] | {name, email}'

# Filter by condition
curl -s "https://api.example.com/items" | jq '[.[] | select(.status == "active")]'

# Count results
curl -s "https://api.example.com/items" | jq 'length'

# Get nested value
curl -s "https://api.example.com/config" | jq '.database.host'
```

### Fetch Plain Text

```bash
# Strip HTML tags for plain text
curl -sL "https://example.com/page" | python3 -c "
import html.parser, sys

class Stripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
    def get_text(self):
        return ''.join(self.text)

s = Stripper()
s.feed(sys.stdin.read())
print(s.get_text())
"
```

Or use `WebFetch` which returns clean markdown — close enough to plain text for most
purposes.

---

## Authenticated Requests

### Bearer Token

```bash
curl -s "https://api.example.com/data" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json"
```

### API Key in Header

```bash
curl -s "https://api.example.com/data" \
  -H "X-API-Key: $API_KEY"
```

### API Key in Query Parameter

```bash
curl -s "https://api.example.com/data?api_key=$API_KEY"
```

### Basic Auth

```bash
curl -s -u "username:$PASSWORD" "https://api.example.com/data"
```

Store credentials in environment variables. Never hardcode tokens or passwords in
commands.

---

## POST, PUT, PATCH, DELETE

### POST with JSON Body

```bash
curl -s -X POST "https://api.example.com/items" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{
    "name": "item-name",
    "value": 42
  }' | jq '.'
```

### POST with Form Data

```bash
curl -s -X POST "https://api.example.com/upload" \
  -F "file=@./document.pdf" \
  -F "description=Uploaded via curl"
```

### PUT (Full Update)

```bash
curl -s -X PUT "https://api.example.com/items/123" \
  -H "Content-Type: application/json" \
  -d '{"name": "updated-name", "value": 99}' | jq '.'
```

### PATCH (Partial Update)

```bash
curl -s -X PATCH "https://api.example.com/items/123" \
  -H "Content-Type: application/json" \
  -d '{"value": 100}' | jq '.'
```

### DELETE

```bash
curl -s -X DELETE "https://api.example.com/items/123" \
  -H "Authorization: Bearer $API_TOKEN"
```

---

## Advanced Patterns

### Pagination

```bash
PAGE=1
while true; do
  RESPONSE=$(curl -s "https://api.example.com/items?page=$PAGE&per_page=50" \
    -H "Authorization: Bearer $API_TOKEN")
  COUNT=$(echo "$RESPONSE" | jq 'length')
  echo "$RESPONSE" | jq '.[]'
  [ "$COUNT" -lt 50 ] && break
  PAGE=$((PAGE + 1))
done
```

### Timeout and Retry

```bash
curl -s --connect-timeout 10 --max-time 30 \
  --retry 3 --retry-delay 2 \
  "https://api.example.com/data"
```

### Response Headers Inspection

```bash
curl -sI "https://example.com" | grep -i "content-type"
```

### Save Response with Status Code

```bash
HTTP_CODE=$(curl -s -o /tmp/response.json -w "%{http_code}" "https://api.example.com/data")
echo "Status: $HTTP_CODE"
cat /tmp/response.json | jq '.'
```

### Cookie Handling

```bash
# Save cookies
curl -s -c /tmp/cookies.txt "https://example.com/login" \
  -d "user=admin&pass=$PASSWORD"

# Reuse cookies
curl -s -b /tmp/cookies.txt "https://example.com/dashboard"
```

---

## Error Handling

| HTTP Status | Meaning             | Resolution                                               |
| ----------- | ------------------- | -------------------------------------------------------- |
| 301/302     | Redirect            | Add `-L` flag to follow                                  |
| 401         | Unauthorized        | Check token/credentials; verify env var is set           |
| 403         | Forbidden           | Insufficient permissions or IP restriction               |
| 404         | Not Found           | Verify URL path; resource may be deleted                 |
| 429         | Rate Limited        | Respect `Retry-After` header; add delay between requests |
| 500         | Server Error        | Retry once; if persistent, report upstream               |
| SSL error   | Certificate issue   | Do not use `-k` (insecure) — fix the root cause          |
| Timeout     | Network/server slow | Increase `--max-time`; check connectivity                |

Verify a URL is reachable before complex operations:

```bash
curl -sI -o /dev/null -w "%{http_code}" "https://example.com"
```

---

## Limitations

- **WebFetch** does not support custom headers, POST bodies, or cookies. Use `curl` for
  authenticated or stateful requests.
- **curl** does not render JavaScript. For JS-heavy SPAs, prefer `WebFetch` which handles
  rendered content.
- **Large responses** may exceed context limits. Pipe through `jq`, `head`, or `python3`
  to extract only needed data before loading into context.
- **Binary content** (images, PDFs, archives) should be saved to disk with `-o`, not
  piped to stdout.

---

## Calibration Rules

1. **Default to WebFetch for reading web pages.** It returns clean markdown, handles JS
   rendering, and requires no flags. Switch to curl only when you need headers, auth,
   POST, or raw format control.
2. **Always pipe JSON through jq.** Raw JSON in context wastes tokens. Filter to only the
   fields needed.
3. **Never hardcode credentials.** Use `$ENV_VAR` references. If the variable is not set,
   surface the error immediately.
4. **Follow redirects by default.** Always use `-L` with curl unless you specifically need
   to inspect the redirect chain.
5. **Prefer `-s` (silent) on every curl call.** Progress meters add noise to output.

---
name: lightpanda-browser
description: 'Lightweight headless browser automation via Lightpanda and agent-browser CLI: 9x lower memory, 11x faster than Chromium, for scraping and DOM interaction without rendering. Triggers on: "lightpanda", "lightweight browser", "fast headless browser", "headless scraping", "low memory browser", "browser without rendering".'
metadata:
  version: 1.0.1
  category: visualization
  tags: [browser, headless, scraping, lightweight]
  difficulty: beginner
---

# Lightpanda Browser — Fast Headless Automation

Headless browser automation using [Lightpanda](https://github.com/lightpanda-io/browser) as the backend engine, controlled through the `agent-browser` CLI via CDP (Chrome DevTools Protocol).

**When to use this over agent-browser:**

| Use Lightpanda                   | Use agent-browser (Chromium)       |
| -------------------------------- | ---------------------------------- |
| Web scraping / data extraction   | Screenshots, PDFs, visual testing  |
| Form automation / submission     | Video recording / visual debugging |
| API response inspection          | CSS layout verification            |
| DOM traversal / content parsing  | Mobile device emulation (iOS)      |
| CI environments with limited RAM | Full browser extension support     |
| High-volume parallel sessions    | Sites requiring full rendering     |

**Triggers:**

- "lightpanda", "lightweight browser", "fast headless"
- "scrape with low memory", "headless scraping"
- "browser without rendering", "DOM-only browser"
- "fast browser automation", "efficient scraping"
- "is lightpanda faster than chromium?", "which headless browser uses less memory?"
- "how do I scrape without chromium?", "can I run a browser with less RAM?"
- Any browser task where visual output is not needed

---

## Prerequisites

### Install Lightpanda

```bash
# macOS (Apple Silicon)
curl -fsSL https://github.com/nichochar/install-lightpanda/raw/main/install.sh | bash

# Or build from source
git clone https://github.com/lightpanda-io/browser.git
cd browser && zig build -Doptimize=ReleaseSafe
```

### Install agent-browser (if not already present)

```bash
brew install agent-browser
```

### Verify installation

```bash
lightpanda --version
agent-browser --version
```

---

## Core Workflow

Every session follows this lifecycle:

```
1. Start Lightpanda daemon (CDP server)
2. Connect agent-browser via --cdp
3. Navigate, snapshot, interact
4. Stop daemon when done
```

### Step 1 — Start Lightpanda

```bash
# Start Lightpanda CDP server on port 9222 (background)
lightpanda serve --host 127.0.0.1 --port 9222 &
LIGHTPANDA_PID=$!

# Wait for CDP to be ready
sleep 1
```

### Step 2 — Connect and Automate

```bash
# All agent-browser commands work via --cdp flag
agent-browser --cdp 9222 open https://example.com
agent-browser --cdp 9222 snapshot -i
agent-browser --cdp 9222 fill @e1 "search query"
agent-browser --cdp 9222 click @e2
agent-browser --cdp 9222 snapshot -i  # Re-snapshot after navigation
```

### Step 3 — Cleanup

```bash
agent-browser --cdp 9222 close
kill $LIGHTPANDA_PID 2>/dev/null
```

---

## Supported Commands

All commands below are invoked as `agent-browser --cdp <port> <command>`.

### Navigation

```bash
agent-browser --cdp 9222 open <url>
agent-browser --cdp 9222 back
agent-browser --cdp 9222 forward
agent-browser --cdp 9222 reload
agent-browser --cdp 9222 close
```

### Snapshot (DOM Analysis)

```bash
agent-browser --cdp 9222 snapshot -i         # Interactive elements with refs
agent-browser --cdp 9222 snapshot -i -C      # Include cursor-interactive elements
agent-browser --cdp 9222 snapshot -s "#main"  # Scope to CSS selector
agent-browser --cdp 9222 snapshot -i --json   # JSON output for parsing
```

### Interaction (use @refs from snapshot)

```bash
agent-browser --cdp 9222 click @e1
agent-browser --cdp 9222 dblclick @e1
agent-browser --cdp 9222 fill @e2 "text"
agent-browser --cdp 9222 type @e2 "text"
agent-browser --cdp 9222 press Enter
agent-browser --cdp 9222 select @e1 "option"
agent-browser --cdp 9222 check @e1
agent-browser --cdp 9222 hover @e1
agent-browser --cdp 9222 scroll down 500
agent-browser --cdp 9222 drag @e1 @e2
agent-browser --cdp 9222 upload @e1 file.pdf
```

### Get Information

```bash
agent-browser --cdp 9222 get text @e1        # Element text
agent-browser --cdp 9222 get html @e1        # innerHTML
agent-browser --cdp 9222 get value @e1       # Input value
agent-browser --cdp 9222 get attr @e1 href   # Attribute
agent-browser --cdp 9222 get title           # Page title
agent-browser --cdp 9222 get url             # Current URL
agent-browser --cdp 9222 get count ".item"   # Count elements
```

### Wait

```bash
agent-browser --cdp 9222 wait @e1                     # Wait for element
agent-browser --cdp 9222 wait 2000                    # Wait milliseconds
agent-browser --cdp 9222 wait --text "Success"        # Wait for text
agent-browser --cdp 9222 wait --url "**/dashboard"    # Wait for URL
agent-browser --cdp 9222 wait --load networkidle      # Wait for network idle
agent-browser --cdp 9222 wait --fn "window.ready"     # Wait for JS condition
```

### Cookies and Storage

```bash
agent-browser --cdp 9222 cookies
agent-browser --cdp 9222 cookies set name value
agent-browser --cdp 9222 cookies clear
agent-browser --cdp 9222 storage local
agent-browser --cdp 9222 storage local set key value
```

### Network Interception

```bash
agent-browser --cdp 9222 network route <url>              # Intercept
agent-browser --cdp 9222 network route <url> --abort      # Block
agent-browser --cdp 9222 network route <url> --body '{}'  # Mock response
agent-browser --cdp 9222 network requests                 # View tracked
agent-browser --cdp 9222 network requests --filter api    # Filter
```

### JavaScript Execution

```bash
agent-browser --cdp 9222 eval "document.title"
agent-browser --cdp 9222 eval -b "<base64>"
cat script.js | agent-browser --cdp 9222 eval --stdin
```

### Semantic Locators

```bash
agent-browser --cdp 9222 find text "Sign In" click
agent-browser --cdp 9222 find label "Email" fill "user@test.com"
agent-browser --cdp 9222 find role button click --name "Submit"
agent-browser --cdp 9222 find testid "submit-btn" click
```

### Tabs

```bash
agent-browser --cdp 9222 tab                 # List tabs
agent-browser --cdp 9222 tab new [url]       # New tab
agent-browser --cdp 9222 tab 2               # Switch tab
agent-browser --cdp 9222 tab close           # Close tab
```

### Frames

```bash
agent-browser --cdp 9222 frame "#iframe"     # Enter iframe
agent-browser --cdp 9222 frame main          # Back to main
```

### State Management

```bash
agent-browser --cdp 9222 state save auth.json    # Save session state
agent-browser --cdp 9222 state load auth.json    # Restore session state
```

---

## Unsupported Commands

Lightpanda does not have a rendering engine. These commands will fail or produce empty output:

| Command             | Reason                     | Alternative                             |
| ------------------- | -------------------------- | --------------------------------------- |
| `screenshot`        | No visual rendering        | Use `get text` / `get html` for content |
| `pdf`               | No CSS layout engine       | Use `get html` and convert externally   |
| `record start/stop` | No visual output to record | Use network request logs                |
| `highlight`         | No visual rendering        | Use `snapshot -i` to identify elements  |
| `set device`        | No viewport emulation      | Set user-agent via `set headers`        |
| `set media`         | No CSS media query support | N/A                                     |
| `get styles`        | No computed styles         | Parse raw HTML/CSS                      |
| `get box`           | No layout computation      | N/A                                     |
| `is visible`        | No visibility computation  | Check DOM presence instead              |

---

## Common Patterns

### High-Volume Scraping

```bash
# Start Lightpanda — uses ~60MB vs ~550MB for Chromium
lightpanda serve --host 127.0.0.1 --port 9222 &
LIGHTPANDA_PID=$!
sleep 1

URLS=("https://site.com/page/1" "https://site.com/page/2" "https://site.com/page/3")
for url in "${URLS[@]}"; do
  agent-browser --cdp 9222 open "$url"
  agent-browser --cdp 9222 wait --load networkidle
  agent-browser --cdp 9222 get text body >> output.txt
  echo "---" >> output.txt
done

kill $LIGHTPANDA_PID 2>/dev/null
```

### Form Automation

```bash
lightpanda serve --host 127.0.0.1 --port 9222 &
LIGHTPANDA_PID=$!
sleep 1

agent-browser --cdp 9222 open https://example.com/form
agent-browser --cdp 9222 snapshot -i
agent-browser --cdp 9222 fill @e1 "Jane Doe"
agent-browser --cdp 9222 fill @e2 "jane@example.com"
agent-browser --cdp 9222 select @e3 "California"
agent-browser --cdp 9222 check @e4
agent-browser --cdp 9222 click @e5
agent-browser --cdp 9222 wait --load networkidle
agent-browser --cdp 9222 snapshot -i  # Verify result

kill $LIGHTPANDA_PID 2>/dev/null
```

### Authenticated Session

```bash
lightpanda serve --host 127.0.0.1 --port 9222 &
LIGHTPANDA_PID=$!
sleep 1

# Login and save state
agent-browser --cdp 9222 open https://app.example.com/login
agent-browser --cdp 9222 snapshot -i
agent-browser --cdp 9222 fill @e1 "$USERNAME"
agent-browser --cdp 9222 fill @e2 "$PASSWORD"
agent-browser --cdp 9222 click @e3
agent-browser --cdp 9222 wait --url "**/dashboard"
agent-browser --cdp 9222 state save auth.json

# Reuse state later (new session)
agent-browser --cdp 9222 state load auth.json
agent-browser --cdp 9222 open https://app.example.com/dashboard
agent-browser --cdp 9222 snapshot -i

kill $LIGHTPANDA_PID 2>/dev/null
```

### API Response Inspection

```bash
lightpanda serve --host 127.0.0.1 --port 9222 &
LIGHTPANDA_PID=$!
sleep 1

# Intercept API calls
agent-browser --cdp 9222 open https://app.example.com
agent-browser --cdp 9222 network requests --filter "/api/"

# Or mock API responses for testing
agent-browser --cdp 9222 network route "**/api/users" --body '{"users": []}'
agent-browser --cdp 9222 open https://app.example.com/users
agent-browser --cdp 9222 snapshot -i

kill $LIGHTPANDA_PID 2>/dev/null
```

### Parallel Sessions on Different Ports

```bash
# Launch multiple Lightpanda instances for true parallelism
lightpanda serve --host 127.0.0.1 --port 9222 &
PID1=$!
lightpanda serve --host 127.0.0.1 --port 9223 &
PID2=$!
sleep 1

agent-browser --cdp 9222 open https://site-a.com &
agent-browser --cdp 9223 open https://site-b.com &
wait

agent-browser --cdp 9222 get text body > site-a.txt
agent-browser --cdp 9223 get text body > site-b.txt

kill $PID1 $PID2 2>/dev/null
```

---

## Environment Variables

```bash
LIGHTPANDA_HOST="127.0.0.1"    # Bind address (default: 127.0.0.1)
LIGHTPANDA_PORT="9222"          # CDP port (default: 9222)
```

---

## Troubleshooting

### Lightpanda won't start

```bash
# Check if port is in use
lsof -i :9222
# Kill existing process
kill $(lsof -t -i :9222) 2>/dev/null
```

### CDP connection refused

```bash
# Verify Lightpanda is listening
curl -s http://127.0.0.1:9222/json/version
# Expected: JSON with browser info
```

### Command fails with "not supported"

Lightpanda is in beta. If a CDP method is not yet implemented:

1. Check the [Lightpanda status page](https://engine.lightpanda.io/status.html) for supported APIs
2. Fall back to `agent-browser` (Chromium) for that specific operation
3. File an issue at https://github.com/lightpanda-io/browser/issues

### JavaScript execution errors

Lightpanda uses V8 but not all Web APIs are implemented. If `eval` fails:

1. Check if the API is listed in Lightpanda's supported features
2. Use simpler DOM operations (`get text`, `get html`) instead of complex JS

---

## Performance Benchmarks

Reference numbers for choosing between Lightpanda and Chromium. Measured on typical scraping workloads.

| Metric             | Lightpanda | Chromium (Playwright) | When It Matters                                             |
| ------------------ | ---------- | --------------------- | ----------------------------------------------------------- |
| Memory per page    | ~60MB      | ~550MB                | Parallel sessions, CI runners, constrained environments     |
| Cold start         | <100ms     | ~2s                   | Short-lived scripts, serverless, high-frequency invocations |
| DOM-only page load | ~50ms      | ~300ms                | Bulk scraping (difference compounds over hundreds of pages) |
| Binary size        | ~15MB      | ~300MB                | Docker images, CI caching, disk-constrained hosts           |
| JS execution (V8)  | Equivalent | Equivalent            | No difference — same engine                                 |
| Full page render   | N/A        | ~500ms                | Lightpanda cannot render — use Chromium                     |

### Decision Thresholds

| Scenario                              | Recommendation                                 |
| ------------------------------------- | ---------------------------------------------- |
| < 10 pages, need screenshots          | Chromium — overhead is negligible              |
| 10-100 pages, text extraction only    | Lightpanda — saves 5-50GB RAM                  |
| 100+ pages, parallel sessions         | Lightpanda — Chromium hits memory limits       |
| CI with 2GB RAM limit                 | Lightpanda — fits 30+ pages vs 3 with Chromium |
| Visual regression testing             | Chromium — Lightpanda cannot produce images    |
| Form submission + response validation | Either — Lightpanda is faster but both work    |

---

## Calibration Rules

1. **Always start Lightpanda before agent-browser commands.** CDP connection fails silently if the daemon is not running — verify with `curl -sf http://127.0.0.1:9222/json/version` before proceeding.
2. **Re-snapshot after every navigation.** Refs (`@e1`, `@e2`) are invalidated when the page changes — this is inherited from agent-browser, not Lightpanda-specific.
3. **Prefer `get text` over `eval` for content extraction.** Lightpanda's Web API surface is incomplete — `document.querySelector` works but complex APIs (IntersectionObserver, getComputedStyle) do not.
4. **Use separate ports for parallel sessions, not `--session`.** Lightpanda instances are single-threaded — multiple ports give true parallelism, `--session` multiplexes on one instance.
5. **Fall back to Chromium explicitly, not silently.** If a command fails with "not supported", switch to `agent-browser` (no `--cdp` flag) for that operation. Do not retry or suppress the error.
6. **Kill the daemon on exit.** Use `trap cleanup EXIT` in scripts to prevent orphaned Lightpanda processes consuming port 9222.
7. **Check Lightpanda release notes before upgrading.** Beta software — CDP method coverage changes between versions. Run `agent-browser --cdp 9222 snapshot -i` on a known page as a smoke test after updates.

---

## Deep-Dive Documentation

| Reference                                                        | When to Use                                       |
| ---------------------------------------------------------------- | ------------------------------------------------- |
| [references/commands.md](references/commands.md)                 | Full command reference with CDP flag usage        |
| [references/lightpanda-setup.md](references/lightpanda-setup.md) | Installation, configuration, build from source    |
| [references/compatibility.md](references/compatibility.md)       | Supported vs unsupported CDP methods and Web APIs |

## Ready-to-Use Templates

| Template                                                       | Description                            |
| -------------------------------------------------------------- | -------------------------------------- |
| [templates/scrape-session.sh](templates/scrape-session.sh)     | Start daemon, scrape pages, cleanup    |
| [templates/form-submit.sh](templates/form-submit.sh)           | Form fill + submission with validation |
| [templates/parallel-extract.sh](templates/parallel-extract.sh) | Multi-port parallel data extraction    |

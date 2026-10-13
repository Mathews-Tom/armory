# Opus 4.7 Migration Map

Per-category migration actions with before/after code samples. Apply the action that matches each finding in the scanner report.

## Category A — Fixed-budget Extended Thinking

**Problem:** Opus 4.7 does not accept `thinking={"type": "enabled", "budget_tokens": N}`. The parameter is either rejected at the SDK layer or silently ignored depending on the SDK version. There is no numeric replacement — adaptive thinking chooses depth at each step.

**Action:** Remove the `thinking` parameter from the SDK call and shape reasoning depth via prompt phrasing.

### Before

```python
response = client.messages.create(
    model="claude-opus-4-7",
    thinking={"type": "enabled", "budget_tokens": 8000},
    messages=[{"role": "user", "content": prompt}],
)
```

### After

```python
response = client.messages.create(
    model="claude-opus-4-7",
    messages=[{"role": "user", "content": (
        "Think carefully and step-by-step before responding; "
        "this problem is harder than it looks.\n\n" + prompt
    )}],
)
```

See `rules/adaptive-thinking-control/RULE.md` for the full set of prompt-level controls.

---

## Category B — Retired Model ID Aliases

**Problem:** Dated or superseded aliases (`claude-opus-4-5`, `claude-sonnet-4-20250514`, `claude-3-*`) may still resolve at the API layer but defeat the platform's automatic routing and deprecate at an unpredictable cadence.

**Action:** Rename to the current logical alias for the model family. Prefer `claude-opus-4-7` / `claude-sonnet-4-6` / `claude-haiku-4-5` literal strings, or extract to config and let the platform auto-route.

### Before

```python
MODEL = "claude-opus-4-5"
```

### After — Option 1 (current alias)

```python
MODEL = "claude-opus-4-7"
```

### After — Option 2 (config extraction)

```toml
# config.toml
[models]
reasoner = "claude-opus-4-7"
```

```python
# client.py
from ._config import model_for
MODEL = model_for("reasoner")
```

---

## Category C — Hardcoded Model References Outside Config

**Problem:** Model identifiers scattered across source files require a multi-file edit every time the model version changes. The armory convention is "model refs in config files only."

**Action:** Centralize model IDs in a single `config.toml` (or language equivalent) and import from there. See `skills/animate/config.toml` and `scripts/_config.py` for a reference implementation.

Exceptions that do NOT need migration:

- Synthetic test sentinels like `"test-model-override"` (no model coupling)
- CHANGELOG entries or historical docs (reference, not runtime config)
- Example code in SKILL.md / README.md explicitly showing usage patterns

---

## Category D — Verbosity-Assuming Prompts (Heuristic)

**Problem:** Opus 4.7 produces shorter responses by default than 4.6 did. Prompts that relied on implicit verbosity ("explain this", "walk me through", "summarize in detail") may now return terse outputs.

**Action:** State length and depth expectations explicitly in the first turn.

### Before

```
Walk me through the authentication flow.
```

### After

```
Walk me through the authentication flow. Produce a numbered sequence diagram
with 8–12 steps covering token issuance, refresh, and revocation. For each step,
name the actor, the action, and the resulting state change.
```

Not every prompt needs this treatment. Apply where the output was previously verbose by default and the new terseness materially degrades usability.

---

## Category E — Non-Explicit Parallel Sub-Agent Dispatch (Heuristic)

**Problem:** Opus 4.7 defaults toward judicious delegation. Agent prompts instructing "spawn in parallel" without stating the sub-tasks are independent often serialize.

**Action:** State single-message dispatch and sub-task independence explicitly.

### Before

```
Spawn three research agents in parallel using the Agent tool.
```

### After

```
Spawn three research agents in parallel using the Agent tool, **all in a single
assistant message** — Opus 4.7's judicious-delegation default will serialize
them otherwise. These sub-tasks are independent; no agent's output depends on
another's.
```

See `agents/team-lead/AGENT.md`, `agents/research-analyst/AGENT.md`, and related orchestrators in the armory for examples applied in PR #63.

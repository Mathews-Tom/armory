# Storyboard JSON Schema

Schema produced by `scripts/plan_storyboard.py` (Phase 1, Planner stage).
Consumed by `scripts/critic_pass.py` (Phase 3) and `scripts/fetch_assets.py` (Phase 4).

---

## Top-level object

| Field | Type | Required | Description |
|---|---|---|---|
| `concept` | string (non-empty) | yes | The original concept text passed to the planner |
| `duration_estimate_seconds` | number (> 0) | yes | Total estimated video duration in seconds |
| `scenes` | array (non-empty) | yes | Ordered list of scenes |

---

## Scene object

Each element of `scenes`:

| Field | Type | Required | Description |
|---|---|---|---|
| `index` | integer | yes | Zero-based scene index; must match position in array |
| `title` | string (non-empty) | yes | Human-readable scene title |
| `duration_seconds` | number (> 0) | yes | Estimated duration for this scene in seconds |
| `beats` | array of strings (non-empty) | yes | Narrative or visual beats to animate; at least one entry |
| `assets` | array of Asset objects | yes | Assets required for this scene; may be empty list |

---

## Asset object

Each element of a scene's `assets`:

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | `"icon"` \| `"image"` \| `"text"` | yes | Asset category |
| `query` | string (non-empty) | yes | Search query or literal text for the asset |
| `required` | boolean | yes | Whether the asset is required for the scene to render |

---

## Example

```json
{
  "concept": "How TCP/IP handshake works",
  "duration_estimate_seconds": 90,
  "scenes": [
    {
      "index": 0,
      "title": "Introduction",
      "duration_seconds": 15,
      "beats": [
        "Show two computers on screen",
        "Introduce the question: how do they connect?"
      ],
      "assets": [
        {"kind": "icon", "query": "computer server", "required": true},
        {"kind": "text", "query": "TCP/IP Handshake", "required": true}
      ]
    },
    {
      "index": 1,
      "title": "SYN packet",
      "duration_seconds": 20,
      "beats": [
        "Client sends SYN packet to server",
        "Animate arrow from client to server with label SYN"
      ],
      "assets": [
        {"kind": "icon", "query": "network arrow", "required": false},
        {"kind": "text", "query": "SYN", "required": true}
      ]
    }
  ]
}
```

---

## Validation rules (enforced by `validate_storyboard`)

1. All required fields must be present; missing fields raise `ValueError` with the dot-separated field path.
2. `concept` and `title` must be non-empty strings after stripping whitespace.
3. `duration_estimate_seconds` and `duration_seconds` must be positive numbers.
4. `scenes` must contain at least one scene.
5. `beats` must contain at least one string entry per scene.
6. `kind` must be exactly one of `"icon"`, `"image"`, `"text"`.
7. `query` must be a non-empty string.
8. `required` must be a JSON boolean (`true`/`false`), not a string.

---

## Notes for downstream consumers

- `index` is informational; consumers must not assume gaps are absent. Validate by iterating `scenes` in array order.
- `assets` may be an empty list if the scene requires no external assets (text-only animation).
- `duration_estimate_seconds` at the top level may differ from the sum of per-scene `duration_seconds` to account for transitions.
- The schema is intentionally minimal. Downstream stages (Coder, Critic) may attach additional fields under their own namespaced keys without invalidating this schema.

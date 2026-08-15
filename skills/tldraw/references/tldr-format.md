# .tldr File Format & Shapes

## File Format

### Complete .tldr Skeleton

```json
{
  "tldrawFileFormatVersion": 1,
  "schema": {
    "schemaVersion": 1,
    "storeVersion": 4,
    "recordVersions": {
      "asset": {"version": 1, "subTypeKey": "type", "subTypeVersions": {"image": 2, "video": 2, "bookmark": 0}},
      "camera": {"version": 1},
      "document": {"version": 2},
      "instance": {"version": 17},
      "instance_page_state": {"version": 3},
      "page": {"version": 1},
      "shape": {"version": 3, "subTypeKey": "type", "subTypeVersions": {"group": 0, "embed": 4, "bookmark": 1, "image": 2, "text": 1, "draw": 1, "geo": 7, "line": 0, "note": 4, "frame": 0, "arrow": 1, "highlight": 0, "video": 1}},
      "instance_presence": {"version": 4},
      "pointer": {"version": 1}
    }
  },
  "records": [
    {"id": "document:document", "typeName": "document", "gridSize": 10, "name": "", "meta": {}},
    {"id": "page:page1", "typeName": "page", "name": "Page 1", "index": "a1", "meta": {}}
    /* shapes and arrows go here */
  ]
}
```

**Critical rules:**
- `document:document` and `page:page1` records are ALWAYS required.
- All shapes go in the `records` array after the page record.
- All shapes have `"parentId": "page:page1"`.
- Shape IDs use format `"shape:xxx"` with unique suffix (e.g., `"shape:s1"`, `"shape:a1"`).
- `index` values are fractional-index keys. Use `"a"` + **one** base-62 character, in order: `"a0"`–`"a9"`, then `"aA"`–`"aZ"`, then `"aa"`–`"az"` (62 ordered keys — enough for any normal diagram).
- **Do not append a second character: `"a10"` is invalid.** And never use a leading `"b"`/`"c"` (`"b1"`, `"c1"`, `"b0"`) — those encode a longer integer part, so they are malformed fractional keys and trigger `invalidRecords`. Stick to the single-character `"a*"` keys above.

---

## Geo Shape Record

```json
{
  "id": "shape:s1",
  "typeName": "shape",
  "type": "geo",
  "parentId": "page:page1",
  "index": "a1",
  "x": 100,
  "y": 100,
  "rotation": 0,
  "isLocked": false,
  "opacity": 1,
  "meta": {},
  "props": {
    "w": 180,
    "h": 60,
    "geo": "rectangle",
    "color": "blue",
    "labelColor": "black",
    "fill": "semi",
    "dash": "draw",
    "size": "m",
    "font": "draw",
    "text": "API Gateway",
    "align": "middle",
    "verticalAlign": "middle",
    "growY": 0,
    "url": ""
  }
}
```

### Geo Types

| `geo` value | Use for |
|-------------|---------|
| `rectangle` | services, modules, components |
| `ellipse` | databases, start/end nodes |
| `oval` | pill-shaped start/end terminators (flowcharts) |
| `diamond` | decision points |
| `cloud` | external services, infrastructure |
| `hexagon` | event hubs, message buses |
| `triangle` | gateways, load balancers |
| `star` | highlights, key features |
| `pentagon` | stages, milestones |
| `octagon` | stop / terminal / blocking states |
| `trapezoid` | manual operations, transforms |
| `rhombus` / `rhombus-2` | parallelograms — I/O steps (left/right slant) |
| `arrow-right` / `arrow-left` / `arrow-up` / `arrow-down` | directional flow blocks, data movement |
| `x-box` | failed / invalid / rejected states (box with ✕) |
| `check-box` | passed / validated / done states (box with ✓) |
| `heart` | accents (rarely needed for technical diagrams) |

All 20 `geo` values are valid; the above are the useful subset for technical diagrams.

### Color Palette

| `color` | Use for |
|---------|---------|
| `blue` | clients, core services |
| `green` | success, databases, storage |
| `orange` | queues, event buses, warnings |
| `red` | external APIs, errors, alerts |
| `light-red` | soft alerts, secondary warnings |
| `violet` | gateways, security, auth |
| `yellow` | decisions, caches |
| `grey` | neutral, background, legacy |
| `light-blue` | secondary services, metadata |
| `light-violet` | soft auth/security, secondary gateways |
| `light-green` | soft success, secondary storage |
| `white` | blank/empty nodes, placeholders (pair with `fill: solid`) |
| `black` | titles, emphasis |

Full palette (13): `black`, `grey`, `light-violet`, `violet`, `blue`, `light-blue`, `yellow`, `orange`, `green`, `light-green`, `light-red`, `red`, `white`.

### Style Options

| Property | Values | Notes |
|----------|--------|-------|
| `fill` | `semi`, `solid`, `none`, `pattern` | `semi` = tinted fill (recommended) |
| `dash` | `draw`, `solid`, `dashed`, `dotted` | `draw` = hand-drawn default |
| `size` | `s`, `m`, `l`, `xl` | `m` = default |
| `font` | `draw`, `sans`, `serif`, `mono` | `draw` = default whiteboard style |

---


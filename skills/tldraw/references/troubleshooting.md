# Export & Troubleshooting

## Export Commands

```bash
# Check CLI version
tldraw --version

# PNG at 2x scale (recommended) — outputs diagram.png in ./
tldraw export diagram.tldr -f png --scale 2 -o ./

# SVG — outputs diagram.svg in ./
tldraw export diagram.tldr -f svg -o ./

# Transparent background
tldraw export diagram.tldr -f png --scale 2 --transparent -o ./

# Dark theme
tldraw export diagram.tldr -f png --scale 2 --dark -o ./

# Custom output directory (e.g. CI artifacts dir) — create if missing, then export there
mkdir -p ./artifacts && tldraw export diagram.tldr -f png --scale 2 -o ./artifacts/
```

**Note:** `-o` is an output **directory**, not a file path. The output file is named after the input file (`diagram.tldr` → `diagram.png`).

### Auto-launch after export

Offer to open the `.tldr` file in the user's default tldraw viewer/editor:

| OS | Command |
|----|---------|
| macOS | `open diagram.tldr` |
| Linux | `xdg-open diagram.tldr` |
| Windows | `start diagram.tldr` |

Or upload to https://tldraw.com (drag-and-drop the `.tldr` file) for browser editing.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `tldraw` command not found | Run `npm install -g @kitschpatrol/tldraw-cli` |
| `Could not find Chrome (ver. X)` on export | Install the pinned build: `npx puppeteer browsers install chrome@X` (use the exact version from the error) |
| `invalidRecords` on export | Use single-character `a` keys (`a1`…`a9`, `aA`…`aZ`, `aa`…`az`); `a10`, `b1`, `c1` are malformed fractional-index keys |
| Blank/empty export | Verify `document:document` and `page:page1` records are present |
| Output file not found | `-o` is a directory; file name matches input: `tldraw export foo.tldr -o ./` → `./foo.png` |
| Arrow doesn't appear | Use `"type": "binding"` with `boundShapeId`; set arrow `x`/`y` to `0,0` |
| Shapes overlap | Plan a 200px+ grid before assigning x/y; scale spacing with complexity |
| Box taller than expected / collides below | Label overflowed an undersized box, so tldraw auto-grew it (`growY`). Size `w`/`h` to the label up front using the sizing formula |
| Text not visible | Check `props.text` is set; if `fill: "none"`, ensure text color contrasts |
| Index collision | All shapes must have unique `index` values |
| Shape ID clash | Use unique IDs: `"shape:s1"`, `"shape:s2"`, `"shape:a1"`, etc. |
| Export fails | Ensure the `.tldr` file is valid JSON: `python3 -m json.tool file.tldr > /dev/null` |
| Multi-line label | Use a real newline character inside the JSON string (`"text": "Line1\nLine2"`); tldraw respects `\n` |
| Arrow crosses shape | Use `bend` to curve around, or move endpoint to a different `normalizedAnchor` |
| Iteration loop never ends | After 5 rounds, suggest the user open `.tldr` in tldraw.com for fine-tuning |

---

## Fallback Chain

When tools are unavailable, degrade gracefully:

| Scenario | Behavior |
|----------|----------|
| `tldraw-cli` missing | Generate `.tldr` JSON only; instruct user to drag-and-drop into https://tldraw.com or install the CLI |
| Vision unavailable for self-check | Skip self-check (step 5); proceed directly to showing user the exported PNG |
| Export fails | Validate JSON with `python3 -m json.tool`; deliver the `.tldr` file and suggest opening in tldraw.com |

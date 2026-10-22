"""Static site generator for the armory package catalog.

Reads manifest.yaml and profiles.yaml, generates a single self-contained
index.html with all CSS and JS inline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.package_types import TYPES

SECTION_TYPES: dict[str, str] = {t.manifest_section: t.key for t in TYPES.values()}
_DEFAULT_OUTPUT = _REPO_ROOT / "site" / "dist" / "index.html"


def load_manifest() -> list[dict]:
    """Load all packages from manifest.yaml into a flat list."""
    manifest_path = _REPO_ROOT / "manifest.yaml"
    with open(manifest_path) as f:
        data = yaml.safe_load(f)

    packages: list[dict] = []
    for section, items in data.get("packages", {}).items():
        if not isinstance(items, list):
            continue
        if section not in SECTION_TYPES:
            raise ValueError(f"{manifest_path}: unknown package section '{section}'")
        for item in items:
            item["type"] = SECTION_TYPES[section]
            packages.append(item)
    return packages


def load_profiles() -> dict:
    """Load profile definitions from profiles.yaml."""
    profiles_path = _REPO_ROOT / "profiles.yaml"
    with open(profiles_path) as f:
        data = yaml.safe_load(f)
    return data.get("profiles", {})


def build_html(packages: list[dict], profiles: dict) -> str:
    """Build the complete self-contained HTML page."""
    packages_json = json.dumps(packages, ensure_ascii=False)
    profiles_json = json.dumps(profiles, ensure_ascii=False)
    pkg_count = len(packages)
    type_options = "\n        ".join(
        f'<option value="{key}">{key.capitalize()}</option>' for key in TYPES
    )
    type_colors_json = json.dumps({key: f"type-{key}" for key in TYPES})
    native_types_json = json.dumps([key for key, value in TYPES.items() if value.native])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>armory &mdash; AI Agent Package Catalog</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0d1117;--surface:#161b22;--surface-hover:#1c2129;
  --border:#30363d;--border-hover:#58a6ff;
  --text:#e6edf3;--text-secondary:#8b949e;
  --accent:#58a6ff;--accent-dim:#1f6feb;
  --cyan:#79c0ff;--magenta:#d2a8ff;--yellow:#e3b341;
  --green:#56d364;--blue:#58a6ff;--red:#f85149;
  --amber:#d29922;--gray:#8b949e;
  --font:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
}}
body{{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}

/* Header */
.header{{
  border-bottom:1px solid var(--border);padding:2rem 1.5rem;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;
  max-width:1400px;margin:0 auto;
}}
.header-left{{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap}}
.header h1{{font-size:2rem;font-weight:700;letter-spacing:-0.02em}}
.header h1 span{{color:var(--accent)}}
.subtitle{{color:var(--text-secondary);font-size:0.95rem}}
.badge{{
  background:var(--accent-dim);color:var(--text);font-size:0.75rem;font-weight:600;
  padding:0.2rem 0.6rem;border-radius:10px;white-space:nowrap;
}}
.header-right a{{
  display:inline-flex;align-items:center;gap:0.4rem;
  color:var(--text-secondary);font-size:0.9rem;padding:0.4rem 0.8rem;
  border:1px solid var(--border);border-radius:6px;transition:border-color 0.2s;
}}
.header-right a:hover{{border-color:var(--accent);color:var(--text);text-decoration:none}}

/* Layout */
.layout{{display:flex;gap:1.5rem;max-width:1400px;margin:0 auto;padding:1.5rem}}
.main{{flex:1;min-width:0}}
.sidebar{{width:280px;flex-shrink:0}}
@media(max-width:1024px){{
  .layout{{flex-direction:column}}
  .sidebar{{width:100%;order:-1}}
}}

/* Controls */
.controls{{display:flex;flex-wrap:wrap;gap:0.75rem;margin-bottom:1.5rem}}
.search-box{{
  flex:1;min-width:200px;padding:0.6rem 1rem;font-size:0.9rem;
  background:var(--surface);color:var(--text);border:1px solid var(--border);
  border-radius:6px;outline:none;transition:border-color 0.2s;
}}
.search-box:focus{{border-color:var(--accent)}}
.search-box::placeholder{{color:var(--text-secondary)}}
select{{
  padding:0.6rem 0.8rem;font-size:0.85rem;background:var(--surface);
  color:var(--text);border:1px solid var(--border);border-radius:6px;
  outline:none;cursor:pointer;
}}
select:focus{{border-color:var(--accent)}}

/* Category pills */
.pills{{display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:1.25rem}}
.pill{{
  padding:0.3rem 0.7rem;font-size:0.8rem;border-radius:14px;cursor:pointer;
  background:var(--surface);color:var(--text-secondary);border:1px solid var(--border);
  transition:all 0.2s;user-select:none;
}}
.pill:hover{{border-color:var(--accent);color:var(--text)}}
.pill.active{{background:var(--accent-dim);border-color:var(--accent);color:var(--text)}}

/* Grid */
.grid{{
  display:grid;gap:1rem;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
}}
@media(max-width:720px){{.grid{{grid-template-columns:1fr}}}}

/* Cards */
.card{{
  background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:1.25rem;transition:border-color 0.2s,box-shadow 0.2s;display:flex;flex-direction:column;
}}
.card:hover{{border-color:var(--border-hover);box-shadow:0 0 0 1px var(--border-hover)}}
.card-header{{display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;flex-wrap:wrap}}
.card-name{{font-weight:600;font-size:1rem}}
.card-name a{{color:var(--text)}}
.card-name a:hover{{color:var(--accent)}}
.type-badge,.cat-badge,.diff-badge{{
  font-size:0.65rem;font-weight:600;padding:0.15rem 0.45rem;border-radius:4px;
  text-transform:uppercase;letter-spacing:0.04em;
}}
.type-skill{{background:rgba(121,192,255,0.15);color:var(--cyan)}}
.type-agent{{background:rgba(210,168,255,0.15);color:var(--magenta)}}
.type-hook{{background:rgba(227,179,65,0.15);color:var(--yellow)}}
.type-rule{{background:rgba(86,211,100,0.15);color:var(--green)}}
.type-command{{background:rgba(88,166,255,0.15);color:var(--blue)}}
.type-utility{{background:rgba(248,81,73,0.15);color:var(--red)}}
.type-preset{{background:rgba(139,148,158,0.15);color:var(--gray)}}
.type-extension{{background:rgba(121,192,255,0.08);color:var(--cyan);border:1px dashed rgba(121,192,255,0.4)}}
.cat-badge{{background:rgba(88,166,255,0.1);color:var(--accent);border:1px solid rgba(88,166,255,0.2)}}
.diff-beginner{{background:rgba(86,211,100,0.12);color:var(--green)}}
.diff-intermediate{{background:rgba(210,153,34,0.12);color:var(--amber)}}
.diff-advanced{{background:rgba(248,81,73,0.12);color:var(--red)}}
.card-version{{font-size:0.75rem;color:var(--text-secondary);margin-left:auto}}
.card-desc{{font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;flex:1}}
.card-tags{{display:flex;flex-wrap:wrap;gap:0.3rem}}
.tag{{
  font-size:0.7rem;color:var(--text-secondary);background:rgba(139,148,158,0.1);
  border:1px solid var(--border);border-radius:3px;padding:0.1rem 0.4rem;
}}

/* Sidebar */
.sidebar-section{{margin-bottom:1.5rem}}
.sidebar-title{{font-size:0.9rem;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.75rem}}
.profile-card{{
  background:var(--surface);border:1px solid var(--border);border-radius:6px;
  padding:0.75rem;margin-bottom:0.5rem;cursor:pointer;transition:all 0.2s;
}}
.profile-card:hover{{border-color:var(--accent)}}
.profile-card.active{{border-color:var(--accent);background:rgba(88,166,255,0.05)}}
.profile-name{{font-weight:600;font-size:0.9rem;margin-bottom:0.25rem;text-transform:capitalize}}
.profile-desc{{font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.25rem}}
.profile-count{{font-size:0.7rem;color:var(--accent)}}

/* Install */
.install-section{{
  background:var(--surface);border:1px solid var(--border);border-radius:8px;
  margin-top:1rem;overflow:hidden;
}}
.install-toggle{{
  width:100%;padding:0.75rem 1rem;background:none;border:none;
  color:var(--text);font-family:var(--font);font-size:0.9rem;font-weight:600;
  cursor:pointer;display:flex;align-items:center;justify-content:space-between;
}}
.install-toggle:hover{{background:var(--surface-hover)}}
.install-chevron{{transition:transform 0.2s;font-size:0.8rem;color:var(--text-secondary)}}
.install-toggle[aria-expanded="true"] .install-chevron{{transform:rotate(180deg)}}
.install-body{{padding:0 1rem 1rem;display:none}}
.install-body.open{{display:block}}
.install-item{{margin-bottom:0.75rem}}
.install-label{{font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.25rem}}
.install-cmd{{
  font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
  font-size:0.8rem;background:var(--bg);color:var(--cyan);
  padding:0.5rem 0.75rem;border-radius:4px;border:1px solid var(--border);
  word-break:break-all;position:relative;cursor:pointer;
}}
.install-cmd:hover::after{{
  content:"click to copy";position:absolute;right:0.5rem;top:50%;transform:translateY(-50%);
  font-size:0.65rem;color:var(--text-secondary);
}}

/* Footer */
.footer{{
  border-top:1px solid var(--border);padding:1.5rem;text-align:center;
  max-width:1400px;margin:2rem auto 0;
}}
.footer-links{{display:flex;justify-content:center;gap:1.5rem;flex-wrap:wrap;font-size:0.85rem}}
.footer-links a{{color:var(--text-secondary)}}
.footer-links a:hover{{color:var(--accent)}}

/* Empty state */
.empty-state{{
  text-align:center;padding:3rem 1rem;color:var(--text-secondary);
  grid-column:1/-1;
}}
.empty-state p{{font-size:1.1rem;margin-bottom:0.5rem}}
.empty-state small{{font-size:0.85rem}}

/* Count bar */
.results-count{{font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.75rem}}
</style>
</head>
<body>

<header class="header">
  <div class="header-left">
    <h1><span>armory</span></h1>
    <span class="subtitle">Production-grade AI agent packages</span>
    <span class="badge" id="pkg-count">{pkg_count} packages</span>
  </div>
  <div class="header-right">
    <a href="https://github.com/Mathews-Tom/armory" target="_blank" rel="noopener">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
      GitHub
    </a>
  </div>
</header>

<div class="layout">
  <main class="main">
    <div class="controls">
      <input type="text" class="search-box" id="search" placeholder="Search packages by name, description, or tags..." autocomplete="off">
      <select id="type-filter">
        <option value="all">All types</option>
        {type_options}
      </select>
      <select id="diff-filter">
        <option value="all">All levels</option>
        <option value="beginner">Beginner</option>
        <option value="intermediate">Intermediate</option>
        <option value="advanced">Advanced</option>
      </select>
    </div>

    <div class="pills" id="category-pills"></div>

    <div class="results-count" id="results-count"></div>
    <div class="grid" id="grid"></div>
  </main>

  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-title">Quick Start Profiles</div>
      <div id="profiles"></div>
    </div>

    <div class="install-section">
      <button class="install-toggle" aria-expanded="false" onclick="toggleInstall()">
        Install Commands
        <span class="install-chevron">&#9660;</span>
      </button>
      <div class="install-body" id="install-body">
        <div class="install-item">
          <div class="install-label">Claude Code</div>
          <div class="install-cmd" onclick="copyCmd(this)">npx skills add Mathews-Tom/armory</div>
        </div>
        <div class="install-item">
          <div class="install-label">Cursor</div>
          <div class="install-cmd" onclick="copyCmd(this)">npx @anthropic-armory/installer --target cursor</div>
        </div>
        <div class="install-item">
          <div class="install-label">Codex</div>
          <div class="install-cmd" onclick="copyCmd(this)">npx @anthropic-armory/installer --target codex</div>
        </div>
        <div class="install-item">
          <div class="install-label">Gemini</div>
          <div class="install-cmd" onclick="copyCmd(this)">npx @anthropic-armory/installer --target gemini</div>
        </div>
      </div>
    </div>
  </aside>
</div>

<footer class="footer">
  <div class="footer-links">
    <a href="https://github.com/Mathews-Tom/armory" target="_blank" rel="noopener">GitHub</a>
    <a href="https://github.com/Mathews-Tom/armory/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener">Contributing</a>
    <a href="https://github.com/Mathews-Tom/armory/blob/main/WANTED.md" target="_blank" rel="noopener">Wanted</a>
    <a href="https://github.com/Mathews-Tom/armory/blob/main/CONTRIBUTORS.md" target="_blank" rel="noopener">Contributors</a>
  </div>
</footer>

<script>
const PACKAGES = {packages_json};
const PROFILES = {profiles_json};
const SECTION_TYPES = {json.dumps(SECTION_TYPES)};
const NATIVE_TYPES = new Set({native_types_json});

const CATEGORIES = ["all","development","review","security","research","content","business","visualization","operations","data"];
const TYPE_COLORS = {type_colors_json};

let activeCategory = "all";
let activeProfile = null;

function init() {{
  renderPills();
  renderProfiles();
  renderGrid();
  document.getElementById("search").addEventListener("input", renderGrid);
  document.getElementById("type-filter").addEventListener("change", renderGrid);
  document.getElementById("diff-filter").addEventListener("change", renderGrid);
}}

function renderPills() {{
  const container = document.getElementById("category-pills");
  container.innerHTML = CATEGORIES.map(c =>
    `<span class="pill ${{c === activeCategory ? "active" : ""}}" data-cat="${{c}}" onclick="setCategory('${{c}}')">${{c === "all" ? "All" : c.charAt(0).toUpperCase() + c.slice(1)}}</span>`
  ).join("");
}}

function setCategory(cat) {{
  activeCategory = cat;
  activeProfile = null;
  renderPills();
  renderProfiles();
  renderGrid();
}}

function getProfilePackages(name) {{
  const p = PROFILES[name];
  if (!p) return [];
  let identities = [];
  if (p.all) return PACKAGES
    .filter(pkg => !NATIVE_TYPES.has(pkg.type))
    .map(pkg => `${{pkg.type}}/${{pkg.name}}`);
  if (p.includes) {{
    for (const inc of p.includes) {{
      identities = identities.concat(getProfilePackages(inc));
    }}
  }}
  if (p.packages) {{
    for (const [section, names] of Object.entries(p.packages)) {{
      const type = SECTION_TYPES[section];
      if (!type || NATIVE_TYPES.has(type)) continue;
      identities = identities.concat(names.map(name => `${{type}}/${{name}}`));
    }}
  }}
  return [...new Set(identities)];
}}

function renderProfiles() {{
  const container = document.getElementById("profiles");
  container.innerHTML = Object.entries(PROFILES).map(([name, p]) => {{
    const count = getProfilePackages(name).length;
    return `<div class="profile-card ${{activeProfile === name ? "active" : ""}}" onclick="setProfile('${{name}}')">
      <div class="profile-name">${{name.replace(/-/g, " ")}}</div>
      <div class="profile-desc">${{p.description || ""}}</div>
      <div class="profile-count">${{count}} package${{count !== 1 ? "s" : ""}}</div>
    </div>`;
  }}).join("");
}}

function setProfile(name) {{
  if (activeProfile === name) {{
    activeProfile = null;
  }} else {{
    activeProfile = name;
    activeCategory = "all";
    renderPills();
  }}
  renderProfiles();
  renderGrid();
}}

function truncate(s, n) {{
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "..." : s;
}}

function renderGrid() {{
  const query = document.getElementById("search").value.toLowerCase().trim();
  const typeFilter = document.getElementById("type-filter").value;
  const diffFilter = document.getElementById("diff-filter").value;
  const profilePkgs = activeProfile ? getProfilePackages(activeProfile) : null;

  const filtered = PACKAGES.filter(pkg => {{
    if (activeCategory !== "all" && pkg.category !== activeCategory) return false;
    if (typeFilter !== "all" && pkg.type !== typeFilter) return false;
    if (diffFilter !== "all" && pkg.difficulty !== diffFilter) return false;
    if (profilePkgs && !profilePkgs.includes(`${{pkg.type}}/${{pkg.name}}`)) return false;
    if (query) {{
      const haystack = [pkg.name, pkg.description || "", ...(pkg.tags || [])].join(" ").toLowerCase();
      return haystack.includes(query);
    }}
    return true;
  }});

  document.getElementById("results-count").textContent =
    `Showing ${{filtered.length}} of ${{PACKAGES.length}} packages` +
    (activeProfile ? ` in ${{activeProfile}} profile` : "");

  const grid = document.getElementById("grid");
  if (filtered.length === 0) {{
    grid.innerHTML = `<div class="empty-state"><p>No packages found</p><small>Try adjusting your filters or search query.</small></div>`;
    return;
  }}

  grid.innerHTML = filtered.map(pkg => {{
    const tags = (pkg.tags || []).map(t => `<span class="tag">${{t}}</span>`).join("");
    const typeClass = TYPE_COLORS[pkg.type] || "type-skill";
    const diffClass = pkg.difficulty ? `diff-${{pkg.difficulty}}` : "";
    const src = pkg.source || "#";
    return `<div class="card">
      <div class="card-header">
        <span class="card-name"><a href="${{src}}" target="_blank" rel="noopener">${{pkg.name}}</a></span>
        <span class="type-badge ${{typeClass}}">${{pkg.type}}</span>
        ${{pkg.category ? `<span class="cat-badge">${{pkg.category}}</span>` : ""}}
        ${{pkg.difficulty ? `<span class="diff-badge ${{diffClass}}">${{pkg.difficulty}}</span>` : ""}}
        ${{pkg.version ? `<span class="card-version">v${{pkg.version}}</span>` : ""}}
      </div>
      <div class="card-desc">${{truncate(pkg.description, 200)}}</div>
      <div class="card-tags">${{tags}}</div>
    </div>`;
  }}).join("");
}}

function toggleInstall() {{
  const btn = document.querySelector(".install-toggle");
  const body = document.getElementById("install-body");
  const expanded = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", !expanded);
  body.classList.toggle("open");
}}

function copyCmd(el) {{
  navigator.clipboard.writeText(el.textContent).then(() => {{
    const orig = el.textContent;
    el.style.color = "var(--green)";
    setTimeout(() => {{ el.style.color = ""; }}, 600);
  }});
}}

init();
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate armory catalog site")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT, help="Output HTML path")
    args = parser.parse_args()

    packages = load_manifest()
    profiles = load_profiles()

    html = build_html(packages, profiles)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")

    print(f"Generated {args.output} ({len(packages)} packages)")


if __name__ == "__main__":
    main()

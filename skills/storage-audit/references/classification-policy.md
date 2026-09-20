# Classification policy

|Class|Recognized path|Required evidence|Cleanup command|
|---|---|---|---|
|`rebuildable`|`target/`|Git-ignored path plus `Cargo.toml`|Allowed after a stable strict audit|
|`rebuildable`|`node_modules/`|Git-ignored path, `package.json`, and a recognized lockfile|Allowed after a stable strict audit|
|`rebuildable`|`.venv/`|Git-ignored path, `pyproject.toml`, and `uv.lock` or `requirements.txt`|Allowed after a stable strict audit|
|`rebuildable`|`.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`|Git-ignored known analysis/test cache|Allowed after a stable strict audit|
|`derived-review`|`.archex/`|Detected index path|Never by default; review rebuild cost and provenance|
|`local-data`|A project named `data`, `datasets`, `corpora`, `results`, `checkpoints`, `models`, `embeddings`, or `graphs`|Exact path classification|Never|
|`git-protected`|`.worktrees/`|Exact worktree-root path|Never; use a dedicated worktree audit|

Cleanup-eligible `rebuildable` entries receive `A-###` IDs, where `A` means **actionable**. Protected or review-required entries receive `P-###` IDs. These prefixes identify handling policy, not a tier hierarchy.

Everything outside an exact row is source or unknown material. Do not create a removal recommendation for it.

A clean Git status, remote configuration, commit age, or a missing process is insufficient evidence to delete a source tree. Those signals only inform an archive-review decision.

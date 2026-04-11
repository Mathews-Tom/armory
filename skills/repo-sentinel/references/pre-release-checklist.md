# Pre-Release Readiness Checklist

Stage-4 soft-blocker checklist for the Pre-Release Audit Mode — use during open-source release preparation.

---

## Pre-Release Readiness Checklist

Run during Stage 4 of the Pre-Release Audit Mode, or standalone before any public release.
All items are soft blockers — failures produce advisory output, not hard halts.

### §4.1 Documentation Completeness

| File                               | Required    | Check                                   |
| ---------------------------------- | ----------- | --------------------------------------- |
| `README.md`                        | YES         | Has install + quickstart sections       |
| `CONTRIBUTING.md`                  | YES         | Fork/branch strategy, dev setup         |
| `CODE_OF_CONDUCT.md`               | YES         | Adopted standard (Contributor Covenant) |
| `CHANGELOG.md`                     | RECOMMENDED | Keep-a-changelog format                 |
| `LICENSE`                          | YES         | Verified in Surface 11                  |
| `SECURITY.md`                      | RECOMMENDED | Disclosure process + contact            |
| `ARCHITECTURE.md` or `docs/`       | RECOMMENDED | Module overview                         |
| `.github/ISSUE_TEMPLATE/`          | RECOMMENDED | Bug + feature templates                 |
| `.github/PULL_REQUEST_TEMPLATE.md` | RECOMMENDED | PR checklist                            |

### §4.2 Code Quality Gates

- Linter config: `.eslintrc*`, `ruff.toml`, `pyproject.toml [tool.ruff]`, `.clippy.toml`
- Formatter config: `.prettierrc*`, `pyproject.toml [tool.black]`, `rustfmt.toml`
- Pre-commit: `.pre-commit-config.yaml`
- Type checking: `tsconfig.json` (strict), `py.typed` marker, mypy/pyright config

### §4.3 Test Infrastructure

- Test runner configured and documented
- CI pipeline exists (`.github/workflows/`, `.gitlab-ci.yml`)
- Test data is synthetic (not production-derived)
- Smoke test or single-command verify path documented

### §4.4 API Surface

- Public API explicitly demarcated (`__all__`, `exports`, `pub`)
- No internal implementation leaked across module boundaries
- Configuration via env vars / config files, not hardcoded constants

### §4.5 Package Metadata

Check manifest completeness across: `package.json`, `pyproject.toml`, `Cargo.toml`, `*.csproj`

Required fields: `name`, `version`, `description`, `repository`, `homepage`, `keywords`,
`author`, `license`

### §4.6 Reproducible Builds

- Lock files committed
- Toolchain versions documented: `.tool-versions`, `.python-version`, `.nvmrc`, `rust-toolchain.toml`
- CI runner images pinned

### §4.7 Binary Asset Policy

- No files >1MB without Git LFS
- No build artifacts committed
- `.gitattributes` for LFS if needed

### §4.8 Community Setup

- Issue labels defined: `good-first-issue`, `help-wanted`, `bug`, `enhancement`
- Discussions or external channel linked
- Maintainer expectations documented

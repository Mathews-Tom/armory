set dotenv-load := true

default:
    @just --list

# Install packages to ~/.claude/
install:
    uv run scripts/install.py

# Install all packages non-interactively
install-all:
    echo -e "all\ny" | uv run scripts/install.py

# Install by profile (core, developer, security, full)
install-profile profile:
    uv run scripts/install.py --profile {{profile}}

# Regenerate manifest.yaml
manifest:
    uv run scripts/generate_manifest.py

# Package a specific item (e.g., just package skills/pr-review)
package path:
    uv run scripts/package.py {{path}}

# Validate all eval cases
validate:
    uv run scripts/validate_evals.py

# Sync shared templates to consumers
sync-templates:
    uv run scripts/sync_templates.py

# Run repo-level tests
test-repo:
    # `python -m pytest`, not the `pytest` console script, so the project
    # interpreter is always the one that runs the suite.
    uv run python -m pytest tests/ -q

# Run every package's own test suite
test-packages:
    #!/usr/bin/env bash
    # One pytest process per package: each package's test setup prepends the
    # package root to sys.path, so a shared process would resolve a same-named
    # module to whichever package loaded first.
    set -euo pipefail
    shopt -s nullglob
    ran=0
    for type_dir in skills agents hooks rules commands utilities presets; do
        for suite in "${type_dir}"/*/tests "${type_dir}"/*/engine/tests; do
            cases=("${suite}"/test_*.py)
            [[ ${#cases[@]} -eq 0 ]] && continue
            echo "==> ${suite}"
            uv run python -m pytest "${suite}" -q
            ran=$((ran + 1))
        done
    done
    if [[ ${ran} -eq 0 ]]; then
        echo "no package test suites found" >&2
        exit 1
    fi

# Run every test suite
test: test-repo test-packages

# Full pre-PR check
check:
    just manifest
    just sync-templates
    just validate
    just test

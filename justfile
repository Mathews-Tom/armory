set dotenv-load := true

default:
    @just --list

# Install skills to ~/.claude/skills/
install:
    uv run scripts/install_skills.py

# Install all skills non-interactively
install-all:
    echo -e "all\ny" | uv run scripts/install_skills.py

# Regenerate skills.yaml manifest
manifest:
    uv run scripts/generate_manifest.py

# Package a skill as .skill archive
package name:
    uv run scripts/package_skill.py skills/{{name}}

# Validate all eval cases
validate:
    uv run scripts/validate_evals.py

# Sync shared templates to consuming skills
sync-templates:
    uv run scripts/sync_templates.py

# Run tests
test:
    uv run pytest tests/ -v

# Full pre-PR check: manifest + templates + evals + tests
check:
    just manifest
    just sync-templates
    just validate
    just test

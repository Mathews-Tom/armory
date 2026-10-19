## Summary

<!-- Brief description of what this PR adds or changes. -->

## Static Conformance Results

<!-- Run the repository evaluator for each changed package and paste its actual JSON
     list output, invocation and exit status. For example:
       uv run python scripts/evaluate_package.py --path skills/your-skill-name --json
     Report-v2 separates static PASS/FAIL from live NOT_MEASURED.
     Do not fabricate output or turn skipped checks into a pass. -->

```text
(actual command, exit status and JSON output)
```

## Authored Findings and Behavioral Evidence

<!-- List source-backed authored findings separately from the machine report.
     Record actual authorized checks, invocation/artifact evidence and their limits.
     Name skipped/unmeasured cases and missing prerequisites. Static conformance and
     authored cases do not establish effectiveness. Live model sessions or paid
     checks require separate authorization; this template does not grant it. -->

## Checklist

- [ ] Definition file has valid YAML frontmatter with `name`, `description`, and `metadata.version`
- [ ] Version bumped according to semver (MAJOR/MINOR/PATCH)
- [ ] Manifest regenerated: `uv run scripts/generate_manifest.py`
- [ ] Package name is kebab-case, at most 64 characters
- [ ] Description satisfies the current 50–1024 character validator range and names distinct invocation contexts and adjacent boundaries
- [ ] No angle brackets or pushy language in description
- [ ] No secrets, credentials, or internal URLs in any file
- [ ] Actual authorized local checks and behavioral evidence recorded, with unmeasured/skipped cases and prerequisites explicit
- [ ] All file references in the definition file resolve to existing files within the package directory
- [ ] No cross-package references (`../other-package/`) — package is fully self-contained
- [ ] Eval cases exist in `evals/cases.yaml` with 2+ positive cases covering every distinct invocation branch and 2+ adjacent negatives
- [ ] Eval schema validated: `uv run python scripts/validate_evals.py` (not a behavioral pass)
- [ ] Templates synced (if using shared templates): `uv run python scripts/sync_templates.py`
- [ ] Report-v2 static conformance is PASS; actual output and separate authored findings attached
- [ ] Frontmatter/reference validation and applicable authored-review findings resolved; effectiveness claims limited to separately authorized measured evidence

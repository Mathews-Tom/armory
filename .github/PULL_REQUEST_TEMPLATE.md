## Summary

<!-- What this PR adds or changes, and why. -->

## Risk

<!-- Low / Medium / High — set by the change, not the author — plus one line on why. Low: wording, docs, eval cases. Medium: package behavior, package scripts. High: CI workflows, release/packaging scripts, installers, extensions. -->

## Testing

<!-- CI runs frontmatter, reference, eval-schema, manifest, template-sync, secret-scan and static-conformance checks on changed packages; do not paste their output here. Record the behavioral evidence CI cannot produce: the actual invocations or artifacts you checked and their limits. Name skipped/unmeasured cases and missing prerequisites. Static conformance and authored cases do not establish effectiveness. Live model sessions or paid checks require separate authorization; this template does not grant it. -->

## How to revert

<!-- Usually "revert this PR". Name anything a revert does not undo, e.g. published release assets or already-installed copies. -->

## Checklist

CI enforces frontmatter validity, naming, description length, semver format, manifest freshness, file references, self-containment, eval schema and minimum cases, template sync, secret scan and static conformance. Check only what it cannot; for PRs that change no package, mark the package items N/A:

- [ ] Changed package: version bumped according to semver (MAJOR/MINOR/PATCH)
- [ ] Changed package: description names distinct invocation contexts and adjacent boundaries; no angle brackets or pushy language
- [ ] Changed package: positive eval cases cover every distinct invocation branch
- [ ] No internal URLs in any file

# Changelog — debug-investigator

## 1.2.0

- MINOR from `1.1.1`: add real-boundary regression proof to the existing debugging workflow without removing existing investigation paths.
- Select a correct seam before fixing; exercise implicated callers, shared state and ordering, and report no-seam versus execution-blocked limitations explicitly.
- Require defect-specific observed red/green evidence, conditional forced-red mutation comparison/restoration, the original unminimized scenario and final diagnostic cleanup evidence.
- Add conditional upstream provenance and the verbatim MIT notice for guidance adapted from Matt Pocock's diagnosing-bugs at `49dd158d1076134a641b33efb035946536778336`; future resync is manual.
- Keep the complete Resolution evidence fields inside the copyable output template by closing the nested minimal-reproduction fence separately.

# Pinned live-run reports

Each accepted report directory contains only `run-manifest.json`, `report.json`, and `report.md` from one explicit
real-provider run. Candidate text, evidence, case identifiers, provider responses, errors, and credentials must remain
in the ignored `results/` directory.

Use the package's `pin` command after reviewing a passing run. The command validates the run identity, re-scores the
private observations, requires a complete pass, and regenerates only the safe artifacts; it never copies
`observations.private.jsonl`.

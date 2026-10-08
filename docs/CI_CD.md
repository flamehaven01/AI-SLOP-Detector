# CI/CD Integration

## Start With Evidence, Not A Blocking Gate

AI-SLOP Detector can produce a deterministic report and a process exit code in CI. A green run only means the configured detector policy passed; it does not prove correctness, security, deployment safety, or external score validation.

Begin in soft mode, retain reports, and review scan coverage and representative findings before enabling a hard gate.

## Minimal GitHub Actions Example

```yaml
name: Structural review

on: [push, pull_request]

jobs:
  slop:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install
        run: pip install "ai-slop-detector>=3.8.9"
      - name: Report
        run: slop-detector scan . --ci-mode soft --ci-report --output slop-report.md
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: slop-report
          path: slop-report.md
```

`--ci-report` replaces the scan report with the gate report: written to `--output` when given (nothing is printed to stdout), otherwise printed to stdout; add `--json` for the gate result as JSON. Without `--ci-report`, `--ci-mode` runs the normal scan, with the same report, `--json`, and `--output` as without it, and only adds the gate's exit code. The gate does **not** authenticate with a hosting provider or post a pull-request comment. Add a platform-specific publishing step if comments are wanted.

## Gate Modes

| Mode | Intended use | Exit behavior |
| --- | --- | --- |
| `soft` | Adoption and evidence gathering | Informational; does not fail the build for findings. |
| `hard` | A reviewed repository policy | Returns non-zero when the configured gate decides to fail. |
| `quarantine` | Gradual enforcement of repeated violations | Persists local quarantine state; persist that file as an artifact or cache if runs are ephemeral. |

The detailed decision is part of the report. Do not duplicate historical thresholds in CI configuration docs: thresholds, ignores, and pattern policy belong in `.slopconfig.yaml` and should be reviewed per repository.

## JSON-First Automation

```yaml
- name: Machine-readable review
  run: slop-detector review . --base origin/main --format json --output review.json
```

Use `review` for changed-code attribution, `pulse` for hotspot prioritization, and `sweep <family>` for bounded cleanup evidence. Inspect `finding_summary`, `scan_coverage`, and `ml_scoring`; do not treat an overall `clean` label as a claim that every relevant file was analyzed.

## History And Calibration

The normal scan path records local history unless `--no-history` is passed. Scans never run calibration or change a config. In an ephemeral or policy-controlled CI environment, use `--no-history` unless local history behavior has been deliberately chosen.

`--self-calibrate` is an advisory report, not an external validation mechanism, and it does not change weights. See [SELF_CALIBRATION.md](SELF_CALIBRATION.md).

## Claim-Based Enforcement

`--ci-claims-strict` is a separate heuristic that checks selected textual claims for integration-test evidence. It does not certify production readiness or substitute for security, compliance, or human review.

## Related

- [CONFIGURATION.md](CONFIGURATION.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [VALIDATION.md](VALIDATION.md)

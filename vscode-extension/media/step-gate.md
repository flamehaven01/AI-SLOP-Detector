### Gate, then let it calibrate

Turn a one-off scan into a standing quality signal.

- **Show Gate Decision (SNP)** gives a PASS/HALT verdict you can mirror in CI
  (`--ci-mode hard`).
- **Run Self-Calibration** reports which 4D weights your own run history
  would suggest. It is advisory: it writes nothing, and no scan changes the
  weights. This is repository-local operational calibration, not an
  externally validated control.

[Show Gate](command:slop-detector.showGate) · [Self-Calibrate](command:slop-detector.selfCalibrate)

Calibration is project-scoped and domain-anchored, so the signal never mixes
across repositories. Every scan adds to that repository's history; changing a
weight stays your decision, in `.slopconfig.yaml`.

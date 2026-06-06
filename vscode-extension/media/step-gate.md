### Gate, then let it calibrate

Turn a one-off scan into a standing quality signal.

- **Show Gate Decision (SNP)** gives a PASS/HALT verdict you can mirror in CI
  (`--ci-mode hard`).
- **Run Self-Calibration** tunes the 4D weights to your codebase from your own
  run history — the oracle is your git behavior, not a guess.

[Show Gate](command:slop-detector.showGate) · [Self-Calibrate](command:slop-detector.selfCalibrate)

Calibration is project-scoped and domain-anchored, so the signal never mixes
across repositories. Every scan feeds the history that makes the next one
sharper.

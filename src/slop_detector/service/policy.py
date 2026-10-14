"""Scan decisions shared by the CLI and ScanService: no output, no writes.

The one write is the quarantine gate's own database, which is why that gate is
refused under read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from slop_detector.core_project import score_is_valid

CONFIG_FILENAME = ".slopconfig.yaml"


def resolve_config_path(target: Path, project: bool, explicit: Optional[str]) -> Optional[str]:
    """The config a scan uses: the explicit one, else .slopconfig.yaml in the
    project root (project) or next to the file (single file), else none.
    SLOP_CONFIG still overrides this inside Config."""
    if explicit is not None:
        return explicit
    candidate = (target if project else target.parent) / CONFIG_FILENAME
    return str(candidate) if candidate.exists() else None


def apply_runtime_overrides(
    detector: Any,
    *,
    include_tests: bool = False,
    topology_ceiling: Optional[int] = None,
    topology_mode: Optional[str] = None,
    patterns_only: bool = False,
    disabled: Sequence[str] = (),
) -> None:
    """Apply per-run options onto the detector's config before analysis.

    Disabled patterns are recorded in the config (part of the cache key); an
    unknown pattern id is a ValueError.
    """
    advanced = detector.config.config.setdefault("advanced", {})
    if include_tests:
        detector.config.include_default_tests()
    if topology_ceiling is not None:
        advanced["exact_topology_ceiling"] = topology_ceiling
    if topology_mode is not None:
        advanced["topology_mode_above_ceiling"] = topology_mode
    if patterns_only:
        advanced["patterns_only"] = True
    unknown = sorted({pid for pid in disabled if detector.pattern_registry.get(pid) is None})
    if unknown:
        raise ValueError(f"--disable: unknown pattern id {', '.join(unknown)}; see --list-patterns")
    if not disabled:
        return
    patterns = detector.config.config.setdefault("patterns", {})
    patterns["disabled"] = sorted(set(patterns.get("disabled") or []) | set(disabled))
    for pid in disabled:
        detector.pattern_registry.disable(pid)


def headline_score(result: Any) -> float:
    """The score a threshold applies to: weighted for a project, the file's own otherwise."""
    if hasattr(result, "project_path"):
        return float(result.weighted_deficit_score)
    return float(result.deficit_score)


def evaluate_gate(result: Any, mode: Optional[str], claims_strict: bool, read_only: bool):
    """GateResult for the requested gate, or None when no gate is requested.

    A report-only request (--ci-report without --ci-mode) passes mode="soft".
    """
    if mode is None and not claims_strict:
        return None
    from slop_detector.ci_gate import CIGate, GateMode

    gate_mode = GateMode(mode) if mode else GateMode.SOFT
    if read_only and gate_mode == GateMode.QUARANTINE:
        raise ValueError("the quarantine gate writes its database; not allowed read-only")
    return CIGate(mode=gate_mode, claims_strict=claims_strict).evaluate(result)


def gate_exit_code(gate_result: Any) -> int:
    return 1 if gate_result.should_fail_build else 0


def threshold_breach(result: Any, threshold: Optional[float]) -> Optional[str]:
    """Why the scan fails --fail-threshold, or None when it does not.

    A scan whose every file failed measured nothing; its 0.0 is not a pass.
    A scan with nothing to measure (no eligible or only excluded files) is not
    evaluated and does not fail.
    """
    if threshold is None:
        return None
    if not score_is_valid(result):
        coverage = getattr(result, "scan_coverage", None) or {}
        if coverage.get("reason") == "all_analysis_failed":
            return f"no file could be analyzed; threshold {threshold} cannot be met"
        return None
    score = headline_score(result)
    if score > threshold:
        return f"Deficit score {score:.1f} exceeds threshold {threshold}"
    return None

"""History and self-calibration helpers for the CLI."""

from __future__ import annotations

import argparse
from pathlib import Path


def _compute_project_id() -> str:
    """Return a stable 12-char hex project ID from the resolved cwd (sha256)."""
    import hashlib

    cwd = str(Path.cwd().resolve())
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


def _get_git_context():
    """Capture current git commit and branch; return (None, None) outside a repo."""
    import subprocess

    try:
        commit = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
            ).stdout.strip()
            or None
        )
        branch = (
            subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
            ).stdout.strip()
            or None
        )
        return commit, branch
    except Exception:
        return None, None


def _record_history(result, config=None, path=None, is_project=False) -> None:
    """Auto-record analysis result(s) to history DB with git context and provenance.

    With the detector's config and the scanned path the rows carry v6
    measurement provenance (calibration evidence); without them they are legacy.
    """
    try:
        from slop_detector.history import history_project_root, measurement_provenance

        git_commit, git_branch = _get_git_context()
        project_id = _compute_project_id()
        provenance = (
            measurement_provenance(config, history_project_root(path, is_project))
            if config is not None and path is not None
            else None
        )
        from slop_detector.language_registry import all_file_results

        tracker = _open_history(HISTORY_NOT_RECORDED_KEY)
        if tracker is None:
            return
        # Every analyzed language; each row says which metrics it measured.
        results = all_file_results(result) if hasattr(result, "file_results") else [result]
        for file_analysis in results:
            tracker.record(
                file_analysis,
                git_commit=git_commit,
                git_branch=git_branch,
                project_id=project_id,
                provenance=provenance,
            )
    except Exception as exc:  # noqa: BLE001 — history is best-effort; never block main flow
        import logging as _logging

        _logging.getLogger(__name__).debug("history record skipped: %s", exc)


HISTORY_NOT_RECORDED_KEY = "not_recorded"
HISTORY_NOT_OPENED_KEY = "not_opened"


def _open_history(failure: str):
    """The history tracker, or None when the pre-upgrade copy failed: then one
    line on stderr (HISTORY_NOT_RECORDED for a scan, HISTORY_NOT_OPENED for a
    command that reads history) and the detail in the debug log."""
    import logging
    import sys

    from slop_detector import history

    try:
        return history.HistoryTracker()
    except history.HistoryBackupError as exc:
        logging.getLogger(__name__).debug("history not opened: %s", exc)
        line = (
            history.HISTORY_NOT_RECORDED
            if failure == HISTORY_NOT_RECORDED_KEY
            else history.HISTORY_NOT_OPENED
        )
        print(line, file=sys.stderr)
        return None


def _show_file_history(file_path: str) -> int:
    """Print trend history for a single file."""
    tracker = _open_history(HISTORY_NOT_OPENED_KEY)
    if tracker is None:
        return 1
    resolved = str(Path(file_path).resolve())
    history = tracker.get_file_history(resolved, limit=20)
    file_path = resolved

    if not history:
        print(f"No history found for: {file_path}")
        print(f"  DB: {tracker.db_path}")
        return 0

    print(f"History: {file_path}")
    print(f"  DB: {tracker.db_path}")
    print("-" * 70)
    print(f"  {'Timestamp':<24} {'Deficit':>7} {'LDR':>6} {'Patterns':>8}  Grade")
    print("-" * 70)
    for item in history:
        timestamp = item["timestamp"][:19]
        ldr = "-" if item["ldr_score"] is None else f"{item['ldr_score']:.3f}"  # not measured
        print(
            f"  {timestamp:<24} {item['deficit_score']:>7.1f} {ldr:>6}"
            f" {item['pattern_count']:>8}  {item['grade']}"
        )

    if len(history) >= 2:
        first = history[-1]["deficit_score"]
        last = history[0]["deficit_score"]
        delta = last - first
        direction = "improved" if delta < 0 else "degraded" if delta > 0 else "stable"
        print("-" * 70)
        print(f"  Trend ({len(history)} runs): {direction}  delta={delta:+.1f}")
    return 0


def _show_trends() -> int:
    """Print project-wide daily trend table."""
    tracker = _open_history(HISTORY_NOT_OPENED_KEY)
    if tracker is None:
        return 1
    trends = tracker.get_project_trends(days=7)

    if not trends["data_points"]:
        print("No history found.")
        print(f"  DB: {tracker.db_path}")
        return 0

    print("Project Trends (last 7 days)")
    print(f"  DB: {tracker.db_path}")
    print("-" * 65)
    print(f"  {'Date':<12} {'Avg Deficit':>11} {'Avg LDR':>8} {'Patterns':>9} {'Files':>6}")
    print("-" * 65)
    for item in trends["daily_trends"]:
        ldr = "-" if item["avg_ldr"] is None else f"{item['avg_ldr']:.3f}"
        print(
            f"  {item['date']:<12} {item['avg_deficit']:>11.1f} {ldr:>8}"
            f" {item['total_patterns']:>9} {item['files_analyzed']:>6}"
        )
    return 0


def _export_history(output_path: str) -> int:
    """Export history to JSONL."""
    tracker = _open_history(HISTORY_NOT_OPENED_KEY)
    if tracker is None:
        return 1
    count = tracker.export_jsonl(output_path)
    print(f"[+] Exported {count} records to {output_path}")
    return 0


LEGACY_CALIBRATION_WARNING = (
    "[!] Calibration v2 learns only from comparable runs of this project root (same "
    "detector, engine and configuration) recorded with measurement provenance; legacy "
    "history rows are not evidence. This report is advisory; weight application is disabled."
)


def _run_self_calibration(args: argparse.Namespace) -> int:
    """Print the Calibration v2 advisory report for the target's project root. Never writes weights."""
    import sys

    from slop_detector.config import Config
    from slop_detector.ml.self_calibrator import SelfCalibrator

    print(LEGACY_CALIBRATION_WARNING, file=sys.stderr)
    if getattr(args, "apply_calibration", None):
        print(
            "[-] --apply-calibration is disabled: .slopconfig.yaml was not modified. "
            "Run --self-calibrate alone for the advisory report.",
            file=sys.stderr,
        )
        return 2

    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        console = Console()
        rich_enabled = True
    except ImportError:
        console = None  # type: ignore[assignment]
        rich_enabled = False

    from slop_detector.history import history_project_root

    config = Config(config_path=getattr(args, "config", None))
    current_weights = config.get_weights()
    min_events = getattr(args, "min_history", 5)
    target = getattr(args, "path", None) or "."
    project_root = history_project_root(target, Path(target).is_dir())

    calibrator = SelfCalibrator()
    result = calibrator.calibrate(
        current_weights=current_weights, min_events=min_events, project_root=str(project_root)
    )
    exit_code = 0 if result.status in ("ok", "no_change") else 1

    if getattr(args, "json", False):
        import json

        print(json.dumps(calibration_preview(result), indent=2, sort_keys=True))
        return exit_code

    if rich_enabled and console:
        from rich.panel import Panel
        from rich.text import Text

        status_color = {"ok": "green", "no_change": "yellow", "insufficient_data": "red"}.get(
            result.status, "white"
        )
        header = Text(f"Self-Calibration — {result.status.upper()}", style=f"bold {status_color}")
        console.print(Panel(header, box=box.ROUNDED))
        if result.candidate_gap_passed:
            console.print(f"[yellow]{gap_note(result)}[/yellow]")

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Project root", result.project_root)
        table.add_row("Files with comparable runs", str(result.unique_files))
        table.add_row("Comparable run pairs", str(result.comparable_pairs))
        table.add_row(
            "Pairs with an unmeasured metric (not learned)", str(result.unmeasured_metric_pairs)
        )
        table.add_row("Legacy rows (not evidence)", str(result.legacy_rows_ignored))
        table.add_row(
            "Improvements (flagged file changed, score fell)", str(result.improvement_events)
        )
        table.add_row(
            "Stable flags (flagged file left unchanged)", str(result.stable_flag_candidates)
        )
        table.add_row("Confidence gap", f"{result.confidence_gap:.4f}")
        console.print(table)

        weight_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        weight_table.add_column("Dimension", style="cyan")
        weight_table.add_column("Current", justify="right")
        weight_table.add_column("Optimal", justify="right")
        weight_table.add_column("Delta", justify="right")
        for dimension in ("ldr", "inflation", "ddc", "purity"):
            current = current_weights.get(dimension, 0.0)
            optimal = result.optimal_weights.get(dimension, current)
            delta = optimal - current
            delta_str = f"{delta:+.2f}" if abs(delta) > 0.001 else "—"
            color = "green" if delta < -0.001 else ("red" if delta > 0.001 else "white")
            weight_table.add_row(
                dimension,
                f"{current:.2f}",
                f"{optimal:.2f}",
                f"[{color}]{delta_str}[/{color}]",
            )
        console.print(weight_table)

        if result.status == "ok":
            error_before = result.fn_rate_before + result.fp_rate_before
            error_after = result.fn_rate_after + result.fp_rate_after
            console.print(
                f"\nCombined error on this history's labels: [yellow]{error_before:.4f}[/yellow]"
                f" -> [green]{error_after:.4f}[/green]"
                f"  (FN {result.fn_rate_before:.4f}->{result.fn_rate_after:.4f},"
                f"  FP {result.fp_rate_before:.4f}->{result.fp_rate_after:.4f})"
            )

        _print_rule_tables(console, result)
        if result.warnings:
            for warning in result.warnings:
                console.print(f"[yellow][!] {warning}[/yellow]")
        console.print(f"\n[dim]{result.message}[/dim]")
    else:
        _print_calibration_plain(result, current_weights)

    return exit_code


# How the screen names each evidence state (calibration_evidence.STATES order).
# The key `verified_fix` stays (JSON contract); the label says what it shows.
EVIDENCE_LABELS = (
    ("verified_fix", "Warning resolved - code correctness not verified"),
    ("unchanged_warning", "Unchanged warning"),
    ("user_suppressed_unverified", "Suppressed (unverified)"),
    ("user_declared_false_positive", "Declared false positive"),
)
UNCHANGED_RATE_NOTE = (
    "Unchanged-warning rate: the share of a rule's labeled events where the flagged file "
    "was left unchanged. It is not a false-positive rate, and it changes no rule."
)


def gap_note(result) -> str:
    """What an ok (or no_change) status rests on, said where the status is shown."""
    return (
        "candidate gap passed; detection accuracy not validated"
        f" ({result.externally_validated})"
    )


def calibration_preview(result) -> dict:
    """The --self-calibrate --json preview: the calibration result as data,
    `applied: false` (nothing is written). per_rule_fp_rates is left out: the
    same numbers are in unchanged_warning_rate under the name of what they count."""
    from dataclasses import asdict

    preview = asdict(result)
    preview.pop("per_rule_fp_rates", None)
    preview["applied"] = False
    return preview


def _high_unchanged_rates(result) -> dict:
    return {
        rule_id: rate
        for rule_id, rate in sorted(result.unchanged_warning_rate.items(), key=lambda i: -i[1])
        if rate >= 0.5
    }


def _print_rule_tables(console, result) -> None:
    """Per-rule evidence states and unchanged-warning rates; both are reported,
    neither is a learning label."""
    from rich import box
    from rich.table import Table

    if result.evidence_states:
        evidence = Table(
            box=box.ROUNDED,
            header_style="bold cyan",
            title="Evidence per rule (reported, not learned)",
        )
        evidence.add_column("Rule ID", style="cyan")
        for _, label in EVIDENCE_LABELS:
            evidence.add_column(label, justify="right")
        for rule_id in sorted(result.evidence_states):
            states = result.evidence_states[rule_id]
            evidence.add_row(rule_id, *(str(states.get(key, 0)) for key, _ in EVIDENCE_LABELS))
        console.print(evidence)
    rates = _high_unchanged_rates(result)
    if rates:
        rate_table = Table(
            box=box.ROUNDED,
            header_style="bold cyan",
            title="Unchanged-warning rate per rule (>= 50%)",
        )
        rate_table.add_column("Rule ID", style="cyan")
        rate_table.add_column("Unchanged-warning rate", justify="right")
        for rule_id, rate in rates.items():
            rate_table.add_row(rule_id, f"{rate:.0%}")
        console.print(rate_table)
        console.print(f"[dim]{UNCHANGED_RATE_NOTE}[/dim]")


def _print_calibration_plain(result, current_weights) -> None:
    """Plain-text self-calibration report (no rich available)."""
    print(f"[Self-Calibration] status={result.status}")
    print(f"  project_root={result.project_root}")
    print(f"  unique_files={result.unique_files}")
    print(f"  comparable_pairs={result.comparable_pairs}")
    print(f"  unmeasured_metric_pairs={result.unmeasured_metric_pairs}")
    print(f"  legacy_rows_ignored={result.legacy_rows_ignored}")
    print(f"  improvement_events={result.improvement_events}")
    print(f"  stable_flag_candidates={result.stable_flag_candidates}")
    print(f"  confidence_gap={result.confidence_gap:.4f}")
    print(
        f"  candidate_gap_passed={result.candidate_gap_passed}"
        f" externally_validated={result.externally_validated}"
    )
    print(f"  current_weights={current_weights}")
    print(f"  optimal_weights={result.optimal_weights}")
    for rule_id in sorted(result.evidence_states):
        states = result.evidence_states[rule_id]
        counts = " ".join(f"{key}={states[key]}" for key, _ in EVIDENCE_LABELS if key in states)
        print(f"  evidence {rule_id}: {counts}")
    if result.evidence_states:
        print(f"  verified_fix = {EVIDENCE_LABELS[0][1]}")
    for rule_id, rate in _high_unchanged_rates(result).items():
        print(f"  unchanged_warning_rate {rule_id}: {rate:.0%}")
    if result.unchanged_warning_rate:
        print(f"  {UNCHANGED_RATE_NOTE}")
    for warning in result.warnings:
        print(f"  [!] {warning}")
    print(f"  {result.message}")

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
                text=True,
                timeout=3,
            ).stdout.strip()
            or None
        )
        branch = (
            subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
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
        from slop_detector.history import (
            HistoryTracker,
            history_project_root,
            measurement_provenance,
        )

        git_commit, git_branch = _get_git_context()
        project_id = _compute_project_id()
        provenance = (
            measurement_provenance(config, history_project_root(path, is_project))
            if config is not None and path is not None
            else None
        )
        tracker = HistoryTracker()
        results = result.file_results if hasattr(result, "file_results") else [result]
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


def _show_file_history(file_path: str) -> None:
    """Print trend history for a single file."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    resolved = str(Path(file_path).resolve())
    history = tracker.get_file_history(resolved, limit=20)
    file_path = resolved

    if not history:
        print(f"No history found for: {file_path}")
        print(f"  DB: {tracker.db_path}")
        return

    print(f"History: {file_path}")
    print(f"  DB: {tracker.db_path}")
    print("-" * 70)
    print(f"  {'Timestamp':<24} {'Deficit':>7} {'LDR':>6} {'Patterns':>8}  Grade")
    print("-" * 70)
    for item in history:
        timestamp = item["timestamp"][:19]
        print(
            f"  {timestamp:<24} {item['deficit_score']:>7.1f} {item['ldr_score']:>6.3f}"
            f" {item['pattern_count']:>8}  {item['grade']}"
        )

    if len(history) >= 2:
        first = history[-1]["deficit_score"]
        last = history[0]["deficit_score"]
        delta = last - first
        direction = "improved" if delta < 0 else "degraded" if delta > 0 else "stable"
        print("-" * 70)
        print(f"  Trend ({len(history)} runs): {direction}  delta={delta:+.1f}")


def _show_trends() -> None:
    """Print project-wide daily trend table."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    trends = tracker.get_project_trends(days=7)

    if not trends["data_points"]:
        print("No history found.")
        print(f"  DB: {tracker.db_path}")
        return

    print("Project Trends (last 7 days)")
    print(f"  DB: {tracker.db_path}")
    print("-" * 65)
    print(f"  {'Date':<12} {'Avg Deficit':>11} {'Avg LDR':>8} {'Patterns':>9} {'Files':>6}")
    print("-" * 65)
    for item in trends["daily_trends"]:
        print(
            f"  {item['date']:<12} {item['avg_deficit']:>11.1f} {item['avg_ldr']:>8.3f}"
            f" {item['total_patterns']:>9} {item['files_analyzed']:>6}"
        )


def _export_history(output_path: str) -> None:
    """Export history to JSONL."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    count = tracker.export_jsonl(output_path)
    print(f"[+] Exported {count} records to {output_path}")


LEGACY_CALIBRATION_WARNING = (
    "[!] Calibration v2 learns only from comparable runs of this project root (same "
    "detector, engine and configuration) recorded with measurement provenance; legacy "
    "history rows are not evidence. This report is advisory; weight application is disabled."
)


def _run_self_calibration(args: argparse.Namespace) -> int:
    """Report what the legacy self-calibration would recommend. Never writes weights."""
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

    if rich_enabled and console:
        from rich.panel import Panel
        from rich.text import Text

        status_color = {"ok": "green", "no_change": "yellow", "insufficient_data": "red"}.get(
            result.status, "white"
        )
        header = Text(f"Self-Calibration — {result.status.upper()}", style=f"bold {status_color}")
        console.print(Panel(header, box=box.ROUNDED))

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Project root", result.project_root)
        table.add_row("Files with comparable runs", str(result.unique_files))
        table.add_row("Comparable run pairs", str(result.comparable_pairs))
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
                f"\nCombined error: [yellow]{error_before:.4f}[/yellow] -> [green]{error_after:.4f}[/green]"
                f"  (FN {result.fn_rate_before:.4f}->{result.fn_rate_after:.4f},"
                f"  FP {result.fp_rate_before:.4f}->{result.fp_rate_after:.4f})"
            )

        high_fp = {
            rule_id: rate
            for rule_id, rate in sorted(result.per_rule_fp_rates.items(), key=lambda item: -item[1])
            if rate >= 0.5
        }
        if high_fp:
            rule_table = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
                title="Per-Rule Noisy-Alert Rates (>= 50%)",
            )
            rule_table.add_column("Rule ID", style="cyan")
            rule_table.add_column("FP Rate", justify="right")
            rule_table.add_column("Signal", justify="right")
            for rule_id, rate in high_fp.items():
                signal = "[red]HIGH NOISE[/red]" if rate >= 0.7 else "[yellow]MOD NOISE[/yellow]"
                rule_table.add_row(rule_id, f"{rate:.0%}", signal)
            console.print(rule_table)
            console.print(
                "[dim]Rules with HIGH NOISE (>=70%) are candidates for suppression"
                " via .slopconfig.yaml exclude_rules[/dim]"
            )

        if result.warnings:
            for warning in result.warnings:
                console.print(f"[yellow][!] {warning}[/yellow]")
        console.print(f"\n[dim]{result.message}[/dim]")
    else:
        _print_calibration_plain(result, current_weights)

    return 0 if result.status in ("ok", "no_change") else 1


def _print_calibration_plain(result, current_weights) -> None:
    """Plain-text self-calibration report (no rich available)."""
    print(f"[Self-Calibration] status={result.status}")
    print(f"  project_root={result.project_root}")
    print(f"  unique_files={result.unique_files}")
    print(f"  comparable_pairs={result.comparable_pairs}")
    print(f"  legacy_rows_ignored={result.legacy_rows_ignored}")
    print(f"  improvement_events={result.improvement_events}")
    print(f"  stable_flag_candidates={result.stable_flag_candidates}")
    print(f"  confidence_gap={result.confidence_gap:.4f}")
    print(f"  current_weights={current_weights}")
    print(f"  optimal_weights={result.optimal_weights}")
    if result.per_rule_fp_rates:
        high_fp_plain = {
            rule_id: rate
            for rule_id, rate in sorted(result.per_rule_fp_rates.items(), key=lambda item: -item[1])
            if rate >= 0.5
        }
        if high_fp_plain:
            print("  per_rule_noisy_alert_rates (>=50%):")
            for rule_id, rate in high_fp_plain.items():
                print(f"    {rule_id}: {rate:.0%}")
    for warning in result.warnings:
        print(f"  [!] {warning}")
    print(f"  {result.message}")

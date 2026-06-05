"""History and self-calibration helpers for the CLI."""

from __future__ import annotations

import argparse
from pathlib import Path


def _compute_project_id() -> str:
    """Return a stable 12-char hex project ID from the resolved cwd (sha256)."""
    import hashlib

    cwd = str(Path.cwd().resolve())
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


def _check_calibration_hint(args) -> None:
    """Auto-run calibration when multi-run file history reaches a milestone."""
    if getattr(args, "no_history", False):
        return
    try:
        import sys as _sys

        from slop_detector.config import Config
        from slop_detector.history import HistoryTracker
        from slop_detector.ml.self_calibrator import CALIBRATION_MILESTONE, SelfCalibrator

        project_id = _compute_project_id()
        tracker = HistoryTracker()
        run_count = tracker.count_files_with_multiple_runs(project_id=project_id)
        if run_count < CALIBRATION_MILESTONE or run_count % CALIBRATION_MILESTONE != 0:
            return

        config = Config(config_path=getattr(args, "config", None))
        current_weights = config.get_weights()
        domain_anchor = {
            key: current_weights.get(key, 0.30) for key in ("ldr", "inflation", "ddc", "purity")
        }
        result = SelfCalibrator().calibrate(
            current_weights=current_weights,
            project_id=project_id,
            domain_anchor=domain_anchor,
        )
        config_path = getattr(args, "config", None) or ".slopconfig.yaml"

        if result.status == "ok" and Path(config_path).exists():
            written = SelfCalibrator.apply_to_config(
                result.optimal_weights, config_path=config_path
            )
            print(
                f"\n[*] Auto-calibration ({run_count} multi-run files): weights updated -> {written}",
                file=_sys.stderr,
            )
            for key in ("ldr", "inflation", "ddc", "purity"):
                old_value = current_weights.get(key, 0.0)
                new_value = result.optimal_weights.get(key, 0.0)
                if abs(old_value - new_value) > 0.001:
                    print(f"    {key}: {old_value:.2f} -> {new_value:.2f}", file=_sys.stderr)
        elif result.status == "no_change":
            print(
                f"\n[*] Calibration milestone ({run_count} multi-run files): weights already optimal.",
                file=_sys.stderr,
            )
        else:
            print(
                f"\n[*] Calibration milestone ({run_count} multi-run files): {result.message} "
                f"Run --self-calibrate for details.",
                file=_sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 — hint is informational; never block main flow
        import logging as _logging

        _logging.getLogger(__name__).debug("calibration hint skipped: %s", exc)


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


def _record_history(result) -> None:
    """Auto-record analysis result(s) to history DB with git context and project_id."""
    try:
        from slop_detector.history import HistoryTracker

        git_commit, git_branch = _get_git_context()
        project_id = _compute_project_id()
        tracker = HistoryTracker()
        if hasattr(result, "file_results"):
            for file_analysis in result.file_results:
                tracker.record(
                    file_analysis,
                    git_commit=git_commit,
                    git_branch=git_branch,
                    project_id=project_id,
                )
        else:
            tracker.record(
                result,
                git_commit=git_commit,
                git_branch=git_branch,
                project_id=project_id,
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


def _run_self_calibration(args: argparse.Namespace) -> int:
    """Run self-calibration and optionally apply results to .slopconfig.yaml."""
    from slop_detector.config import Config
    from slop_detector.ml.self_calibrator import SelfCalibrator

    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        console = Console()
        rich_enabled = True
    except ImportError:
        console = None  # type: ignore[assignment]
        rich_enabled = False

    config = Config(config_path=getattr(args, "config", None))
    current_weights = config.get_weights()
    min_events = getattr(args, "min_history", 5)

    calibrator = SelfCalibrator()
    result = calibrator.calibrate(current_weights=current_weights, min_events=min_events)

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
        table.add_row("Unique files in history", str(result.unique_files))
        table.add_row("Improvement events (true positives)", str(result.improvement_events))
        table.add_row("FP candidates (flagged, never fixed)", str(result.fp_candidates))
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
                title="Per-Rule FP Rates (>= 50%)",
            )
            rule_table.add_column("Rule ID", style="cyan")
            rule_table.add_column("FP Rate", justify="right")
            rule_table.add_column("Signal", justify="right")
            for rule_id, rate in high_fp.items():
                signal = "[red]HIGH FP[/red]" if rate >= 0.7 else "[yellow]MOD FP[/yellow]"
                rule_table.add_row(rule_id, f"{rate:.0%}", signal)
            console.print(rule_table)
            console.print(
                "[dim]Rules with HIGH FP (>=70%) are candidates for suppression"
                " via .slopconfig.yaml exclude_rules[/dim]"
            )

        if result.warnings:
            for warning in result.warnings:
                console.print(f"[yellow][!] {warning}[/yellow]")
        console.print(f"\n[dim]{result.message}[/dim]")
    else:
        print(f"[Self-Calibration] status={result.status}")
        print(f"  unique_files={result.unique_files}")
        print(f"  improvement_events={result.improvement_events}")
        print(f"  fp_candidates={result.fp_candidates}")
        print(f"  confidence_gap={result.confidence_gap:.4f}")
        print(f"  current_weights={current_weights}")
        print(f"  optimal_weights={result.optimal_weights}")
        if result.per_rule_fp_rates:
            high_fp_plain = {
                rule_id: rate
                for rule_id, rate in sorted(
                    result.per_rule_fp_rates.items(), key=lambda item: -item[1]
                )
                if rate >= 0.5
            }
            if high_fp_plain:
                print("  per_rule_fp_rates (>=50%):")
                for rule_id, rate in high_fp_plain.items():
                    print(f"    {rule_id}: {rate:.0%}")
        for warning in result.warnings:
            print(f"  [!] {warning}")
        print(f"  {result.message}")

    apply_path = getattr(args, "apply_calibration", None)
    if apply_path and result.status == "ok":
        written = SelfCalibrator.apply_to_config(result.optimal_weights, config_path=apply_path)
        message = f"[+] Calibrated weights written to {written}"
        if rich_enabled and console:
            console.print(f"\n[green]{message}[/green]")
        else:
            print(message)
    elif apply_path and result.status != "ok":
        message = "[-] --apply-calibration skipped: calibration did not produce a confident result."
        if rich_enabled and console:
            console.print(f"\n[yellow]{message}[/yellow]")
        else:
            print(message)

    return 0 if result.status in ("ok", "no_change") else 1

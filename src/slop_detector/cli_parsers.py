"""Argument parser helpers for the CLI surface."""

from __future__ import annotations

import argparse
from typing import Collection

from slop_detector import __version__


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="AI SLOP Detector v4.0 - Sovereign Gate Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  slop-detector scan src/                  # Canonical analysis entry
  slop-detector review .                   # Canonical changed-code review entry
  slop-detector pulse .                    # Canonical repo health entry
  slop-detector sweep dead-code .          # Canonical cleanup entry
  slop-detector verify-governance ./.cr-ep  # Verify governance artifact integrity
  slop-detector --init                       # Bootstrap .slopconfig.yaml + .gitignore
  slop-detector file.py                      # Analyze single file
  slop-detector --project src/               # Analyze project
  slop-detector --project . --json           # JSON output
  slop-detector --project . -o report.html   # HTML report
  slop-detector file.py --fix --dry-run      # Preview auto-fixes
  slop-detector file.py --fix                # Apply auto-fixes
  slop-detector file.py --gate               # Show SNP gate decision
  slop-detector src/ --js                    # Analyze JS/TS files
  slop-detector src/ --cross-file            # Cross-file analysis
  slop-detector src/ --governance            # Emit CR-EP session artifacts
  slop-detector --self-calibrate             # Optimize weights from run history
  slop-detector --project . --emit-leda-yaml # Emit LEDA injection YAML
  slop-detector --version                    # Show version
        """,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to Python file or project directory (default: current directory)",
    )
    parser.add_argument("--project", action="store_true", help="Analyze entire project")
    parser.add_argument("--output", "-o", help="Output file (txt, json, or html)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--format",
        choices=["json"],
        help="Structured output format alias (currently supports: json)",
    )
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")
    parser.add_argument(
        "--topology-ceiling",
        type=int,
        metavar="N",
        help="Maximum Python-file count for exact structural topology before fallback",
    )
    parser.add_argument(
        "--topology-mode",
        choices=["exact", "deterministic_approximate"],
        help="Structural topology mode above the exact ceiling",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply auto-fixes for detected patterns (use --dry-run to preview)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview fixes without writing to disk (use with --fix)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Show SNP-compatible gate decision (PASS/HALT) with sr9/di2/jsd/ove metrics",
    )
    parser.add_argument(
        "--js",
        action="store_true",
        help="Analyze JavaScript/TypeScript files in addition to Python",
    )
    parser.add_argument(
        "--cross-file",
        action="store_true",
        help="Run cross-file analysis (cycles, duplicates, hotspots)",
    )
    parser.add_argument(
        "--governance",
        action="store_true",
        help="Emit CR-EP v2.7.2 session artifacts to .cr-ep/ directory",
    )
    parser.add_argument(
        "--emit-leda-yaml",
        action="store_true",
        help="Emit LEDA injection YAML for downstream SPAR review",
    )
    parser.add_argument(
        "--leda-output",
        default="reports/leda_injection.yaml",
        help="Output path for --emit-leda-yaml (default: reports/leda_injection.yaml)",
    )
    parser.add_argument(
        "--leda-profile",
        choices=["internal", "restricted", "public"],
        default="restricted",
        help="Redaction profile for LEDA YAML (default: restricted)",
    )
    parser.add_argument(
        "--disable",
        "-d",
        action="append",
        default=[],
        metavar="PATTERN_ID",
        help="Disable specific pattern by ID (can be repeated)",
    )
    parser.add_argument(
        "--patterns-only", action="store_true", help="Only run pattern detection (skip metrics)"
    )
    parser.add_argument(
        "--list-patterns", action="store_true", help="List all available patterns and exit"
    )
    parser.add_argument(
        "--fail-threshold",
        type=float,
        default=None,
        help="Exit with code 1 if slop score exceeds threshold",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--version", action="version", version=f"ai-slop-detector {__version__}")
    parser.add_argument(
        "--no-color", action="store_true", help="Disable rich output (force plain text)"
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip recording this run to history (~/.slop-detector/history.db)",
    )
    parser.add_argument(
        "--show-history", action="store_true", help="Show trend history for the given file and exit"
    )
    parser.add_argument(
        "--history-trends",
        action="store_true",
        help="Show project-wide daily trends (last 7 days) and exit",
    )
    parser.add_argument(
        "--export-history", metavar="PATH", help="Export full history to JSONL file and exit"
    )
    parser.add_argument(
        "--self-calibrate",
        action="store_true",
        help="Analyze usage history to find optimal ldr/inflation/ddc weights for this codebase",
    )
    parser.add_argument(
        "--apply-calibration",
        metavar="CONFIG",
        nargs="?",
        const=".slopconfig.yaml",
        help="Write calibrated weights to .slopconfig.yaml (or specified path). Use with --self-calibrate",
    )
    parser.add_argument(
        "--min-history",
        type=int,
        default=5,
        metavar="N",
        help="Minimum labeled events per class (improvements / FP candidates) before calibration runs (default: 5 per class)",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Bootstrap .slopconfig.yaml for this project and add it to .gitignore",
    )
    parser.add_argument(
        "--force-init",
        action="store_true",
        help="Overwrite existing .slopconfig.yaml when using --init",
    )
    parser.add_argument(
        "--domain",
        help=(
            "Override auto-detected domain when using --init. "
            "Choices: general, scientific/ml, scientific/numerical, "
            "web/api, library/sdk, cli/tool, bio, finance"
        ),
    )
    parser.add_argument(
        "--adaptive-init",
        action="store_true",
        help="Run adaptive repository signal collection and suggestion synthesis during --init",
    )
    parser.add_argument(
        "--init-preview",
        action="store_true",
        help="Preview baseline/adaptive init suggestions without writing .slopconfig.yaml",
    )
    parser.add_argument(
        "--apply-init-suggestions",
        action="store_true",
        help="Opt in to merging adaptive init suggestions into a new or existing .slopconfig.yaml",
    )
    parser.add_argument(
        "--ci-mode",
        choices=["soft", "hard", "quarantine"],
        help="CI gate mode: soft (PR comments only), hard (fail build), quarantine (track repeat offenders)",
    )
    parser.add_argument(
        "--ci-report",
        action="store_true",
        help="Output CI gate report and exit with appropriate code",
    )
    parser.add_argument(
        "--ci-claims-strict",
        action="store_true",
        help="Enable claim-based enforcement: fail if production/enterprise/scalable/fault-tolerant claims lack integration tests (v2.6.2)",
    )
    return parser


def _build_operations_parser(command: str) -> argparse.ArgumentParser:
    """Build a focused parser for review/cleanup commands."""
    parser = argparse.ArgumentParser(
        prog=f"slop-detector {command}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"{command} operation for the AI SLOP detector",
    )
    if command == "explain":
        parser.add_argument("identifier", help="Rule ID, cleanup family, or target to explain")
    else:
        parser.add_argument("target", nargs="?", default=".", help="Project root or file path")
    parser.add_argument(
        "--base",
        default="HEAD",
        help="Git base ref used for introduced vs inherited attribution (audit only)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--format",
        choices=["json"],
        help="Structured output format alias (currently supports: json)",
    )
    parser.add_argument("--output", "-o", help="Write report to file")
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-color", action="store_true", help="Disable rich output")
    if command == "watch":
        parser.add_argument(
            "--follow",
            action="store_true",
            help="Keep watching and re-run on interval instead of a one-shot scan",
        )
        parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    if command == "fix":
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview auto-fixes without writing to disk",
        )
    return parser


def build_sweep_parser(cleanup_families: Collection[str]) -> argparse.ArgumentParser:
    """Build the canonical cleanup parser surface."""
    parser = argparse.ArgumentParser(
        prog="slop-detector sweep",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Cleanup sweep for the AI SLOP detector",
    )
    parser.add_argument("family", choices=sorted(cleanup_families), help="Cleanup family to run")
    parser.add_argument("target", nargs="?", default=".", help="Project root or file path")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--format",
        choices=["json"],
        help="Structured output format alias (currently supports: json)",
    )
    parser.add_argument("--output", "-o", help="Write report to file")
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-color", action="store_true", help="Disable rich output")
    return parser


def _build_impact_parser() -> argparse.ArgumentParser:
    """Build parser for local impact commands."""
    parser = argparse.ArgumentParser(
        prog="slop-detector impact",
        description="Local repository impact tracking",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["summary", "status", "enable", "disable"],
        default="summary",
        help="Impact action to run",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Project root for local impact tracking",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    return parser


def _build_telemetry_parser() -> argparse.ArgumentParser:
    """Build parser for telemetry control commands."""
    parser = argparse.ArgumentParser(
        prog="slop-detector telemetry",
        description="Opt-in telemetry controls",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["status", "enable", "disable", "inspect"],
        default="status",
        help="Telemetry action to run",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="Show an example telemetry payload instead of a live one",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    return parser


def _normalize_format_args(args) -> None:
    """Map format aliases onto existing boolean output flags."""
    if getattr(args, "format", None) == "json":
        args.json = True

"""Command-line interface for SLOP detector."""

import argparse
import json
import logging
import math
import sys
from pathlib import Path

from slop_detector import __version__
from slop_detector.cli_commands import (  # noqa: F401
    _check_calibration_hint,
    _export_history,
    _get_git_context,
    _record_history,
    _run_autofix,
    _run_cross_file,
    _run_gate,
    _run_governance,
    _run_init,
    _run_js_analysis,
    _run_self_calibration,
    _show_file_history,
    _show_trends,
)
from slop_detector.cli_renderer import (  # noqa: F401
    RICH_AVAILABLE,
    generate_html_report,
    generate_markdown_report,
    generate_text_report,
    get_mitigation,
    list_patterns,
    print_rich_report,
)
from slop_detector.core import SlopDetector
from slop_detector.leda_injection import build_leda_injection, write_leda_injection
from slop_detector.models import FileAnalysis, ProjectAnalysis


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stderr)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="AI SLOP Detector v4.0 - Sovereign Gate Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
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
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")
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
    # History tracking (v2.9.0)
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
    # Self-Calibration (v2.9.2)
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
    # Bootstrap (v3.2.0)
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
    # CI/CD Gate options (v2.2)
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


def _write_file(path: str, content: str, label: str = "") -> None:
    """Write content to a file, with optional console confirmation."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if label:
        print(f"[+] {label} saved to {path}")


def _sanitize_for_json(obj):
    """Recursively replace non-finite floats with None for RFC 8259 compliance.

    Python's json.dumps serializes float('inf') as 'Infinity' which is invalid
    JSON (RFC 8259 §6) and rejected by jq and most JSON parsers.
    """
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _write_json_output(args, result) -> None:
    """Serialize result to JSON and write to file or stdout."""
    output = json.dumps(_sanitize_for_json(result.to_dict()), indent=2)
    if args.output:
        _write_file(args.output, output)
    else:
        print(output)


def _route_file_output(out: str, result, rich_ok: bool) -> None:
    """Write result to file or console based on output extension and flags."""
    if out.endswith(".html"):
        _write_file(out, generate_html_report(result), "HTML report")
        return
    if out.endswith(".md"):
        _write_file(out, generate_markdown_report(result), "Markdown report")
        return
    if out:
        _write_file(out, generate_text_report(result))
        return
    if rich_ok:
        print_rich_report(result)
        return
    print(generate_text_report(result))


def _handle_output(args, result) -> None:
    """Route analysis result to the appropriate output format."""
    if args.json:
        _write_json_output(args, result)
        return
    out = str(args.output) if args.output else ""
    _route_file_output(out, result, RICH_AVAILABLE and not args.no_color)


def _evaluate_ci_gate(args, result):
    """Run CI gate evaluation; return exit code or None to continue."""
    claims_strict = getattr(args, "ci_claims_strict", False)
    if not (args.ci_mode or args.ci_report or claims_strict):
        return None
    from slop_detector.ci_gate import CIGate, GateMode

    gate_mode = GateMode(args.ci_mode) if args.ci_mode else GateMode.SOFT
    gate_result = CIGate(mode=gate_mode, claims_strict=claims_strict).evaluate(result)
    if args.ci_report:
        if args.json:
            print(json.dumps(_sanitize_for_json(gate_result.to_dict()), indent=2))
        else:
            print(gate_result.pr_comment or gate_result.message)
        return 1 if gate_result.should_fail_build else 0
    return None


def _run_optional_features(args, result) -> None:
    """Run optional post-output features (gate, fix, js, cross-file, governance)."""
    if getattr(args, "gate", False):
        _run_gate(result)
    if getattr(args, "fix", False):
        _run_autofix(result, dry_run=getattr(args, "dry_run", True))
    if getattr(args, "js", False):
        _run_js_analysis(args.path)
    if getattr(args, "cross_file", False) and hasattr(result, "project_path"):
        _run_cross_file(result)
    if getattr(args, "governance", False):
        _run_governance(args.path, result)


def _emit_leda_yaml(args, result) -> None:
    """Build and write LEDA injection YAML."""
    payload = build_leda_injection(
        result,
        path=args.path,
        config_path=args.config,
        profile=args.leda_profile,
    )
    written = write_leda_injection(args.leda_output, payload)
    print(f"[+] LEDA injection YAML saved to {written}")


def _run_analysis_phase(args, detector):
    """Run file or project analysis. Returns (result, score)."""
    from typing import Union

    result: Union[ProjectAnalysis, FileAnalysis]
    if args.project:
        result = detector.analyze_project(args.path)
        return result, result.weighted_deficit_score
    result = detector.analyze_file(args.path)
    return result, result.deficit_score


def main() -> int:
    """CLI entry point."""
    args = _build_arg_parser().parse_args()
    setup_logging(args.verbose)

    if getattr(args, "history_trends", False):
        _show_trends()
        return 0
    if getattr(args, "export_history", None):
        _export_history(args.export_history)
        return 0
    if getattr(args, "show_history", False):
        _show_file_history(args.path)
        return 0
    if getattr(args, "init", False):
        return _run_init(args)
    if getattr(args, "self_calibrate", False):
        return _run_self_calibration(args)

    if Path(args.path).is_dir() and not args.project:
        args.project = True
        logging.info("Directory detected, enabling --project mode")

    # Auto-detect .slopconfig.yaml when --config is not specified.
    # In project mode the config lives in the project root; in single-file
    # mode it lives next to the file.  Either way, prefer it over defaults.
    if args.config is None:
        config_dir = Path(args.path) if args.project else Path(args.path).parent
        candidate = config_dir / ".slopconfig.yaml"
        if candidate.exists():
            args.config = str(candidate)
            logging.info(f"Auto-detected config: {candidate}")

    if args.list_patterns:
        list_patterns()
        return 0

    try:
        detector = SlopDetector(config_path=args.config)
    except Exception as e:
        print(f"[!] Failed to initialize detector: {e}", file=sys.stderr)
        return 1

    try:
        result, score = _run_analysis_phase(args, detector)
    except Exception as e:
        print(f"[!] Analysis failed: {e}", file=sys.stderr)
        return 1

    ci_exit = _evaluate_ci_gate(args, result)
    if ci_exit is not None:
        return ci_exit

    _handle_output(args, result)

    if getattr(args, "emit_leda_yaml", False):
        _emit_leda_yaml(args, result)

    if args.fail_threshold is not None and score > args.fail_threshold:
        print(
            f"\n[!] FAIL: Deficit score {score:.1f} exceeds threshold {args.fail_threshold}",
            file=sys.stderr,
        )
        return 1

    _run_optional_features(args, result)

    if not getattr(args, "no_history", False):
        _record_history(result)
        _check_calibration_hint(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())

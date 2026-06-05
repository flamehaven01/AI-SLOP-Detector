"""Command-line interface for SLOP detector."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from slop_detector.core import SlopDetector  # re-exported for CLI patch surface/tests
from slop_detector.leda_injection import build_leda_injection, write_leda_injection

_OPERATIONS_COMMANDS = {
    "audit",
    "health",
    "dead-code",
    "dupes",
    "unused-deps",
    "stale-suppressions",
    "boundary-violations",
    "watch",
    "fix",
    "explain",
}
_CLEANUP_FAMILIES = {
    "dead-code",
    "dupes",
    "unused-deps",
    "stale-suppressions",
    "boundary-violations",
}
_CANONICAL_COMMAND_ALIASES = {
    "review": "audit",
    "pulse": "health",
}


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stderr)


def _build_arg_parser():
    from slop_detector.cli_parsers import _build_arg_parser as _impl

    return _impl()


def _normalize_format_args(args) -> None:
    from slop_detector.cli_parsers import _normalize_format_args as _impl

    _impl(args)


def _apply_runtime_overrides(args, detector) -> None:
    from slop_detector.cli_analysis import _apply_runtime_overrides as _impl

    _impl(args, detector)


def _run_analysis_phase(args, detector):
    from slop_detector.cli_analysis import _run_analysis_phase as _impl

    return _impl(args, detector)


def _record_optional_impact(command_name: str, result) -> None:
    from slop_detector.cli_observability import _record_optional_impact as _impl

    _impl(command_name, result)


def _capture_optional_telemetry(command_name: str, result) -> None:
    from slop_detector.cli_observability import _capture_optional_telemetry as _impl

    _impl(command_name, result)


def _handle_output(args, result) -> None:
    from slop_detector.cli_output import _handle_output as _impl

    _impl(args, result)


def generate_html_report(*args, **kwargs):
    from slop_detector.cli_renderer import generate_html_report as _impl

    return _impl(*args, **kwargs)


def generate_markdown_report(*args, **kwargs):
    from slop_detector.cli_renderer import generate_markdown_report as _impl

    return _impl(*args, **kwargs)


def generate_text_report(*args, **kwargs):
    from slop_detector.cli_renderer import generate_text_report as _impl

    return _impl(*args, **kwargs)


def get_mitigation(*args, **kwargs):
    from slop_detector.cli_renderer import get_mitigation as _impl

    return _impl(*args, **kwargs)


def list_patterns(*args, **kwargs):
    from slop_detector.cli_renderer import list_patterns as _impl

    return _impl(*args, **kwargs)


def print_rich_report(*args, **kwargs):
    from slop_detector.cli_renderer import print_rich_report as _impl

    return _impl(*args, **kwargs)


def _check_calibration_hint(*args, **kwargs):
    from slop_detector.cli_commands import _check_calibration_hint as _impl

    return _impl(*args, **kwargs)


def _export_history(*args, **kwargs):
    from slop_detector.cli_commands import _export_history as _impl

    return _impl(*args, **kwargs)


def _get_git_context(*args, **kwargs):
    from slop_detector.cli_commands import _get_git_context as _impl

    return _impl(*args, **kwargs)


def _record_history(*args, **kwargs):
    from slop_detector.cli_commands import _record_history as _impl

    return _impl(*args, **kwargs)


def _run_init(*args, **kwargs):
    from slop_detector.cli_commands import _run_init as _impl

    return _impl(*args, **kwargs)


def _run_self_calibration(*args, **kwargs):
    from slop_detector.cli_commands import _run_self_calibration as _impl

    return _impl(*args, **kwargs)


def _run_verify_governance(*args, **kwargs):
    from slop_detector.cli_commands import _run_verify_governance as _impl

    return _impl(*args, **kwargs)


def _show_file_history(*args, **kwargs):
    from slop_detector.cli_commands import _show_file_history as _impl

    return _impl(*args, **kwargs)


def _show_trends(*args, **kwargs):
    from slop_detector.cli_commands import _show_trends as _impl

    return _impl(*args, **kwargs)


def _run_impact_command(argv: list[str]) -> int:
    """Execute local impact summary and control commands."""
    from slop_detector.cli_handlers import run_impact_command as _impl

    return _impl(argv)


def _run_telemetry_command(argv: list[str]) -> int:
    """Execute telemetry control commands."""
    from slop_detector.cli_handlers import run_telemetry_command as _impl

    return _impl(argv)


def _run_operations_command(command: str, argv: list[str]) -> int:
    """Execute an operational command family (audit / health / cleanup / explain / watch)."""
    from slop_detector.cli_handlers import run_operations_command as _impl

    return _impl(
        command,
        argv,
        setup_logging_fn=setup_logging,
        detector_cls=SlopDetector,
    )


def _run_sweep_command(argv: list[str]) -> int:
    """Execute canonical cleanup sweep surface."""
    from slop_detector.cli_handlers import run_sweep_command as _impl

    return _impl(
        argv,
        cleanup_families=_CLEANUP_FAMILIES,
        setup_logging_fn=setup_logging,
        detector_cls=SlopDetector,
    )


def _evaluate_ci_gate(args, result):
    """Run CI gate evaluation; return exit code or None to continue."""
    from slop_detector.cli_handlers import evaluate_ci_gate as _impl

    return _impl(args, result)


def _run_optional_features(args, result) -> None:
    """Run optional post-output features (gate, fix, js, cross-file, governance)."""
    from slop_detector.cli_handlers import run_optional_features as _impl

    _impl(args, result)


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    argv_list = list(sys.argv[1:] if argv is None else argv)

    if argv_list and argv_list[0] in _OPERATIONS_COMMANDS:
        return _run_operations_command(argv_list[0], argv_list[1:])
    if argv_list and argv_list[0] in _CANONICAL_COMMAND_ALIASES:
        return _run_operations_command(_CANONICAL_COMMAND_ALIASES[argv_list[0]], argv_list[1:])
    if argv_list and argv_list[0] == "sweep":
        return _run_sweep_command(argv_list[1:])
    if argv_list and argv_list[0] == "impact":
        return _run_impact_command(argv_list[1:])
    if argv_list and argv_list[0] == "telemetry":
        return _run_telemetry_command(argv_list[1:])
    if argv_list and argv_list[0] == "mcp":
        from slop_detector.mcp.server import run_stdio_server

        return run_stdio_server()
    if argv_list and argv_list[0] == "verify-governance":
        verify_parser = argparse.ArgumentParser(
            prog="slop-detector verify-governance",
            description="Verify CR-EP governance artifacts",
        )
        verify_parser.add_argument(
            "target",
            nargs="?",
            default=".",
            help="Project root or .cr-ep/governance_record.json path",
        )
        verify_args = verify_parser.parse_args(argv_list[1:])
        return _run_verify_governance(verify_args.target)
    if argv_list and argv_list[0] == "scan":
        argv_list = argv_list[1:]

    args = _build_arg_parser().parse_args(argv_list)
    _normalize_format_args(args)
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

    _apply_runtime_overrides(args, detector)

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

    _record_optional_impact("scan", result)
    _capture_optional_telemetry("scan", result)

    if not getattr(args, "no_history", False):
        _record_history(result)
        _check_calibration_hint(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())

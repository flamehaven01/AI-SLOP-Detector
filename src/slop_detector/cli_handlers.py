"""Command handlers for the CLI surface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from slop_detector.cli_analysis import (
    _apply_runtime_overrides,
    _build_fallback_project_analysis,
)
from slop_detector.cli_commands import (
    _run_autofix,
    _run_cross_file,
    _run_gate,
    _run_governance,
    _run_js_analysis,
)
from slop_detector.cli_observability import (
    _capture_optional_telemetry,
    _public_command_name,
    _record_optional_impact,
)
from slop_detector.cli_output import (
    _emit_command_payload,
    _emit_simple_payload,
    _sanitize_for_json,
)
from slop_detector.cli_parsers import (
    _build_impact_parser,
    _build_operations_parser,
    _build_telemetry_parser,
    _normalize_format_args,
    build_sweep_parser,
)


def run_impact_command(argv: list[str]) -> int:
    """Execute local impact summary and control commands."""
    from slop_detector.impact import ImpactTracker

    args = _build_impact_parser().parse_args(argv)
    tracker = ImpactTracker(Path(args.target))
    if args.action == "enable":
        payload = tracker.enable()
    elif args.action == "disable":
        payload = tracker.disable()
    elif args.action == "status":
        payload = tracker.status()
    else:
        payload = tracker.summary()
    return _emit_simple_payload(payload, as_json=bool(args.json))


def run_telemetry_command(argv: list[str]) -> int:
    """Execute telemetry control commands."""
    from slop_detector.telemetry import TelemetryManager

    args = _build_telemetry_parser().parse_args(argv)
    manager = TelemetryManager()
    if args.action == "enable":
        payload = manager.enable()
    elif args.action == "disable":
        payload = manager.disable()
    elif args.action == "inspect":
        payload = (
            manager.example_payload()
            if args.example
            else {
                "message": "Set AI_SLOP_DETECTOR_TELEMETRY=inspect and run an analysis command for a live payload."
            }
        )
    else:
        payload = manager.status()
    return _emit_simple_payload(payload, as_json=bool(args.json))


def run_operations_command(
    command: str,
    argv: list[str],
    *,
    setup_logging_fn,
    detector_cls,
) -> int:
    """Execute an operational command family (audit / health / cleanup / explain / watch)."""
    args = _build_operations_parser(command).parse_args(argv)
    _normalize_format_args(args)
    setup_logging_fn(args.verbose)

    if command == "explain":
        from slop_detector.operations import build_explain_payload

        return _emit_command_payload(args, build_explain_payload(args.identifier))

    target_path = Path(args.target).resolve()
    project_path = target_path if target_path.is_dir() else target_path.parent

    try:
        detector = detector_cls(config_path=args.config)
    except Exception as exc:
        print(f"[!] Failed to initialize detector: {exc}", file=sys.stderr)
        return 1

    _apply_runtime_overrides(args, detector)

    try:
        result = detector.analyze_project(str(project_path))
    except Exception as exc:
        print(f"[!] Analysis failed: {exc}", file=sys.stderr)
        return 1

    needs_fallback = (
        not getattr(result, "file_results", None) and getattr(result, "total_files", 0) == 0
    )
    if needs_fallback:
        fallback = _build_fallback_project_analysis(detector, project_path)
        if fallback is not None:
            result = fallback

    if command == "audit":
        from slop_detector.operations import build_audit_payload

        _record_optional_impact(_public_command_name(command), result)
        _capture_optional_telemetry(_public_command_name(command), result)
        return _emit_command_payload(args, build_audit_payload(result, project_path, args.base))

    if command == "health":
        from slop_detector.operations import build_health_payload

        _record_optional_impact(_public_command_name(command), result)
        _capture_optional_telemetry(_public_command_name(command), result)
        return _emit_command_payload(args, build_health_payload(result))

    if command in {
        "dead-code",
        "dupes",
        "unused-deps",
        "stale-suppressions",
        "boundary-violations",
    }:
        from slop_detector.operations import build_cleanup_payload

        _record_optional_impact(_public_command_name(command), result)
        _capture_optional_telemetry(_public_command_name(command), result)
        return _emit_command_payload(args, build_cleanup_payload(result, command, detector.config))

    if command == "fix":
        _run_autofix(result, dry_run=bool(getattr(args, "dry_run", False)))
        payload = {
            "command": "fix",
            "verdict": "pass",
            "summary": {
                "project_path": result.project_path,
                "overall_status": getattr(
                    result.overall_status, "value", str(result.overall_status)
                ),
                "weighted_deficit_score": result.weighted_deficit_score,
            },
        }
        return _emit_command_payload(args, payload)

    if command == "watch":
        from slop_detector.operations import build_health_payload, watch_project

        def _factory():
            refreshed = detector.analyze_project(str(project_path))
            return build_health_payload(refreshed)

        if getattr(args, "follow", False):
            return watch_project(_factory, interval=float(args.interval), follow=True)
        return _emit_command_payload(args, _factory())

    return 1


def run_sweep_command(
    argv: list[str],
    *,
    cleanup_families,
    setup_logging_fn,
    detector_cls,
) -> int:
    """Execute canonical cleanup sweep surface."""
    args = build_sweep_parser(cleanup_families).parse_args(argv)
    _normalize_format_args(args)
    forwarded = [args.target]
    if getattr(args, "json", False):
        forwarded.append("--json")
    if getattr(args, "output", None):
        forwarded.extend(["--output", str(args.output)])
    if getattr(args, "config", None):
        forwarded.extend(["--config", str(args.config)])
    if getattr(args, "verbose", False):
        forwarded.append("--verbose")
    if getattr(args, "no_color", False):
        forwarded.append("--no-color")
    return run_operations_command(
        args.family,
        forwarded,
        setup_logging_fn=setup_logging_fn,
        detector_cls=detector_cls,
    )


def evaluate_ci_gate(args, result):
    """Run CI gate evaluation; return exit code or None to continue."""
    claims_strict = getattr(args, "ci_claims_strict", False)
    if not (args.ci_mode or args.ci_report or claims_strict):
        return None
    from slop_detector.ci_gate import CIGate, GateMode

    gate_mode = GateMode(args.ci_mode) if args.ci_mode else GateMode.SOFT
    gate_result = CIGate(mode=gate_mode, claims_strict=claims_strict).evaluate(result)
    if args.ci_report:
        if args.json:
            print(json.dumps(_sanitize_for_json(gate_result.to_dict()), indent=2, allow_nan=False))
        else:
            print(gate_result.pr_comment or gate_result.message)
    return 1 if gate_result.should_fail_build else 0


def run_optional_features(args, result) -> None:
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


def emit_leda_yaml(args, result) -> None:
    """Build and write LEDA injection YAML."""
    from slop_detector.leda_injection import build_leda_injection, write_leda_injection

    payload = build_leda_injection(
        result,
        path=args.path,
        config_path=args.config,
        profile=args.leda_profile,
    )
    written = write_leda_injection(args.leda_output, payload)
    print(f"[+] LEDA injection YAML saved to {written}")

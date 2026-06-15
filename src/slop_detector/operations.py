"""Operational command helpers for review, cleanup, and watch workflows."""

from __future__ import annotations

import time
from pathlib import Path

from slop_detector import operations_architecture as _architecture
from slop_detector import operations_cleanup as _cleanup
from slop_detector import operations_manifest as _manifest
from slop_detector import operations_payloads as _payloads
from slop_detector import operations_render as _render

_STDLIB_MODULES = _manifest._STDLIB_MODULES
_compute_stdlib_modules = _manifest._compute_stdlib_modules
_scan_python_manifest_hygiene = _manifest._scan_python_manifest_hygiene
_scan_js_manifest_hygiene = _manifest._scan_js_manifest_hygiene

build_explain_payload = _render.build_explain_payload
render_payload_text = _render.render_payload_text
render_payload_markdown = _render.render_payload_markdown

_LAYERED_PRESET = _architecture._LAYERED_PRESET
_architecture_layers_from_config = _architecture._architecture_layers_from_config
_normalize_architecture_layers = _architecture._normalize_architecture_layers
_match_architecture_layer = _architecture._match_architecture_layer
_match_architecture_layer_with_pattern = _architecture._match_architecture_layer_with_pattern
_detect_boundary_violations = _architecture._detect_boundary_violations
_project_relative_path = _architecture._project_relative_path
_build_boundary_violation_issue = _architecture._build_boundary_violation_issue
_score_boundary_confidence = _architecture._score_boundary_confidence

_looks_like_dead_code = _cleanup._looks_like_dead_code
_safe_parse_ast = _cleanup._safe_parse_ast
_has_placeholder_markers = _cleanup._has_placeholder_markers
_is_script_entrypoint = _cleanup._is_script_entrypoint
_is_main_guard = _cleanup._is_main_guard
_has_placeholder_only_body = _cleanup._has_placeholder_only_body
_is_placeholder_expression = _cleanup._is_placeholder_expression
_build_hotspot_index = _cleanup._build_hotspot_index
_find_file_result = _cleanup._find_file_result
_clamp_confidence = _cleanup._clamp_confidence
_classify_action = _cleanup._classify_action
_cleanup_file_evidence = _cleanup._cleanup_file_evidence
_score_dead_code_confidence = _cleanup._score_dead_code_confidence
_dead_code_strength_bonus = _cleanup._dead_code_strength_bonus
_dead_code_churn_adjustment = _cleanup._dead_code_churn_adjustment
_dead_code_coverage_adjustment = _cleanup._dead_code_coverage_adjustment
_score_duplicate_confidence = _cleanup._score_duplicate_confidence
_score_unused_dep_confidence = _cleanup._score_unused_dep_confidence
_score_stale_suppression_confidence = _cleanup._score_stale_suppression_confidence
_DEAD_CODE_PATTERN_IDS = _cleanup._DEAD_CODE_PATTERN_IDS
_dead_code_pattern_ids = _cleanup._dead_code_pattern_ids
_has_dead_code_patterns = _cleanup._has_dead_code_patterns
_dead_code_reason = _cleanup._dead_code_reason
_should_include_dead_code_candidate = _cleanup._should_include_dead_code_candidate
_collect_duplicate_issues = _cleanup._collect_duplicate_issues
_build_cross_file_duplicate_issue = _cleanup._build_cross_file_duplicate_issue
_collect_same_file_duplicate_issues = _cleanup._collect_same_file_duplicate_issues
_build_same_file_duplicate_issue = _cleanup._build_same_file_duplicate_issue
_collect_unused_dependency_issues = _cleanup._collect_unused_dependency_issues
_collect_file_unused_dependency_issues = _cleanup._collect_file_unused_dependency_issues
_build_file_unused_dependency_issue = _cleanup._build_file_unused_dependency_issue
_collect_stale_suppression_issues = _cleanup._collect_stale_suppression_issues
_collect_boundary_issues = _cleanup._collect_boundary_issues

_run_git = _payloads._run_git
_top_targets = _payloads._top_targets
_find_findings = _payloads._find_findings
_relative_project_path = _payloads._relative_project_path


def get_changed_files(project_path: Path, base_ref: str = "HEAD"):
    return _payloads.get_changed_files(project_path, base_ref=base_ref)


def build_audit_payload(result, project_path: Path, base_ref: str = "HEAD"):
    return _payloads.build_audit_payload(
        result,
        project_path,
        base_ref=base_ref,
        get_changed_files_func=get_changed_files,
    )


def build_health_payload(result):
    return _payloads.build_health_payload(result)


def _collect_cleanup_issues(kind: str, result, project_path: Path, cross, config):
    return _cleanup._collect_cleanup_issues(
        kind,
        result,
        project_path,
        cross,
        config,
        looks_like_dead_code_func=_looks_like_dead_code,
    )


def build_cleanup_payload(result, kind: str, config=None):
    return _payloads.build_cleanup_payload(
        result,
        kind,
        config=config,
        collect_cleanup_issues_func=_collect_cleanup_issues,
    )


def _collect_dead_code_issues(result):
    return _cleanup._collect_dead_code_issues(
        result,
        looks_like_dead_code_func=_looks_like_dead_code,
    )


def watch_project(result_factory, interval: float = 2.0, follow: bool = False) -> int:
    """Poll a project scan periodically. `result_factory` returns a fresh payload."""
    try:
        while True:
            payload = result_factory()
            print(render_payload_text(payload))
            if not follow:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 130

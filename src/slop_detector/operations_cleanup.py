"""Cleanup-family collection and confidence helpers."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

from slop_detector.clone_signals import EXACT_DUPLICATE_PAIR_ID
from slop_detector.operations_architecture import (
    _detect_boundary_violations,
    _score_boundary_confidence,
)
from slop_detector.operations_manifest import (
    _scan_js_manifest_hygiene,
    _scan_python_manifest_hygiene,
)

_DEAD_CODE_PATTERN_IDS = frozenset(
    {
        "dead_code",
        "not_implemented",
        "pass_placeholder",
        "ellipsis_placeholder",
        "return_none_placeholder",
        "return_constant_stub",
        "interface_only_class",
    }
)


def _looks_like_dead_code(file_path: str) -> bool:
    """Return True for obvious placeholder / dead-code only files."""
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if _is_script_entrypoint(tree := _safe_parse_ast(source, path)):
        return False

    if _has_placeholder_markers(source):
        return True
    return _has_placeholder_only_body(tree)


def _safe_parse_ast(source: str, path: Path) -> Optional[ast.AST]:
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def _has_placeholder_markers(source: str) -> bool:
    markers = ("TODO", "FIXME", "NotImplementedError", "pass  # placeholder")
    return any(marker in source for marker in markers)


def _is_script_entrypoint(tree: Optional[ast.AST]) -> bool:
    if tree is None:
        return False
    has_main_guard = False
    has_cli_setup = False
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.If) and _is_main_guard(node):
            has_main_guard = True
        elif isinstance(node, ast.Import):
            has_cli_setup = has_cli_setup or any(alias.name == "argparse" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            has_cli_setup = has_cli_setup or node.module in {"argparse", "click", "typer"}
    return has_main_guard or has_cli_setup


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _has_placeholder_only_body(tree: Optional[ast.AST]) -> bool:
    if tree is None:
        return False
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not all(isinstance(item, (ast.Pass, ast.Expr)) for item in body):
            continue
        if any(isinstance(item, ast.Pass) for item in body):
            return True
        if any(_is_placeholder_expression(item) for item in body):
            return True
    return False


def _is_placeholder_expression(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(getattr(node, "value", None), ast.Constant)
        and getattr(node.value, "value", None) in (Ellipsis, "")
    )


def _build_hotspot_index(result) -> Dict[str, Any]:
    index: Dict[str, Any] = {}
    for hotspot in list(getattr(result, "priority_hotspots", []) or []):
        try:
            key = str(Path(hotspot.file_path).resolve())
        except Exception:
            key = str(hotspot.file_path)
        index[key] = hotspot
    return index


def _find_file_result(result, file_path: str):
    for file_result in list(getattr(result, "file_results", []) or []):
        try:
            if Path(file_result.file_path).resolve() == Path(file_path).resolve():
                return file_result
        except Exception:
            if file_result.file_path == file_path:
                return file_result
    return None


def _clamp_confidence(value: float) -> float:
    return round(max(0.05, min(0.95, value)), 2)


def _classify_action(confidence: float) -> str:
    if confidence >= 0.75:
        return "safe_review"
    if confidence >= 0.45:
        return "needs_review"
    return "unsafe_auto_remove"


def _cleanup_file_evidence(result, file_path: str) -> Dict[str, Any]:
    hotspot = _build_hotspot_index(result).get(str(Path(file_path).resolve()))
    file_result = _find_file_result(result, file_path)
    evidence: Dict[str, Any] = {
        "deficit_score": None,
        "churn_count": 0,
        "churn_score": 0.0,
        "coverage_ratio": None,
        "reasons": [],
    }
    if file_result is not None:
        evidence["deficit_score"] = round(float(getattr(file_result, "deficit_score", 0.0)), 4)
    if hotspot is not None:
        evidence["deficit_score"] = round(float(getattr(hotspot, "deficit_score", 0.0)), 4)
        evidence["churn_count"] = int(getattr(hotspot, "churn_count", 0) or 0)
        evidence["churn_score"] = round(float(getattr(hotspot, "churn_score", 0.0) or 0.0), 4)
        coverage_ratio = getattr(hotspot, "coverage_ratio", None)
        evidence["coverage_ratio"] = (
            None if coverage_ratio is None else round(float(coverage_ratio), 4)
        )
        evidence["reasons"] = list(getattr(hotspot, "reasons", []) or [])
    return evidence


def _score_dead_code_confidence(
    result, file_path: str, pattern_count: int, placeholder: bool
) -> Dict[str, Any]:
    evidence = _cleanup_file_evidence(result, file_path)
    confidence = 0.45
    confidence += _dead_code_strength_bonus(placeholder, pattern_count, evidence)
    confidence += _dead_code_churn_adjustment(evidence)
    confidence += _dead_code_coverage_adjustment(evidence["coverage_ratio"])
    confidence = _clamp_confidence(confidence)
    evidence["rule_inputs"] = {
        "pattern_count": pattern_count,
        "placeholder": placeholder,
        "counts_dead_code_patterns_only": True,
    }
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": evidence,
    }


def _dead_code_strength_bonus(
    placeholder: bool, pattern_count: int, evidence: Dict[str, Any]
) -> float:
    confidence = 0.0
    deficit_score = float(evidence["deficit_score"] or 0.0)
    if placeholder:
        confidence += 0.15
    if pattern_count > 0:
        confidence += 0.10
    if deficit_score >= 60:
        confidence += 0.10
    elif deficit_score >= 30:
        confidence += 0.05
    return confidence


def _dead_code_churn_adjustment(evidence: Dict[str, Any]) -> float:
    churn_score = float(evidence["churn_score"] or 0.0)
    if churn_score >= 0.60:
        return -0.30
    if churn_score >= 0.30:
        return -0.15
    if churn_score == 0.0:
        return 0.10
    return 0.0


def _dead_code_coverage_adjustment(coverage_ratio: Optional[float]) -> float:
    if coverage_ratio is None:
        return 0.0
    if coverage_ratio <= 0.10:
        return 0.15
    if coverage_ratio <= 0.30:
        return 0.10
    if coverage_ratio >= 0.60:
        return -0.15
    return 0.0


def _score_duplicate_confidence(
    result, file_a: str, file_b: str, similarity: float
) -> Dict[str, Any]:
    evidence_a = _cleanup_file_evidence(result, file_a)
    evidence_b = _cleanup_file_evidence(result, file_b)
    max_churn = max(
        float(evidence_a["churn_score"] or 0.0), float(evidence_b["churn_score"] or 0.0)
    )
    coverage_values = [
        value
        for value in [evidence_a["coverage_ratio"], evidence_b["coverage_ratio"]]
        if value is not None
    ]
    min_coverage = min(coverage_values) if coverage_values else None

    confidence = 0.55
    if similarity >= 0.99:
        confidence += 0.15
    elif similarity >= 0.90:
        confidence += 0.10

    if max_churn >= 0.60:
        confidence -= 0.25
    elif max_churn >= 0.30:
        confidence -= 0.10
    elif max_churn == 0.0:
        confidence += 0.05

    if min_coverage is not None and min_coverage <= 0.30:
        confidence += 0.05

    confidence = _clamp_confidence(confidence)
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": {
            "similarity": round(similarity, 4),
            "file_a": evidence_a,
            "file_b": evidence_b,
        },
    }


def _score_unused_dep_confidence(
    result, file_path: str, unused_count: int, usage_ratio: float
) -> Dict[str, Any]:
    evidence = _cleanup_file_evidence(result, file_path)
    confidence = 0.55
    if unused_count >= 3:
        confidence += 0.10
    if usage_ratio <= 0.50:
        confidence += 0.10

    churn_score = float(evidence["churn_score"] or 0.0)
    coverage_ratio = evidence["coverage_ratio"]
    if churn_score >= 0.60:
        confidence -= 0.20
    elif churn_score >= 0.30:
        confidence -= 0.10

    if coverage_ratio is not None and coverage_ratio <= 0.30:
        confidence += 0.05

    confidence = _clamp_confidence(confidence)
    evidence["rule_inputs"] = {
        "unused_count": unused_count,
        "usage_ratio": round(float(usage_ratio), 4),
    }
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": evidence,
    }


def _score_stale_suppression_confidence(
    lineno: int, scope: str, rules: List[str], source: str
) -> Dict[str, Any]:
    confidence = _clamp_confidence(0.85)
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": {
            "lineno": lineno,
            "scope": scope,
            "rules": list(rules),
            "source": source,
            "reasons": ["suppression no longer matches any recorded finding"],
        },
    }


def _collect_cleanup_issues(
    kind: str,
    result,
    project_path: Path,
    cross,
    config,
    looks_like_dead_code_func=_looks_like_dead_code,
) -> List[Dict[str, Any]]:
    if kind == "dead-code":
        return _collect_dead_code_issues(
            result, looks_like_dead_code_func=looks_like_dead_code_func
        )
    if kind == "dupes":
        return _collect_duplicate_issues(result, cross)
    if kind == "unused-deps":
        return _collect_unused_dependency_issues(result, project_path)
    if kind == "stale-suppressions":
        return _collect_stale_suppression_issues(result)
    if kind == "boundary-violations":
        return _collect_boundary_issues(result, project_path, cross, config)
    return []


def _collect_dead_code_issues(
    result, looks_like_dead_code_func=_looks_like_dead_code
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for fr in result.file_results:
        placeholder = looks_like_dead_code_func(fr.file_path)
        dead_pattern_ids = _dead_code_pattern_ids(fr)
        if not _should_include_dead_code_candidate(fr, placeholder):
            continue
        ranking = _score_dead_code_confidence(
            result,
            fr.file_path,
            len(dead_pattern_ids),
            placeholder,
        )
        issues.append(
            {
                "file_path": fr.file_path,
                "deficit_score": getattr(fr, "deficit_score", 0.0),
                "pattern_count": len(dead_pattern_ids),
                "reason": _dead_code_reason(placeholder, dead_pattern_ids),
                **ranking,
            }
        )
    return issues


def _dead_code_pattern_ids(fr) -> List[str]:
    return sorted(
        {
            getattr(p, "pattern_id", "")
            for p in getattr(fr, "pattern_issues", [])
            if getattr(p, "pattern_id", "") in _DEAD_CODE_PATTERN_IDS
        }
    )


def _has_dead_code_patterns(fr) -> bool:
    return bool(_dead_code_pattern_ids(fr))


def _dead_code_reason(placeholder: bool, dead_pattern_ids: List[str]) -> str:
    if placeholder and dead_pattern_ids:
        return "placeholder-only file with dead-code patterns"
    if placeholder:
        return "placeholder-only file"
    if dead_pattern_ids:
        return "dead-code pattern detected"
    return "dead-code candidate"


def _should_include_dead_code_candidate(fr, placeholder: bool) -> bool:
    return bool(placeholder or _has_dead_code_patterns(fr))


def _collect_duplicate_issues(result, cross) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for dup in cross.duplicates:
        issues.append(_build_cross_file_duplicate_issue(result, dup))
    issues.extend(_collect_same_file_duplicate_issues(result))
    return issues


def _build_cross_file_duplicate_issue(result, dup) -> Dict[str, Any]:
    ranking = _score_duplicate_confidence(result, dup.file_a, dup.file_b, dup.similarity)
    return {
        "file_a": dup.file_a,
        "file_b": dup.file_b,
        "func_a": dup.func_a,
        "func_b": dup.func_b,
        "similarity": dup.similarity,
        **ranking,
    }


def _collect_same_file_duplicate_issues(result) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for fr in list(getattr(result, "file_results", []) or []):
        file_path = str(getattr(fr, "file_path", ""))
        if not file_path:
            continue
        for issue in list(getattr(fr, "pattern_issues", []) or []):
            if getattr(issue, "pattern_id", "") != EXACT_DUPLICATE_PAIR_ID:
                continue
            issues.append(_build_same_file_duplicate_issue(result, file_path, issue))
    return issues


def _build_same_file_duplicate_issue(result, file_path: str, issue) -> Dict[str, Any]:
    ranking = _score_duplicate_confidence(result, file_path, file_path, 1.0)
    return {
        "issue_type": "same_file_exact_duplicate",
        "file_a": file_path,
        "file_b": file_path,
        "func_a": getattr(issue, "code", "") or None,
        "func_b": getattr(issue, "code", "") or None,
        "similarity": 1.0,
        "line": getattr(issue, "line", 1),
        "display": getattr(issue, "message", ""),
        **ranking,
    }


def _collect_unused_dependency_issues(result, project_path: Path) -> List[Dict[str, Any]]:
    issues = _collect_file_unused_dependency_issues(result)
    issues.extend(_scan_python_manifest_hygiene(project_path, result))
    issues.extend(_scan_js_manifest_hygiene(project_path))
    return issues


def _collect_file_unused_dependency_issues(result) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for fr in result.file_results:
        if not getattr(fr.ddc, "unused", []):
            continue
        issues.append(_build_file_unused_dependency_issue(result, fr))
    return issues


def _build_file_unused_dependency_issue(result, fr) -> Dict[str, Any]:
    ranking = _score_unused_dep_confidence(
        result,
        fr.file_path,
        len(getattr(fr.ddc, "unused", [])),
        getattr(fr.ddc, "usage_ratio", 0.0),
    )
    return {
        "file_path": fr.file_path,
        "usage_ratio": fr.ddc.usage_ratio,
        "unused": list(fr.ddc.unused),
        **ranking,
    }


def _collect_stale_suppression_issues(result) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    ledger_entries = getattr(result, "suppression_ledger", []) or []
    directives = (
        getattr(result.file_results[0], "suppression_directives", []) if result.file_results else []
    )
    directive_lines = {entry.directive_line for entry in ledger_entries}
    for directive in directives:
        if directive.lineno in directive_lines:
            continue
        ranking = _score_stale_suppression_confidence(
            directive.lineno,
            directive.scope,
            list(directive.rules),
            directive.source,
        )
        issues.append(
            {
                "lineno": directive.lineno,
                "scope": directive.scope,
                "rules": list(directive.rules),
                "source": directive.source,
                **ranking,
            }
        )
    return issues


def _collect_boundary_issues(result, project_path: Path, cross, config) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for cycle in cross.import_cycles:
        ranking = _score_boundary_confidence(list(cycle.cycle))
        issues.append(
            {
                "issue_type": "import_cycle",
                "cycle": list(cycle.cycle),
                "display": str(cycle),
                **ranking,
            }
        )
    issues.extend(_detect_boundary_violations(project_path, cross, config))
    return issues

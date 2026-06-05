"""Command execution helpers for the SLOP detector CLI."""

import argparse
import ast
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _run_gate(result) -> None:
    """Display SNP-compatible gate decision."""
    from slop_detector.gate.slop_gate import SlopGate

    gate = SlopGate()
    if hasattr(result, "file_results"):
        avg_ldr = getattr(result, "avg_ldr", 0.0)
        avg_inflation = getattr(result, "avg_inflation", 0.0)
        avg_ddc = getattr(result, "avg_ddc", 1.0)
        pattern_penalty = min(result.deficit_files * 5.0, 50.0)
        decision = gate.evaluate(avg_ldr, avg_ddc, avg_inflation, pattern_penalty, "project")
    else:
        decision = gate.evaluate_from_file_analysis(result)

    print("\n[Gate Decision]")
    print(f"  Status   : {decision.status}")
    print(f"  Allowed  : {decision.allowed}")
    m = decision.metrics_snapshot
    print(f"  sr9={m['sr9']:.4f}  di2={m['di2']:.4f}  jsd={m['jsd']:.4f}  ove={m['ove']:.4f}")
    if decision.halt_reason:
        print(f"  Halt     : {decision.halt_reason}")
    if decision.recommendation:
        print(f"  Recommend: {decision.recommendation}")
    print(f"  AuditHash: {decision.audit_hash[:16]}...")


def _run_autofix(result, dry_run: bool = True) -> None:
    """Run auto-fix engine on analysis results."""
    from slop_detector.autofix.engine import FixEngine

    engine = FixEngine()
    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"\n[Auto-Fix] {mode}")

    if hasattr(result, "file_results"):
        file_analyses = [
            (fa.file_path, getattr(fa, "pattern_issues", [])) for fa in result.file_results
        ]
    else:
        file_analyses = [(result.file_path, getattr(result, "pattern_issues", []))]

    fix_results = engine.fix_project(file_analyses, dry_run=dry_run)

    if not fix_results:
        print("  [+] No auto-fixable issues found.")
        return

    total_fixed = 0
    for fix_result in fix_results:
        if fix_result.changed:
            print(f"\n  File: {fix_result.file_path}")
            for ch in fix_result.changes:
                print(f"    [L{ch.line}] {ch.pattern_id} (confidence={ch.confidence:.0%})")
                print(f"      - {ch.original.strip()!r}")
                print(f"      + {ch.replacement.strip()!r}")
            total_fixed += fix_result.change_count
        if fix_result.unfixable:
            print(f"  Unfixable (manual): {', '.join(fix_result.unfixable)}")

    action = "Would fix" if dry_run else "Fixed"
    print(f"\n  [+] {action} {total_fixed} issues across {len(fix_results)} files.")
    if dry_run:
        print("  Run without --dry-run to apply changes.")


def _run_js_analysis(path: str) -> None:
    """Analyze JS/TS files in a directory."""
    from slop_detector.languages.js_analyzer import JSAnalyzer

    analyzer = JSAnalyzer()
    target = Path(path)

    if target.is_file() and target.suffix.lower() in (".js", ".jsx", ".ts", ".tsx"):
        results = [analyzer.analyze(str(target))]
    elif target.is_dir():
        results = analyzer.analyze_directory(str(target))
    else:
        print(f"[!] No JS/TS files found at {path}")
        return

    print(f"\n[JS/TS Analysis] {len(results)} files")
    clean = sum(1 for r in results if r.status == "clean")
    suspicious = sum(1 for r in results if r.status == "suspicious")
    critical = sum(1 for r in results if r.status == "critical_deficit")
    print(f"  Clean: {clean}  Suspicious: {suspicious}  Critical: {critical}")

    for r in sorted(results, key=lambda x: x.slop_score, reverse=True):
        if r.status == "clean":
            continue
        print(f"\n  [{r.status.upper()}] {r.file_path}")
        print(f"    Score={r.slop_score:.1f}  LDR={r.ldr_equivalent:.2%}  Issues={len(r.issues)}")
        for issue in r.issues[:5]:
            print(f"    L{issue.line} [{issue.severity}] {issue.message}")


def _run_cross_file(result) -> None:
    """Run cross-file analysis on project results."""
    from slop_detector.analysis.cross_file import CrossFileAnalyzer

    analyzer = CrossFileAnalyzer()
    report = analyzer.analyze(
        result.project_path,
        result.file_results,
    )

    print("\n[Cross-File Analysis]")
    print(f"  Files: {report.total_files}  Risk Score: {report.risk_score:.2f}")

    if report.import_cycles:
        print(f"\n  Import Cycles ({len(report.import_cycles)}):")
        for cycle in report.import_cycles[:5]:
            print(f"    {cycle}")

    if report.duplicates:
        print(f"\n  Duplicate Functions ({len(report.duplicates)}):")
        for dup in report.duplicates[:5]:
            a = Path(dup.file_a).name
            b = Path(dup.file_b).name
            print(f"    {a}:{dup.func_a}() == {b}:{dup.func_b}() (sim={dup.similarity:.0%})")

    if report.hotspots:
        print(f"\n  Slop Hotspots ({len(report.hotspots)}) - heavily imported + sloppy:")
        for h in report.hotspots:
            print(
                f"    {Path(h.file_path).name}  score={h.slop_score:.1f}  imported_by={h.import_count}"
            )

    if not report.import_cycles and not report.duplicates and not report.hotspots:
        print("  [+] No cross-file issues detected.")


def _run_governance(path: str, result) -> None:
    """Emit CR-EP v2.7.2 session artifacts."""
    from slop_detector.governance.session import AnalysisSession

    project_path = Path(path).resolve()
    if not project_path.is_dir():
        project_path = project_path.parent

    session = AnalysisSession(project_path=project_path)

    if hasattr(result, "file_results"):
        planned = [fa.file_path for fa in result.file_results]
        actual = planned
        total_issues = sum(len(getattr(fa, "pattern_issues", [])) for fa in result.file_results)
        halt_count = sum(
            1
            for fa in result.file_results
            if getattr(fa, "status", "") in {"critical_deficit", "suspicious"}
        )
        for fa in result.file_results:
            session.record_file_analyzed(
                file_path=fa.file_path,
                slop_score=getattr(fa, "deficit_score", 0.0),
                status=str(getattr(fa, "status", "unknown")),
                issues_count=len(getattr(fa, "pattern_issues", [])),
            )
    else:
        planned = [result.file_path]
        actual = planned
        total_issues = len(getattr(result, "pattern_issues", []))
        halt_count = 1 if str(getattr(result, "status", "")) == "critical_deficit" else 0
        session.record_file_analyzed(
            file_path=result.file_path,
            slop_score=getattr(result, "deficit_score", 0.0),
            status=str(getattr(result, "status", "unknown")),
            issues_count=total_issues,
        )

    session.record_enforcement("SD-0", "CONFIRMED", f"Analyzing {len(planned)} files")
    cr_ep_dir = session.finalize(planned, actual, total_issues, halt_count)
    print(f"\n[Governance] CR-EP v2.7.2 artifacts written to: {cr_ep_dir}")
    print("  session.json, why_gate.json, scope_declaration.json")
    print("  enforcement_log.jsonl, change_events.jsonl, review_contract.json")


def _resolve_governance_record_path(target: str) -> Path:
    path = Path(target)
    if path.is_dir():
        candidate = path / ".cr-ep" / "governance_record.json"
        if candidate.exists():
            return candidate
        candidate = path / "governance_record.json"
        if candidate.exists():
            return candidate
    if path.is_file():
        return path
    candidate = path / ".cr-ep" / "governance_record.json"
    if candidate.exists():
        return candidate
    return path


def _run_verify_governance(target: str) -> int:
    """Verify governance artifact integrity and policy constraints."""
    from slop_detector.governance.verification import (
        GovernanceVerificationError,
        verify_governance_record,
    )

    record_path = _resolve_governance_record_path(target)
    try:
        record, computed_hash = verify_governance_record(record_path)
    except GovernanceVerificationError as exc:
        print(f"[!] Governance verification failed: {exc}", file=sys.stderr)
        return 1

    print("[Governance Verification]")
    print(f"  Record     : {record_path}")
    print(f"  Hash       : {computed_hash[:16]}...")
    print(f"  Session    : {record.get('session_id', 'unknown')}")
    print("  Integrity  : PASS")
    print("  Policy     : PASS")
    return 0


def _detect_project_type(path: Path) -> str:
    """Infer project type from root directory structure."""
    if (path / "package.json").exists():
        return "javascript"
    if (path / "go.mod").exists():
        return "go"
    return "python"  # pyproject.toml / setup.py / .py files — default


def detect_domain(project_path: Path) -> tuple:
    """Scan project imports and return (domain_path, detected_by, confidence).

    Scans all .py files for import statements and matches against DOMAIN_PROFILES
    triggers.  Returns ('general', [], 0.0) when no profile exceeds the threshold.
    """
    import re
    from typing import Dict, List

    from slop_detector.config import DOMAIN_PROFILES

    import_re = re.compile(r"^\s*(?:import\s+([\w]+)|from\s+([\w]+)\s+import)", re.MULTILINE)
    found_imports: set = set()
    try:
        for py_file in project_path.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                for m in import_re.finditer(text):
                    mod = (m.group(1) or m.group(2) or "").lower()
                    if mod:
                        found_imports.add(mod)
            except OSError:
                continue
    except OSError as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("domain detection scan failed: %s", exc)

    scores: Dict[str, List[str]] = {}
    for dp, profile in DOMAIN_PROFILES.items():
        if dp == "general":
            continue
        hits = [t for t in profile.get("triggers", []) if t.lower() in found_imports]
        if hits:
            scores[dp] = hits

    if not scores:
        return "general", [], 0.0

    # Rank by hit count; break ties by specificity (fewer triggers = more specific)
    best = max(
        scores,
        key=lambda k: (len(scores[k]), -len(DOMAIN_PROFILES[k].get("triggers", []) or [1])),
    )
    hits = scores[best]
    n_triggers = max(len(DOMAIN_PROFILES[best].get("triggers", [])), 1)
    confidence = round(min(1.0, len(hits) / max(n_triggers * 0.4, 1)), 2)
    return best, hits, confidence


_INIT_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "venv",
    "site-packages",
    "node_modules",
}

_INIT_NOISE_DIR_NAMES = {
    "tests",
    "test",
    "__tests__",
    "migrations",
    "dist",
    "build",
    "static",
    "datasets",
    "data",
    "checkpoints",
    "results",
    "output",
    "backtests",
    "docs",
    "examples",
    "notebooks",
    "vendor",
}

_INIT_ARCHITECTURE_LAYER_NAMES = {
    "api",
    "routes",
    "controllers",
    "presentation",
    "service",
    "services",
    "application",
    "use_cases",
    "domain",
    "models",
    "entities",
    "value_objects",
    "data",
    "repositories",
    "infrastructure",
    "adapters",
}


def _iter_init_python_files(project_path: Path) -> List[Path]:
    """Collect Python files suitable for lightweight adaptive-init inspection."""
    files: List[Path] = []
    try:
        for path in project_path.rglob("*.py"):
            if any(part in _INIT_SKIP_DIRS for part in path.parts):
                continue
            files.append(path)
    except OSError:
        return []
    return files


def _relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _collect_noise_directories(project_path: Path) -> List[str]:
    """Return repository directories likely to influence ignore suggestions later."""
    found: List[str] = []
    seen = set()
    try:
        for path in project_path.rglob("*"):
            if not path.is_dir():
                continue
            if any(part in _INIT_SKIP_DIRS for part in path.parts):
                continue
            if path.name not in _INIT_NOISE_DIR_NAMES:
                continue
            rel = _relative_posix(path, project_path)
            if rel not in seen:
                seen.add(rel)
                found.append(rel)
    except OSError:
        return []
    return sorted(found)


def _count_repo_languages(project_path: Path) -> Dict[str, int]:
    """Count dominant code file types with a lightweight directory walk."""
    counts = {"python": 0, "javascript": 0, "typescript": 0, "go": 0}
    try:
        for path in project_path.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _INIT_SKIP_DIRS for part in path.parts):
                continue
            suffix = path.suffix.lower()
            if suffix == ".py":
                counts["python"] += 1
            elif suffix in {".js", ".jsx", ".mjs", ".cjs"}:
                counts["javascript"] += 1
            elif suffix in {".ts", ".tsx"}:
                counts["typescript"] += 1
            elif suffix == ".go":
                counts["go"] += 1
    except OSError:
        return counts
    return counts


def _collect_architecture_markers(project_path: Path) -> Dict[str, Any]:
    """Collect coarse package/layout markers useful for later opt-in hints."""
    matched_dirs: List[str] = []
    unique_names = set()
    seen_dirs = set()
    try:
        for path in project_path.rglob("*"):
            if not path.is_dir():
                continue
            if any(part in _INIT_SKIP_DIRS for part in path.parts):
                continue
            if path.name not in _INIT_ARCHITECTURE_LAYER_NAMES:
                continue
            rel = _relative_posix(path, project_path)
            if rel in seen_dirs:
                continue
            seen_dirs.add(rel)
            matched_dirs.append(rel)
            unique_names.add(path.name)
    except OSError:
        return {
            "matched_directories": [],
            "layer_names": [],
            "layered_hint_strength": 0.0,
            "has_src_layout": False,
        }

    strength = round(min(1.0, len(unique_names) / 4.0), 2)
    return {
        "matched_directories": sorted(matched_dirs),
        "layer_names": sorted(unique_names),
        "layered_hint_strength": strength,
        "has_src_layout": (project_path / "src").exists(),
    }


def _collect_python_complexity_candidates(project_path: Path) -> List[Dict[str, Any]]:
    """Collect a bounded set of Python functions worth later override review."""
    from slop_detector.patterns.python_complexity import _cyclomatic_complexity

    candidates: List[Dict[str, Any]] = []
    for path in _iter_init_python_files(project_path):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except (OSError, SyntaxError, UnicodeError):
            continue
        lines = content.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            logic_lines = sum(
                1
                for line in lines[max(0, start - 1) : end]
                if line.strip() and not line.strip().startswith("#")
            )
            complexity = _cyclomatic_complexity(node)
            # Adaptive init should collect "override candidates", not only
            # exact current rule violations.
            if complexity < 8 and logic_lines < 20:
                continue
            candidates.append(
                {
                    "file_path": _relative_posix(path, project_path),
                    "function_name": node.name,
                    "complexity": complexity,
                    "logic_lines": logic_lines,
                }
            )
    candidates.sort(key=lambda item: (item["complexity"], item["logic_lines"]), reverse=True)
    return candidates[:10]


def collect_init_signals(project_path: Path) -> Dict[str, Any]:
    """Collect lightweight repository signals for adaptive --init follow-up phases."""
    project_type = _detect_project_type(project_path)
    domain_path, detected_by, confidence = detect_domain(project_path)
    language_counts = _count_repo_languages(project_path)
    noise_directories = _collect_noise_directories(project_path)
    complexity_candidates = _collect_python_complexity_candidates(project_path)
    architecture_markers = _collect_architecture_markers(project_path)

    return {
        "project_type": project_type,
        "domain": {
            "path": domain_path,
            "detected_by": detected_by,
            "confidence": confidence,
        },
        "manifests": {
            "pyproject_toml": (project_path / "pyproject.toml").exists(),
            "package_json": (project_path / "package.json").exists(),
            "go_mod": (project_path / "go.mod").exists(),
        },
        "language_counts": language_counts,
        "noise_directories": noise_directories,
        "python_complexity_candidates": complexity_candidates,
        "architecture_markers": architecture_markers,
        "cleanup_markers": {
            "has_tests": bool(
                any(marker in noise_directories for marker in ("tests", "test", "__tests__"))
            ),
            "candidate_count": len(complexity_candidates),
        },
    }


def _get_init_baseline_ignore_patterns(project_type: str, domain_path: str) -> set:
    """Return ignore patterns already covered by baseline init generation."""
    from slop_detector.config import DOMAIN_PROFILES, Config

    ignore_patterns = set(Config.DEFAULT_CONFIG.get("ignore", []))
    profile = DOMAIN_PROFILES.get(domain_path, DOMAIN_PROFILES["general"])
    ignore_patterns.update(profile.get("ignore_extra", []))
    if project_type == "javascript":
        ignore_patterns.update({"node_modules/**", "dist/**", "build/**"})
    if project_type == "go":
        ignore_patterns.add("vendor/**")
    return ignore_patterns


def _suggest_ignore_patterns(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate bounded ignore suggestions from observed repository noise markers."""
    baseline = _get_init_baseline_ignore_patterns(
        str(signals.get("project_type", "python")),
        str(signals.get("domain", {}).get("path", "general")),
    )
    suggestions: List[Dict[str, Any]] = []
    for directory in sorted(signals.get("noise_directories", [])):
        pattern = f"{directory}/**"
        if pattern in baseline:
            continue
        suggestions.append(
            {
                "pattern": pattern,
                "reason": f"Observed repository noise directory '{directory}'.",
                "evidence": {
                    "directory": directory,
                    "baseline_covered": False,
                },
            }
        )
    return suggestions


def _suggest_domain_overrides(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggest highly conservative god_function overrides from strong evidence."""
    from slop_detector.config import DOMAIN_PROFILES

    domain_path = str(signals.get("domain", {}).get("path", "general"))
    profile = DOMAIN_PROFILES.get(domain_path, DOMAIN_PROFILES["general"])
    god_config = profile.get("pattern_config", {}).get(
        "god_function",
        {"complexity_threshold": 10, "lines_threshold": 50},
    )
    base_complexity = int(god_config.get("complexity_threshold", 10))
    base_lines = int(god_config.get("lines_threshold", 50))

    suggestions: List[Dict[str, Any]] = []
    for candidate in signals.get("python_complexity_candidates", []):
        complexity = int(candidate.get("complexity", 0))
        logic_lines = int(candidate.get("logic_lines", 0))
        complexity_excess = max(0, complexity - base_complexity)
        line_excess = max(0, logic_lines - base_lines)
        strong_candidate = (
            complexity >= base_complexity + 3
            or logic_lines >= base_lines + 25
            or (complexity_excess >= 1 and line_excess >= 10)
        )
        if not strong_candidate:
            continue
        suggestions.append(
            {
                "function_pattern": str(candidate.get("function_name", "")),
                "complexity_threshold": max(base_complexity, complexity + 1),
                "lines_threshold": max(base_lines, logic_lines + 5),
                "reason": (
                    "Observed function exceeds the baseline domain thresholds strongly "
                    "enough to justify override review."
                ),
                "evidence": {
                    "file_path": candidate.get("file_path"),
                    "complexity": complexity,
                    "logic_lines": logic_lines,
                    "base_complexity_threshold": base_complexity,
                    "base_lines_threshold": base_lines,
                },
            }
        )
    return suggestions[:3]


def _suggest_architecture_config(signals: Dict[str, Any]) -> Dict[str, Any]:
    """Recommend whether layered architecture should remain disabled or opt in."""
    markers = signals.get("architecture_markers", {})
    layer_names = set(markers.get("layer_names", []))
    strength = float(markers.get("layered_hint_strength", 0.0) or 0.0)
    has_src_layout = bool(markers.get("has_src_layout", False))
    has_boundary_shape = (
        "domain" in layer_names
        and "data" in layer_names
        and bool(layer_names.intersection({"api", "service", "services", "application"}))
    )

    if has_src_layout and has_boundary_shape and strength >= 0.75:
        return {
            "recommendation": "enable_layered_preset",
            "preset": "layered",
            "reason": (
                "Detected a src-based repository layout with domain, data, and "
                "application-facing layers."
            ),
            "evidence": {
                "has_src_layout": has_src_layout,
                "layer_names": sorted(layer_names),
                "layered_hint_strength": strength,
            },
        }

    return {
        "recommendation": "stay_disabled",
        "preset": "none",
        "reason": "Architecture evidence is not strong enough to enable layered review by default.",
        "evidence": {
            "has_src_layout": has_src_layout,
            "layer_names": sorted(layer_names),
            "layered_hint_strength": strength,
        },
    }


def _suggest_cleanup_hints(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Produce small, explainable cleanup guidance for init-time onboarding."""
    manifests = signals.get("manifests", {})
    cleanup_markers = signals.get("cleanup_markers", {})
    hints: List[Dict[str, Any]] = []

    if manifests.get("pyproject_toml") or manifests.get("package_json"):
        hints.append(
            {
                "hint": "unused_deps_review",
                "reason": "Manifest files were detected, so project-level dependency hygiene is likely valuable.",
                "evidence": {
                    "pyproject_toml": bool(manifests.get("pyproject_toml")),
                    "package_json": bool(manifests.get("package_json")),
                },
            }
        )

    if not cleanup_markers.get("has_tests"):
        hints.append(
            {
                "hint": "coverage_signals_limited",
                "reason": "No test directories were detected, so coverage-aware cleanup guidance will stay weaker until tests exist.",
                "evidence": {
                    "has_tests": False,
                },
            }
        )

    if int(cleanup_markers.get("candidate_count", 0) or 0) >= 5:
        hints.append(
            {
                "hint": "review_domain_overrides_before_cleanup",
                "reason": "Multiple high-complexity candidates were found, so cleanup review will benefit from domain override tuning first.",
                "evidence": {
                    "candidate_count": int(cleanup_markers.get("candidate_count", 0) or 0),
                },
            }
        )

    return hints


def synthesize_init_suggestions(signals: Dict[str, Any]) -> Dict[str, Any]:
    """Convert adaptive-init signals into conservative, explainable suggestions."""
    return {
        "ignore_patterns": _suggest_ignore_patterns(signals),
        "god_function_domain_overrides": _suggest_domain_overrides(signals),
        "architecture": _suggest_architecture_config(signals),
        "cleanup_hints": _suggest_cleanup_hints(signals),
    }


def _render_init_preview(
    project_type: str,
    domain_path: str,
    signals: Dict[str, Any],
    suggestions: Dict[str, Any],
) -> str:
    """Render a small adaptive-init preview without mutating repository config."""
    lines = [
        "[Adaptive Init Preview]",
        f"  Project type : {project_type}",
        f"  Domain       : {domain_path}",
        f"  Languages    : {signals.get('language_counts', {})}",
    ]

    ignore_patterns = suggestions.get("ignore_patterns", [])
    if ignore_patterns:
        lines.append("  Ignore suggestions:")
        for item in ignore_patterns:
            lines.append(f"    - {item['pattern']}  # {item['reason']}")

    overrides = suggestions.get("god_function_domain_overrides", [])
    if overrides:
        lines.append("  Override suggestions:")
        for item in overrides:
            lines.append(
                "    - "
                f"{item['function_pattern']} -> complexity {item['complexity_threshold']}, "
                f"lines {item['lines_threshold']}"
            )

    architecture = suggestions.get("architecture", {})
    lines.append(
        "  Architecture : "
        f"{architecture.get('recommendation', 'stay_disabled')} "
        f"({architecture.get('reason', 'no reason available')})"
    )

    cleanup_hints = suggestions.get("cleanup_hints", [])
    if cleanup_hints:
        lines.append("  Cleanup hints:")
        for item in cleanup_hints:
            lines.append(f"    - {item['hint']}: {item['reason']}")

    if not ignore_patterns and not overrides and not cleanup_hints:
        lines.append("  No adaptive config suggestions were strong enough to apply.")

    return "\n".join(lines)


def _merge_adaptive_init_suggestions(
    config_data: Dict[str, Any],
    suggestions: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge conservative adaptive-init suggestions into an existing config dict."""
    merged = dict(config_data)

    ignore_list = list(merged.get("ignore", []) or [])
    for item in suggestions.get("ignore_patterns", []):
        pattern = item.get("pattern")
        if pattern and pattern not in ignore_list:
            ignore_list.append(pattern)
    if ignore_list:
        merged["ignore"] = ignore_list

    patterns = dict(merged.get("patterns", {}) or {})
    god_function = dict(patterns.get("god_function", {}) or {})
    domain_overrides = list(god_function.get("domain_overrides", []) or [])
    existing_patterns = {str(item.get("function_pattern", "")) for item in domain_overrides}
    for item in suggestions.get("god_function_domain_overrides", []):
        function_pattern = str(item.get("function_pattern", "")).strip()
        if not function_pattern or function_pattern in existing_patterns:
            continue
        domain_overrides.append(
            {
                "function_pattern": function_pattern,
                "complexity_threshold": int(item.get("complexity_threshold", 10)),
                "lines_threshold": int(item.get("lines_threshold", 50)),
                "reason": item.get("reason", "Adaptive init suggestion"),
            }
        )
        existing_patterns.add(function_pattern)
    god_function["domain_overrides"] = domain_overrides
    patterns["god_function"] = god_function
    merged["patterns"] = patterns

    architecture = dict(merged.get("architecture", {}) or {})
    architecture_suggestion = suggestions.get("architecture", {})
    if architecture_suggestion.get("recommendation") == "enable_layered_preset":
        if not architecture.get("enabled", False):
            architecture["enabled"] = True
        if architecture.get("preset", "none") in {"none", "", None}:
            architecture["preset"] = "layered"
    if "layers" not in architecture:
        architecture["layers"] = []
    merged["architecture"] = architecture

    return merged


def _write_init_config(
    config_path: Path,
    config_data: Dict[str, Any],
    comment_lines: List[str],
) -> None:
    """Write YAML config with a preserved explanatory comment block."""
    header = "\n".join(comment_lines).rstrip() + "\n\n"
    yaml_body = yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True)
    config_path.write_text(header + yaml_body, encoding="utf-8")


def _inject_gitignore_entry(gitignore_path: Path, entry: str, comment: str) -> None:
    """Append entry to .gitignore if not already present."""
    if gitignore_path.exists():
        text = gitignore_path.read_text(encoding="utf-8")
        if entry in text:
            return
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write(f"\n{comment}\n{entry}\n")
    else:
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(f"{comment}\n{entry}\n")
    print(f"[+] {entry} added to {gitignore_path}")


def _run_init(args: argparse.Namespace) -> int:
    """Bootstrap .slopconfig.yaml and secure it in .gitignore."""
    from slop_detector.config import DOMAIN_PROFILES, generate_slopconfig_template

    config_path = Path(".slopconfig.yaml")
    force = getattr(args, "force_init", False)
    adaptive_init = bool(getattr(args, "adaptive_init", False))
    init_preview = bool(getattr(args, "init_preview", False))
    apply_init_suggestions = bool(getattr(args, "apply_init_suggestions", False))
    repo_path = Path(".")
    config_exists = config_path.exists()

    project_type = _detect_project_type(repo_path)

    # Domain detection: --domain flag overrides auto-detection
    manual_domain = getattr(args, "domain", None)
    if manual_domain:
        if manual_domain not in DOMAIN_PROFILES:
            valid = ", ".join(DOMAIN_PROFILES.keys())
            print(f"[!] Unknown domain '{manual_domain}'. Valid: {valid}")
            return 1
        domain_path = manual_domain
        detected_by: list = []
        confidence = 1.0
        print(f"[o] Domain: {domain_path} (manually specified)")
    else:
        domain_path, detected_by, confidence = detect_domain(repo_path)
        if domain_path != "general":
            print(
                f"[o] Domain detected: {domain_path} "
                f"(imports: {', '.join(detected_by)}  confidence={confidence:.0%})"
            )
        else:
            print("[o] Domain: general (no specific imports detected)")

    profile = dict(DOMAIN_PROFILES[domain_path])
    profile["detected_by"] = detected_by  # embed for template header comment
    needs_adaptive = adaptive_init or init_preview or apply_init_suggestions
    signals = collect_init_signals(repo_path) if needs_adaptive else {}
    suggestions = synthesize_init_suggestions(signals) if needs_adaptive else {}

    template = generate_slopconfig_template(project_type, domain_profile=profile)
    if init_preview:
        if config_exists and not force:
            print("[*] Preview mode: existing .slopconfig.yaml will not be modified.")
        else:
            print("[*] Preview mode: .slopconfig.yaml would be generated.")
        if needs_adaptive:
            print()
            print(_render_init_preview(project_type, domain_path, signals, suggestions))
        return 0

    if config_exists and not force and not apply_init_suggestions:
        # v3.7.6 (SLOP-006): idempotent — re-running on initialized project
        # is a no-op success, not a failure. CI scripts can call --init safely.
        print("[*] .slopconfig.yaml already initialized.")
        print("    Run with --force-init to regenerate.")
        if needs_adaptive:
            print()
            print(_render_init_preview(project_type, domain_path, signals, suggestions))
        return 0

    if config_exists and not force and apply_init_suggestions:
        print("[*] Existing .slopconfig.yaml detected. Applying adaptive suggestions only.")
    else:
        config_path.write_text(template, encoding="utf-8")
        print(f"[+] .slopconfig.yaml generated (project_type={project_type}, domain={domain_path})")

        _inject_gitignore_entry(
            Path(".gitignore"),
            entry=".slopconfig.yaml",
            comment="# slop-detector: governance config (contains codebase complexity surface — keep private)",
        )

    if apply_init_suggestions:
        try:
            current_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            print(f"[!] Failed to read .slopconfig.yaml for adaptive merge: {exc}")
            return 1

        merged = _merge_adaptive_init_suggestions(current_data, suggestions)
        _write_init_config(
            config_path,
            merged,
            comment_lines=[
                "# .slopconfig.yaml — ai-slop-detector governance configuration",
                "# Updated by: slop-detector --init --apply-init-suggestions",
                "# Adaptive init suggestions are evidence-backed and opt-in.",
            ],
        )
        print("[+] Adaptive init suggestions merged into .slopconfig.yaml")

    if needs_adaptive:
        print()
        print(_render_init_preview(project_type, domain_path, signals, suggestions))

    print()
    print("[>] Next steps:")
    print("    slop-detector --project .")
    print(f"    # domain profile: {profile.get('description', '')}")
    print()
    print("[!] Security: .slopconfig.yaml is in .gitignore (maps acceptable-complexity surface).")
    print("    To share governance config with your team, remove it from .gitignore.")
    return 0


def _compute_project_id() -> str:
    """Return a stable 12-char hex project ID from the resolved cwd (sha256)."""
    import hashlib

    cwd = str(Path.cwd().resolve())
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


def _check_calibration_hint(args) -> None:
    """At every CALIBRATION_MILESTONE of multi-run files, auto-run calibration and apply if confident.

    v3.5.0 (P1/P2): trigger is now count_files_with_multiple_runs(project_id) — not
    count_total_records(). A first-time scan of N files records N rows but zero
    repeat-file pairs, so total_records % 10 == 0 was a false trigger. Multi-run
    count is the correct proxy for calibration readiness.
    """
    if getattr(args, "no_history", False):
        return
    try:
        import sys as _sys

        from slop_detector.config import Config
        from slop_detector.history import HistoryTracker
        from slop_detector.ml.self_calibrator import CALIBRATION_MILESTONE, SelfCalibrator

        project_id = _compute_project_id()
        tracker = HistoryTracker()
        n = tracker.count_files_with_multiple_runs(project_id=project_id)
        if n < CALIBRATION_MILESTONE or n % CALIBRATION_MILESTONE != 0:
            return

        # Auto-calibrate at milestone
        config = Config(config_path=getattr(args, "config", None))
        current_weights = config.get_weights()
        # P3: use current config weights as domain anchor to constrain grid search
        domain_anchor = {
            k: current_weights.get(k, 0.30) for k in ("ldr", "inflation", "ddc", "purity")
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
                f"\n[*] Auto-calibration ({n} multi-run files): weights updated -> {written}",
                file=_sys.stderr,
            )
            for k in ("ldr", "inflation", "ddc", "purity"):
                old_v = current_weights.get(k, 0.0)
                new_v = result.optimal_weights.get(k, 0.0)
                if abs(old_v - new_v) > 0.001:
                    print(f"    {k}: {old_v:.2f} -> {new_v:.2f}", file=_sys.stderr)
        elif result.status == "no_change":
            print(
                f"\n[*] Calibration milestone ({n} multi-run files): weights already optimal.",
                file=_sys.stderr,
            )
        else:
            print(
                f"\n[*] Calibration milestone ({n} multi-run files): {result.message} "
                f"Run --self-calibrate for details.",
                file=_sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 — hint is informational; never block main flow
        import logging as _logging

        _logging.getLogger(__name__).debug("calibration hint skipped: %s", exc)


def _get_git_context():
    """Capture current git commit (short SHA) and branch. Returns (None, None) if not in a repo."""
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
            for fa in result.file_results:
                tracker.record(
                    fa, git_commit=git_commit, git_branch=git_branch, project_id=project_id
                )
        else:
            tracker.record(
                result, git_commit=git_commit, git_branch=git_branch, project_id=project_id
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
    for h in history:
        ts = h["timestamp"][:19]
        print(
            f"  {ts:<24} {h['deficit_score']:>7.1f} {h['ldr_score']:>6.3f}"
            f" {h['pattern_count']:>8}  {h['grade']}"
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
    for d in trends["daily_trends"]:
        print(
            f"  {d['date']:<12} {d['avg_deficit']:>11.1f} {d['avg_ldr']:>8.3f}"
            f" {d['total_patterns']:>9} {d['files_analyzed']:>6}"
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
        _rich = True
    except ImportError:
        console = None  # type: ignore[assignment]
        _rich = False

    config = Config(config_path=getattr(args, "config", None))
    current_weights = config.get_weights()
    min_events = getattr(args, "min_history", 5)

    calibrator = SelfCalibrator()
    result = calibrator.calibrate(current_weights=current_weights, min_events=min_events)

    # --- Print summary ---
    if _rich and console:
        from rich.panel import Panel
        from rich.text import Text

        status_color = {"ok": "green", "no_change": "yellow", "insufficient_data": "red"}.get(
            result.status, "white"
        )
        header = Text(f"Self-Calibration — {result.status.upper()}", style=f"bold {status_color}")
        console.print(Panel(header, box=box.ROUNDED))

        t = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        t.add_column("Metric", style="cyan")
        t.add_column("Value", justify="right")
        t.add_row("Unique files in history", str(result.unique_files))
        t.add_row("Improvement events (true positives)", str(result.improvement_events))
        t.add_row("FP candidates (flagged, never fixed)", str(result.fp_candidates))
        t.add_row("Confidence gap", f"{result.confidence_gap:.4f}")
        console.print(t)

        wt = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        wt.add_column("Dimension", style="cyan")
        wt.add_column("Current", justify="right")
        wt.add_column("Optimal", justify="right")
        wt.add_column("Delta", justify="right")
        for dim in ("ldr", "inflation", "ddc", "purity"):
            cur = current_weights.get(dim, 0.0)
            opt = result.optimal_weights.get(dim, cur)
            delta = opt - cur
            delta_str = f"{delta:+.2f}" if abs(delta) > 0.001 else "—"
            color = "green" if delta < -0.001 else ("red" if delta > 0.001 else "white")
            wt.add_row(dim, f"{cur:.2f}", f"{opt:.2f}", f"[{color}]{delta_str}[/{color}]")
        console.print(wt)

        if result.status == "ok":
            err_before = result.fn_rate_before + result.fp_rate_before
            err_after = result.fn_rate_after + result.fp_rate_after
            console.print(
                f"\nCombined error: [yellow]{err_before:.4f}[/yellow] -> [green]{err_after:.4f}[/green]"
                f"  (FN {result.fn_rate_before:.4f}->{result.fn_rate_after:.4f},"
                f"  FP {result.fp_rate_before:.4f}->{result.fp_rate_after:.4f})"
            )

        # Per-rule FP rates (v3.4.0): show rules with notable FP behaviour
        high_fp = {
            rid: rate
            for rid, rate in sorted(result.per_rule_fp_rates.items(), key=lambda x: -x[1])
            if rate >= 0.5
        }
        if high_fp:
            rt = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
                title="Per-Rule FP Rates (>= 50%)",
            )
            rt.add_column("Rule ID", style="cyan")
            rt.add_column("FP Rate", justify="right")
            rt.add_column("Signal", justify="right")
            for rid, rate in high_fp.items():
                signal = "[red]HIGH FP[/red]" if rate >= 0.7 else "[yellow]MOD FP[/yellow]"
                rt.add_row(rid, f"{rate:.0%}", signal)
            console.print(rt)
            console.print(
                "[dim]Rules with HIGH FP (>=70%) are candidates for suppression"
                " via .slopconfig.yaml exclude_rules[/dim]"
            )

        if result.warnings:
            for w in result.warnings:
                console.print(f"[yellow][!] {w}[/yellow]")
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
                rid: rate
                for rid, rate in sorted(result.per_rule_fp_rates.items(), key=lambda x: -x[1])
                if rate >= 0.5
            }
            if high_fp_plain:
                print("  per_rule_fp_rates (>=50%):")
                for rid, rate in high_fp_plain.items():
                    print(f"    {rid}: {rate:.0%}")
        for w in result.warnings:
            print(f"  [!] {w}")
        print(f"  {result.message}")

    # --- Apply if requested ---
    apply_path = getattr(args, "apply_calibration", None)
    if apply_path and result.status == "ok":
        written = SelfCalibrator.apply_to_config(result.optimal_weights, config_path=apply_path)
        msg = f"[+] Calibrated weights written to {written}"
        if _rich and console:
            console.print(f"\n[green]{msg}[/green]")
        else:
            print(msg)
    elif apply_path and result.status != "ok":
        msg = "[-] --apply-calibration skipped: calibration did not produce a confident result."
        if _rich and console:
            console.print(f"\n[yellow]{msg}[/yellow]")
        else:
            print(msg)

    return 0 if result.status in ("ok", "no_change") else 1

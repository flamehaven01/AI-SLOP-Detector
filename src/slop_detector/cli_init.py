"""Adaptive init and domain-detection helpers for the CLI."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


def _detect_project_type(path: Path) -> str:
    """Infer project type from root directory structure."""
    if (path / "package.json").exists():
        return "javascript"
    if (path / "go.mod").exists():
        return "go"
    return "python"  # pyproject.toml / setup.py / .py files — default


def detect_domain(project_path: Path) -> Tuple[str, List[str], float]:
    """Scan project imports and return (domain_path, detected_by, confidence)."""
    import re

    from slop_detector.config import DOMAIN_PROFILES

    import_re = re.compile(r"^\s*(?:import\s+([\w]+)|from\s+([\w]+)\s+import)", re.MULTILINE)
    found_imports: set[str] = set()
    try:
        for py_file in project_path.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                for match in import_re.finditer(text):
                    module = (match.group(1) or match.group(2) or "").lower()
                    if module:
                        found_imports.add(module)
            except OSError:
                continue
    except OSError as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("domain detection scan failed: %s", exc)

    scores: Dict[str, List[str]] = {}
    for domain_path, profile in DOMAIN_PROFILES.items():
        if domain_path == "general":
            continue
        hits = [
            trigger for trigger in profile.get("triggers", []) if trigger.lower() in found_imports
        ]
        if hits:
            scores[domain_path] = hits

    if not scores:
        return "general", [], 0.0

    best = max(
        scores,
        key=lambda key: (len(scores[key]), -len(DOMAIN_PROFILES[key].get("triggers", []) or [1])),
    )
    hits = scores[best]
    trigger_count = max(len(DOMAIN_PROFILES[best].get("triggers", [])), 1)
    confidence = round(min(1.0, len(hits) / max(trigger_count * 0.4, 1)), 2)
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
    god_config = profile.get(
        "pattern_config",
        {},
    ).get(
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
                "evidence": {"has_tests": False},
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
        with open(gitignore_path, "a", encoding="utf-8") as handle:
            handle.write(f"\n{comment}\n{entry}\n")
    else:
        with open(gitignore_path, "w", encoding="utf-8") as handle:
            handle.write(f"{comment}\n{entry}\n")
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

    manual_domain = getattr(args, "domain", None)
    if manual_domain:
        if manual_domain not in DOMAIN_PROFILES:
            valid = ", ".join(DOMAIN_PROFILES.keys())
            print(f"[!] Unknown domain '{manual_domain}'. Valid: {valid}")
            return 1
        domain_path = manual_domain
        detected_by: List[str] = []
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
    profile["detected_by"] = detected_by
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

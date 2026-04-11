"""Configuration management for SLOP detector."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class Config:
    """Configuration manager with YAML support and sensible defaults."""

    DEFAULT_CONFIG = {
        "version": "2.0",
        "thresholds": {
            "ldr": {
                "excellent": 0.85,
                "good": 0.75,
                "acceptable": 0.60,
                "warning": 0.45,
                "critical": 0.30,
            },
            "inflation": {"pass": 0.50, "warning": 1.0, "fail": 2.0},
            "ddc": {
                "excellent": 0.90,
                "good": 0.70,
                "acceptable": 0.50,
                "suspicious": 0.30,
            },
        },
        "weights": {"ldr": 0.40, "inflation": 0.30, "ddc": 0.30},
        "ignore": [
            "**/__init__.py",
            "tests/**",
            "**/*_test.py",
            "**/test_*.py",
            "**/*.pyi",
            "**/.venv/**",
            ".venv/**",
            "**/venv/**",
            "venv/**",
            "**/site-packages/**",
            "site-packages/**",
            "**/node_modules/**",
            "node_modules/**",
            "**/__pycache__/**",
        ],
        "exceptions": {
            "abc_interface": {"enabled": True, "penalty_reduction": 0.5},
            "config_files": {
                "enabled": True,
                "patterns": [
                    "**/settings.py",
                    "**/config.py",
                    "**/constants.py",
                    "**/*_config.py",
                ],
            },
            "type_stubs": {"enabled": True, "patterns": ["**/*.pyi"]},
        },
        "advanced": {
            "use_radon": True,
            "weighted_analysis": True,
            "min_file_size": 10,
            "max_file_size": 10000,
        },
        "patterns": {
            "enabled": True,
            "disabled": [],  # List of pattern IDs to disable
            "severity_threshold": "low",  # minimum severity to report
            "god_function": {
                # Default thresholds (applied to all functions not matched by domain_overrides)
                "complexity_threshold": 10,
                "lines_threshold": 50,
                # Per-function-name overrides for domain-complex safety systems.
                # Each entry: {function_pattern: str, complexity_threshold: int, lines_threshold: int}
                # function_pattern supports fnmatch wildcards (e.g. "evaluate", "validate_*")
                "domain_overrides": [],
            },
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        """Initialize config from file or use defaults."""
        self.config: Dict[str, Any] = self.DEFAULT_CONFIG.copy()

        # Try loading from environment variable
        env_config = os.getenv("SLOP_CONFIG")
        if env_config and Path(env_config).exists():
            config_path = env_config

        # Load custom config
        if config_path and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                custom_config = yaml.safe_load(f)
                self._merge_config(custom_config)

    def _merge_config(self, custom: Dict[str, Any]) -> None:
        """Deep merge custom config into defaults."""
        self._deep_update(self.config, custom)

    def _deep_update(self, base: Dict[str, Any], update: Dict[str, Any]) -> None:
        """Recursively update nested dictionaries."""
        for key, value in update.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def get(self, path: str, default: Any = None) -> Any:
        """Get config value by dot-separated path."""
        keys = path.split(".")
        value: Any = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    def get_ldr_thresholds(self) -> Dict[str, float]:
        """Get LDR threshold mapping."""
        thresholds = self.get("thresholds.ldr", {})
        return {
            "S++": thresholds.get("excellent", 0.85),
            "S": thresholds.get("good", 0.75),
            "A": thresholds.get("acceptable", 0.60),
            "B": thresholds.get("warning", 0.45),
            "C": thresholds.get("critical", 0.30),
            "D": 0.15,
            "F": 0.00,
        }

    def get_ignore_patterns(self) -> List[str]:
        """Get file patterns to ignore."""
        return self.get("ignore", [])

    def is_abc_exception_enabled(self) -> bool:
        """Check if ABC interface exception is enabled."""
        return self.get("exceptions.abc_interface.enabled", True)

    def is_config_file_exception_enabled(self) -> bool:
        """Check if config file exception is enabled."""
        return self.get("exceptions.config_files.enabled", True)

    def get_weights(self) -> Dict[str, float]:
        """Get metric weights for slop score calculation."""
        return self.get("weights", {"ldr": 0.4, "inflation": 0.3, "ddc": 0.3})

    def use_radon(self) -> bool:
        """Check if radon should be used for complexity."""
        return self.get("advanced.use_radon", True)

    def use_weighted_analysis(self) -> bool:
        """Check if weighted project analysis is enabled."""
        return self.get("advanced.weighted_analysis", True)

    def get_god_function_config(self) -> Dict[str, Any]:
        """Get god_function pattern configuration including domain_overrides."""
        return self.get(
            "patterns.god_function",
            {
                "complexity_threshold": 10,
                "lines_threshold": 50,
                "domain_overrides": [],
            },
        )

    def get_nested_complexity_config(self) -> Dict[str, Any]:
        """Get nested_complexity pattern configuration including domain_overrides."""
        return self.get(
            "patterns.nested_complexity",
            {
                "depth_threshold": 4,
                "cc_threshold": 5,
                "domain_overrides": [],
            },
        )


def generate_slopconfig_template(project_type: str = "python") -> str:
    """
    Return a project-type-aware .slopconfig.yaml template string.

    SECURITY NOTE: This file maps your acceptable-complexity surface (domain_overrides).
    It is added to .gitignore by default when generated via --init. To share governance
    config with your team, explicitly remove .slopconfig.yaml from .gitignore.
    """
    js_ignore_extra = (
        "\n  - node_modules/**\n  - dist/**\n  - build/**" if project_type == "javascript" else ""
    )
    go_ignore_extra = "\n  - vendor/**" if project_type == "go" else ""

    return f"""\
# .slopconfig.yaml — ai-slop-detector governance configuration
# Generated by: slop-detector --init
# Project type: {project_type}
#
# SECURITY: This file contains domain_overrides (your acceptable-complexity surface).
# It is in .gitignore by default. Remove that entry to share with your team.
# See: https://github.com/flamehaven01/AI-SLOP-Detector#security-considerations

version: "2.0"

# ── Metric weights ──────────────────────────────────────────────────────────
# Sum must equal 1.0. Use --self-calibrate after 20+ runs to optimize.
weights:
  ldr:       0.40  # Logic Density Ratio (code-to-total lines)
  inflation:  0.30  # Inflation-to-Code Ratio (jargon density)
  ddc:        0.30  # Deep Dependency Check (import usage ratio)
  purity:     0.10  # Critical-pattern penalty (auto-calibrated v3.2.0+)

# ── Ignore patterns ─────────────────────────────────────────────────────────
ignore:
  - "**/__init__.py"
  - "tests/**"
  - "**/*_test.py"
  - "**/test_*.py"
  - "**/*.pyi"
  - "**/.venv/**"
  - ".venv/**"
  - "**/venv/**"
  - "venv/**"
  - "**/site-packages/**"{js_ignore_extra}{go_ignore_extra}

# ── Pattern detection ────────────────────────────────────────────────────────
patterns:
  enabled: true
  severity_threshold: low  # minimum severity: low | medium | high | critical

  god_function:
    complexity_threshold: 10   # cyclomatic complexity limit
    lines_threshold: 50        # physical line limit
    # domain_overrides: add per-function exemptions here
    # Example:
    # domain_overrides:
    #   - function_pattern: "validate_*"
    #     complexity_threshold: 20
    #     lines_threshold: 100
    #     reason: "Validation functions are inherently complex"
    domain_overrides: []

  nested_complexity:
    depth_threshold: 4
    cc_threshold: 5
    domain_overrides: []

# ── Advanced ─────────────────────────────────────────────────────────────────
advanced:
  use_radon: true
  min_file_size: 10
"""

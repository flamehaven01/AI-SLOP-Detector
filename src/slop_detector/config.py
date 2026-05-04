"""Configuration management for SLOP detector."""

import logging as _logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel as _BaseModel
from pydantic import Field as _Field
from pydantic import ValidationError as _ValidationError

_logger = _logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime schema guards for .slopconfig.yaml user input.
# Catches bad values (wrong types, out-of-range floats) at load time so they
# never reach the GQG formula or pattern matchers.
# ---------------------------------------------------------------------------


class _WeightsSchema(_BaseModel):
    model_config = {"extra": "allow"}
    ldr: float = _Field(default=0.40, ge=0.0, le=1.0)
    inflation: float = _Field(default=0.30, ge=0.0, le=1.0)
    ddc: float = _Field(default=0.20, ge=0.0, le=1.0)
    purity: float = _Field(default=0.10, ge=0.0, le=1.0)


class _DomainOverrideSchema(_BaseModel):
    model_config = {"extra": "allow"}
    function_pattern: str
    complexity_threshold: int = _Field(ge=1)
    lines_threshold: int = _Field(ge=1)


class _GodFunctionSchema(_BaseModel):
    model_config = {"extra": "allow"}
    complexity_threshold: int = _Field(default=10, ge=1)
    lines_threshold: int = _Field(default=50, ge=1)
    domain_overrides: List[_DomainOverrideSchema] = _Field(default_factory=list)


def _validate_yaml_config(raw: Dict[str, Any]) -> None:
    """Validate critical sections of a raw YAML config dict before merging.

    Raises ValueError with a user-readable message if any section is invalid.
    Unknown top-level keys are silently ignored (forward compatibility).
    """
    errors: List[str] = []

    if "weights" in raw and isinstance(raw["weights"], dict):
        try:
            _WeightsSchema.model_validate(raw["weights"])
        except _ValidationError as exc:
            errors.append(f"weights: {exc}")

    patterns = raw.get("patterns") or {}
    if isinstance(patterns, dict) and "god_function" in patterns:
        try:
            _GodFunctionSchema.model_validate(patterns["god_function"])
        except _ValidationError as exc:
            errors.append(f"patterns.god_function: {exc}")

    if errors:
        raise ValueError(
            ".slopconfig.yaml validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )


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
        "weights": {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10},
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
        """Deep merge custom config into defaults (validated before merge)."""
        _validate_yaml_config(custom)
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
        return self.get("weights", {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10})

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


# ---------------------------------------------------------------------------
# Domain profiles: NNSL-inspired trigger+capability_vector mapping.
# Each profile defines:
#   parent           — top-level domain category
#   domain_path      — slash-delimited hierarchy (parent/sub)
#   triggers         — import names used for auto-detection during --init
#   capability_vector — metric weights (ldr, inflation, ddc, purity)
#   pattern_config   — god_function / nested_complexity thresholds
#   ignore_extra     — additional ignore patterns beyond defaults
# ---------------------------------------------------------------------------
DOMAIN_PROFILES: Dict[str, Any] = {
    "general": {
        "parent": "general",
        "domain_path": "general",
        "description": "General-purpose project (default)",
        "triggers": [],
        "capability_vector": {"ldr": 0.15, "inflation": 0.1285, "ddc": 0.6215, "purity": 0.1},
        "pattern_config": {
            "god_function": {"complexity_threshold": 10, "lines_threshold": 50},
            "nested_complexity": {"depth_threshold": 4, "cc_threshold": 5},
        },
        "ignore_extra": [],
    },
    "scientific/ml": {
        "parent": "scientific",
        "domain_path": "scientific/ml",
        "description": "Machine learning, deep learning, data science",
        "triggers": [
            "numpy",
            "scipy",
            "torch",
            "tensorflow",
            "keras",
            "sklearn",
            "jax",
            "xgboost",
            "lightgbm",
            "matplotlib",
            "seaborn",
        ],
        "capability_vector": {"ldr": 0.50, "inflation": 0.05, "ddc": 0.40, "purity": 0.05},
        "pattern_config": {
            "god_function": {"complexity_threshold": 15, "lines_threshold": 100},
            "nested_complexity": {"depth_threshold": 6, "cc_threshold": 20},
        },
        "ignore_extra": ["data/**", "datasets/**", "checkpoints/**", "**/*.ipynb"],
    },
    "scientific/numerical": {
        "parent": "scientific",
        "domain_path": "scientific/numerical",
        "description": "Numerical computing, simulations, physical modelling",
        "triggers": ["sympy", "cupy", "numba", "cython", "mpmath", "astropy", "fenics"],
        "capability_vector": {"ldr": 0.50, "inflation": 0.05, "ddc": 0.40, "purity": 0.05},
        "pattern_config": {
            "god_function": {"complexity_threshold": 15, "lines_threshold": 120},
            "nested_complexity": {"depth_threshold": 6, "cc_threshold": 25},
        },
        "ignore_extra": ["output/**", "results/**"],
    },
    "web/api": {
        "parent": "web",
        "domain_path": "web/api",
        "description": "Web applications and REST APIs",
        "triggers": [
            "fastapi",
            "flask",
            "django",
            "starlette",
            "aiohttp",
            "tornado",
            "sanic",
            "falcon",
        ],
        "capability_vector": {"ldr": 0.35, "inflation": 0.25, "ddc": 0.30, "purity": 0.10},
        "pattern_config": {
            "god_function": {"complexity_threshold": 10, "lines_threshold": 60},
            "nested_complexity": {"depth_threshold": 4, "cc_threshold": 8},
        },
        "ignore_extra": ["static/**", "migrations/**", "node_modules/**", "dist/**"],
    },
    "library/sdk": {
        "parent": "library",
        "domain_path": "library/sdk",
        "description": "Libraries, SDKs, and reusable packages (Protocol/ABC heavy)",
        "triggers": [],  # detected via Protocol/ABC prevalence, not imports
        "capability_vector": {"ldr": 0.30, "inflation": 0.20, "ddc": 0.35, "purity": 0.15},
        "pattern_config": {
            "god_function": {"complexity_threshold": 12, "lines_threshold": 70},
            "nested_complexity": {"depth_threshold": 5, "cc_threshold": 10},
        },
        "ignore_extra": ["docs/**", "examples/**"],
    },
    "cli/tool": {
        "parent": "cli",
        "domain_path": "cli/tool",
        "description": "Command-line tools and scripts",
        "triggers": ["argparse", "click", "typer", "docopt", "fire", "plumbum"],
        "capability_vector": {"ldr": 0.35, "inflation": 0.30, "ddc": 0.25, "purity": 0.10},
        "pattern_config": {
            "god_function": {"complexity_threshold": 12, "lines_threshold": 70},
            "nested_complexity": {"depth_threshold": 5, "cc_threshold": 15},
        },
        "ignore_extra": ["dist/**", "build/**"],
    },
    "bio": {
        "parent": "bio",
        "domain_path": "bio",
        "description": "Bioinformatics, genomics, proteomics",
        "triggers": [
            "Bio",
            "biopython",
            "pysam",
            "pybedtools",
            "anndata",
            "scanpy",
            "mne",
            "pyvcf",
        ],
        "capability_vector": {"ldr": 0.55, "inflation": 0.05, "ddc": 0.35, "purity": 0.05},
        "pattern_config": {
            "god_function": {"complexity_threshold": 15, "lines_threshold": 100},
            "nested_complexity": {"depth_threshold": 6, "cc_threshold": 20},
        },
        "ignore_extra": ["data/**", "genomes/**"],
    },
    "finance": {
        "parent": "finance",
        "domain_path": "finance",
        "description": "Financial applications and quantitative analysis",
        "triggers": ["yfinance", "quantlib", "zipline", "backtrader", "alpaca", "ccxt", "ta"],
        "capability_vector": {"ldr": 0.35, "inflation": 0.15, "ddc": 0.40, "purity": 0.10},
        "pattern_config": {
            "god_function": {"complexity_threshold": 12, "lines_threshold": 80},
            "nested_complexity": {"depth_threshold": 5, "cc_threshold": 12},
        },
        "ignore_extra": ["data/**", "backtests/**"],
    },
}


def generate_slopconfig_template(
    project_type: str = "python",
    domain_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Return a domain-aware .slopconfig.yaml template string.

    SECURITY NOTE: This file maps your acceptable-complexity surface (domain_overrides).
    It is added to .gitignore by default when generated via --init. To share governance
    config with your team, explicitly remove .slopconfig.yaml from .gitignore.
    """
    profile = domain_profile or DOMAIN_PROFILES["general"]
    domain_path = profile.get("domain_path", "general")
    description = profile.get("description", "")
    detected_by = profile.get("detected_by", [])  # injected at call-site
    cv = profile.get("capability_vector", DOMAIN_PROFILES["general"]["capability_vector"])
    pc = profile.get("pattern_config", DOMAIN_PROFILES["general"]["pattern_config"])
    gf = pc.get("god_function", {"complexity_threshold": 10, "lines_threshold": 50})
    nc = pc.get("nested_complexity", {"depth_threshold": 4, "cc_threshold": 5})

    detected_line = f"# Detected by imports: {', '.join(detected_by)}\n" if detected_by else ""

    ignore_extra_lines = "".join(f'\n  - "{p}"' for p in profile.get("ignore_extra", []))
    js_ignore_extra = (
        "\n  - node_modules/**\n  - dist/**\n  - build/**" if project_type == "javascript" else ""
    )
    go_ignore_extra = "\n  - vendor/**" if project_type == "go" else ""

    return f"""\
# .slopconfig.yaml — ai-slop-detector governance configuration
# Generated by: slop-detector --init
# Project type: {project_type}
# Domain:       {domain_path}  ({description})
{detected_line}#
# SECURITY: This file contains domain_overrides (your acceptable-complexity surface).
# It is in .gitignore by default. Remove that entry to share with your team.
# See: https://github.com/flamehaven01/AI-SLOP-Detector#security-considerations

version: "2.0"

# ── Metric weights ──────────────────────────────────────────────────────────
# Domain: {domain_path} — tuned by slop-detector --init.
# Sum must equal 1.0. Use --self-calibrate after 20+ runs to refine.
weights:
  ldr:       {cv['ldr']:.2f}  # Logic Density Ratio
  inflation: {cv['inflation']:.2f}  # Inflation-to-Code Ratio (jargon density)
  ddc:       {cv['ddc']:.2f}  # Deep Dependency Check (import usage ratio)
  purity:    {cv['purity']:.2f}  # Critical-pattern penalty

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
  - "**/site-packages/**"{js_ignore_extra}{go_ignore_extra}{ignore_extra_lines}

# ── Pattern detection ────────────────────────────────────────────────────────
patterns:
  enabled: true
  severity_threshold: low  # minimum severity: low | medium | high | critical

  god_function:
    complexity_threshold: {gf['complexity_threshold']}
    lines_threshold: {gf['lines_threshold']}
    # domain_overrides: add per-function exemptions here
    # Example:
    # domain_overrides:
    #   - function_pattern: "validate_*"
    #     complexity_threshold: 20
    #     lines_threshold: 100
    #     reason: "Validation functions are inherently complex"
    domain_overrides: []

  nested_complexity:
    depth_threshold: {nc['depth_threshold']}
    cc_threshold: {nc['cc_threshold']}
    domain_overrides: []

# ── Advanced ─────────────────────────────────────────────────────────────────
advanced:
  use_radon: true
  min_file_size: 10
"""

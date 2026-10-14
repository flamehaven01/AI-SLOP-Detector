"""Configuration management for SLOP detector."""

import logging as _logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

import yaml

_logger = _logging.getLogger(__name__)

DEFAULT_TEST_IGNORE_PATTERNS = frozenset({"tests/**", "**/*_test.py", "**/test_*.py"})

# ---------------------------------------------------------------------------
# Runtime schema guards for .slopconfig.yaml user input.
# Pydantic v2 is a base dependency. Without it the package still imports and
# runs on defaults, but a named config file is refused rather than unchecked.
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """A config file that cannot be applied as written (missing, unreadable, invalid)."""


# Every key the code consumes is typed here. Strict: "10" is not 10 and true is
# not 1. Unknown keys are allowed (legacy keys warn below). Only validation:
# the raw values, not these models, are merged, so no schema default is added.
try:
    from pydantic import BaseModel as _BaseModel
    from pydantic import ConfigDict as _ConfigDict
    from pydantic import Field as _Field
    from pydantic import ValidationError as _ValidationError

    class _Section(_BaseModel):
        model_config = _ConfigDict(strict=True, extra="allow")

    _Ratio = Optional[float]

    class _LdrThresholds(_Section):
        excellent: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        good: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        acceptable: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        warning: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        critical: _Ratio = _Field(default=None, ge=0.0, le=1.0)

    class _Thresholds(_Section):
        ldr: Optional[_LdrThresholds] = None

    class _Weights(_Section):
        ldr: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        inflation: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        ddc: _Ratio = _Field(default=None, ge=0.0, le=1.0)
        purity: _Ratio = _Field(default=None, ge=0.0, le=1.0)

    class _AbcInterface(_Section):
        enabled: Optional[bool] = None
        penalty_reduction: _Ratio = _Field(default=None, ge=0.0, le=1.0)

    class _ConfigFiles(_Section):
        enabled: Optional[bool] = None
        patterns: Optional[List[str]] = None

    class _Exceptions(_Section):
        abc_interface: Optional[_AbcInterface] = None
        config_files: Optional[_ConfigFiles] = None

    class _HotspotWeights(_Section):
        deficit: Optional[float] = _Field(default=None, ge=0.0)
        churn: Optional[float] = _Field(default=None, ge=0.0)
        coverage_gap: Optional[float] = _Field(default=None, ge=0.0)

    class _Advanced(_Section):
        use_radon: Optional[bool] = None
        weighted_analysis: Optional[bool] = None
        exact_topology_ceiling: Optional[int] = None
        topology_mode_above_ceiling: Optional[Literal["deterministic_approximate", "exact"]] = None
        analysis_cache_enabled: Optional[bool] = None
        analysis_cache_db: Optional[str] = None
        patterns_only: Optional[bool] = None
        churn_commit_window: Optional[int] = None
        coverage_data_file: Optional[str] = None
        hotspot_limit: Optional[int] = None
        hotspot_weights: Optional[_HotspotWeights] = None

    class _Layer(_Section):
        name: str
        patterns: List[str]
        can_import: Optional[List[str]] = None
        cannot_import: Optional[List[str]] = None

    class _Architecture(_Section):
        enabled: Optional[bool] = None
        preset: Optional[str] = None
        layers: Optional[List[_Layer]] = None

    class _GodOverride(_Section):
        function_pattern: str
        complexity_threshold: int = _Field(ge=1)
        lines_threshold: int = _Field(ge=1)

    class _GodFunction(_Section):
        complexity_threshold: Optional[int] = _Field(default=None, ge=1)
        lines_threshold: Optional[int] = _Field(default=None, ge=1)
        domain_overrides: Optional[List[_GodOverride]] = None

    class _NestedOverride(_Section):
        function_pattern: str
        depth_threshold: Optional[int] = _Field(default=None, ge=1)
        cc_threshold: Optional[int] = _Field(default=None, ge=1)

    class _NestedComplexity(_Section):
        depth_threshold: Optional[int] = _Field(default=None, ge=1)
        cc_threshold: Optional[int] = _Field(default=None, ge=1)
        domain_overrides: Optional[List[_NestedOverride]] = None

    class _Patterns(_Section):
        disabled: Optional[List[str]] = None
        god_function: Optional[_GodFunction] = None
        nested_complexity: Optional[_NestedComplexity] = None

    class _ConfigFile(_Section):
        thresholds: Optional[_Thresholds] = None
        weights: Optional[_Weights] = None
        ignore: Optional[List[str]] = None
        exceptions: Optional[_Exceptions] = None
        advanced: Optional[_Advanced] = None
        architecture: Optional[_Architecture] = None
        phantom_import_allowlist: Optional[List[str]] = None
        patterns: Optional[_Patterns] = None

    _PYDANTIC_AVAILABLE = True

except ImportError:
    _PYDANTIC_AVAILABLE = False


def _validate_yaml_config(raw: Any, source: str) -> None:
    """Reject a config whose consumed keys have the wrong type, range or shape.

    The message names the file, each key path and the expected type; it does
    not repeat the values (a config may hold paths or other private data).
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: the top level must be a mapping of settings")
    if not _PYDANTIC_AVAILABLE:
        raise ConfigError(f"{source}: cannot be validated (pydantic is not installed)")
    try:
        _ConfigFile.model_validate(raw)
    except _ValidationError as exc:
        problems = [
            f"  - {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        raise ConfigError(f"{source}: invalid configuration\n" + "\n".join(problems)) from None


# Keys that earlier defaults, --init templates, the example config or the docs
# carried, but that no code ever read. Accepted, warned about, never applied.
_IGNORED_KEYS: Dict[Tuple[str, str], str] = {
    ("patterns", "severity_threshold"): (
        "every severity is reported; to drop a pattern use patterns.disabled"
    ),
    (
        "patterns",
        "enabled",
    ): "pattern detection is always on; to drop a pattern use patterns.disabled",
    ("thresholds", "inflation"): "only thresholds.ldr is configurable",
    ("thresholds", "ddc"): "only thresholds.ldr is configurable",
    ("thresholds", "bcr"): "only thresholds.ldr is configurable",
    ("weights", "bcr"): "the inflation weight is weights.inflation",
    ("advanced", "min_file_size"): "no file is skipped by size; use ignore patterns",
    ("advanced", "max_file_size"): "no file is skipped by size; use ignore patterns",
    ("advanced", "ml_detection"): "ML scoring is enabled by a model artifact, not by this key",
}


def _load_yaml(path: Path) -> Any:
    """Read one config file; a missing, unreadable or non-YAML file is a ConfigError."""
    if not path.is_file():
        raise ConfigError(f"{path}: config file not found")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: config file cannot be read ({type(exc).__name__})") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or "syntax error"
        raise ConfigError(f"{path}: not valid YAML{where}: {problem}") from None


def _warn_ignored_keys(raw: Dict[str, Any]) -> None:
    """Warn about keys that are accepted but have no effect."""
    for (section, key), hint in _IGNORED_KEYS.items():
        block = raw.get(section)
        if isinstance(block, dict) and key in block:
            _logger.warning(
                "%s.%s has no effect and is ignored: %s. Remove it from the config.",
                section,
                key,
                hint,
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
            "**/build/**",
            "build/**",
            "**/dist/**",
            "dist/**",
            "**/.tox/**",
            ".tox/**",
            "**/.next/**",
            ".next/**",
            "**/htmlcov/**",
            "htmlcov/**",
            "**/.claude/**",
            ".claude/**",
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
            "exact_topology_ceiling": 300,
            "topology_mode_above_ceiling": "deterministic_approximate",
            "analysis_cache_enabled": True,
            "analysis_cache_db": "",
            "patterns_only": False,
            "churn_commit_window": 200,
            "coverage_data_file": ".coverage",
            "hotspot_limit": 10,
            "hotspot_weights": {"deficit": 0.50, "churn": 0.30, "coverage_gap": 0.20},
        },
        "architecture": {
            "enabled": False,
            "preset": "none",
            "layers": [],
        },
        "phantom_import_allowlist": [],
        "patterns": {
            "disabled": [],  # List of pattern IDs to disable
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
        # Runtime CLI overrides must not mutate nested default lists/dicts shared
        # by future detector instances in the same process.
        self.config: Dict[str, Any] = deepcopy(self.DEFAULT_CONFIG)

        # SLOP_CONFIG wins over config_path. A named file that cannot be used
        # stops here: running on defaults would not be the requested config.
        env_config = os.getenv("SLOP_CONFIG")
        if env_config:
            if not Path(env_config).is_file():
                raise ConfigError(f"SLOP_CONFIG={env_config}: config file not found")
            config_path = env_config
        if config_path:
            self._merge_config(_load_yaml(Path(config_path)), str(config_path))

    def _merge_config(self, custom: Any, source: str = "config") -> None:
        """Validate the raw config, then deep-merge it as written into the defaults."""
        if custom is None:  # an empty file sets nothing
            return
        _validate_yaml_config(custom, source)
        _warn_ignored_keys(custom)
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

    def include_default_tests(self) -> None:
        """Remove the built-in test ignores, from the defaults or from a config.

        `--include-tests` is a per-run request and wins over the built-in test
        patterns a config repeats (every --init template does). Other test
        patterns a config adds (e.g. "backend/tests/**") are kept.
        """
        self.config["ignore"] = [
            pattern
            for pattern in self.get_ignore_patterns()
            if pattern not in DEFAULT_TEST_IGNORE_PATTERNS
        ]

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

    def get_exact_topology_ceiling(self) -> int:
        """Maximum file count allowed for exact structural topology."""
        value = self.get("advanced.exact_topology_ceiling", 300)
        try:
            return max(2, int(value))
        except (TypeError, ValueError):
            return 300

    def get_topology_mode_above_ceiling(self) -> str:
        """How to compute topology after the exact ceiling is exceeded."""
        value = str(self.get("advanced.topology_mode_above_ceiling", "deterministic_approximate"))
        return (
            value
            if value in {"deterministic_approximate", "exact"}
            else "deterministic_approximate"
        )

    def patterns_only(self) -> bool:
        """Score pattern findings only: LDR, inflation and DDC are reported but not scored."""
        return bool(self.get("advanced.patterns_only", False))

    def use_analysis_cache(self) -> bool:
        """Check if repeated-run file analysis cache is enabled."""
        return bool(self.get("advanced.analysis_cache_enabled", True))

    def get_analysis_cache_db(self) -> str:
        """Get configured SQLite path for the file analysis cache."""
        return str(self.get("advanced.analysis_cache_db", "") or "")

    def get_churn_commit_window(self) -> int:
        """Get the recent commit window used for churn-based prioritization."""
        value = self.get("advanced.churn_commit_window", 200)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 200

    def get_coverage_data_file(self) -> str:
        """Get the relative coverage data filename used for hotspot prioritization."""
        value = str(self.get("advanced.coverage_data_file", ".coverage") or ".coverage").strip()
        return value or ".coverage"

    def get_hotspot_limit(self) -> int:
        """Get the number of prioritized hotspots to retain."""
        value = self.get("advanced.hotspot_limit", 10)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 10

    def get_hotspot_weights(self) -> Dict[str, float]:
        """Get normalized weights for project hotspot prioritization."""
        raw = self.get(
            "advanced.hotspot_weights",
            {"deficit": 0.50, "churn": 0.30, "coverage_gap": 0.20},
        )
        if not isinstance(raw, dict):
            return {"deficit": 0.50, "churn": 0.30, "coverage_gap": 0.20}
        try:
            weights = {
                "deficit": max(0.0, float(raw.get("deficit", 0.50) or 0.0)),
                "churn": max(0.0, float(raw.get("churn", 0.30) or 0.0)),
                "coverage_gap": max(0.0, float(raw.get("coverage_gap", 0.20) or 0.0)),
            }
        except (TypeError, ValueError):
            return {"deficit": 0.50, "churn": 0.30, "coverage_gap": 0.20}
        total = sum(weights.values())
        if total <= 0:
            return {"deficit": 0.50, "churn": 0.30, "coverage_gap": 0.20}
        return {key: value / total for key, value in weights.items()}

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

    def get_phantom_import_allowlist(self) -> List[str]:
        """Get list of module names to skip in phantom import detection."""
        val = self.get("phantom_import_allowlist", [])
        return val if isinstance(val, list) else []

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

    def get_architecture_config(self) -> Dict[str, Any]:
        """Get architecture boundary analysis configuration."""
        value = self.get(
            "architecture",
            {
                "enabled": False,
                "preset": "none",
                "layers": [],
            },
        )
        return (
            value if isinstance(value, dict) else {"enabled": False, "preset": "none", "layers": []}
        )


# ---------------------------------------------------------------------------
# Domain profiles: import triggers -> pattern thresholds and ignore extras.
# Profiles do not carry metric weights: every generated config uses the
# default weights (Config.DEFAULT_CONFIG), since no profile weight vector has
# a measured derivation and weights move every file's band.
# Each profile defines:
#   parent           — top-level domain category
#   domain_path      — slash-delimited hierarchy (parent/sub)
#   triggers         — import names used for auto-detection during --init;
#                      generic stacks (numpy, scipy, matplotlib, argparse)
#                      appear in most repositories and are not triggers
#   pattern_config   — god_function / nested_complexity thresholds
#   ignore_extra     — additional ignore patterns beyond defaults
# ---------------------------------------------------------------------------
DOMAIN_PROFILES: Dict[str, Any] = {
    "general": {
        "parent": "general",
        "domain_path": "general",
        "description": "General-purpose project (default)",
        "triggers": [],
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
            "torch",
            "tensorflow",
            "keras",
            "sklearn",
            "jax",
            "xgboost",
            "lightgbm",
        ],
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
        "triggers": ["click", "typer", "docopt", "fire", "plumbum"],
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
    cv = cast(Dict[str, float], Config.DEFAULT_CONFIG["weights"])
    pc = profile.get("pattern_config", DOMAIN_PROFILES["general"]["pattern_config"])
    gf = pc.get("god_function", {"complexity_threshold": 10, "lines_threshold": 50})
    nc = pc.get("nested_complexity", {"depth_threshold": 4, "cc_threshold": 5})

    detected_line = f"# Detected by imports: {', '.join(detected_by)}\n" if detected_by else ""

    ignore_extra_lines = "".join(f'\n  - "{p}"' for p in profile.get("ignore_extra", []))
    js_ignore_extra = (
        "\n  - node_modules/**\n  - dist/**\n  - build/**\n  - .next/**"
        if project_type == "javascript"
        else ""
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
# Default weights for every domain (the profile changes pattern thresholds
# only). Weights are normalized by their sum. --self-calibrate prints an advisory
# report from your local history; it never writes these values.
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
"""

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
            ".venv/**",
            "venv/**",
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
        value = self.config
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

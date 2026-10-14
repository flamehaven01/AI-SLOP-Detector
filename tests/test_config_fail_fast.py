"""A config that cannot be applied as written stops the run before analysis.

Only weights and patterns.god_function were checked, a missing pydantic
skipped every check, and a missing --config / SLOP_CONFIG file silently ran
with defaults. A wrong-typed value (thresholds.ldr.good: "abc") then failed
every file at analysis time. Every consumed key is now validated strictly
(no "10" -> 10, no true -> 1) before the raw values are merged.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import slop_detector.config as config_module
from slop_detector.cli import main
from slop_detector.config import DOMAIN_PROFILES, Config, ConfigError, generate_slopconfig_template
from slop_detector.core import SlopDetector

REPO = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".slopconfig.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "text, key",
    [
        ('thresholds:\n  ldr:\n    good: "SECRET-VALUE"\n', "thresholds.ldr.good"),
        ('patterns:\n  god_function:\n    complexity_threshold: "10"\n', "complexity_threshold"),
        ("advanced:\n  hotspot_limit: true\n", "advanced.hotspot_limit"),
        ("advanced:\n  topology_mode_above_ceiling: SECRET-MODE\n", "topology_mode_above_ceiling"),
        ("ignore: 42\n", "ignore"),
        ("ignore:\n  - 5\n", "ignore.0"),
        ("patterns: 5\n", "patterns"),
        ("weights:\n  ldr: 2.0\n", "weights.ldr"),
        ("exceptions:\n  abc_interface:\n    enabled: 1\n", "exceptions.abc_interface.enabled"),
        ("phantom_import_allowlist: numpy\n", "phantom_import_allowlist"),
        ("architecture:\n  layers:\n    - name: 3\n", "architecture.layers.0.name"),
        (
            "patterns:\n  nested_complexity:\n    domain_overrides:\n      - cc_threshold: 3\n",
            "function_pattern",
        ),
        ("- a\n- b\n", "mapping"),
    ],
)
def test_invalid_value_is_rejected_with_its_key_path(tmp_path, text, key):
    path = _write(tmp_path, text)
    with pytest.raises(ConfigError) as err:
        Config(str(path))
    message = str(err.value)
    assert str(path) in message and key in message
    assert "SECRET" not in message  # values are not echoed


def test_missing_explicit_config_fails(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        Config(str(tmp_path / "missing.yaml"))


def test_missing_env_config_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(ConfigError, match="SLOP_CONFIG"):
        Config()


def test_env_config_still_wins_over_explicit_path(tmp_path, monkeypatch):
    """Preservation: the existing SLOP_CONFIG precedence is unchanged."""
    env = tmp_path / "env.yaml"
    env.write_text("weights:\n  ldr: 0.9\n", encoding="utf-8")
    explicit = _write(tmp_path, "weights:\n  ldr: 0.1\n")
    monkeypatch.setenv("SLOP_CONFIG", str(env))
    assert Config(str(explicit)).get_weights()["ldr"] == 0.9


def test_unvalidatable_config_fails_instead_of_skipping(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "_PYDANTIC_AVAILABLE", False)
    with pytest.raises(ConfigError, match="cannot be validated"):
        Config(str(_write(tmp_path, "weights:\n  ldr: 0.5\n")))


def test_empty_config_file_means_defaults(tmp_path):
    assert Config(str(_write(tmp_path, ""))).config == Config().config


def test_partial_and_nested_values_merge_as_written(tmp_path):
    path = _write(
        tmp_path,
        "weights:\n  ldr: 0.5\n"
        "patterns:\n  god_function:\n    domain_overrides:\n"
        "      - {function_pattern: 'z_*', complexity_threshold: 30, lines_threshold: 90,"
        " reason: keep}\n"
        "      - {function_pattern: 'a_*', complexity_threshold: 20, lines_threshold: 80}\n",
    )
    config = Config(str(path))
    assert config.get_weights() == {"ldr": 0.5, "inflation": 0.30, "ddc": 0.20, "purity": 0.10}
    assert config.get_god_function_config()["domain_overrides"] == [
        {
            "function_pattern": "z_*",
            "complexity_threshold": 30,
            "lines_threshold": 90,
            "reason": "keep",
        },
        {"function_pattern": "a_*", "complexity_threshold": 20, "lines_threshold": 80},
    ]
    assert config.get_god_function_config()["complexity_threshold"] == 10


def test_legacy_ignored_key_still_only_warns(tmp_path, caplog):
    path = _write(tmp_path, "patterns:\n  severity_threshold: high\n")
    with caplog.at_level(logging.WARNING, logger="slop_detector.config"):
        Config(str(path))
    assert "severity_threshold has no effect" in caplog.text


def test_unknown_key_is_not_an_error(tmp_path):
    Config(str(_write(tmp_path, "future_section:\n  x: 1\nadvanced:\n  new_knob: on\n")))


@pytest.mark.parametrize("profile", sorted(DOMAIN_PROFILES))
@pytest.mark.parametrize("project_type", ["python", "javascript", "go"])
def test_generated_templates_validate(tmp_path, profile, project_type):
    text = generate_slopconfig_template(project_type, DOMAIN_PROFILES[profile])
    Config(str(_write(tmp_path, text)))


@pytest.mark.parametrize("name", [".slopconfig.yaml", ".slopconfig.example.yaml"])
def test_shipped_configs_validate(name):
    Config(str(REPO / name))


def test_cli_rejects_bad_config_before_any_analysis(tmp_path, monkeypatch, capsys):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    path = _write(tmp_path, 'thresholds:\n  ldr:\n    good: "abc"\n')
    calls = []
    monkeypatch.setattr(SlopDetector, "analyze_project", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(SlopDetector, "analyze_file", lambda *a, **k: calls.append(a))
    assert main(["--project", str(tmp_path), "--config", str(path)]) == 1
    assert calls == []
    assert "thresholds.ldr.good" in capsys.readouterr().err

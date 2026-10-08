"""Documented configuration keys that nothing reads are gone, and warned about.

Same contract as `patterns.severity_threshold`: these keys were in the
defaults, the `--init` template, the example config, or the docs, and the docs
described an effect, but no code consumed them. They are removed rather than
implemented; a user config that still sets one loads, warns on stderr, and gives
the same results. `weights.bcr` and `thresholds.bcr` are the example config's
legacy names for the inflation weight and thresholds (also never read).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml

from slop_detector.config import DOMAIN_PROFILES, Config, generate_slopconfig_template
from slop_detector.core import SlopDetector

NOOP_KEYS = (
    "patterns.enabled",
    "thresholds.inflation",
    "thresholds.ddc",
    "thresholds.bcr",
    "weights.bcr",
    "advanced.min_file_size",
    "advanced.max_file_size",
    "advanced.ml_detection",
)
REPO = Path(__file__).resolve().parents[1]

SOURCE = (
    "from os.path import *\n\n\n"
    "def f(items=[]):\n"
    "    try:\n"
    "        return items[0]\n"
    "    except:\n"
    "        pass\n"
)


def _has(tree, dotted: str) -> bool:
    node = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


@pytest.mark.parametrize("key", NOOP_KEYS)
def test_defaults_do_not_carry_the_key(key):
    assert not _has(Config.DEFAULT_CONFIG, key)


@pytest.mark.parametrize("key", NOOP_KEYS)
def test_init_templates_do_not_write_the_key(key):
    for name, profile in DOMAIN_PROFILES.items():
        template = yaml.safe_load(generate_slopconfig_template(domain_profile=profile))
        assert not _has(template, key), name


@pytest.mark.parametrize("key", NOOP_KEYS)
def test_example_config_does_not_show_the_key(key):
    example = yaml.safe_load((REPO / ".slopconfig.example.yaml").read_text(encoding="utf-8"))
    assert not _has(example, key)


def _config_with(tmp_path, text: str) -> Path:
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    return path


ALL_NOOP = (
    "patterns:\n  enabled: false\n"
    "thresholds:\n  inflation: {fail: 0.1}\n  ddc: {excellent: 0.99}\n  bcr: {fail: 0.1}\n"
    "weights:\n  bcr: 0.9\n"
    "advanced:\n  min_file_size: 100000\n  max_file_size: 1\n  ml_detection: true\n"
)


def test_each_key_warns_and_the_config_still_loads(tmp_path, caplog):
    path = _config_with(tmp_path, ALL_NOOP)
    with caplog.at_level(logging.WARNING, logger="slop_detector.config"):
        Config(str(path))
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    missing = [key for key in NOOP_KEYS if key not in text]
    assert missing == []


def test_consumed_keys_do_not_warn(tmp_path, caplog):
    path = _config_with(
        tmp_path,
        "thresholds:\n  ldr: {critical: 0.3}\nweights:\n  inflation: 0.3\n"
        "advanced:\n  use_radon: true\n  weighted_analysis: true\npatterns:\n  disabled: []\n",
    )
    with caplog.at_level(logging.WARNING, logger="slop_detector.config"):
        Config(str(path))
    assert [r.getMessage() for r in caplog.records if "no effect" in r.getMessage()] == []


def test_the_keys_change_no_result(tmp_path):
    """Preservation, with values that would visibly matter if anything read them
    (patterns off, every file too small or too large, weight 0.9)."""
    source = tmp_path / "mod.py"
    source.write_text(SOURCE, encoding="utf-8")
    plain = _config_with(tmp_path, "patterns:\n  disabled: []\n")
    keyed = tmp_path / "keyed.yaml"
    keyed.write_text(
        "patterns:\n  disabled: []\n"
        + ALL_NOOP.replace("patterns:\n", "", 1).replace("  enabled: false\n", "", 1),
        encoding="utf-8",
    )

    def analyze(config):
        result = SlopDetector(config_path=str(config), read_only=True).analyze_file(str(source))
        payload = result.to_dict()
        payload.pop("file_path", None)
        return json.dumps(payload, sort_keys=True)

    assert analyze(plain) == analyze(keyed)

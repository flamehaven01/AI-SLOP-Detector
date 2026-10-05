"""`patterns.severity_threshold` was a config key that nothing read.

It shipped in the defaults and in the `--init` template ("minimum severity to
report"), but no code consulted it: setting it to `critical` still reported
every severity. The key is removed rather than implemented. An explicit key in
a user's config, which earlier `--init` runs wrote, is accepted with a warning
and changes nothing.
"""

from __future__ import annotations

import json
import logging

from slop_detector.config import DOMAIN_PROFILES, Config, generate_slopconfig_template
from slop_detector.core import SlopDetector

SOURCE = (
    "from os.path import *\n"
    "\n"
    "\n"
    "def f(items=[]):\n"
    "    try:\n"
    "        return items[0]\n"
    "    except:\n"
    "        pass\n"
)


def test_defaults_do_not_carry_the_key():
    assert "severity_threshold" not in Config.DEFAULT_CONFIG["patterns"]


def test_init_templates_do_not_write_the_key():
    for name, profile in DOMAIN_PROFILES.items():
        template = generate_slopconfig_template(domain_profile=profile)
        assert "severity_threshold" not in template, name


def test_explicit_key_warns_and_still_loads(tmp_path, caplog):
    config_path = tmp_path / ".slopconfig.yaml"
    config_path.write_text("patterns:\n  severity_threshold: critical\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="slop_detector.config"):
        Config(str(config_path))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("patterns.severity_threshold" in m for m in warnings), warnings


def test_no_warning_without_the_key(tmp_path, caplog):
    config_path = tmp_path / ".slopconfig.yaml"
    config_path.write_text("patterns:\n  disabled: []\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="slop_detector.config"):
        Config(str(config_path))
    assert not [r for r in caplog.records if "severity_threshold" in r.getMessage()]


def test_explicit_key_changes_no_result(tmp_path):
    """Preservation: the key never filtered anything and still does not."""
    source = tmp_path / "mod.py"
    source.write_text(SOURCE, encoding="utf-8")
    plain = tmp_path / "plain.yaml"
    plain.write_text("patterns:\n  disabled: []\n", encoding="utf-8")
    keyed = tmp_path / "keyed.yaml"
    keyed.write_text(
        "patterns:\n  disabled: []\n  severity_threshold: critical\n", encoding="utf-8"
    )

    def analyze(config):
        detector = SlopDetector(config_path=str(config), read_only=True)
        result = detector.analyze_file(str(source)).to_dict()
        result.pop("file_path", None)
        return json.dumps(result, sort_keys=True)

    without, with_key = analyze(plain), analyze(keyed)
    assert '"severity": "high"' in without, "fixture must report a non-critical finding"
    assert without == with_key

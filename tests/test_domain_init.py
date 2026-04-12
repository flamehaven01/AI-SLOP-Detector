"""Tests for Phase 3a: domain-aware --init (detect_domain + template generation)."""

from pathlib import Path

import pytest
import yaml

from slop_detector.cli_commands import detect_domain
from slop_detector.config import DOMAIN_PROFILES, generate_slopconfig_template

# ---------------------------------------------------------------------------
# Fixtures — minimal project trees written to tmp_path
# ---------------------------------------------------------------------------


def _write_py(tmp_path: Path, filename: str, imports: str) -> None:
    (tmp_path / filename).write_text(imports, encoding="utf-8")


# ---------------------------------------------------------------------------
# detect_domain — trigger matching
# ---------------------------------------------------------------------------


class TestDetectDomain:
    def test_ml_imports_detected(self, tmp_path):
        _write_py(tmp_path, "model.py", "import numpy\nimport torch\n")
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "scientific/ml"
        assert "numpy" in hits or "torch" in hits
        assert conf > 0.0

    def test_web_imports_detected(self, tmp_path):
        _write_py(tmp_path, "app.py", "from fastapi import FastAPI\nimport uvicorn\n")
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "web/api"
        assert "fastapi" in hits

    def test_cli_imports_detected(self, tmp_path):
        _write_py(tmp_path, "cli.py", "import click\n")
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "cli/tool"
        assert "click" in hits

    def test_bio_imports_detected(self, tmp_path):
        _write_py(tmp_path, "pipeline.py", "from Bio import SeqIO\nimport pysam\n")
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "bio"

    def test_finance_imports_detected(self, tmp_path):
        _write_py(tmp_path, "quant.py", "import yfinance\nimport backtrader\n")
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "finance"

    def test_no_triggers_returns_general(self, tmp_path):
        _write_py(tmp_path, "utils.py", "import os\nimport sys\n")
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "general"
        assert hits == []
        assert conf == 0.0

    def test_empty_directory_returns_general(self, tmp_path):
        domain, hits, conf = detect_domain(tmp_path)
        assert domain == "general"

    def test_confidence_increases_with_more_hits(self, tmp_path):
        # one hit
        _write_py(tmp_path, "a.py", "import numpy\n")
        _, _, conf_one = detect_domain(tmp_path)
        # add more hits
        _write_py(tmp_path, "b.py", "import torch\nimport sklearn\n")
        _, _, conf_many = detect_domain(tmp_path)
        assert conf_many >= conf_one

    def test_multiple_profiles_best_wins(self, tmp_path):
        # numpy alone — could match numerical, but scientific/ml has more triggers
        _write_py(tmp_path, "a.py", "import numpy\nimport torch\nimport sklearn\n")
        domain, _, _ = detect_domain(tmp_path)
        assert domain == "scientific/ml"


# ---------------------------------------------------------------------------
# DOMAIN_PROFILES — structural invariants
# ---------------------------------------------------------------------------


class TestDomainProfiles:
    def test_all_profiles_have_required_keys(self):
        required = {
            "parent",
            "domain_path",
            "description",
            "triggers",
            "capability_vector",
            "pattern_config",
            "ignore_extra",
        }
        for name, profile in DOMAIN_PROFILES.items():
            missing = required - profile.keys()
            assert not missing, f"Profile '{name}' missing keys: {missing}"

    def test_capability_vector_sums_to_one(self):
        for name, profile in DOMAIN_PROFILES.items():
            cv = profile["capability_vector"]
            total = sum(cv.values())
            assert (
                abs(total - 1.0) < 1e-6
            ), f"Profile '{name}' capability_vector sums to {total:.4f}, expected 1.0"

    def test_domain_path_starts_with_parent(self):
        for name, profile in DOMAIN_PROFILES.items():
            parent = profile["parent"]
            dp = profile["domain_path"]
            assert dp == parent or dp.startswith(
                f"{parent}/"
            ), f"Profile '{name}': domain_path '{dp}' must start with parent '{parent}'"


# ---------------------------------------------------------------------------
# generate_slopconfig_template — domain-specific output
# ---------------------------------------------------------------------------


class TestGenerateSlopconfigTemplate:
    def test_general_template_has_default_weights(self):
        tmpl = generate_slopconfig_template()
        cfg = yaml.safe_load(tmpl)
        assert cfg["weights"]["ldr"] == pytest.approx(0.40)
        assert cfg["weights"]["purity"] == pytest.approx(0.10)

    def test_ml_template_has_low_purity_weight(self):
        profile = DOMAIN_PROFILES["scientific/ml"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        cfg = yaml.safe_load(tmpl)
        assert cfg["weights"]["purity"] == pytest.approx(0.05)
        assert cfg["weights"]["inflation"] == pytest.approx(0.05)

    def test_bio_template_has_low_purity_weight(self):
        profile = DOMAIN_PROFILES["bio"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        cfg = yaml.safe_load(tmpl)
        assert cfg["weights"]["purity"] == pytest.approx(0.05)

    def test_ml_template_has_relaxed_god_function(self):
        profile = DOMAIN_PROFILES["scientific/ml"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        cfg = yaml.safe_load(tmpl)
        assert cfg["patterns"]["god_function"]["lines_threshold"] == 100

    def test_web_template_has_tighter_god_function(self):
        profile = DOMAIN_PROFILES["web/api"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        cfg = yaml.safe_load(tmpl)
        assert cfg["patterns"]["god_function"]["lines_threshold"] == 60

    def test_domain_header_appears_in_template(self):
        profile = DOMAIN_PROFILES["scientific/ml"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        assert "scientific/ml" in tmpl

    def test_detected_by_appears_in_template_header(self):
        profile = dict(DOMAIN_PROFILES["scientific/ml"])
        profile["detected_by"] = ["numpy", "torch"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        assert "numpy" in tmpl
        assert "torch" in tmpl

    def test_ignore_extra_injected(self):
        profile = DOMAIN_PROFILES["scientific/ml"]
        tmpl = generate_slopconfig_template(domain_profile=profile)
        assert "checkpoints/**" in tmpl

    def test_js_ignore_extra_injected_for_javascript(self):
        profile = DOMAIN_PROFILES["web/api"]
        tmpl = generate_slopconfig_template(project_type="javascript", domain_profile=profile)
        assert "node_modules/**" in tmpl

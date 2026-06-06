"""Tests for domain-aware and adaptive --init support."""

from pathlib import Path

import pytest
import yaml

from slop_detector.cli_commands import (
    collect_init_signals,
    detect_domain,
    synthesize_init_suggestions,
)
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
        assert cfg["weights"]["ldr"] == pytest.approx(0.15)
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


# ---------------------------------------------------------------------------
# --init idempotency (SLOP-006)
# ---------------------------------------------------------------------------


class TestInitIdempotency:
    """Re-running --init on an initialized project must exit 0, not 1.

    CI scripts that call --init unconditionally should not fail when the
    config already exists. --force-init remains the explicit overwrite path.
    """

    def test_rerun_returns_zero(self, tmp_path, monkeypatch, capsys):
        from argparse import Namespace

        from slop_detector.cli_commands import _run_init

        monkeypatch.chdir(tmp_path)
        args = Namespace(force_init=False, domain=None)

        rc_first = _run_init(args)
        assert rc_first == 0
        assert (tmp_path / ".slopconfig.yaml").exists()

        capsys.readouterr()  # drain first-run output
        rc_second = _run_init(args)
        out = capsys.readouterr().out
        assert rc_second == 0, "re-running --init should succeed (idempotent)"
        assert "already initialized" in out.lower()

    def test_preview_does_not_write_config(self, tmp_path, monkeypatch, capsys):
        from argparse import Namespace

        from slop_detector.cli_commands import _run_init

        monkeypatch.chdir(tmp_path)
        args = Namespace(
            force_init=False,
            domain=None,
            adaptive_init=True,
            init_preview=True,
            apply_init_suggestions=False,
        )

        rc = _run_init(args)
        out = capsys.readouterr().out

        assert rc == 0
        assert not (tmp_path / ".slopconfig.yaml").exists()
        assert "Preview mode" in out
        assert "Adaptive Init Preview" in out

    def test_apply_init_suggestions_merges_existing_config(self, tmp_path, monkeypatch, capsys):
        from argparse import Namespace

        from slop_detector.cli_commands import _run_init

        monkeypatch.chdir(tmp_path)
        (tmp_path / "src" / "domain").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "api").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "results").mkdir()
        existing = {
            "version": "2.0",
            "ignore": ["tests/**"],
            "patterns": {
                "god_function": {
                    "complexity_threshold": 10,
                    "lines_threshold": 50,
                    "domain_overrides": [],
                }
            },
            "architecture": {
                "enabled": False,
                "preset": "none",
                "layers": [],
            },
            "custom_section": {
                "keep_me": True,
            },
        }
        (tmp_path / ".slopconfig.yaml").write_text(yaml.safe_dump(existing, sort_keys=False))
        _write_py(
            tmp_path / "src" / "domain",
            "workflow.py",
            "\n".join(
                [
                    "def reconcile(items):",
                    "    total = 0",
                    "    for item in items:",
                    "        if item > 10:",
                    "            total += item",
                    "        elif item > 5:",
                    "            total += item - 1",
                    "        elif item > 0:",
                    "            total += item - 2",
                    "        else:",
                    "            total -= 1",
                    "    if total > 100:",
                    "        return total",
                    "    if total > 80:",
                    "        return total - 1",
                    "    if total > 60:",
                    "        return total - 2",
                    "    if total > 40:",
                    "        return total - 3",
                    "    if total > 35:",
                    "        return total - 4",
                    "    if total > 30:",
                    "        return total - 5",
                    "    if total > 25:",
                    "        return total - 6",
                    "    if total > 20:",
                    "        return total - 7",
                    "    return total",
                ]
            ),
        )
        args = Namespace(
            force_init=False,
            domain=None,
            adaptive_init=True,
            init_preview=False,
            apply_init_suggestions=True,
        )

        rc = _run_init(args)
        out = capsys.readouterr().out
        merged = yaml.safe_load((tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8"))

        assert rc == 0
        assert "Applying adaptive suggestions only" in out
        assert "Adaptive init suggestions merged" in out
        assert "results/**" in merged["ignore"]
        assert merged["custom_section"]["keep_me"] is True
        assert merged["architecture"]["enabled"] is True
        assert merged["architecture"]["preset"] == "layered"
        assert merged["patterns"]["god_function"]["domain_overrides"]

    def test_force_init_with_apply_suggestions_preserves_handwritten(
        self, tmp_path, monkeypatch, capsys
    ):
        from argparse import Namespace

        from slop_detector.cli_commands import _run_init

        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        _write_py(
            tmp_path / "src",
            "app.py",
            "import os\n\n\ndef main():\n    return os.getcwd()\n",
        )
        existing = {
            "version": "2.0",
            "patterns": {
                "god_function": {
                    "complexity_threshold": 10,
                    "lines_threshold": 50,
                    "domain_overrides": [],
                }
            },
            "custom_section": {"keep_me": True},
        }
        (tmp_path / ".slopconfig.yaml").write_text(yaml.safe_dump(existing, sort_keys=False))

        # force + apply must NOT wipe hand-written config (the adaptive safety model).
        args = Namespace(
            force_init=True,
            domain=None,
            adaptive_init=True,
            init_preview=False,
            apply_init_suggestions=True,
        )
        rc = _run_init(args)

        assert rc == 0
        merged = yaml.safe_load((tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8"))
        assert merged["custom_section"]["keep_me"] is True
        assert merged["patterns"]["god_function"]["complexity_threshold"] == 10


class TestAdaptiveInitSignals:
    def test_collect_init_signals_includes_manifests_and_counts(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        (tmp_path / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
        (tmp_path / "go.mod").write_text("module example/demo\n", encoding="utf-8")
        _write_py(tmp_path, "app.py", "import click\n")
        (tmp_path / "frontend.ts").write_text("export const ok = true;\n", encoding="utf-8")
        (tmp_path / "worker.go").write_text("package main\n", encoding="utf-8")

        signals = collect_init_signals(tmp_path)

        assert signals["project_type"] == "javascript"
        assert signals["manifests"]["pyproject_toml"] is True
        assert signals["manifests"]["package_json"] is True
        assert signals["manifests"]["go_mod"] is True
        assert signals["language_counts"]["python"] == 1
        assert signals["language_counts"]["typescript"] == 1
        assert signals["language_counts"]["go"] == 1

    def test_collect_init_signals_finds_noise_directories(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "dist").mkdir()
        (tmp_path / "node_modules").mkdir()
        _write_py(tmp_path / "tests", "test_demo.py", "import os\n")

        signals = collect_init_signals(tmp_path)

        assert "tests" in signals["noise_directories"]
        assert "dist" in signals["noise_directories"]
        assert "node_modules" not in signals["noise_directories"]
        assert signals["cleanup_markers"]["has_tests"] is True

    def test_collect_init_signals_collects_complexity_candidates(self, tmp_path):
        code = """
def orchestrate(payload):
    total = 0
    for item in payload:
        if item > 0:
            if item % 2 == 0:
                total += item
            else:
                total -= item
        elif item == 0:
            total += 0
        else:
            total -= 1
    if total > 100:
        return total
    if total > 50:
        return total - 10
    if total > 25:
        return total - 5
    return total
"""
        _write_py(tmp_path, "workflow.py", code)

        signals = collect_init_signals(tmp_path)

        candidates = signals["python_complexity_candidates"]
        assert candidates
        assert candidates[0]["function_name"] == "orchestrate"
        assert candidates[0]["complexity"] >= 8 or candidates[0]["logic_lines"] >= 20

    def test_collect_init_signals_collects_architecture_markers(self, tmp_path):
        for rel in [
            "src/api",
            "src/domain",
            "src/data",
            "src/services",
        ]:
            (tmp_path / rel).mkdir(parents=True, exist_ok=True)
        _write_py(tmp_path / "src" / "api", "controller.py", "import os\n")

        signals = collect_init_signals(tmp_path)

        markers = signals["architecture_markers"]
        assert markers["has_src_layout"] is True
        assert markers["layered_hint_strength"] > 0.0
        assert "api" in markers["layer_names"]
        assert "domain" in markers["layer_names"]


class TestAdaptiveInitSuggestions:
    def test_suggestions_are_stable_for_same_repository(self, tmp_path):
        (tmp_path / "src" / "domain").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "api").mkdir(parents=True, exist_ok=True)
        (tmp_path / "results").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        long_function = "\n".join(
            [
                "def orchestrate(items):",
                "    total = 0",
                "    for item in items:",
                "        if item > 0:",
                "            if item % 2 == 0:",
                "                total += item",
                "            else:",
                "                total -= item",
                "        elif item == 0:",
                "            total += 0",
                "        else:",
                "            total -= 1",
                "    if total > 100:",
                "        return total",
                "    if total > 90:",
                "        return total - 1",
                "    if total > 80:",
                "        return total - 2",
                "    if total > 70:",
                "        return total - 3",
                "    if total > 60:",
                "        return total - 4",
                "    if total > 50:",
                "        return total - 5",
                "    if total > 40:",
                "        return total - 6",
                "    if total > 30:",
                "        return total - 7",
                "    if total > 20:",
                "        return total - 8",
                "    return total",
            ]
        )
        _write_py(tmp_path / "src" / "domain", "workflow.py", long_function)

        signals_a = collect_init_signals(tmp_path)
        signals_b = collect_init_signals(tmp_path)

        assert synthesize_init_suggestions(signals_a) == synthesize_init_suggestions(signals_b)

    def test_weak_evidence_does_not_escalate_to_strong_config_changes(self, tmp_path):
        (tmp_path / "src" / "helpers").mkdir(parents=True, exist_ok=True)
        _write_py(tmp_path / "src" / "helpers", "utils.py", "def helper(x):\n    return x + 1\n")

        suggestions = synthesize_init_suggestions(collect_init_signals(tmp_path))

        assert suggestions["god_function_domain_overrides"] == []
        assert suggestions["architecture"]["recommendation"] == "stay_disabled"
        assert suggestions["cleanup_hints"]
        assert suggestions["cleanup_hints"][0]["hint"] == "coverage_signals_limited"

    def test_suggestions_are_plainly_explainable(self, tmp_path):
        (tmp_path / "src" / "api").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "domain").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "checkpoints").mkdir()
        (tmp_path / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
        _write_py(
            tmp_path / "src" / "domain",
            "logic.py",
            "\n".join(
                [
                    "def reconcile(items):",
                    "    total = 0",
                    "    for item in items:",
                    "        if item > 10:",
                    "            total += item",
                    "        elif item > 5:",
                    "            total += item - 1",
                    "        elif item > 0:",
                    "            total += item - 2",
                    "        else:",
                    "            total -= 1",
                    "    if total > 100:",
                    "        return total",
                    "    if total > 80:",
                    "        return total - 1",
                    "    if total > 60:",
                    "        return total - 2",
                    "    if total > 40:",
                    "        return total - 3",
                    "    return total",
                ]
            ),
        )

        suggestions = synthesize_init_suggestions(collect_init_signals(tmp_path))

        assert suggestions["ignore_patterns"]
        assert isinstance(suggestions["ignore_patterns"][0]["reason"], str)
        assert suggestions["ignore_patterns"][0]["reason"]
        assert isinstance(suggestions["architecture"]["reason"], str)
        assert suggestions["architecture"]["reason"]
        assert all(item["reason"] for item in suggestions["cleanup_hints"])

"""v3.10 --init contract: a generated config states evidence, never hides findings.

Found by running --init on NSRW, TOE and RExSyn (3.9.3):
- domain detection read every `*.py` under the root including `.venv`
  (RExSyn: 241.7 s, ten ML libraries found only in site-packages) and the
  ubiquitous numpy/matplotlib/argparse decided the domain;
- the scientific/ml weights alone removed every CRITICAL file (RExSyn 4 -> 0,
  TOE 1 -> 0) and the general profile still carried the weights v3.7.0 tried
  and the defaults reverted (ddc 0.6215), so `--init` changed scores with no
  derivation;
- `--apply-init-suggestions` wrote god_function overrides that exempt the
  current worst functions by bare name, project-wide, and rewrote the whole
  file with `yaml.safe_dump` (TOE config: 44 comment lines -> 3);
- the template's explicit test patterns made `--include-tests` fail;
- ignore suggestions named default-excluded and code-free directories.

Contract:
- detection walks the tree once with default-excluded directories pruned,
  ignores test files, does not count generic scientific/CLI imports, and a
  tie for the lead is `general`;
- every generated config uses the default weights; a profile's threshold
  changes are printed by --init;
- function overrides are listed for review, never written;
- merging keeps the existing text (comments included) and adds only the new
  lines; no change, no write;
- `--include-tests` removes the built-in test patterns from any config;
- an ignore suggestion names a directory that holds source code and is not
  already excluded.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import yaml

from slop_detector.cli_commands import _run_init, collect_init_signals, detect_domain
from slop_detector.config import DOMAIN_PROFILES, Config, generate_slopconfig_template

BIG_FUNCTION = "\n".join(
    ["def orchestrate(items):", "    total = 0"]
    + [f"    if total > {n}:\n        total -= {n}" for n in range(40)]
    + ["    return total", ""]
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_args(root: Path, **overrides) -> Namespace:
    values = dict(
        path=str(root),
        force_init=False,
        domain=None,
        adaptive_init=False,
        init_preview=False,
        apply_init_suggestions=False,
    )
    values.update(overrides)
    return Namespace(**values)


# --- domain detection -------------------------------------------------------


def test_detection_ignores_virtualenv_and_test_files(tmp_path):
    _write(tmp_path, "app/main.py", "import fastapi\n")
    _write(tmp_path, ".venv/lib/site-packages/ml/core.py", "import torch\nimport sklearn\n")
    _write(tmp_path, "tests/test_models.py", "import torch\nimport keras\n")

    domain, hits, _ = detect_domain(tmp_path)

    assert (domain, hits) == ("web/api", ["fastapi"])


def test_generic_scientific_and_cli_imports_do_not_decide_domain(tmp_path):
    _write(tmp_path, "a.py", "import numpy\nimport scipy\nimport matplotlib\nimport argparse\n")

    assert detect_domain(tmp_path)[0] == "general"


def test_tied_lead_falls_back_to_general(tmp_path):
    _write(tmp_path, "api.py", "import fastapi\n")
    _write(tmp_path, "model.py", "import torch\n")

    assert detect_domain(tmp_path)[0] == "general"


# --- generated weights and disclosed thresholds -----------------------------


def test_every_profile_template_uses_default_weights():
    default = Config.DEFAULT_CONFIG["weights"]
    for name, profile in DOMAIN_PROFILES.items():
        cfg = yaml.safe_load(generate_slopconfig_template(domain_profile=dict(profile)))
        assert cfg["weights"] == default, name


def test_init_prints_profile_threshold_changes(tmp_path, capsys):
    _write(tmp_path, "train.py", "import torch\nimport sklearn\n")

    assert _run_init(_init_args(tmp_path)) == 0
    out = capsys.readouterr().out

    assert "god_function: complexity 10 -> 15, lines 50 -> 100" in out
    assert "nested_complexity: depth 4 -> 6, cc 5 -> 20" in out


# --- suggestions and merge --------------------------------------------------


def test_function_overrides_are_listed_for_review_not_written(tmp_path, capsys):
    _write(tmp_path, "src/flow.py", BIG_FUNCTION)

    assert _run_init(_init_args(tmp_path, adaptive_init=True, apply_init_suggestions=True)) == 0
    out = capsys.readouterr().out
    cfg = yaml.safe_load((tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8"))

    assert cfg["patterns"]["god_function"]["domain_overrides"] == []
    assert "orchestrate" in out
    assert "not written" in out


def test_merge_keeps_comments_and_adds_only_new_ignore_lines(tmp_path):
    original = (
        "# team config: keep these notes\n"
        "version: '2.0'\n"
        "ignore:\n"
        '  - "tests/**"  # tests are reviewed separately\n'
        "  # generated protobuf stubs\n"
        '  - "src/proto/**"\n'
        "custom_section:\n"
        "  keep_me: true\n"
    )
    (tmp_path / ".slopconfig.yaml").write_text(original, encoding="utf-8")
    _write(tmp_path, "examples/demo.py", "def demo():\n    return 1\n")

    assert _run_init(_init_args(tmp_path, adaptive_init=True, apply_init_suggestions=True)) == 0
    text = (tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8")

    for line in original.splitlines():
        assert line in text
    cfg = yaml.safe_load(text)
    assert cfg["ignore"] == ["tests/**", "src/proto/**", "examples/**"]
    assert cfg["custom_section"] == {"keep_me": True}


def test_merge_without_changes_leaves_file_untouched(tmp_path):
    # No trailing newline: a rewrite of an unchanged file would add one.
    original = "# hand written\nversion: '2.0'\nignore:\n  - \"tests/**\""
    (tmp_path / ".slopconfig.yaml").write_text(original, encoding="utf-8")
    _write(tmp_path, "src/app.py", "def f():\n    return 1\n")

    assert _run_init(_init_args(tmp_path, adaptive_init=True, apply_init_suggestions=True)) == 0

    assert (tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8") == original


def test_merge_keeps_crlf_line_endings(tmp_path):
    original = '# windows config\r\nignore:\r\n  - "tests/**"\r\n'
    (tmp_path / ".slopconfig.yaml").write_bytes(original.encode("utf-8"))
    _write(tmp_path, "examples/demo.py", "def demo():\n    return 1\n")

    assert _run_init(_init_args(tmp_path, adaptive_init=True, apply_init_suggestions=True)) == 0

    data = (tmp_path / ".slopconfig.yaml").read_bytes().decode("utf-8")
    assert data == original + '  - "examples/**"\r\n'


def test_unextendable_layout_is_rewritten_and_says_so(tmp_path, capsys):
    (tmp_path / ".slopconfig.yaml").write_text(
        '# flow list\nignore: ["tests/**"]\n', encoding="utf-8"
    )
    _write(tmp_path, "examples/demo.py", "def demo():\n    return 1\n")

    assert _run_init(_init_args(tmp_path, adaptive_init=True, apply_init_suggestions=True)) == 0

    cfg = yaml.safe_load((tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8"))
    assert cfg["ignore"] == ["tests/**", "examples/**"]
    assert "comments were not kept" in capsys.readouterr().out


def test_insertion_that_would_change_meaning_falls_back_to_rewrite(tmp_path):
    # Zero-indented list items: an inserted indented item would not parse to
    # the merged config, so the parse check must reject the in-place edit.
    (tmp_path / ".slopconfig.yaml").write_text(
        'ignore:\n- "tests/**"\nversion: "2.0"\n', encoding="utf-8"
    )
    _write(tmp_path, "examples/demo.py", "def demo():\n    return 1\n")

    assert _run_init(_init_args(tmp_path, adaptive_init=True, apply_init_suggestions=True)) == 0

    cfg = yaml.safe_load((tmp_path / ".slopconfig.yaml").read_text(encoding="utf-8"))
    assert cfg == {"ignore": ["tests/**", "examples/**"], "version": "2.0"}


def test_ignore_suggestions_need_source_and_skip_default_excluded(tmp_path):
    _write(tmp_path, "dashboard/.next/static/chunk.js", "var a = 1;\n")
    _write(tmp_path, "docs/guide.md", "# guide\n")
    _write(tmp_path, "examples/demo.py", "def demo():\n    return 1\n")
    _write(tmp_path, "examples/output/render.py", "def render():\n    return 1\n")
    # "data" is an architecture layer name; its code is product code.
    _write(tmp_path, "src/app/data/repository.py", "def load():\n    return 1\n")

    signals = collect_init_signals(tmp_path)

    assert signals["noise_directories"] == ["examples"]


# --- include-tests after init -----------------------------------------------


def test_include_tests_overrides_builtin_test_patterns_in_config(tmp_path):
    assert _run_init(_init_args(tmp_path)) == 0
    config = Config(str(tmp_path / ".slopconfig.yaml"))

    config.include_default_tests()
    assert "tests/**" not in config.get_ignore_patterns()
    assert "**/.venv/**" in config.get_ignore_patterns()

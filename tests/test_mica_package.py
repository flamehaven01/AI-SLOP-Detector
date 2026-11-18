"""The repository's AI memory (MICA) resolves, and every reference in it exists.

README.md invokes mica.yaml; mica.yaml selects the archive (decisions a change
must not undo) and the playbook (how work is verified and released). The
archive names, for each invariant, the tests or the procedure that hold it.

This file checks existence and binding only: that each named test, file and
map path exists, and that each critical invariant says where it came from.
It does not check that an invariant holds or that its tests are sufficient;
the named tests do that. If a test is renamed or removed, or a path in the
playbook's map moves, this file fails: memory that points at nothing is worse
than no memory. MICA's own validator (tools/mica_pct.py) checks the contract;
this test needs no MICA install.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DIRECTIVE = re.compile(r'<!--\s*MICA:INVOKE\s+manifest="([^"]+)"\s*-->')
EPISODE = re.compile(r"v\d+\.\d+|\d{4}-\d{2}-\d{2}")


def _manifest() -> dict:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    found = DIRECTIVE.findall(readme)
    assert len(found) == 1, f"README must invoke exactly one manifest, found {found}"
    head = readme.splitlines()[:5]
    assert any(DIRECTIVE.search(line) for line in head), "the directive belongs near the top"
    return yaml.safe_load((REPO / found[0]).read_text(encoding="utf-8"))


def _archive() -> dict:
    layers = {layer["name"]: layer for layer in _manifest()["layers"]}
    return json.loads((REPO / layers["archive"]["path"]).read_text(encoding="utf-8"))


def test_the_readme_invokes_one_manifest_that_selects_archive_and_playbook():
    manifest = _manifest()
    layers = {layer["name"]: layer for layer in manifest["layers"]}
    assert set(layers) >= {"archive", "playbook"}
    for name in ("archive", "playbook"):
        assert layers[name]["loading_hint"] == "always"
        assert (REPO / layers[name]["path"]).is_file(), layers[name]["path"]
    surfaces = manifest["invocation_protocol"]["agent_context_surfaces"]
    assert surfaces == ["archive", "playbook"]


def test_every_invariant_points_at_tests_that_exist():
    invariants = _archive()["design_invariants"]
    ids = [item["id"] for item in invariants]
    assert len(ids) == len(set(ids)), "invariant ids repeat"
    for item in invariants:
        assert item["statement"].strip(), item["id"]
        for ref in item.get("held_by", []):
            path, _, name = ref.partition("::")
            source = REPO / path
            assert source.is_file(), f"{item['id']}: {path} does not exist"
            text = source.read_text(encoding="utf-8")
            assert re.search(
                rf"^def {re.escape(name)}\(", text, re.M
            ), f"{item['id']}: {path} has no test {name}"


def test_every_critical_invariant_names_where_it_came_from():
    for item in _archive()["design_invariants"]:
        if item["severity"] != "critical":
            continue
        binding = item.get("binding") or {}
        assert EPISODE.search(
            binding.get("origin_episode", "")
        ), f"{item['id']}: origin_episode needs a release or a date"
        assert (
            REPO / binding.get("lesson_ref", "")
        ).is_file(), f"{item['id']}: lesson_ref {binding.get('lesson_ref')} does not exist"
        assert item.get("held_by") or binding["lesson_ref"].startswith(
            "memory/"
        ), f"{item['id']}: name the tests that hold it, or the procedure that does"


def test_an_unreleased_invariant_is_never_critical():
    for item in _archive()["design_invariants"]:
        if item.get("status", "").startswith("unreleased"):
            assert item["severity"] != "critical", f"{item['id']}: unreleased but critical"


def test_the_playbook_map_points_at_files_that_exist():
    layers = {layer["name"]: layer for layer in _manifest()["layers"]}
    playbook = (REPO / layers["playbook"]["path"]).read_text(encoding="utf-8")
    table = playbook.split("## Where things are", 1)[1].split("\n## ", 1)[0]
    for token in re.findall(r"`([^`]+)`", table):
        candidates = [REPO / token, REPO / "src" / "slop_detector" / token]
        assert any(p.exists() for p in candidates), f"playbook map: {token} does not exist"

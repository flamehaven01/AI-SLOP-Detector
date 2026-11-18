"""The README is shown on GitHub and on PyPI (pyproject's `readme`).

PyPI resolves no repository-relative path, so every link and image in it is an
absolute URL or an anchor on the page itself; and every link into this
repository names a file, and a section, that exists.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
BASE = "https://github.com/flamehaven01/AI-SLOP-Detector/"
RAW = "https://raw.githubusercontent.com/flamehaven01/AI-SLOP-Detector/main/"

# Sections the README held up to 3.15.2: an old link to one still lands on a
# line that leads to the section's new place.
MOVED = {
    "what-is-ai-slop-detector",
    "60-second-first-run",
    "what-you-get",
    "verification-path",
    "scope-and-boundaries",
    "scoring-model",
    "key-features",
    "claude-code-integration",
    "local-calibration",
    "security-considerations",
    "cicd-integration",
    "configuration",
    "inline-suppression",
    "repeated-run-cache",
    "priority-hotspots",
    "agent-surface",
    "vs-code-extension",
    "release-highlights",
    "development",
}


def _targets(text: str) -> list:
    found = re.findall(r"\]\(([^)\s]+)\)", text)
    found += re.findall(r'(?:href|src)="([^"]+)"', text)
    return found


def _anchors(text: str) -> set:
    """The anchors GitHub gives a Markdown page: one per heading, plus explicit ids."""
    anchors = set(re.findall(r'<a id="([^"]+)"', text))
    for heading in re.findall(r"^#+ (.+)$", text, re.MULTILINE):
        anchors.add(re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-"))
    return anchors


def test_readme_has_no_repository_relative_link():
    relative = [t for t in _targets(README) if not t.startswith(("https://", "#"))]
    assert not relative, relative


def test_readme_links_into_the_repository_exist():
    missing = []
    for target in _targets(README):
        if target.startswith(RAW):
            path, anchor = target[len(RAW) :].replace("%20", " "), ""
        elif target.startswith(BASE + "blob/main/") or target.startswith(BASE + "tree/main/"):
            path, _, anchor = target[len(BASE) + len("blob/main/") :].partition("#")
        else:
            continue
        local = REPO / path
        if not local.exists():
            missing.append(target)
        elif anchor and anchor not in _anchors(local.read_text(encoding="utf-8")):
            missing.append(target)
    assert not missing, missing


def test_readme_page_anchors_exist():
    own = _anchors(README)
    missing = [t for t in _targets(README) if t.startswith("#") and t[1:] not in own]
    assert not missing, missing


def test_each_moved_section_leads_to_its_new_place():
    """An old anchor is a section of this page again, or the line that carries
    it links to where the section is now."""
    lines = [line for line in README.splitlines() if '<a id="' in line]
    by_anchor = {re.search(r'<a id="([^"]+)"', line).group(1): line for line in lines}
    headings = _anchors(re.sub(r'<a id="[^"]+"></a>', "", README))
    assert set(by_anchor) <= MOVED, sorted(set(by_anchor) - MOVED)
    assert not set(by_anchor) & headings, sorted(set(by_anchor) & headings)  # one place each
    assert MOVED <= set(by_anchor) | headings, sorted(MOVED - set(by_anchor) - headings)
    for anchor, line in by_anchor.items():
        assert len(re.findall(r'<a id="', line)) == 1, line
        assert re.search(r"\]\(https://github\.com/[^)]+\)", line), (anchor, line)

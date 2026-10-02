"""Controls for sync/async parity of the placeholder patterns.

`async def` with a placeholder body gets the same finding as `def` with that
body, and every exemption that keeps a sync function silent keeps its async
twin silent. Sync findings do not change.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

import pytest

from slop_detector.analysis_cache import CACHE_ENGINE_VERSION
from slop_detector.core import SlopDetector

PLACEHOLDER_IDS = {
    "pass_placeholder",
    "ellipsis_placeholder",
    "not_implemented",
    "return_none_placeholder",
    "return_constant_stub",
}

BODIES = {
    "pass": ("pass", "pass_placeholder"),
    "ellipsis": ("...", "ellipsis_placeholder"),
    "raise_call": ("raise NotImplementedError()", "not_implemented"),
    "raise_name": ("raise NotImplementedError", "not_implemented"),
    "return_none": ("return None", "return_none_placeholder"),
    "return_constant": ("return 0", "return_constant_stub"),
    "return_empty_list": ("return []", "return_constant_stub"),
    "docstring_then_pass": ('"""Fetch it."""\n    pass', "pass_placeholder"),
}


def _ids(tmp_path: Path, name: str, source: str) -> List[str]:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    analysis = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(i.pattern_id for i in analysis.pattern_issues if i.pattern_id in PLACEHOLDER_IDS)


def _function(prefix: str, body: str, name: str = "fetch", args: str = "") -> str:
    return f"{prefix}def {name}({args}):\n    {body}\n"


# ---------------------------------------------------------------------------
# Positive twins: same finding for def and async def
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(BODIES))
def test_async_placeholder_gets_the_sync_finding(tmp_path, case):
    body, expected = BODIES[case]
    sync = _ids(tmp_path, "s.py", _function("", body))
    asyn = _ids(tmp_path, "a.py", _function("async ", body))
    assert sync == [expected], f"sync baseline changed: {sync}"
    assert asyn == sync, f"async {case}: {asyn} != sync {sync}"


def test_async_method_placeholder_in_a_class(tmp_path):
    source = "class Client:\n    async def fetch(self):\n        pass\n"
    assert _ids(tmp_path, "c.py", source) == ["pass_placeholder"]


# ---------------------------------------------------------------------------
# Negative twins: exemptions hold for async too
# ---------------------------------------------------------------------------


def test_real_async_implementation_has_no_placeholder_finding(tmp_path):
    source = """
    import asyncio


    async def fetch(url):
        await asyncio.sleep(0)
        parts = url.split("/")
        return parts[-1]
    """
    stub = _ids(tmp_path, "stub.py", _function("async ", "pass", args="url"))
    assert stub == ["pass_placeholder"], "async stubs are not seen at all; this control is blind"
    assert _ids(tmp_path, "r.py", source) == []


@pytest.mark.parametrize("case", sorted(BODIES))
def test_abstract_async_method_is_exempt_like_sync(tmp_path, case):
    body = BODIES[case][0]
    template = (
        "from abc import ABC, abstractmethod\n\n\n"
        "class Base(ABC):\n"
        "    @abstractmethod\n"
        "    {prefix}def fetch(self):\n"
        "        {body}\n"
    )
    body = body.replace("\n    ", "\n        ")
    plain = template.replace("    @abstractmethod\n", "").replace("class Base(ABC):", "class Base:")
    seen = _ids(tmp_path, "u.py", plain.format(prefix="async ", body=body))
    assert BODIES[case][1] in seen, f"plain async twin not flagged: {seen}"
    # An ABC subclass is exempt for sync methods even without the decorator; async follows.
    in_abc = template.replace("    @abstractmethod\n", "")
    assert _ids(tmp_path, "abc_s.py", in_abc.format(prefix="", body=body)) == _ids(
        tmp_path, "abc_a.py", in_abc.format(prefix="async ", body=body)
    )
    sync = _ids(tmp_path, "s.py", template.format(prefix="", body=body))
    asyn = _ids(tmp_path, "a.py", template.format(prefix="async ", body=body))
    assert sync == [] and asyn == [], (sync, asyn)


@pytest.mark.parametrize("case", sorted(BODIES))
def test_abstractmethod_alone_exempts_async_like_sync(tmp_path, case):
    """No ABC base, so the decorator is the only reason for the exemption."""
    body = BODIES[case][0].replace("\n    ", "\n        ")
    template = (
        "from abc import abstractmethod\n\n\n"
        "class Base:\n"
        "{decorator}"
        "    {prefix}def fetch(self):\n"
        "        {body}\n"
    )
    bare = template.format(decorator="", prefix="async ", body=body)
    assert BODIES[case][1] in _ids(tmp_path, "bare.py", bare), "plain async twin not flagged"
    deco = "    @abstractmethod\n"
    assert _ids(tmp_path, "s.py", template.format(decorator=deco, prefix="", body=body)) == []
    assert _ids(tmp_path, "a.py", template.format(decorator=deco, prefix="async ", body=body)) == []


def test_protocol_async_method_with_ellipsis_is_exempt_like_sync(tmp_path):
    template = (
        "from typing import Protocol\n\n\n"
        "class Fetcher(Protocol):\n"
        "    {prefix}def fetch(self) -> bytes:\n"
        "        ...\n"
    )
    plain = template.replace("class Fetcher(Protocol):", "class Fetcher:")
    assert _ids(tmp_path, "p.py", plain.format(prefix="async ")) == ["ellipsis_placeholder"]
    assert _ids(tmp_path, "s.py", template.format(prefix="")) == []
    assert _ids(tmp_path, "a.py", template.format(prefix="async ")) == []


def test_async_context_exit_is_exempt_like_sync_exit(tmp_path):
    sync = "class C:\n    def __exit__(self, *exc):\n        return False\n"
    asyn = "class C:\n    async def __aexit__(self, *exc):\n        return False\n"
    plain = "class C:\n    async def close(self, *exc):\n        return False\n"
    assert _ids(tmp_path, "p.py", plain) == ["return_constant_stub"]
    assert _ids(tmp_path, "s.py", sync) == []
    assert _ids(tmp_path, "a.py", asyn) == []


def test_async_dunder_returning_none_is_exempt_like_sync(tmp_path):
    sync = "class C:\n    def __del__(self):\n        return None\n"
    asyn = "class C:\n    async def __aenter__(self):\n        return None\n"
    plain = "class C:\n    async def open(self):\n        return None\n"
    assert _ids(tmp_path, "p.py", plain) == ["return_none_placeholder"]
    assert _ids(tmp_path, "s.py", sync) == []
    assert _ids(tmp_path, "a.py", asyn) == []


# ---------------------------------------------------------------------------
# Preservation and cache
# ---------------------------------------------------------------------------


def test_preservation_sync_file_findings_and_score_unchanged(tmp_path):
    """PRESERVATION: a sync-only file keeps its findings; async code is absent."""
    source = "def a():\n    pass\n\n\ndef b():\n    return 0\n\n\ndef c(x):\n    return x + 1\n"
    path = tmp_path / "sync_only.py"
    path.write_text(source, encoding="utf-8")
    analysis = SlopDetector(read_only=True).analyze_file(str(path))
    ids = sorted(i.pattern_id for i in analysis.pattern_issues if i.pattern_id in PLACEHOLDER_IDS)
    assert ids == ["pass_placeholder", "return_constant_stub"]


def test_cache_engine_version_moves_with_detection_changes():
    """Cached results from before async parity must not be reused."""
    assert CACHE_ENGINE_VERSION != "analysis-cache-v11"

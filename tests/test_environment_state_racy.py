"""The environment state sees an install or uninstall that keeps the directory's
mtime (2026-11-15).

environment_state() identified each search-path directory by its mtime, and the
environment fingerprint and the resolvable-module set were memoized on it. On
Windows a directory's mtime was unchanged after a quick uninstall in 182 of 300
tries (the clock tick is coarser than the change), so a long-lived process kept
a stale fingerprint and still resolved the removed package
(tests/test_v310_import_evidence.py::test_uninstall_is_seen_in_the_same_process
failed now and then). Here the mtime is held fixed on purpose: the change must
still be seen. A directory changed long ago is identified by its mtime alone,
without listing it.
"""

import importlib
import os
import shutil
import time

from slop_detector import environment_resolution as env
from slop_detector.patterns import python_imports


def _site(tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "zzracypkg").mkdir(parents=True)
    (site / "zzracypkg" / "__init__.py").write_text("V = 1\n", encoding="utf-8")
    info = site / "zzracypkg-1.0.dist-info"  # an installed distribution, as pip leaves it
    info.mkdir()
    (info / "METADATA").write_text("Name: zzracypkg\nVersion: 1.0\n", encoding="utf-8")
    (info / "top_level.txt").write_text("zzracypkg\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()
    return site


def _hold_mtime(path, ns):
    os.utime(path, ns=(ns, ns))


def test_an_uninstall_that_keeps_the_mtime_changes_the_fingerprint(tmp_path, monkeypatch):
    site = _site(tmp_path, monkeypatch)
    now = time.time_ns()
    _hold_mtime(site, now)
    before = env.environment_fingerprint()

    shutil.rmtree(site / "zzracypkg")
    shutil.rmtree(site / "zzracypkg-1.0.dist-info")
    _hold_mtime(site, now)  # the same tick: the mtime does not show the change
    assert os.stat(site).st_mtime_ns == now

    assert env.environment_fingerprint() != before


def test_an_uninstall_that_keeps_the_mtime_is_seen_by_import_resolution(tmp_path, monkeypatch):
    site = _site(tmp_path, monkeypatch)
    monkeypatch.setattr(python_imports, "_RESOLVABLE_MODULES_STORE", {})
    now = time.time_ns()
    _hold_mtime(site, now)
    assert python_imports._module_exists("zzracypkg") is True

    shutil.rmtree(site / "zzracypkg")
    shutil.rmtree(site / "zzracypkg-1.0.dist-info")
    _hold_mtime(site, now)
    importlib.invalidate_caches()

    assert python_imports._module_exists("zzracypkg") is False


def test_a_directory_changed_long_ago_is_not_listed(tmp_path, monkeypatch):
    site = _site(tmp_path, monkeypatch)
    _hold_mtime(site, time.time_ns() - 3600 * 10**9)  # an hour ago
    listed = []
    original = env._top_level_names
    monkeypatch.setattr(
        env, "_top_level_names", lambda entry: listed.append(entry) or original(entry)
    )
    env.environment_state()
    assert str(site) not in listed

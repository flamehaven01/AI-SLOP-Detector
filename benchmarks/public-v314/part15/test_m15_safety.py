"""Negative tests for the scratch-directory handling of m15.py (PUB-001).

Run in the measurement venv:  python -m pytest -q test_m15_safety.py

A link here is a directory junction on Windows (no privilege needed) and a
symbolic link elsewhere. Every test plants a "victim" directory outside the
output directory and checks that it survives.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m15  # noqa: E402


def make_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


@pytest.fixture
def victim(tmp_path):
    v = tmp_path / "victim"
    v.mkdir()
    (v / "keep.txt").write_text("must survive", encoding="utf-8")
    return v


def intact(v: Path) -> bool:
    return (v / "keep.txt").read_text(encoding="utf-8") == "must survive"


def test_a_planted_work_link_is_never_followed_or_deleted(tmp_path, victim):
    out = tmp_path / "out"
    out.mkdir()
    make_link(out / "_work", victim)  # the old fixed name, pointing outside
    work = m15.Work(out)
    assert intact(victim)  # the acceptance: nothing outside --out was touched
    work.close()
    assert intact(victim)
    assert work.root.parent == out.resolve() and work.root.name.startswith("m15_work_")
    assert m15.is_link(out / "_work")  # left as it was
    assert not work.root.exists()  # only the run's own root was removed


def test_an_out_directory_that_is_a_link_is_refused(tmp_path, victim):
    link = tmp_path / "out_link"
    make_link(link, victim)
    with pytest.raises(SystemExit):
        m15.Work(link)
    assert intact(victim)


def test_main_refuses_an_out_link_before_resolving_it(tmp_path, victim, monkeypatch):
    link = tmp_path / "out_link"
    make_link(link, victim)
    monkeypatch.setattr(sys, "argv", ["m15.py", "--demo", str(tmp_path / "d"),
                                      "--repo", str(tmp_path / "r"), "--out", str(link)])
    with pytest.raises(SystemExit) as exc:
        m15.main()
    assert "link or junction" in str(exc.value)
    assert intact(victim)


def test_remove_owned_refuses_a_link_inside_the_owner(tmp_path, victim):
    owner = tmp_path / "owner"
    owner.mkdir()
    make_link(owner / "inner", victim)
    with pytest.raises(SystemExit):
        m15.remove_owned(owner / "inner", owner)
    assert intact(victim)


def test_remove_owned_refuses_a_directory_outside_the_owner(tmp_path, victim):
    owner = tmp_path / "owner"
    owner.mkdir()
    with pytest.raises(SystemExit):
        m15.remove_owned(victim, owner)
    with pytest.raises(SystemExit):
        m15.remove_owned(owner, owner)  # the owner itself is not inside the owner
    assert intact(victim)


def test_fresh_copies_are_new_and_separate(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    work = m15.Work(out)
    one, two = work.fresh("p", src), work.fresh("p", src)
    assert one != two and one.parent.parent == work.root
    (one / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert (src / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (two / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    work.close()
    assert (src / "a.py").exists()

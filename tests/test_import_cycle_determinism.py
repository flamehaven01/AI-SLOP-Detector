"""Controls for deterministic `import_cycles` output.

The same project must give the same cycles, in the same order and rotation, under
any PYTHONHASHSEED. A cycle is written from its smallest path, in its own
direction: rotations of one directed cycle are one cycle, and the reverse cycle is
never rewritten into the forward one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from slop_detector.analysis import cross_file
from slop_detector.analysis.cross_file import CrossFileAnalyzer

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")

_DUMP = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "from types import SimpleNamespace\n"
    "from slop_detector.analysis.cross_file import CrossFileAnalyzer\n"
    "root = Path(sys.argv[1])\n"
    "files = [SimpleNamespace(file_path=str(p), deficit_score=0.0)"
    " for p in sorted(root.rglob('*.py'))]\n"
    "report = CrossFileAnalyzer().analyze(str(root), files)\n"
    "print(json.dumps(report.to_dict()['import_cycles']))\n"
)


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _analyze(root: Path):
    files = [
        SimpleNamespace(file_path=str(p), deficit_score=0.0) for p in sorted(root.rglob("*.py"))
    ]
    return CrossFileAnalyzer().analyze(str(root), files)


def _canonical():
    fn = getattr(cross_file, "canonical_cycle", None)
    assert fn is not None, "cross_file.canonical_cycle is not implemented"
    return fn


def _branching(root: Path) -> None:
    """a -> b, a -> c, b -> c, c -> a: which cycle DFS meets first depends on visit order."""
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/a.py", "from pkg import b, c\n")
    _write(root, "pkg/b.py", "from pkg import c\n")
    _write(root, "pkg/c.py", "from pkg import a\n")


def _several(root: Path) -> None:
    """The branching case plus independent cycles in other packages (five in all)."""
    _branching(root)
    _write(root, "two/__init__.py")
    _write(root, "two/x.py", "from two import y\n")
    _write(root, "two/y.py", "from two import x\n")
    _write(root, "ring/__init__.py")
    _write(root, "ring/p.py", "from ring import q\n")
    _write(root, "ring/q.py", "from ring import r\n")
    _write(root, "ring/r.py", "from ring import p\n")
    # Entered from outside at its larger file (a -> z, z <-> y), then a smaller cycle
    # found later (b <-> c): discovery order is neither rotation- nor list-sorted.
    _write(root, "entry/__init__.py")
    _write(root, "entry/a.py", "from entry import z\n")
    _write(root, "entry/z.py", "from entry import y\n")
    _write(root, "entry/y.py", "from entry import z\n")
    _write(root, "entry/b.py", "from entry import c\n")
    _write(root, "entry/c.py", "from entry import b\n")


# ---------------------------------------------------------------------------
# Canonical form
# ---------------------------------------------------------------------------


def test_every_rotation_of_a_cycle_has_one_canonical_form():
    canonical = _canonical()
    forms = {canonical(("a", "b", "c")), canonical(("b", "c", "a")), canonical(("c", "a", "b"))}
    assert forms == {("a", "b", "c")}


def test_the_reverse_cycle_keeps_its_direction():
    canonical = _canonical()
    assert canonical(("a", "c", "b")) == ("a", "c", "b")
    assert canonical(("c", "b", "a")) == ("a", "c", "b")
    assert canonical(("a", "c", "b")) != canonical(("a", "b", "c"))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


SEEDS = range(6)


def _cycles_under(seed: int, root: Path) -> list:
    """`import_cycles` from a child process with a fixed PYTHONHASHSEED."""
    env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=REPO_SRC)
    result = subprocess.run(
        [sys.executable, "-c", _DUMP, str(root)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-400:]
    return json.loads(result.stdout)


def test_import_cycles_are_identical_under_every_hash_seed(tmp_path):
    _several(tmp_path)
    outputs = {json.dumps(_cycles_under(seed, tmp_path)) for seed in SEEDS}
    assert len(outputs) == 1, f"{len(outputs)} different outputs across {len(SEEDS)} hash seeds"
    assert len(json.loads(outputs.pop())) == 5


def test_reported_cycles_start_at_their_smallest_path_and_are_sorted(tmp_path):
    _several(tmp_path)
    for seed in SEEDS:
        cycles = [row["cycle"] for row in _cycles_under(seed, tmp_path)]
        assert cycles, "fixture has no cycles"
        for cycle in cycles:
            assert cycle[0] == min(cycle), (seed, cycle)
        assert cycles == sorted(cycles), seed


def test_traversal_order_is_sorted_so_the_branching_case_is_pinned(tmp_path):
    """Sorted visiting reaches b before c from a, so the a -> b -> c loop is the one met."""
    _branching(tmp_path)
    for seed in SEEDS:
        (row,) = _cycles_under(seed, tmp_path)
        assert [Path(p).name for p in row["cycle"]] == ["a.py", "b.py", "c.py"], seed


def test_caller_file_order_does_not_change_the_cycles(tmp_path):
    """DFS starts from sorted nodes, not from the order the caller passed files in."""
    _several(tmp_path)
    paths = sorted(tmp_path.rglob("*.py"))

    def cycles(order):
        files = [SimpleNamespace(file_path=str(p), deficit_score=0.0) for p in order]
        report = CrossFileAnalyzer().analyze(str(tmp_path), files)
        return [c.cycle for c in report.import_cycles]

    assert cycles(paths) == cycles(list(reversed(paths)))


def test_the_cap_keeps_the_first_twenty_in_sorted_order(tmp_path):
    """21 cycles; the smallest (b <-> c) is discovered last and must survive the cap of 20."""
    _write(tmp_path, "pkg/__init__.py")
    names = [f"m{i:02d}" for i in range(20)]
    _write(tmp_path, "pkg/a.py", "".join(f"from pkg import {m}\n" for m in names))
    for i, m in enumerate(names):
        _write(tmp_path, f"pkg/{m}.py", f"from pkg import n{i:02d}\n")
        _write(tmp_path, f"pkg/n{i:02d}.py", f"from pkg import {m}\n")
    _write(tmp_path, "pkg/b.py", "from pkg import c\n")
    _write(tmp_path, "pkg/c.py", "from pkg import b\n")
    cycles = [[Path(p).name for p in c.cycle] for c in _analyze(tmp_path).import_cycles]
    assert len(cycles) == 20
    assert cycles[0] == ["b.py", "c.py"]


# ---------------------------------------------------------------------------
# Preservation
# ---------------------------------------------------------------------------


def test_preservation_one_cycle_per_set_of_files(tmp_path):
    """PRESERVATION: cycles over the same files are reported once, as before."""
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b, c\n")
    _write(tmp_path, "pkg/b.py", "from pkg import a, c\n")
    _write(tmp_path, "pkg/c.py", "from pkg import a, b\n")
    sets = [frozenset(c.cycle) for c in _analyze(tmp_path).import_cycles]
    assert len(sets) == len(set(sets))


def test_preservation_display_closes_the_loop(tmp_path):
    """PRESERVATION: display text is still `first -> ... -> first`."""
    _branching(tmp_path)
    (cycle,) = _analyze(tmp_path).to_dict()["import_cycles"]
    names = [Path(p).name for p in cycle["cycle"]]
    assert cycle["display"] == " -> ".join(names + names[:1])

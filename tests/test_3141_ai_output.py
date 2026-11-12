"""3.14.1: the AI report and the work order reach stdout whatever the console
code page, and a file scanned on its own is located by its name.
"""

import json
import os
import subprocess
import sys

from slop_detector.report_view import short_path

DASH = chr(0x2014)  # not in cp949
PY = (
    "def compute_total(order):\n"
    f'    """Compute the total {DASH} with the customer tier."""\n'
    "    return 0.1\n"
)
JS = "function addItem(cart, item) {\n  console.log(item);\n  return cart;\n}\n"


def _scan(cwd, target, *args, encoding):
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    return subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", "scan", target, "--no-history", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
    )


def test_ai_outputs_on_a_cp949_console_are_utf8(tmp_path):
    # a project root, so the file's test status is known and its promise judged
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pricing.py").write_text(PY, encoding="utf-8")
    for fmt in ("ai", "ai-md"):
        run = _scan(tmp_path, "pricing.py", "--format", fmt, encoding="cp949")
        assert run.returncode == 0, (fmt, run.stderr.decode("utf-8", "replace")[-400:])
        text = run.stdout.decode("utf-8")
        assert DASH in text, fmt
    records = [
        json.loads(line)
        for line in _scan(tmp_path, "pricing.py", "--format", "ai", encoding="cp949")
        .stdout.decode("utf-8")
        .splitlines()
        if line.strip()
    ]
    assert records[0]["record"] == "header" and any(
        DASH in json.dumps(r, ensure_ascii=False) for r in records[1:]
    )


def test_a_file_scanned_alone_is_located_by_its_name(tmp_path):
    (tmp_path / "cart.js").write_text(JS, encoding="utf-8")
    run = _scan(tmp_path, "cart.js", "--format", "ai", encoding="utf-8")
    items = [
        json.loads(line) for line in run.stdout.decode("utf-8").splitlines()[1:] if line.strip()
    ]
    assert items and {i["file"] for i in items} == {"cart.js"}
    order = _scan(tmp_path, "cart.js", "--format", "ai-md", encoding="utf-8").stdout.decode("utf-8")
    assert "at [FACT]: cart.js:" in order and "at [FACT]: .:" not in order


def test_short_path_of_the_root_itself_is_its_name(tmp_path):
    f = tmp_path / "m.go"
    f.write_text("package main\n", encoding="utf-8")
    assert short_path(str(f), str(f)) == "m.go"
    assert short_path(str(f), str(tmp_path)) == "m.go"
    assert short_path(str(tmp_path / "sub" / "a.py"), str(tmp_path)) == "sub/a.py"

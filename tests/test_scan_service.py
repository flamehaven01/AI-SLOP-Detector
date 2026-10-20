"""ScanService and ExportService: the GUI and the CLI reach the same engine the same way.

Acceptance (V4-P1): A1 the service's JSON and exit code equal the CLI's;
A2 events are complete and ordered; A4 the default is read-only; A5 a cancel
stops at a file boundary; A6 failures are typed; A7 a second concurrent scan
is refused; A8 every export format renders, and a written report equals the
CLI's file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from slop_detector.cli import main
from slop_detector.service.export import ExportService
from slop_detector.service.scan import (
    CancelToken,
    ScanCancelledError,
    ScanFailedError,
    ScanRequest,
    ScanService,
    WritePolicy,
)
from tests.test_read_only import _diff, _state

CODE = "def f(x):\n    return x + 1\n"
STUB = "def g():\n    pass\n"


def _fixtures(root: Path) -> dict:
    project = root / "proj"
    project.mkdir()
    (project / "a.py").write_text(CODE, encoding="utf-8")
    (project / "b.py").write_text(STUB, encoding="utf-8")
    configured = root / "configured"
    configured.mkdir()
    (configured / "a.py").write_text(STUB, encoding="utf-8")
    (configured / ".slopconfig.yaml").write_text("patterns:\n  disabled: [pass_placeholder]\n")
    empty = root / "empty"
    empty.mkdir()
    js = root / "app.js"
    js.write_text("function f(a) { return a + 1; }\n", encoding="utf-8")
    return {
        "project": project,
        "file": project / "b.py",
        "js": js,
        "empty": empty,
        "configured": configured,
    }


@pytest.fixture
def targets(tmp_path):
    return _fixtures(tmp_path)


def _cli(capsys, target: Path, *options: str):
    code = main([str(target), "--json", "--no-history", *options])
    return code, capsys.readouterr().out


# -- A1: same JSON and exit code as the CLI --------------------------------------


@pytest.mark.parametrize("name", ["project", "file", "js", "empty", "configured"])
@pytest.mark.parametrize(
    "gate, threshold",
    [(None, None), ("soft", None), ("hard", None), (None, 0.0), (None, 99.0)],
)
def test_service_json_and_exit_code_equal_the_cli(targets, capsys, name, gate, threshold):
    options = []
    if gate:
        options += ["--ci-mode", gate]
    if threshold is not None:
        options += ["--fail-threshold", str(threshold)]
    cli_code, cli_out = _cli(capsys, targets[name], *options)
    outcome = ScanService().run(ScanRequest(targets[name], gate=gate, fail_threshold=threshold))
    assert ExportService.render(outcome, "json") == cli_out.rstrip("\n")
    assert outcome.exit_code == cli_code


# -- A2: events ---------------------------------------------------------------------


def test_events_are_complete_and_ordered(targets):
    events = []
    outcome = ScanService().run(ScanRequest(targets["project"]), on_event=events.append)
    kinds = [e.kind for e in events]
    assert kinds[0] == "started" and kinds[-1] == "completed"
    assert kinds.count("started") == kinds.count("completed") == 1
    assert kinds[1] == "discovered" and kinds[-2] == "aggregating"
    done = [e for e in events if e.kind == "file_done"]
    coverage = outcome.result.scan_coverage
    assert len(done) == coverage["analyzed"]["total"] + coverage["failed"]["total"] == 2
    assert outcome.measurement_state == "COMPLETE" and outcome.score_valid is True


def test_single_file_events(targets):
    events = []
    ScanService().run(ScanRequest(targets["file"]), on_event=events.append)
    assert [e.kind for e in events] == ["started", "file_done", "completed"]


# -- A4: read-only by default; writes only on request ---------------------------

RUNNER = """
import sys
from pathlib import Path
from slop_detector.service.scan import ScanRequest, ScanService, WritePolicy
policy = WritePolicy[sys.argv[2]]
ScanService().run(ScanRequest(Path(sys.argv[1]), writes=policy))
print("OK")
"""


def _run_isolated(tmp_path: Path, project: Path, policy: str) -> subprocess.CompletedProcess:
    home = tmp_path / f"home_{policy}"
    home.mkdir(exist_ok=True)
    script = tmp_path / "runner.py"
    script.write_text(RUNNER, encoding="utf-8")
    repo_src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONPATH=repo_src)
    return home, subprocess.run(
        [sys.executable, str(script), str(project), policy],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=180,
    )


def test_default_scan_writes_nothing(tmp_path, targets):
    home = tmp_path / "home_READ_ONLY"
    home.mkdir()
    before = _state(home, targets["project"])
    _, result = _run_isolated(tmp_path, targets["project"], "READ_ONLY")
    assert result.stdout.strip() == "OK", result.stderr[-400:]
    assert _diff(before, _state(home, targets["project"])) == []


def test_record_history_is_an_explicit_opt_in(tmp_path, targets):
    home, result = _run_isolated(tmp_path, targets["project"], "RECORD_HISTORY")
    assert result.stdout.strip() == "OK", result.stderr[-400:]
    assert (home / ".slop-detector" / "history.db").exists()


def test_quarantine_gate_is_refused_read_only(targets):
    with pytest.raises(ScanFailedError) as err:
        ScanService().run(ScanRequest(targets["project"], gate="quarantine"))
    assert err.value.kind == "invalid_request"


# -- A5: cancel at a file boundary ----------------------------------------------------


def test_cancel_stops_after_the_current_file(targets, monkeypatch):
    from slop_detector.core import SlopDetector

    analyzed = []
    original = SlopDetector.analyze_file

    def counted(self, *args, **kwargs):
        analyzed.append(args[0])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SlopDetector, "analyze_file", counted)
    token, events = CancelToken(), []

    def on_event(event):
        events.append(event)
        if event.kind == "file_done":
            token.cancel()

    with pytest.raises(ScanCancelledError):
        ScanService().run(ScanRequest(targets["project"]), on_event=on_event, cancel=token)
    assert [e.kind for e in events].count("file_done") == 1
    assert len(analyzed) == 1  # the next file is not analyzed
    assert events[-1].kind == "cancelled"


# -- A6: typed failures ---------------------------------------------------------------


def test_missing_config_is_a_config_failure_with_no_file_events(targets, tmp_path):
    events = []
    with pytest.raises(ScanFailedError) as err:
        ScanService().run(
            ScanRequest(targets["project"], config_path=tmp_path / "missing.yaml"),
            on_event=events.append,
        )
    assert err.value.kind == "config"
    assert not [e for e in events if e.kind == "file_done"]


def test_missing_target(tmp_path):
    with pytest.raises(ScanFailedError) as err:
        ScanService().run(ScanRequest(tmp_path / "nope"))
    assert err.value.kind == "target_not_found"


def test_unknown_disabled_pattern_is_an_invalid_request(targets):
    with pytest.raises(ScanFailedError) as err:
        ScanService().run(ScanRequest(targets["project"], disabled_patterns=("no_such",)))
    assert err.value.kind == "invalid_request"


def test_observer_error_is_typed_and_ends_the_scan(targets):
    def on_event(event):
        if event.kind == "discovered":
            raise RuntimeError("ui broke")

    with pytest.raises(ScanFailedError) as err:
        ScanService().run(ScanRequest(targets["project"]), on_event=on_event)
    assert err.value.kind == "observer"


# -- A7: one scan at a time, across instances ----------------------------------------


def test_second_concurrent_scan_is_refused(targets):
    entered, release = threading.Event(), threading.Event()

    def hold(event):
        if event.kind == "discovered":
            entered.set()
            release.wait(30)

    worker = threading.Thread(
        target=lambda: ScanService().run(ScanRequest(targets["project"]), on_event=hold)
    )
    worker.start()
    try:
        assert entered.wait(30)
        with pytest.raises(ScanFailedError) as err:
            ScanService().run(ScanRequest(targets["file"]))
        assert err.value.kind == "busy"
    finally:
        release.set()
        worker.join(30)
    ScanService().run(ScanRequest(targets["file"]))  # the lock is released


# -- A8: export -------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["project", "file", "empty"])
@pytest.mark.parametrize("fmt, suffix", [("md", ".md"), ("html", ".html"), ("text", ".txt")])
def test_written_report_equals_the_cli_file(targets, tmp_path, capsys, name, fmt, suffix):
    cli_file = tmp_path / f"cli{suffix}"
    main([str(targets[name]), "-o", str(cli_file), "--no-history"])
    capsys.readouterr()
    outcome = ScanService().run(ScanRequest(targets[name]))
    service_file = tmp_path / f"service{suffix}"
    ExportService.export(outcome, fmt, service_file)
    assert service_file.read_bytes() == cli_file.read_bytes()
    if name == "empty":
        assert "NOT EVALUATED" in service_file.read_text(encoding="utf-8")


def test_json_export_parses(targets, tmp_path):
    outcome = ScanService().run(ScanRequest(targets["project"]))
    path = tmp_path / "r.json"
    ExportService.export(outcome, "json", path)
    assert json.loads(path.read_text(encoding="utf-8"))["scan_coverage"]["score_valid"] is True


def test_unknown_export_format(targets):
    outcome = ScanService().run(ScanRequest(targets["project"]))
    with pytest.raises(ValueError):
        ExportService.render(outcome, "pdf")


def test_write_policy_default_is_read_only():
    assert ScanRequest(Path(".")).writes is WritePolicy.READ_ONLY


# -- Phase 4: the CLI scans through ScanService ---------------------------------------


def test_cli_scan_runs_through_the_service(targets, capsys):
    """Holding the service's process lock makes a CLI scan a typed refusal."""
    from slop_detector.service import scan as scan_module

    assert scan_module._SCAN_LOCK.acquire(blocking=False)
    try:
        code = main([str(targets["file"]), "--no-history"])
    finally:
        scan_module._SCAN_LOCK.release()
    assert code == 1
    assert "another scan is running" in capsys.readouterr().err


def test_cli_setup_failure_keeps_its_message_and_exit_code(targets, tmp_path, capsys):
    code = main([str(targets["file"]), "--config", str(tmp_path / "missing.yaml")])
    assert code == 1
    assert "[!] Failed to initialize detector:" in capsys.readouterr().err


def test_cli_unknown_disabled_pattern_keeps_exit_code_2(targets, capsys):
    assert main([str(targets["file"]), "--disable", "no_such", "--no-history"]) == 2
    assert "[!] Invalid runtime override:" in capsys.readouterr().err

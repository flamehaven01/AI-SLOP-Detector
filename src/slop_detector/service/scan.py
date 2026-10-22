"""ScanService: one scan, run the same way for the CLI and the desktop GUI.

It resolves the config, applies per-run options, analyzes the target with the
engine, evaluates the gate and the exit policy (service.policy), and reports
progress. It adds no analysis of its own.

The CLI scan, the MCP tools and the REST routes all scan through it. Guarantees:
- READ_ONLY (the default) builds no analysis cache and records no history;
  RECORD_HISTORY is the explicit opt-in. Exports are separate, explicit writes.
- One scan per process, across instances; a second concurrent run is refused.
- Failures are typed (ScanFailedError.kind). A cancel takes effect at a file
  boundary and returns no result.
"""

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple, Union

from slop_detector.config import ConfigError
from slop_detector.core import SlopDetector, UnsupportedLanguageError
from slop_detector.core_project import score_is_valid
from slop_detector.models import FileAnalysis, ProjectAnalysis
from slop_detector.service.events import ScanEvent, ScanObserver, ScanProgress
from slop_detector.service.policy import (
    apply_runtime_overrides,
    evaluate_gate,
    gate_exit_code,
    resolve_config_path,
    threshold_breach,
)
from slop_detector.service.targets import analyze_single_source_file, target_kind

logger = logging.getLogger(__name__)

# Shared by every ScanService: module-level caches in the engine are not proven
# safe for concurrent scans.
_SCAN_LOCK = threading.Lock()


class WritePolicy(enum.Enum):
    READ_ONLY = "read_only"  # no analysis cache, no history
    RECORD_HISTORY = "record_history"  # analysis cache and local history
    CACHE_ONLY = "cache_only"  # analysis cache; the caller records history (the CLI does)


@dataclass(frozen=True)
class ScanRequest:
    target: Path
    # "auto": a directory is a project; or "file" / "project". "python_file": the
    # Python-file entry point of MCP and REST, which refuses JS/TS/Go source.
    mode: str = "auto"
    config_path: Optional[Path] = None
    discover_config: bool = True  # .slopconfig.yaml in the project root / next to the file
    include_tests: bool = False
    patterns_only: bool = False
    disabled_patterns: Tuple[str, ...] = ()
    topology_ceiling: Optional[int] = None
    topology_mode: Optional[str] = None
    gate: Optional[str] = None  # "soft", "hard" or "quarantine"
    claims_strict: bool = False
    fail_threshold: Optional[float] = None
    writes: WritePolicy = WritePolicy.READ_ONLY


@dataclass(frozen=True)
class ScanOutcome:
    result: Union[ProjectAnalysis, FileAnalysis]
    gate: Any  # GateResult or None
    exit_code: int  # the CLI's exit code for the same request
    exit_reason: Optional[str]  # why --fail-threshold failed, if it did
    config_path_used: Optional[str]
    measurement_state: Optional[str]  # project results only
    score_valid: bool
    config: Any  # the detector's Config, with the run's options applied


class ScanFailedError(Exception):
    """A scan that produced no result.

    kind: target_not_found, config, invalid_request, busy, observer,
    unsupported_language, internal. stage: "request" (before setup), "setup"
    (config and detector), "analysis". detail: the underlying error's text.
    """

    def __init__(
        self, kind: str, message: str, stage: str = "analysis", detail: Optional[str] = None
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.stage = stage
        self.detail = detail if detail is not None else message


class ScanCancelledError(Exception):
    """The scan was cancelled; no result is returned."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class _CancelRequestedError(Exception):
    pass


class _ObserverFailedError(Exception):
    pass


def _deliver_quietly(on_event: Optional[ScanObserver], event: ScanEvent) -> None:
    """A terminal event: the scan is over, so a UI error here is only logged."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:  # noqa: BLE001 - nothing left to abort
        logger.debug("observer failed on %s", event.kind, exc_info=True)


class ScanService:
    def run(
        self,
        request: ScanRequest,
        on_event: Optional[ScanObserver] = None,
        cancel: Optional[CancelToken] = None,
    ) -> ScanOutcome:
        if not _SCAN_LOCK.acquire(blocking=False):
            raise ScanFailedError("busy", "another scan is running in this process", "request")
        try:
            return self._run(request, on_event, cancel)
        finally:
            _SCAN_LOCK.release()

    def _run(
        self,
        request: ScanRequest,
        on_event: Optional[ScanObserver],
        cancel: Optional[CancelToken],
    ) -> ScanOutcome:
        target = Path(request.target)
        project = request.mode == "project" or (request.mode == "auto" and target.is_dir())
        read_only = request.writes is WritePolicy.READ_ONLY
        if read_only and request.gate == "quarantine":
            raise ScanFailedError(
                "invalid_request",
                "the quarantine gate writes its database; not allowed read-only",
                "request",
            )
        explicit = str(request.config_path) if request.config_path is not None else None
        config_path = (
            resolve_config_path(target, project, explicit)
            if explicit is not None or request.discover_config
            else None
        )
        # Setup before the target check: a config error is reported first (CLI order).
        detector = self._build_detector(request, config_path, read_only)
        if not target.exists():
            raise ScanFailedError("target_not_found", f"{target} does not exist", "request")

        def notify(event: ScanEvent) -> None:
            # Outside the engine's per-file except: a cancel or a UI error ends the scan.
            if cancel is not None and cancel.cancelled:
                raise _CancelRequestedError()
            if on_event is not None:
                try:
                    on_event(event)
                except Exception as exc:
                    raise _ObserverFailedError(f"{type(exc).__name__}: {exc}") from exc
            if cancel is not None and cancel.cancelled:
                raise _CancelRequestedError()

        try:
            notify(ScanEvent("started", path=str(target)))
            kind = "python_file" if request.mode == "python_file" else target_kind(target, project)
            result = self._analyze(detector, target, kind, notify)
        except _CancelRequestedError:
            _deliver_quietly(on_event, ScanEvent("cancelled"))
            raise ScanCancelledError("scan cancelled") from None
        except _ObserverFailedError as exc:
            _deliver_quietly(on_event, ScanEvent("failed", outcome="observer"))
            raise ScanFailedError(
                "observer", f"the progress observer raised {exc}", detail=str(exc)
            ) from None
        except UnsupportedLanguageError as exc:
            _deliver_quietly(on_event, ScanEvent("failed", outcome="unsupported_language"))
            raise ScanFailedError("unsupported_language", str(exc)) from None
        except Exception as exc:
            logger.debug("scan failed", exc_info=True)
            _deliver_quietly(on_event, ScanEvent("failed", outcome="internal"))
            raise ScanFailedError(
                "internal", f"analysis failed: {type(exc).__name__}", detail=str(exc)
            ) from None

        gate = evaluate_gate(result, request.gate, request.claims_strict, read_only)
        breach = threshold_breach(result, request.fail_threshold)
        exit_code = 1 if breach is not None else (gate_exit_code(gate) if gate else 0)
        if request.writes is WritePolicy.RECORD_HISTORY:
            from slop_detector.cli_history import _record_history

            _record_history(result, detector.config, str(target), project)
        coverage = getattr(result, "scan_coverage", None) or {}
        _deliver_quietly(on_event, ScanEvent("completed"))
        return ScanOutcome(
            result=result,
            gate=gate,
            exit_code=exit_code,
            exit_reason=breach,
            config_path_used=config_path,
            measurement_state=coverage.get("measurement_state"),
            score_valid=score_is_valid(result),
            config=detector.config,
        )

    @staticmethod
    def _build_detector(
        request: ScanRequest, config_path: Optional[str], read_only: bool
    ) -> SlopDetector:
        try:
            detector = SlopDetector(config_path=config_path, read_only=read_only)
        except ConfigError as exc:
            raise ScanFailedError("config", str(exc), "setup") from None
        except Exception as exc:
            raise ScanFailedError(
                "internal", f"detector setup failed: {type(exc).__name__}", "setup", str(exc)
            ) from None
        try:
            apply_runtime_overrides(
                detector,
                include_tests=request.include_tests,
                topology_ceiling=request.topology_ceiling,
                topology_mode=request.topology_mode,
                patterns_only=request.patterns_only,
                disabled=request.disabled_patterns,
            )
        except ValueError as exc:
            raise ScanFailedError("invalid_request", str(exc), "setup") from None
        return detector

    @staticmethod
    def _analyze(
        detector: SlopDetector, target: Path, kind: str, notify: ScanObserver
    ) -> Union[ProjectAnalysis, FileAnalysis]:
        if kind == "project":
            return detector.analyze_project(str(target), observer=notify)
        result: Union[ProjectAnalysis, FileAnalysis]
        if kind == "source_file":
            language = "javascript" if target.suffix.lower() in detector._JS_EXTENSIONS else "go"
            result = analyze_single_source_file(detector, target)
            failed = (getattr(result, "scan_coverage", None) or {}).get("failed", {})
            outcome = "failed" if failed.get("total") else "analyzed"
        else:
            language = "python"
            result = detector.analyze_file(str(target))
            outcome = "analyzed"
        ScanProgress(notify, {language: 1}).file_done(str(target), language, outcome)
        return result

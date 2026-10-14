"""Scan progress events. No slop_detector imports: the engine uses these too.

Engine events: "discovered" (totals per language, before any file),
"file_done" (one per discovered file; outcome "analyzed" or "failed"),
"aggregating" (before the project result is built). An exception raised by
the observer is not caught by the engine: it ends the scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class ScanEvent:
    kind: str
    totals: Optional[Dict[str, int]] = None
    index: Optional[int] = None
    total: Optional[int] = None
    path: Optional[str] = None
    language: Optional[str] = None
    outcome: Optional[str] = None


ScanObserver = Callable[[ScanEvent], None]


class ScanProgress:
    """Numbers file events and forwards them; does nothing without an observer."""

    def __init__(self, observer: Optional[ScanObserver], totals: Dict[str, int]) -> None:
        self._observer = observer
        self._totals = dict(totals)
        self._total = sum(totals.values())
        self._index = 0

    def discovered(self) -> None:
        if self._observer is not None:
            self._observer(ScanEvent("discovered", totals=dict(self._totals), total=self._total))

    def file_done(self, path: str, language: str, outcome: str) -> None:
        self._index += 1
        if self._observer is not None:
            self._observer(
                ScanEvent(
                    "file_done",
                    index=self._index,
                    total=self._total,
                    path=path,
                    language=language,
                    outcome=outcome,
                )
            )

    def aggregating(self) -> None:
        if self._observer is not None:
            self._observer(ScanEvent("aggregating", total=self._total))

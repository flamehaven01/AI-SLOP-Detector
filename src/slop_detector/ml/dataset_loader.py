"""
Real training data loader using public HuggingFace datasets (v2.9.0).

Strategy
--------
Labels are derived from the rule-based detector (self-supervised):
  deficit_score >= 30  ->  label = 1  (slop)
  deficit_score <  30  ->  label = 0  (clean)

This lets the ML model generalise to borderline cases where individual
rule signals are weak but their combination is meaningful.

Supported datasets
------------------
- code_search_net  (Python subset, ~500k functions, ~200MB)
- bigcode/the-stack (Python, streamed — TB scale, use max_samples)
- custom CSV/JSONL with columns: code, label (optional manual labels)

Usage
-----
    from slop_detector.ml.dataset_loader import DatasetLoader
    loader = DatasetLoader(max_samples=10_000)
    samples = loader.load_codesearchnet()
    # or
    samples = loader.load_stack(max_samples=5_000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)

LABEL_THRESHOLD = 30.0  # deficit_score >= this -> slop


@dataclass
class RealSample:
    """A labelled code sample from a public dataset."""

    code: str
    label: int  # 0 = clean, 1 = slop
    source: str  # dataset name
    func_name: str = ""
    deficit_score: float = 0.0


class DatasetLoader:
    """Load and label real code samples from public datasets."""

    def __init__(self, max_samples: Optional[int] = None):
        """
        Args:
            max_samples: Cap total samples per load call. None = no limit.
        """
        self.max_samples = max_samples

    # ------------------------------------------------------------------
    # Public loaders
    # ------------------------------------------------------------------

    def load_codesearchnet(self, split: str = "train") -> List[RealSample]:
        """Load Python functions from CodeSearchNet (~500k, ~200MB).

        Requires: pip install datasets
        Downloads automatically on first call (~200MB, cached).
        """
        try:
            from datasets import load_dataset  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("Install HuggingFace datasets: pip install datasets") from exc

        logger.info("[DatasetLoader] Loading code_search_net/python (%s)...", split)
        ds = load_dataset(
            "code_search_net",
            "python",
            split=split,
        )

        return list(
            self._label_stream(
                ((row["func_code_string"], row.get("func_name", "")) for row in ds),
                source="code_search_net",
            )
        )

    def load_stack(self, max_samples: Optional[int] = None) -> List[RealSample]:
        """Stream Python files from bigcode/the-stack (TB scale, streamed).

        Requires: pip install datasets
        Uses streaming — no full download needed.

        Args:
            max_samples: Override instance max_samples for this call.
        """
        try:
            from datasets import load_dataset  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("Install HuggingFace datasets: pip install datasets") from exc

        cap = max_samples or self.max_samples
        logger.info(
            "[DatasetLoader] Streaming bigcode/the-stack (cap=%s)...",
            cap or "unlimited",
        )
        ds = load_dataset(
            "bigcode/the-stack",
            data_files="data/python/data-*.parquet",
            split="train",
            streaming=True,
        )

        def _gen() -> Iterator[tuple[str, str]]:
            for row in ds:
                yield row.get("content", ""), ""

        return list(self._label_stream(_gen(), source="the-stack", cap=cap))

    def load_jsonl(self, path: str | Path) -> List[RealSample]:
        """Load from a custom JSONL file.

        Each line: {"code": "...", "label": 0|1, "func_name": "..."}
        If "label" is absent, the rule-based detector assigns it.
        """
        import json

        samples: List[RealSample] = []
        path = Path(path)
        logger.info("[DatasetLoader] Loading custom JSONL: %s", path)

        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                code = row.get("code", "")
                if not code.strip():
                    continue
                if "label" in row:
                    samples.append(
                        RealSample(
                            code=code,
                            label=int(row["label"]),
                            source=str(path),
                            func_name=row.get("func_name", ""),
                        )
                    )
                else:
                    labelled = list(self._label_stream(iter([(code, "")]), source=str(path)))
                    samples.extend(labelled)

                if self.max_samples and len(samples) >= self.max_samples:
                    break

        logger.info("[DatasetLoader] Loaded %d samples from JSONL", len(samples))
        return samples

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _label_stream(
        self,
        stream: Iterator[tuple[str, str]],
        source: str,
        cap: Optional[int] = None,
    ) -> Iterator[RealSample]:
        """Run rule-based detector on each (code, func_name) pair and yield labelled samples."""
        from slop_detector.core import SlopDetector

        detector = SlopDetector()
        limit = cap or self.max_samples
        count = 0

        for code, func_name in stream:
            if not code or not code.strip():
                continue

            try:
                result = detector.analyze_code_string(code, filename=f"<{source}>")
            except Exception as exc:
                logger.debug("[DatasetLoader] Skip sample (%s): %s", func_name, exc)
                continue

            label = 1 if result.deficit_score >= LABEL_THRESHOLD else 0
            yield RealSample(
                code=code,
                label=label,
                source=source,
                func_name=func_name,
                deficit_score=result.deficit_score,
            )

            count += 1
            if count % 1000 == 0:
                logger.info("[DatasetLoader] Processed %d samples...", count)

            if limit and count >= limit:
                logger.info("[DatasetLoader] Reached cap (%d), stopping.", limit)
                break

        logger.info("[DatasetLoader] Labelled %d samples from %s", count, source)

"""Project prioritization overlay using churn and coverage signals."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from slop_detector.models import FileAnalysis, PriorityHotspot, SlopStatus

_CoverageData: Any = None
try:
    from coverage import CoverageData

    _CoverageData = CoverageData
    _COVERAGE_AVAILABLE = True
except ImportError:
    _COVERAGE_AVAILABLE = False


class ProjectPrioritizer:
    """Ranks file-level findings by change pressure and test coverage gaps."""

    def __init__(self, config) -> None:
        self.config = config

    def prioritize_project(
        self, project_path: str, file_results: Sequence[FileAnalysis]
    ) -> Tuple[List[PriorityHotspot], bool, bool]:
        python_results = [
            result for result in file_results if Path(result.file_path).suffix.lower() == ".py"
        ]
        if not python_results:
            return [], False, False

        file_paths = [Path(result.file_path).resolve() for result in python_results]
        churn_counts = self._load_git_churn(project_path, file_paths)
        coverage_ratios = self._load_coverage_ratios(project_path, file_paths)

        churn_available = any(count > 0 for count in churn_counts.values())
        coverage_available = any(ratio is not None for ratio in coverage_ratios.values())
        weights = self.config.get_hotspot_weights()
        hotspot_limit = self.config.get_hotspot_limit()

        max_churn = max(churn_counts.values(), default=0)
        hotspots: List[PriorityHotspot] = []

        for result in python_results:
            if result.status == SlopStatus.CLEAN and result.deficit_score < 30.0:
                continue

            file_key = str(Path(result.file_path).resolve())
            churn_count = churn_counts.get(file_key, 0)
            churn_score = (churn_count / max_churn) if max_churn > 0 else 0.0
            coverage_ratio = coverage_ratios.get(file_key)
            coverage_gap = (
                max(0.0, min(1.0, 1.0 - coverage_ratio)) if coverage_ratio is not None else None
            )

            priority_score = self._compute_priority_score(
                deficit_score=result.deficit_score,
                churn_score=churn_score,
                coverage_gap=coverage_gap,
                weights=weights,
            )
            reasons = self._build_hotspot_reasons(result, churn_score, coverage_ratio)
            if not reasons:
                continue

            hotspots.append(
                PriorityHotspot(
                    file_path=result.file_path,
                    deficit_score=result.deficit_score,
                    churn_count=churn_count,
                    churn_score=round(churn_score, 4),
                    coverage_ratio=None if coverage_ratio is None else round(coverage_ratio, 4),
                    priority_score=round(priority_score, 4),
                    reasons=reasons,
                )
            )

        hotspots.sort(
            key=lambda item: (
                item.priority_score,
                item.deficit_score,
                item.churn_count,
                -1.0 if item.coverage_ratio is None else 1.0 - item.coverage_ratio,
            ),
            reverse=True,
        )
        return hotspots[:hotspot_limit], churn_available, coverage_available

    def _compute_priority_score(
        self,
        deficit_score: float,
        churn_score: float,
        coverage_gap: Optional[float],
        weights: Dict[str, float],
    ) -> float:
        weighted_sum = weights["deficit"] * max(0.0, min(1.0, deficit_score / 100.0))
        total_weight = weights["deficit"]

        if churn_score > 0.0:
            weighted_sum += weights["churn"] * churn_score
            total_weight += weights["churn"]

        if coverage_gap is not None:
            weighted_sum += weights["coverage_gap"] * coverage_gap
            total_weight += weights["coverage_gap"]

        return 100.0 * (weighted_sum / total_weight if total_weight > 0 else 0.0)

    def _build_hotspot_reasons(
        self, result: FileAnalysis, churn_score: float, coverage_ratio: Optional[float]
    ) -> List[str]:
        reasons: List[str] = []
        if result.deficit_score >= 70:
            reasons.append("critical deficit")
        elif result.deficit_score >= 50:
            reasons.append("high deficit")
        elif result.deficit_score >= 30:
            reasons.append("elevated deficit")

        if churn_score >= 0.60:
            reasons.append("high churn")
        elif churn_score >= 0.30:
            reasons.append("active churn")

        if coverage_ratio is not None and coverage_ratio <= 0.30:
            reasons.append("low coverage")
        elif coverage_ratio is not None and coverage_ratio <= 0.60:
            reasons.append("partial coverage")

        return reasons

    def _load_git_churn(self, project_path: str, file_paths: Sequence[Path]) -> Dict[str, int]:
        target_paths = {str(path.resolve()) for path in file_paths}
        if not target_paths:
            return {}

        project_root = self._resolve_git_root(project_path)
        if project_root is None:
            return {}

        commit_window = self.config.get_churn_commit_window()
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--format=format:",
                    "--name-only",
                    "--no-merges",
                    "-n",
                    str(commit_window),
                    "--",
                    ".",
                ],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {}

        counts = {path: 0 for path in target_paths}
        for line in result.stdout.splitlines():
            rel = line.strip()
            if not rel:
                continue
            candidate = (project_root / rel).resolve()
            key = str(candidate)
            if key in counts:
                counts[key] += 1
        return counts

    def _load_coverage_ratios(
        self, project_path: str, file_paths: Sequence[Path]
    ) -> Dict[str, Optional[float]]:
        if not _COVERAGE_AVAILABLE:
            return {}

        coverage_file = Path(project_path) / self.config.get_coverage_data_file()
        if not coverage_file.exists():
            return {}

        try:
            data = _CoverageData(basename=str(coverage_file))
            data.read()
        except Exception:
            return {}

        target_paths = {str(path.resolve()): path.resolve() for path in file_paths}
        ratios: Dict[str, Optional[float]] = {}
        for measured in data.measured_files():
            resolved = self._resolve_coverage_path(project_path, measured)
            key = str(resolved)
            if key not in target_paths:
                continue
            executed = set(data.lines(measured) or [])
            executable = self._estimate_executable_lines(target_paths[key])
            if not executable:
                ratios[key] = None
                continue
            ratios[key] = len(executed & executable) / len(executable)
        return ratios

    def _resolve_git_root(self, project_path: str) -> Optional[Path]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
        root = result.stdout.strip()
        return Path(root).resolve() if root else None

    @staticmethod
    def _resolve_coverage_path(project_path: str, measured_path: str) -> Path:
        candidate = Path(measured_path)
        if candidate.is_absolute():
            return candidate.resolve()
        return (Path(project_path) / candidate).resolve()

    @staticmethod
    def _estimate_executable_lines(file_path: Path) -> Set[int]:
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        except (OSError, SyntaxError):
            return set()

        docstring_lines: Set[int] = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            first_value = getattr(first, "value", None)
            nested_value = getattr(first_value, "value", None)
            if (
                isinstance(first, ast.Expr)
                and isinstance(first_value, ast.Constant)
                and isinstance(nested_value, str)
                and hasattr(first, "lineno")
            ):
                docstring_lines.add(first.lineno)

        executable = {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.stmt)
            and hasattr(node, "lineno")
            and node.lineno not in docstring_lines
        }
        return executable

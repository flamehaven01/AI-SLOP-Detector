#!/usr/bin/env python3
"""
Training Data Collection Module
================================
Collects and prepares training data for ML-based slop detection.

Data Sources:
1. Good Code: NumPy, Flask, Django, Requests (10K+ files)
2. Bad Code: AI-generated slop repositories (5K+ files)
3. Manual: Code review labeled data (1K+ files)

Author: Flamehaven Labs
Version: 2.2.0
Date: 2026-01-08
"""

import ast
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TrainingExample:
    """Single training example with features and label."""

    file_path: str
    label: int  # 0 = clean, 1 = slop
    ldr_score: float
    bcr_score: float
    ddc_score: float
    pattern_count_critical: int
    pattern_count_high: int
    pattern_count_medium: int
    pattern_count_low: int
    avg_function_length: float
    comment_ratio: float
    cross_language_patterns: int
    hallucination_count: int
    total_lines: int
    logic_lines: int
    empty_lines: int
    avg_complexity: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def to_feature_vector(self) -> List[float]:
        """Convert to feature vector for ML models."""
        return [
            self.ldr_score,
            self.bcr_score,
            self.ddc_score,
            float(self.pattern_count_critical),
            float(self.pattern_count_high),
            float(self.pattern_count_medium),
            float(self.pattern_count_low),
            self.avg_function_length,
            self.comment_ratio,
            float(self.cross_language_patterns),
            float(self.hallucination_count),
            float(self.total_lines),
            float(self.logic_lines),
            float(self.empty_lines),
            self.avg_complexity,
        ]


class TrainingDataCollector:
    """Collects training data from various sources."""

    GOOD_REPOS = [
        ("numpy", "numpy"),
        ("pallets", "flask"),
        ("django", "django"),
        ("psf", "requests"),
        ("python", "cpython"),
    ]

    BAD_REPOS = [
        # AI-generated slop repositories (examples)
        # These would be actual repos known to contain AI slop
    ]

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.good_data_dir = self.data_dir / "good"
        self.bad_data_dir = self.data_dir / "bad"
        self.good_data_dir.mkdir(exist_ok=True)
        self.bad_data_dir.mkdir(exist_ok=True)

    def clone_repository(self, owner: str, repo: str, target_dir: Path) -> Optional[Path]:
        """Clone a GitHub repository."""
        repo_url = f"https://github.com/{owner}/{repo}.git"
        repo_path = target_dir / repo

        if repo_path.exists():
            logger.info(f"Repository {repo} already exists, skipping clone")
            return repo_path

        try:
            logger.info(f"Cloning {repo_url}...")
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(repo_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Successfully cloned {repo}")
            return repo_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to clone {repo}: {e.stderr}")
            return None

    def collect_good_data(self, max_files: int = 1000) -> List[Path]:
        """Collect Python files from high-quality repositories."""
        all_files = []

        for owner, repo in self.GOOD_REPOS:
            repo_path = self.clone_repository(owner, repo, self.good_data_dir)
            if not repo_path:
                continue

            python_files = list(repo_path.rglob("*.py"))

            # Filter out tests, docs, examples
            filtered_files = [
                f
                for f in python_files
                if not any(
                    part in f.parts
                    for part in ["test", "tests", "docs", "doc", "examples", "example"]
                )
            ]

            all_files.extend(filtered_files[: max_files // len(self.GOOD_REPOS)])
            logger.info(f"Collected {len(filtered_files)} files from {repo}")

        return all_files

    def collect_bad_data(self, max_files: int = 500) -> List[Path]:
        """Collect Python files from known slop repositories."""
        # In practice, this would clone known AI-slop repos
        # For now, return empty list as placeholder
        logger.warning("Bad data collection not implemented - using manual corpus")
        return []

    def extract_features(self, file_path: Path, detector) -> Optional[TrainingExample]:
        """Extract features from a Python file using SlopDetector."""
        try:
            result = detector.analyze_file(str(file_path))

            # Count pattern severities
            pattern_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for issue in result.pattern_issues:
                pattern_counts[issue.severity] += 1

            # Calculate comment ratio
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            comment_lines = sum(1 for line in lines if line.strip().startswith("#"))
            comment_ratio = comment_lines / len(lines) if lines else 0.0

            # Calculate avg function length
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                functions = [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if functions:
                    total_func_lines = sum(
                        node.end_lineno - node.lineno
                        for node in functions
                        if hasattr(node, "end_lineno")
                    )
                    avg_function_length = total_func_lines / len(functions) if functions else 0.0
                else:
                    avg_function_length = 0.0
            except:
                avg_function_length = 0.0

            # Count cross-language and hallucination patterns
            cross_language_count = sum(
                1 for issue in result.pattern_issues if "cross-language" in issue.category.lower()
            )
            hallucination_count = sum(
                1 for issue in result.pattern_issues if "hallucination" in issue.category.lower()
            )

            return TrainingExample(
                file_path=str(file_path),
                label=-1,  # Will be set by caller
                ldr_score=result.ldr.ldr_score,
                bcr_score=result.bcr.bcr_score,
                ddc_score=result.ddc.usage_ratio,
                pattern_count_critical=pattern_counts["critical"],
                pattern_count_high=pattern_counts["high"],
                pattern_count_medium=pattern_counts["medium"],
                pattern_count_low=pattern_counts["low"],
                avg_function_length=avg_function_length,
                comment_ratio=comment_ratio,
                cross_language_patterns=cross_language_count,
                hallucination_count=hallucination_count,
                total_lines=result.ldr.total_lines,
                logic_lines=result.ldr.logic_lines,
                empty_lines=result.ldr.empty_lines,
                avg_complexity=result.bcr.avg_complexity,
            )
        except Exception as e:
            logger.error(f"Failed to extract features from {file_path}: {e}")
            return None

    def build_dataset(
        self, detector, good_limit: int = 1000, bad_limit: int = 500
    ) -> Tuple[List[TrainingExample], List[TrainingExample]]:
        """Build training dataset with good and bad examples."""
        logger.info("Collecting good code examples...")
        good_files = self.collect_good_data(max_files=good_limit)

        logger.info("Collecting bad code examples...")
        bad_files = self.collect_bad_data(max_files=bad_limit)

        logger.info("Extracting features from good code...")
        good_examples = []
        for file_path in good_files:
            example = self.extract_features(file_path, detector)
            if example:
                example.label = 0  # Clean code
                good_examples.append(example)

        logger.info("Extracting features from bad code...")
        bad_examples = []
        for file_path in bad_files:
            example = self.extract_features(file_path, detector)
            if example:
                example.label = 1  # Slop code
                bad_examples.append(example)

        logger.info(f"Dataset built: {len(good_examples)} good, {len(bad_examples)} bad")
        return good_examples, bad_examples

    def save_dataset(
        self,
        good_examples: List[TrainingExample],
        bad_examples: List[TrainingExample],
        output_path: Path,
    ):
        """Save dataset to JSON file."""
        dataset = {
            "good": [ex.to_dict() for ex in good_examples],
            "bad": [ex.to_dict() for ex in bad_examples],
            "metadata": {
                "total_examples": len(good_examples) + len(bad_examples),
                "good_count": len(good_examples),
                "bad_count": len(bad_examples),
                "feature_names": [
                    "ldr_score",
                    "bcr_score",
                    "ddc_score",
                    "pattern_count_critical",
                    "pattern_count_high",
                    "pattern_count_medium",
                    "pattern_count_low",
                    "avg_function_length",
                    "comment_ratio",
                    "cross_language_patterns",
                    "hallucination_count",
                    "total_lines",
                    "logic_lines",
                    "empty_lines",
                    "avg_complexity",
                ],
            },
        }

        with open(output_path, "w") as f:
            json.dump(dataset, f, indent=2)

        logger.info(f"Dataset saved to {output_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example usage
    from slop_detector.core import SlopDetector

    data_dir = Path("data/training")
    collector = TrainingDataCollector(data_dir)

    detector = SlopDetector()
    good_examples, bad_examples = collector.build_dataset(detector, good_limit=100, bad_limit=50)

    collector.save_dataset(good_examples, bad_examples, data_dir / "training_data.json")
    print(f"[+] Collected {len(good_examples)} good and {len(bad_examples)} bad examples")

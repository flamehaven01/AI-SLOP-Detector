"""
ML Training Pipeline

End-to-end: synthetic data generation -> feature extraction -> training -> evaluation.

Steps:
  1. Generate synthetic labeled samples (SyntheticGenerator)
  2. Analyze each sample with SlopDetector to extract features
  3. Train SlopClassifier (RandomForest + optional XGBoost ensemble)
  4. Evaluate on hold-out set
  5. Save model + emit training report

Usage:
    pipeline = MLPipeline(output_dir=Path("models"))
    report = pipeline.run(n_slop=500, n_clean=500)
    print(report.summary())
"""

from __future__ import annotations

import json
import logging
import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TrainingSample:
    """A single labeled training example."""

    label: int  # 0 = clean, 1 = slop
    features: Dict[str, float]
    source: str  # "synthetic_slop" | "synthetic_clean" | "real"


@dataclass
class PipelineReport:
    """Training pipeline results."""

    n_samples: int
    n_train: int
    n_test: int
    model_type: str
    metrics: Dict[str, Any]
    model_path: Optional[str]
    feature_importance: List[Tuple[str, float]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "[ML Pipeline Report]",
            f"  Samples: {self.n_samples} (train={self.n_train}, test={self.n_test})",
            f"  Model: {self.model_type}",
        ]
        for model_name, model_metrics in self.metrics.items():
            lines.append(f"  {model_name}:")
            if hasattr(model_metrics, "__dict__"):
                m = model_metrics
                lines.append(
                    f"    Acc={m.accuracy:.3f} Prec={m.precision:.3f} "
                    f"Rec={m.recall:.3f} F1={m.f1_score:.3f}"
                )
        if self.model_path:
            lines.append(f"  Saved: {self.model_path}")
        if self.feature_importance:
            lines.append("  Top Features:")
            for feat, imp in self.feature_importance[:5]:
                lines.append(f"    {feat}: {imp:.4f}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_samples": self.n_samples,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "model_type": self.model_type,
            "metrics": {
                k: (
                    {
                        "accuracy": v.accuracy,
                        "precision": v.precision,
                        "recall": v.recall,
                        "f1_score": v.f1_score,
                    }
                    if hasattr(v, "accuracy")
                    else v
                )
                for k, v in self.metrics.items()
            },
            "model_path": self.model_path,
            "feature_importance": self.feature_importance,
        }


def _extract_features(file_analysis) -> Dict[str, float]:
    """
    Extract feature vector from a FileAnalysis object.
    Must match SlopClassifier.FEATURE_NAMES.
    """
    ldr = getattr(file_analysis, "ldr", None)
    inflation = getattr(file_analysis, "inflation", None)
    ddc = getattr(file_analysis, "ddc", None)
    pattern_issues = getattr(file_analysis, "pattern_issues", [])

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    cross_lang = 0
    hallucination = 0
    god_function_count = 0
    dead_code_count = 0
    deep_nesting_count = 0

    for issue in pattern_issues:
        sev = getattr(getattr(issue, "severity", None), "value", "low")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        pid = getattr(issue, "pattern_id", "")
        if any(x in pid for x in ("js_push", "java_", "ruby_", "go_print", "csharp_", "php_")):
            cross_lang += 1
        if "hallucin" in pid:
            hallucination += 1
        if pid == "god_function":
            god_function_count += 1
        if pid == "dead_code":
            dead_code_count += 1
        if pid == "deep_nesting":
            deep_nesting_count += 1

    ldr_score = getattr(ldr, "ldr_score", 0.0) if ldr else 0.0
    total_lines = float(getattr(ldr, "total_lines", 0) if ldr else 0)
    logic_lines = float(getattr(ldr, "logic_lines", 0) if ldr else 0)
    empty_lines = float(getattr(ldr, "empty_lines", 0) if ldr else 0)

    raw_inflation = getattr(inflation, "inflation_score", 0.0) if inflation else 0.0
    # Normalize inflation to [0, 1]
    inflation_score = 0.0 if not math.isfinite(raw_inflation) else min(raw_inflation / 2.0, 1.0)
    avg_complexity = getattr(inflation, "avg_complexity", 1.0) if inflation else 1.0

    ddc_score = getattr(ddc, "usage_ratio", 1.0) if ddc else 1.0

    return {
        "ldr_score": ldr_score,
        "inflation_score": inflation_score,
        "ddc_score": ddc_score,
        "pattern_count_critical": float(severity_counts["critical"]),
        "pattern_count_high": float(severity_counts["high"]),
        "pattern_count_medium": float(severity_counts["medium"]),
        "pattern_count_low": float(severity_counts["low"]),
        "god_function_count": float(god_function_count),
        "dead_code_count": float(dead_code_count),
        "deep_nesting_count": float(deep_nesting_count),
        "avg_complexity": avg_complexity,
        "cross_language_patterns": float(cross_lang),
        "hallucination_count": float(hallucination),
        "total_lines": total_lines,
        "logic_lines": logic_lines,
        "empty_lines": empty_lines,
    }


class MLPipeline:
    """
    End-to-end ML training pipeline for slop detection.

    Generates synthetic data, trains SlopClassifier, saves model.
    """

    def __init__(self, output_dir: Path = Path("models")) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_on_real_data(
        self,
        dataset: str = "code_search_net",
        max_samples: int = 10_000,
        model_type: str = "ensemble",
        test_size: float = 0.2,
        save_model: bool = True,
        jsonl_path: Optional[str] = None,
    ) -> PipelineReport:
        """Train on real public code instead of synthetic samples.

        Args:
            dataset:     "code_search_net" | "the-stack" | "jsonl"
            max_samples: Cap per dataset (streaming-safe).
            model_type:  "random_forest" | "xgboost" | "ensemble"
            test_size:   Fraction held out for evaluation.
            save_model:  Write model to output_dir/slop_classifier_real.pkl
            jsonl_path:  Required when dataset="jsonl".

        Returns:
            PipelineReport with accuracy, feature importance, sample counts.
        """
        from slop_detector.ml.dataset_loader import DatasetLoader

        loader = DatasetLoader(max_samples=max_samples)

        logger.info("[Pipeline] Loading real data from: %s", dataset)
        if dataset == "code_search_net":
            real_samples = loader.load_codesearchnet()
        elif dataset == "the-stack":
            real_samples = loader.load_stack(max_samples=max_samples)
        elif dataset == "jsonl":
            if not jsonl_path:
                raise ValueError("jsonl_path required when dataset='jsonl'")
            real_samples = loader.load_jsonl(jsonl_path)
        else:
            raise ValueError(f"Unknown dataset: {dataset!r}")

        slop_count = sum(1 for s in real_samples if s.label == 1)
        clean_count = sum(1 for s in real_samples if s.label == 0)
        logger.info(
            "[Pipeline] Real data: %d total (%d slop, %d clean)",
            len(real_samples),
            slop_count,
            clean_count,
        )

        # Convert RealSample -> TrainingSample via feature extraction
        from slop_detector.core import SlopDetector

        detector = SlopDetector()
        samples: List[TrainingSample] = []
        for rs in real_samples:
            try:
                result = detector.analyze_code_string(rs.code, filename=f"<{rs.source}>")
                features = _extract_features(result)
                samples.append(
                    TrainingSample(
                        label=rs.label,
                        features=features,
                        source=rs.source,
                    )
                )
            except Exception as exc:
                logger.debug("[Pipeline] Skipping sample: %s", exc)
                continue

        logger.info("[Pipeline] Feature extraction complete: %d usable samples", len(samples))
        return self._train_from_samples(samples, model_type, test_size, save_model, suffix="_real")

    def run(
        self,
        n_slop: int = 500,
        n_clean: int = 500,
        model_type: str = "ensemble",
        test_size: float = 0.2,
        save_model: bool = True,
    ) -> PipelineReport:
        """
        Full pipeline execution.

        Args:
            n_slop:      Number of synthetic slop samples to generate.
            n_clean:     Number of synthetic clean samples to generate.
            model_type:  "random_forest" | "xgboost" | "ensemble".
            test_size:   Fraction for test split.
            save_model:  Whether to write model to disk.

        Returns:
            PipelineReport with metrics and feature importance.
        """
        try:
            from slop_detector.ml.classifier import SlopClassifier
        except ImportError as e:
            raise RuntimeError(f"Pipeline dependencies missing: {e}") from e

        logger.info("[Pipeline] Generating synthetic training data...")
        samples = self._generate_samples(n_slop, n_clean)
        logger.info(f"[Pipeline] Generated {len(samples)} samples")

        logger.info("[Pipeline] Extracting features via SlopDetector...")
        dataset = self._build_dataset(samples)
        logger.info(
            f"[Pipeline] Feature dataset ready: {len(dataset['good'])} clean, {len(dataset['bad'])} slop"
        )

        # Write dataset to temp file
        dataset_path = self.output_dir / "training_data.json"
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f)

        logger.info(f"[Pipeline] Training {model_type} classifier...")
        classifier = SlopClassifier(model_type=model_type)
        metrics = classifier.train(dataset_path, test_size=test_size)

        model_path = None
        if save_model:
            model_path = str(self.output_dir / "slop_classifier.pkl")
            classifier.save(Path(model_path))
            logger.info(f"[Pipeline] Model saved: {model_path}")

        # Feature importance from RF model
        feature_importance: List[Tuple[str, float]] = []
        if classifier.rf_model is not None:
            feature_importance = sorted(
                zip(classifier.FEATURE_NAMES, classifier.rf_model.feature_importances_),
                key=lambda x: x[1],
                reverse=True,
            )

        n_total = len(samples)
        n_test = int(n_total * test_size)
        n_train = n_total - n_test

        report = PipelineReport(
            n_samples=n_total,
            n_train=n_train,
            n_test=n_test,
            model_type=model_type,
            metrics=metrics,
            model_path=model_path,
            feature_importance=list(feature_importance),
        )

        # Save report
        report_path = self.output_dir / "pipeline_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)

        logger.info(f"[Pipeline] Complete. Report: {report_path}")
        return report

    def _train_from_samples(
        self,
        samples: List[TrainingSample],
        model_type: str,
        test_size: float,
        save_model: bool,
        suffix: str = "",
    ) -> PipelineReport:
        """Shared training logic for both synthetic and real-data pipelines."""
        from slop_detector.ml.classifier import SlopClassifier

        good = [s.features for s in samples if s.label == 0 and s.features]
        bad = [s.features for s in samples if s.label == 1 and s.features]
        dataset = {"good": good, "bad": bad}

        dataset_path = self.output_dir / f"training_data{suffix}.json"
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f)

        logger.info(
            "[Pipeline] Training %s classifier (%d clean, %d slop)...",
            model_type,
            len(good),
            len(bad),
        )
        classifier = SlopClassifier(model_type=model_type)
        metrics = classifier.train(dataset_path, test_size=test_size)

        model_path = None
        if save_model:
            model_path = str(self.output_dir / f"slop_classifier{suffix}.pkl")
            classifier.save(Path(model_path))
            logger.info("[Pipeline] Model saved: %s", model_path)

        feature_importance: List[Tuple[str, float]] = []
        if classifier.rf_model is not None:
            feature_importance = sorted(
                zip(classifier.FEATURE_NAMES, classifier.rf_model.feature_importances_),
                key=lambda x: x[1],
                reverse=True,
            )

        n_total = len(samples)
        n_test = int(n_total * test_size)
        report = PipelineReport(
            n_samples=n_total,
            n_train=n_total - n_test,
            n_test=n_test,
            model_type=model_type,
            metrics=metrics,
            model_path=model_path,
            feature_importance=list(feature_importance),
        )
        report_path = self.output_dir / f"pipeline_report{suffix}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info("[Pipeline] Complete. Report: %s", report_path)
        return report

    def _generate_samples(self, n_slop: int, n_clean: int) -> List[TrainingSample]:
        from slop_detector.ml.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        samples: List[TrainingSample] = []

        # Generate slop samples
        for _ in range(n_slop):
            gen.generate_slop_file()
            samples.append(TrainingSample(label=1, features={}, source="synthetic_slop"))

        # Generate clean samples
        for _ in range(n_clean):
            gen.generate_clean_file()
            samples.append(TrainingSample(label=0, features={}, source="synthetic_clean"))

        return samples

    def _build_dataset(self, samples: List[TrainingSample]) -> Dict[str, List[Dict[str, float]]]:
        """
        Analyze each synthetic sample and extract feature vectors.
        Returns {"good": [...], "bad": [...]} format for SlopClassifier.load_dataset.
        """
        from slop_detector.core import SlopDetector
        from slop_detector.ml.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        detector = SlopDetector()

        good: List[Dict[str, float]] = []
        bad: List[Dict[str, float]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            for idx, sample in enumerate(samples):
                is_slop = sample.label == 1
                try:
                    if is_slop:
                        code = gen.generate_slop_file()
                    else:
                        code = gen.generate_clean_file()

                    fpath = tmp_path / f"sample_{idx}.py"
                    fpath.write_text(code, encoding="utf-8")

                    analysis = detector.analyze_file(str(fpath))
                    features = _extract_features(analysis)

                    if is_slop:
                        bad.append(features)
                    else:
                        good.append(features)

                except Exception as e:
                    logger.debug(f"Sample {idx} skipped: {e}")

        return {"good": good, "bad": bad}

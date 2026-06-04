"""Tests for ML pipeline sample lifecycle and reporting."""

from types import SimpleNamespace

import pytest

from slop_detector.ml.pipeline import MLPipeline, TrainingSample


def test_generate_samples_preserves_generated_code(tmp_path):
    """Synthetic samples should keep the generated source for later analysis."""
    pipeline = MLPipeline(output_dir=tmp_path / "models")

    samples = pipeline._generate_samples(n_slop=1, n_clean=1)

    assert len(samples) == 2
    assert all(sample.code.strip() for sample in samples)


def test_build_dataset_uses_sample_code_without_regeneration(tmp_path, monkeypatch):
    """Provided sample.code should be used directly instead of re-generating code."""
    pipeline = MLPipeline(output_dir=tmp_path / "models")

    from slop_detector.ml import synthetic_generator as synthetic_generator_module

    def _unexpected(*args, **kwargs):
        raise AssertionError("SyntheticGenerator should not be called when sample.code exists")

    monkeypatch.setattr(
        synthetic_generator_module.SyntheticGenerator, "generate_slop_file", _unexpected
    )
    monkeypatch.setattr(
        synthetic_generator_module.SyntheticGenerator, "generate_clean_file", _unexpected
    )

    samples = [
        TrainingSample(
            label=0,
            features={},
            source="synthetic_clean",
            code="def clean():\n    return 1\n",
        ),
        TrainingSample(
            label=1,
            features={},
            source="synthetic_slop",
            code='def sloppy():\n    """enterprise-grade production-ready"""\n    pass\n',
        ),
    ]

    dataset = pipeline._build_dataset(samples)

    assert len(dataset["good"]) == 1
    assert len(dataset["bad"]) == 1


def test_train_from_samples_reports_usable_counts(tmp_path, monkeypatch):
    """Report counts should reflect usable feature rows, not requested sample rows."""
    pipeline = MLPipeline(output_dir=tmp_path / "models")

    from slop_detector.ml import classifier as classifier_module

    class FakeClassifier:
        FEATURE_NAMES = ["ldr_score", "inflation_score"]

        def __init__(self, model_type="ensemble"):
            self.model_type = model_type
            self.rf_model = SimpleNamespace(feature_importances_=[0.7, 0.3])

        def train(self, dataset_path, test_size=0.2):
            return {
                "fake": SimpleNamespace(
                    accuracy=1.0,
                    precision=1.0,
                    recall=1.0,
                    f1_score=1.0,
                )
            }

        def save(self, path):
            path.write_text("model", encoding="utf-8")

    monkeypatch.setattr(classifier_module, "SlopClassifier", FakeClassifier)

    samples = [
        TrainingSample(label=0, features={}, source="skipped"),
        TrainingSample(label=0, features={"ldr_score": 0.9}, source="good"),
        TrainingSample(label=1, features={"ldr_score": 0.1}, source="bad"),
    ]

    report = pipeline._train_from_samples(
        samples,
        model_type="random_forest",
        test_size=0.5,
        save_model=False,
    )

    assert report.n_samples == 2
    assert report.n_train == 1
    assert report.n_test == 1


def test_train_from_dataset_requires_both_classes(tmp_path):
    """Training should fail fast when only one class remains after filtering."""
    pipeline = MLPipeline(output_dir=tmp_path / "models")

    with pytest.raises(ValueError, match="at least one clean sample and one slop sample"):
        pipeline._train_from_dataset(
            {"good": [{"ldr_score": 0.9}], "bad": []},
            model_type="random_forest",
            test_size=0.2,
            save_model=False,
        )

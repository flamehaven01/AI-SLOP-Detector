#!/usr/bin/env python3
"""
ML-based Slop Classification Module
====================================
Machine learning models for slop detection with ensemble approach.

Models:
1. RandomForest - Baseline ensemble model
2. XGBoost - Gradient boosting for better accuracy
3. Ensemble - Combines multiple models for maximum accuracy

Performance Targets:
- Accuracy: >90%
- Precision: >85% (minimize false positives)
- Recall: >95% (catch most slop)
- F1-Score: >90%

Author: Flamehaven Labs
Version: 2.2.0
Date: 2026-01-08
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import (
        accuracy_score,
        precision_score,
        recall_score,
        f1_score,
        classification_report,
    )

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb

    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Model performance metrics."""

    accuracy: float
    precision: float
    recall: float
    f1_score: float

    def __str__(self) -> str:
        return (
            f"Accuracy: {self.accuracy:.3f}, "
            f"Precision: {self.precision:.3f}, "
            f"Recall: {self.recall:.3f}, "
            f"F1: {self.f1_score:.3f}"
        )


class SlopClassifier:
    """ML-based slop classifier with ensemble support."""

    FEATURE_NAMES = [
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
    ]

    def __init__(self, model_type: str = "ensemble"):
        """
        Initialize classifier.

        Args:
            model_type: "random_forest", "xgboost", or "ensemble"
        """
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn not installed. Run: pip install scikit-learn")

        self.model_type = model_type
        self.rf_model: Optional[RandomForestClassifier] = None
        self.xgb_model: Optional[xgb.XGBClassifier] = None
        self.is_trained = False

    def load_dataset(self, dataset_path: Path) -> Tuple[np.ndarray, np.ndarray]:
        """Load training dataset from JSON file."""
        with open(dataset_path, "r") as f:
            data = json.load(f)

        # Extract features and labels
        good_examples = data["good"]
        bad_examples = data["bad"]

        X = []
        y = []

        for example in good_examples:
            X.append([example[feat] for feat in self.FEATURE_NAMES])
            y.append(0)  # Clean

        for example in bad_examples:
            X.append([example[feat] for feat in self.FEATURE_NAMES])
            y.append(1)  # Slop

        return np.array(X), np.array(y)

    def train_random_forest(
        self, X_train: np.ndarray, y_train: np.ndarray
    ) -> RandomForestClassifier:
        """Train RandomForest classifier."""
        logger.info("Training RandomForest...")

        rf = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )

        rf.fit(X_train, y_train)

        # Feature importance
        feature_importance = sorted(
            zip(self.FEATURE_NAMES, rf.feature_importances_), key=lambda x: x[1], reverse=True
        )
        logger.info("Top 5 features:")
        for feat, importance in feature_importance[:5]:
            logger.info(f"  {feat}: {importance:.3f}")

        return rf

    def train_xgboost(
        self, X_train: np.ndarray, y_train: np.ndarray
    ) -> Optional[xgb.XGBClassifier]:
        """Train XGBoost classifier."""
        if not XGBOOST_AVAILABLE:
            logger.warning("XGBoost not available, skipping")
            return None

        logger.info("Training XGBoost...")

        xgb_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )

        xgb_model.fit(X_train, y_train)

        return xgb_model

    def train(self, dataset_path: Path, test_size: float = 0.2) -> Dict[str, ModelMetrics]:
        """
        Train model(s) on dataset.

        Args:
            dataset_path: Path to training data JSON
            test_size: Fraction of data for testing

        Returns:
            Dict mapping model name to metrics
        """
        logger.info(f"Loading dataset from {dataset_path}...")
        X, y = self.load_dataset(dataset_path)

        logger.info(f"Dataset: {len(X)} examples ({sum(y == 0)} clean, {sum(y == 1)} slop)")

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")

        metrics = {}

        # Train RandomForest
        self.rf_model = self.train_random_forest(X_train, y_train)
        rf_metrics = self.evaluate(self.rf_model, X_test, y_test)
        metrics["random_forest"] = rf_metrics
        logger.info(f"RandomForest: {rf_metrics}")

        # Train XGBoost
        if self.model_type in ["xgboost", "ensemble"] and XGBOOST_AVAILABLE:
            self.xgb_model = self.train_xgboost(X_train, y_train)
            if self.xgb_model:
                xgb_metrics = self.evaluate(self.xgb_model, X_test, y_test)
                metrics["xgboost"] = xgb_metrics
                logger.info(f"XGBoost: {xgb_metrics}")

        # Evaluate ensemble
        if self.model_type == "ensemble" and self.xgb_model:
            ensemble_metrics = self.evaluate_ensemble(X_test, y_test)
            metrics["ensemble"] = ensemble_metrics
            logger.info(f"Ensemble: {ensemble_metrics}")

        self.is_trained = True
        logger.info("Training complete!")

        return metrics

    def evaluate(self, model, X_test: np.ndarray, y_test: np.ndarray) -> ModelMetrics:
        """Evaluate model on test set."""
        y_pred = model.predict(X_test)

        return ModelMetrics(
            accuracy=accuracy_score(y_test, y_pred),
            precision=precision_score(y_test, y_pred, zero_division=0),
            recall=recall_score(y_test, y_pred, zero_division=0),
            f1_score=f1_score(y_test, y_pred, zero_division=0),
        )

    def evaluate_ensemble(self, X_test: np.ndarray, y_test: np.ndarray) -> ModelMetrics:
        """Evaluate ensemble (voting) on test set."""
        rf_pred = self.rf_model.predict(X_test)
        xgb_pred = self.xgb_model.predict(X_test)

        # Voting: majority wins
        ensemble_pred = ((rf_pred + xgb_pred) >= 1).astype(int)

        return ModelMetrics(
            accuracy=accuracy_score(y_test, ensemble_pred),
            precision=precision_score(y_test, ensemble_pred, zero_division=0),
            recall=recall_score(y_test, ensemble_pred, zero_division=0),
            f1_score=f1_score(y_test, ensemble_pred, zero_division=0),
        )

    def predict(self, features: Dict[str, float]) -> Tuple[float, float]:
        """
        Predict slop probability for a file.

        Args:
            features: Dictionary of feature name -> value

        Returns:
            (slop_probability, confidence)
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        # Convert features to vector
        X = np.array([[features[feat] for feat in self.FEATURE_NAMES]])

        if self.model_type == "random_forest":
            proba = self.rf_model.predict_proba(X)[0]
            return proba[1], max(proba)

        elif self.model_type == "xgboost":
            if not self.xgb_model:
                raise RuntimeError("XGBoost model not available")
            proba = self.xgb_model.predict_proba(X)[0]
            return proba[1], max(proba)

        elif self.model_type == "ensemble":
            rf_proba = self.rf_model.predict_proba(X)[0]
            xgb_proba = self.xgb_model.predict_proba(X)[0] if self.xgb_model else rf_proba

            # Weighted average
            ensemble_proba = 0.5 * rf_proba + 0.5 * xgb_proba

            return ensemble_proba[1], max(ensemble_proba)

        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

    def save(self, output_path: Path):
        """Save trained model to disk."""
        if not self.is_trained:
            raise RuntimeError("Model not trained")

        model_data = {
            "model_type": self.model_type,
            "rf_model": self.rf_model,
            "xgb_model": self.xgb_model,
            "feature_names": self.FEATURE_NAMES,
        }

        with open(output_path, "wb") as f:
            pickle.dump(model_data, f)

        logger.info(f"Model saved to {output_path}")

    def load(self, model_path: Path):
        """Load trained model from disk."""
        with open(model_path, "rb") as f:
            model_data = pickle.load(f)

        self.model_type = model_data["model_type"]
        self.rf_model = model_data["rf_model"]
        self.xgb_model = model_data["xgb_model"]
        self.is_trained = True

        logger.info(f"Model loaded from {model_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example usage
    classifier = SlopClassifier(model_type="ensemble")

    # Train (requires dataset)
    dataset_path = Path("data/training/training_data.json")
    if dataset_path.exists():
        metrics = classifier.train(dataset_path)

        print("\n[+] Training Results:")
        for model_name, model_metrics in metrics.items():
            print(f"  {model_name}: {model_metrics}")

        # Save model
        classifier.save(Path("models/slop_classifier.pkl"))
    else:
        print(f"[-] Dataset not found: {dataset_path}")
        print("Run training_data.py first to collect data")

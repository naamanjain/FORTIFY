from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)


def evaluate_binary_predictions(y_true, probabilities, threshold: float = 0.5) -> dict[str, Any]:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    pred = (p >= threshold).astype(int)

    result: dict[str, Any] = {
        "samples": int(len(y)),
        "positive_count": int(y.sum()),
        "negative_count": int((y == 0).sum()),
        "positive_rate": float(y.mean()) if len(y) else None,
        "prediction_threshold": float(threshold),
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y, p)),
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
    }
    if np.unique(y).size == 2:
        result["roc_auc"] = float(roc_auc_score(y, p))
        result["average_precision"] = float(average_precision_score(y, p))
    else:
        result["roc_auc"] = None
        result["average_precision"] = None
    return result

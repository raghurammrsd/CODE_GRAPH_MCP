"""Retrieval Quality Metrics: Precision, Recall, F1, MRR, NDCG, and Path Accuracy."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PathAccuracy:
    path_recall: float
    path_precision: float
    missing_nodes: tuple[str, ...]
    extra_nodes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path_recall": round(self.path_recall, 4),
            "path_precision": round(self.path_precision, 4),
            "missing_nodes": list(self.missing_nodes),
            "extra_nodes": list(self.extra_nodes),
        }


@dataclass(frozen=True)
class RetrievalScores:
    precision: float
    recall: float
    f1: float
    mrr: float
    ndcg: float

    def as_dict(self) -> dict[str, float]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "mrr": round(self.mrr, 4),
            "ndcg": round(self.ndcg, 4),
        }


def calculate_precision_recall(
    retrieved: set[str],
    expected: set[str],
) -> tuple[float, float]:
    """Calculate standard precision and recall."""
    if not retrieved and not expected:
        return 1.0, 1.0
    if not retrieved:
        return 0.0, 0.0
    if not expected:
        return 1.0, 1.0

    true_positives = len(retrieved & expected)
    precision = true_positives / len(retrieved)
    recall = true_positives / len(expected)
    return round(precision, 4), round(recall, 4)


def calculate_mrr(ranked_items: list[str], ground_truth: set[str]) -> float:
    """Mean Reciprocal Rank of the first relevant item in ranked list."""
    if not ground_truth:
        return 1.0
    for idx, item in enumerate(ranked_items, start=1):
        if item in ground_truth or item.split(".")[-1] in ground_truth:
            return round(1.0 / idx, 4)
    return 0.0


def calculate_ndcg(ranked_items: list[str], ground_truth: set[str], k: int = 10) -> float:
    """Normalized Discounted Cumulative Gain at rank k."""
    if not ground_truth:
        return 1.0
    items_k = ranked_items[:k]
    dcg = 0.0
    for idx, item in enumerate(items_k, start=1):
        rel = 1.0 if (item in ground_truth or item.split(".")[-1] in ground_truth) else 0.0
        dcg += rel / math.log2(idx + 1)

    # Ideal DCG: all relevant items ranked at the top
    ideal_hits = min(len(ground_truth), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    if idcg == 0.0:
        return 1.0
    return round(dcg / idcg, 4)


def calculate_retrieval_scores(
    ranked_items: list[str],
    ground_truth: set[str],
    k: int = 10,
) -> RetrievalScores:
    retrieved_set = set(ranked_items)
    prec, rec = calculate_precision_recall(retrieved_set, ground_truth)
    f1 = round(2 * (prec * rec) / max(prec + rec, 1e-6), 4) if (prec + rec) > 0 else 0.0
    mrr = calculate_mrr(ranked_items, ground_truth)
    ndcg = calculate_ndcg(ranked_items, ground_truth, k=k)
    return RetrievalScores(
        precision=prec,
        recall=rec,
        f1=f1,
        mrr=mrr,
        ndcg=ndcg,
    )


def calculate_path_accuracy(
    retrieved_nodes: list[str],
    expected_path_nodes: tuple[str, ...],
) -> PathAccuracy:
    """Evaluate path node sequence for TRACE tasks."""
    if not expected_path_nodes:
        return PathAccuracy(1.0, 1.0, (), ())

    retrieved_set = set(retrieved_nodes)
    expected_set = set(expected_path_nodes)

    missing = tuple(n for n in expected_path_nodes if n not in retrieved_set)
    extra = tuple(n for n in retrieved_nodes if n not in expected_set)

    hits = len(expected_set & retrieved_set)
    recall = round(hits / len(expected_set), 4)
    precision = round(hits / max(len(retrieved_set), 1), 4)

    return PathAccuracy(
        path_recall=recall,
        path_precision=precision,
        missing_nodes=missing,
        extra_nodes=extra,
    )

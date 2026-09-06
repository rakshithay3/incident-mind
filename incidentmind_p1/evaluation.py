"""Evaluation metrics required by the P1 screenshots."""

from __future__ import annotations

from typing import Iterable, List, Optional

from .contracts import EvaluationMetrics, NodeScore, precision_at_k


def evaluate_ranking(scores: Iterable[NodeScore], root_cause: Optional[str]) -> EvaluationMetrics:
    ranked = sorted(scores, key=lambda score: score.rank)
    service_ids = [score.service_id for score in ranked]
    if root_cause in service_ids:
        mttd = service_ids.index(root_cause) + 1
    else:
        mttd = len(service_ids) + 1
    return EvaluationMetrics(
        pr_at_1=precision_at_k(service_ids, root_cause, 1),
        pr_at_3=precision_at_k(service_ids, root_cause, 3),
        pr_at_5=precision_at_k(service_ids, root_cause, 5),
        mttd_steps=mttd,
    )

"""Fast anomaly scoring path for GNN embeddings.

The production version should feed GraphSAGE embeddings into this scorer. For
early RCAEval work, this module also provides a deterministic feature projection
so tests and dashboard mocks can run before heavy ML dependencies are installed.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Sequence

from .contracts import DEFAULT_EMBEDDING_DIM, FEATURES, IncidentGraph, NodeScore


class AnomalyScorer:
    def __init__(
        self,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        alpha: float = 0.2,
        threshold: float = 0.35,
        feature_names: Sequence[str] = FEATURES,
    ) -> None:
        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be positive")
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.embedding_dim = embedding_dim
        self.alpha = alpha
        self.threshold = threshold
        self.feature_names = tuple(feature_names)
        self.baselines: Dict[str, List[float]] = {}

    def embed_features(self, features: Sequence[float]) -> List[float]:
        if not features:
            return [0.0] * self.embedding_dim
        projected: List[float] = []
        for index in range(self.embedding_dim):
            value = features[index % len(features)]
            neighbor = features[(index + 1) % len(features)]
            projected.append(math.tanh((value * 0.01) + (neighbor * 0.003) + ((index % 7) * 0.01)))
        return projected

    def update_baseline(self, service_id: str, embedding: Sequence[float]) -> None:
        existing = self.baselines.get(service_id)
        if existing is None:
            self.baselines[service_id] = list(embedding)
            return
        self.baselines[service_id] = [
            (self.alpha * float(new)) + ((1.0 - self.alpha) * float(old))
            for old, new in zip(existing, embedding)
        ]

    def cosine_distance(self, embedding: Sequence[float], baseline: Sequence[float]) -> float:
        dot = sum(float(a) * float(b) for a, b in zip(embedding, baseline))
        norm_a = math.sqrt(sum(float(a) * float(a) for a in embedding))
        norm_b = math.sqrt(sum(float(b) * float(b) for b in baseline))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return 1.0 - (dot / (norm_a * norm_b))

    def fit_normal(self, graphs: Iterable[IncidentGraph]) -> None:
        for graph in graphs:
            for node in graph.nodes:
                if node.label == "normal" or node.service_id != graph.root_cause:
                    self.update_baseline(node.service_id, self.embed_features(node.feature_vector(self.feature_names)))

    def score_graph(self, graph: IncidentGraph) -> List[NodeScore]:
        raw_scores = []
        for node in graph.nodes:
            embedding = self.embed_features(node.feature_vector(self.feature_names))
            baseline = self.baselines.get(node.service_id)
            if baseline is None:
                baseline = [0.0] * self.embedding_dim
            score = self.cosine_distance(embedding, baseline)
            raw_scores.append((node.service_id, score))
        ranked = sorted(raw_scores, key=lambda item: item[1], reverse=True)
        return [
            NodeScore(
                service_id=service_id,
                anomaly_score=score,
                embedding_dim=self.embedding_dim,
                status="anomalous" if score >= self.threshold else "normal",
                rank=rank,
            )
            for rank, (service_id, score) in enumerate(ranked, start=1)
        ]


def scores_by_service(scores: Iterable[NodeScore]) -> Mapping[str, NodeScore]:
    return {score.service_id: score for score in scores}

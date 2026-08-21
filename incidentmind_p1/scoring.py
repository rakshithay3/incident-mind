"""Anomaly scoring for service-dependency graphs.

Two complementary signals are supported:

1. Peer z-score (default, no history required): within a single incident
   snapshot, score each service by how many standard deviations it deviates
   from its *peers in the same graph* across CPU/memory/latency/error-rate/
   p99 latency. This is the z-score statistical-thresholding design we
   settled on after dropping the CLIP metrics agent, and it works on a
   single incident with no prior "normal" window -- exactly what RCAEval
   incident files and live ShopMind snapshots both look like.

2. Historical baseline (opt-in, via fit_normal/update_baseline): once we
   have a rolling "normal" embedding per service from prior time windows,
   cosine distance against that baseline is a sharper signal than peer
   z-score alone. This path is kept for when the GraphSAGE embedding
   pipeline is wired in, but it is NOT used unless a baseline has actually
   been fitted for a given service -- previously the code silently fell
   back to an all-zero baseline and produced meaningless all-zero scores
   for every node.
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, Iterable, List, Mapping, Sequence

from .contracts import DEFAULT_EMBEDDING_DIM, FEATURES, IncidentGraph, NodeScore


class AnomalyScorer:
    def __init__(
        self,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        alpha: float = 0.2,
        threshold: float = 1.5,
        feature_names: Sequence[str] = FEATURES,
    ) -> None:
        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be positive")
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.embedding_dim = embedding_dim
        self.alpha = alpha
        # NOTE: threshold is on an RMS z-score scale (roughly "how many std
        # devs off, averaged across features"), not on the old 0-2 cosine
        # distance scale. 1.5 means "on average ~1.5 std devs off across
        # features" counts as anomalous.
        self.threshold = threshold
        self.feature_names = tuple(feature_names)
        self.baselines: Dict[str, List[float]] = {}

    # ------------------------------------------------------------------
    # Embedding placeholder (kept for future GraphSAGE swap-in and for the
    # historical-baseline path below; not used by the default peer z-score
    # scoring path).
    # ------------------------------------------------------------------
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
        """Fit historical per-service baselines from graphs known to be normal.

        Only call this with incidents (or pre-incident windows) where the
        service was NOT the root cause and was behaving normally. Fitting a
        baseline from the same graph you are about to score defeats the
        purpose (baseline collapses to current features) -- use a separate
        historical window instead.
        """
        for graph in graphs:
            for node in graph.nodes:
                if node.service_id == graph.root_cause:
                    continue
                self.update_baseline(node.service_id, self.embed_features(node.feature_vector(self.feature_names)))

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def _peer_zscores(self, graph: IncidentGraph) -> Dict[str, float]:
        """RMS z-score per service, computed against its peers in this graph."""
        per_feature_values: Dict[str, List[float]] = {name: [] for name in self.feature_names}
        for node in graph.nodes:
            vector = node.feature_vector(self.feature_names)
            for name, value in zip(self.feature_names, vector):
                per_feature_values[name].append(value)

        means = {name: statistics.fmean(values) for name, values in per_feature_values.items()}
        stdevs = {
            name: (statistics.pstdev(values) if len(values) > 1 else 0.0)
            for name, values in per_feature_values.items()
        }

        scores: Dict[str, float] = {}
        for node in graph.nodes:
            vector = node.feature_vector(self.feature_names)
            squared_z = []
            for name, value in zip(self.feature_names, vector):
                std = stdevs[name]
                z = (value - means[name]) / std if std > 0 else 0.0
                squared_z.append(z * z)
            scores[node.service_id] = math.sqrt(statistics.fmean(squared_z)) if squared_z else 0.0
        return scores

    def score_graph(self, graph: IncidentGraph) -> List[NodeScore]:
        peer_scores = self._peer_zscores(graph)
        raw_scores = []
        for node in graph.nodes:
            baseline = self.baselines.get(node.service_id)
            if baseline is not None:
                # Historical baseline available: use it, it's a sharper signal.
                embedding = self.embed_features(node.feature_vector(self.feature_names))
                score = self.cosine_distance(embedding, baseline)
            else:
                # No history yet -- fall back to peer z-score within this graph.
                score = peer_scores[node.service_id]
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

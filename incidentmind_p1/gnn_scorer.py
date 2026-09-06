"""Adapter exposing a trained GraphSAGE encoder through the same
`score_graph(incident) -> List[NodeScore]` interface as scoring.AnomalyScorer.

DispatchEnv, PPODispatcher, and pipeline.run_inference all take a scorer
object and only ever call `.score_graph(incident)` on it -- they were built
duck-typed against that interface from the start, so wiring the real GNN in
means constructing a GraphSAGEScorer and passing it wherever an AnomalyScorer
used to go. No changes needed to dispatch.py, ppo_env.py, or pipeline.py.
"""

from __future__ import annotations

from typing import List

from .contracts import DEFAULT_EMBEDDING_DIM, IncidentGraph, NodeScore
from .training import FeatureStats, GraphSAGEEncoder, score_incident


class GraphSAGEScorer:
    """Wraps a trained (encoder, stats) pair with the AnomalyScorer interface.

    stats MUST be the FeatureStats returned alongside this encoder from
    train_graphsage() (or load_checkpoint()) -- never refit on the incident
    being scored, exactly like AnomalyScorer's own historical-baseline path
    warns against.
    """

    def __init__(
        self,
        encoder: GraphSAGEEncoder,
        stats: FeatureStats,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        threshold: float = 0.5,
    ) -> None:
        self.encoder = encoder
        self.stats = stats
        self.embedding_dim = embedding_dim
        self.threshold = threshold

    def score_graph(self, incident: IncidentGraph) -> List[NodeScore]:
        ranked = score_incident(self.encoder, incident, stats=self.stats)
        return [
            NodeScore(
                service_id=service_id,
                anomaly_score=probability,
                embedding_dim=self.embedding_dim,
                status="anomalous" if probability >= self.threshold else "normal",
                rank=rank,
            )
            for rank, (service_id, probability) in enumerate(ranked, start=1)
        ]

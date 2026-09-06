"""End-to-end inference pipeline for P1 handoff output."""

from __future__ import annotations

from .contracts import DispatchOutput
from .dispatch import PPODispatcher
from .evaluation import evaluate_ranking
from .loader import load_incident
from .scoring import AnomalyScorer


def run_inference(incident_path: str, scorer: AnomalyScorer | None = None) -> DispatchOutput:
    graph = load_incident(incident_path)
    scorer = scorer or AnomalyScorer()
    scores = scorer.score_graph(graph)
    dispatch = PPODispatcher().choose(scores)
    metrics = evaluate_ranking(scores, graph.root_cause)
    return DispatchOutput(
        incident_id=graph.incident_id,
        timestamp=graph.timestamp,
        nodes=scores,
        ppo_dispatch=dispatch,
        metrics=metrics,
    )

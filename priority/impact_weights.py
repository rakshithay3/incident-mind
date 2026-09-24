"""
priority/impact_weights.py -- static 3-tier criticality weighting for
priority-weighted dispatch (extension item 2).

priority_score = anomaly_score * impact_weight

This is a re-ranking nudge, not an override: raw anomaly_score values are
left untouched (PPO's observation vector still sees true GraphSAGE
probabilities at each rank slot), only .rank is reassigned based on the
weighted order. The GraphSAGE anomaly signal remains dominant; impact
weight breaks ties and nudges ranking toward business-critical services.
"""

import dataclasses

from incidentmind_p1.contracts import NodeScore  # noqa: F401  (re-exported type)

TIER_WEIGHTS = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

DEFAULT_WEIGHT = 0.6

SERVICE_TIERS = {
    "auth-service": "high",
    "payment-service": "high",
    "order-service": "high",
    "postgres-primary": "high",
    "user-service": "medium",
    "inventory-service": "medium",
    "api-gateway": "medium",
    "cache": "medium",
    "postgres-replica": "medium",
    "search-service": "low",
    "notification-service": "low",
    "frontend": "low",
}


def get_impact_weight(service_id):
    tier = SERVICE_TIERS.get(service_id)
    return TIER_WEIGHTS.get(tier, DEFAULT_WEIGHT)


class PriorityWeightedScorer:
    """Wraps any object exposing score_graph(incident) -> List[NodeScore]
    and re-ranks its output by priority_score = anomaly_score * impact_weight.

    Duck-typed against the same interface as GraphSAGEScorer / AnomalyScorer,
    so it drops in wherever a scorer object is expected -- no changes needed
    to dispatch.py, ppo_env.py, or pipeline.py.
    """

    def __init__(self, base_scorer):
        self.base_scorer = base_scorer

    def score_graph(self, incident):
        raw_scores = self.base_scorer.score_graph(incident)
        weighted = []
        for s in raw_scores:
            weight = get_impact_weight(s.service_id)
            priority_score = s.anomaly_score * weight
            weighted.append((priority_score, s))

        weighted.sort(key=lambda pair: pair[0], reverse=True)

        result = []
        for new_rank, (priority_score, s) in enumerate(weighted, start=1):
            # dataclasses.replace keeps every other field (instance_id in
            # particular) -- rebuilding NodeScore by hand used to drop it.
            result.append(dataclasses.replace(s, rank=new_rank))
        return result

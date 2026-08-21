"""PPO dispatch interface and Baseline C greedy dispatch."""

from __future__ import annotations

from typing import Iterable, Optional

from .contracts import DispatchAction, DispatchDecision, NodeScore


AGENT_TYPES = ("log", "metrics", "code")


def greedy_baseline_c(scores: Iterable[NodeScore], agent_type: str = "log") -> DispatchDecision:
    ranked = sorted(scores, key=lambda score: score.rank)
    if not ranked:
        raise ValueError("cannot dispatch without node scores")
    top = ranked[0]
    confidence = max(0.0, min(1.0, top.anomaly_score / 2.0))
    return DispatchDecision(
        step=1,
        action=DispatchAction(agent_type=agent_type, target_service=top.service_id),
        policy_confidence=confidence,
    )


class PPODispatcher:
    """Thin adapter for trained PPO policies.

    Real Stable-Baselines3 policies can be wrapped by passing an object with a
    `predict(observation, deterministic=True)` method. Until then, the adapter
    falls back to Baseline C so downstream consumers can integrate early.
    """

    def __init__(self, policy: Optional[object] = None) -> None:
        self.policy = policy

    def choose(self, scores: Iterable[NodeScore]) -> DispatchDecision:
        ranked = sorted(scores, key=lambda score: score.rank)
        if self.policy is None:
            return greedy_baseline_c(ranked)
        # The trained-policy observation is deliberately left as ranked anomaly
        # scores. The training module owns the final tensorization.
        action_index, _ = self.policy.predict([score.anomaly_score for score in ranked], deterministic=True)
        action_index = int(action_index)
        agent_type = AGENT_TYPES[action_index % len(AGENT_TYPES)]
        service = ranked[(action_index // len(AGENT_TYPES)) % len(ranked)].service_id
        return DispatchDecision(
            step=1,
            action=DispatchAction(agent_type=agent_type, target_service=service),
            policy_confidence=1.0,
        )

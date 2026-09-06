"""PPO dispatch interface and Baseline C greedy dispatch.

Action space is fixed at MAX_SERVICES=12 regardless of the incident's actual
node count, so the same trained PPO policy transfers across RE1 (Online
Boutique, up to 11 nodes) and ShopMind (12 nodes) without retraining or
resizing anything -- this is what lets the RL orchestrator ride along with
the inductive GraphSAGE story instead of undermining it. Slots beyond the
incident's actual node count wrap via modulo (see decode_action /
build_observation), never crash, and never require the action space itself
to change shape.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set

from .contracts import DispatchAction, DispatchDecision, NodeScore


AGENT_TYPES = ("log", "metrics", "code")
MAX_SERVICES = 12
ACTION_SPACE_SIZE = MAX_SERVICES * len(AGENT_TYPES)  # 36


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


def decode_action(action_index: int, ranked_scores: Sequence[NodeScore]) -> DispatchAction:
    """Map a flat action index in [0, ACTION_SPACE_SIZE) to a DispatchAction.

    Slot = action_index % MAX_SERVICES selects a position in the *rank-ordered*
    node list (slot 0 = most anomalous). Agent index = action_index //
    MAX_SERVICES selects which agent type. The slot wraps via modulo against
    the incident's actual node count, so an 11-node RE1 incident and a
    12-node ShopMind incident both decode cleanly against the same fixed
    36-action space -- no resizing, no retraining.
    """
    n = len(ranked_scores)
    if n == 0:
        raise ValueError("cannot decode action without ranked scores")
    if not 0 <= action_index < ACTION_SPACE_SIZE:
        raise ValueError(f"action_index out of range [0, {ACTION_SPACE_SIZE}): {action_index}")
    slot = action_index % MAX_SERVICES
    agent_idx = action_index // MAX_SERVICES
    service_id = ranked_scores[slot % n].service_id
    return DispatchAction(agent_type=AGENT_TYPES[agent_idx], target_service=service_id)


def build_observation(ranked_scores: Sequence[NodeScore], visited: Set[str]) -> List[float]:
    """Build the fixed-length PPO observation vector.

    Layout: MAX_SERVICES anomaly scores (rank-ordered, zero-padded past the
    incident's actual node count) followed by MAX_SERVICES visited one-hot
    flags in the same slot order. Always length 24 regardless of incident
    size, which is what makes the fixed action/observation space work across
    RE1 and ShopMind topologies.
    """
    scores_vec = [0.0] * MAX_SERVICES
    visited_vec = [0.0] * MAX_SERVICES
    for slot, score in enumerate(ranked_scores[:MAX_SERVICES]):
        scores_vec[slot] = float(score.anomaly_score)
        visited_vec[slot] = 1.0 if score.service_id in visited else 0.0
    return scores_vec + visited_vec


class PPODispatcher:
    """Thin adapter for trained PPO policies.

    Real Stable-Baselines3 policies can be wrapped by passing an object with a
    `predict(observation, deterministic=True)` method -- the same object
    `PPO.load(...)` returns. Until a policy is supplied, the adapter falls
    back to Baseline C so downstream consumers can integrate early.
    """

    def __init__(self, policy: Optional[object] = None) -> None:
        self.policy = policy

    def choose(
        self,
        scores: Iterable[NodeScore],
        visited: Optional[Set[str]] = None,
        step: int = 1,
    ) -> DispatchDecision:
        ranked = sorted(scores, key=lambda score: score.rank)
        if not ranked:
            raise ValueError("cannot dispatch without node scores")
        if self.policy is None:
            return greedy_baseline_c(ranked)
        visited = visited or set()
        observation = build_observation(ranked, visited)
        action_index, _ = self.policy.predict(observation, deterministic=True)
        action = decode_action(int(action_index), ranked)
        return DispatchDecision(step=step, action=action, policy_confidence=1.0)

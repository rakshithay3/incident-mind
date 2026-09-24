"""PPO dispatch interface and Baseline A/B/C dispatch strategies.

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

import random
from typing import Any, Iterable, List, Optional, Sequence, Set

from .contracts import DispatchAction, DispatchDecision, NodeScore


AGENT_TYPES = ("log", "metrics", "code")
MAX_SERVICES = 12
ACTION_SPACE_SIZE = MAX_SERVICES * len(AGENT_TYPES)  # 36


def _node_key(score: NodeScore) -> Any:
    """Identity used for visited-tracking. A plain service_id is ambiguous
    once nodes from multiple instances are mixed into one ranked list (every
    ShopMind instance runs the same service names), so a node tagged with
    instance_id is keyed by (instance_id, service_id) instead. Single-instance
    NodeScores (instance_id=None, the default) key by service_id alone,
    matching every existing caller's plain-string visited sets unchanged."""
    return (score.instance_id, score.service_id) if score.instance_id is not None else score.service_id


def greedy_baseline_c(
    scores: Iterable[NodeScore], agent_type: str = "log", visited: Optional[Set] = None
) -> DispatchDecision:
    ranked = sorted(scores, key=lambda score: score.rank)
    if visited:
        ranked = [s for s in ranked if _node_key(s) not in visited]
    if not ranked:
        raise ValueError("cannot dispatch without node scores")
    top = ranked[0]
    confidence = max(0.0, min(1.0, top.anomaly_score / 2.0))
    return DispatchDecision(
        step=1,
        action=DispatchAction(agent_type=agent_type, target_service=top.service_id, instance_id=top.instance_id),
        policy_confidence=confidence,
    )


def baseline_a(
    scores: Iterable[NodeScore],
    agent_type: str = "log",
    visited: Optional[Set] = None,
    seed: int = 0,
) -> DispatchDecision:
    """Baseline A: uniformly random dispatch among anomalous, not-yet-visited
    nodes -- no ranking or score signal used at all, the floor a learned
    policy has to beat.

    Seeded so a given (seed, visited) state always dispatches the same node
    -- reproducible across runs -- but the seed is combined with len(visited)
    so successive steps within one episode draw independently instead of
    repeating whatever index the same seed picks whenever the candidate
    count happens to match.
    """
    candidates = [s for s in scores if s.status == "anomalous"]
    if visited:
        candidates = [s for s in candidates if _node_key(s) not in visited]
    if not candidates:
        raise ValueError("cannot dispatch without anomalous node scores")
    # Canonicalize onto a content-derived order before drawing, so the pick
    # depends only on WHICH services are anomalous, never on whatever order
    # the caller happened to supply them in (e.g. score-descending rank
    # order) -- otherwise the random draw's index would implicitly
    # correlate with whatever ordering convention the caller used.
    candidates.sort(key=_node_key)
    rng = random.Random(seed + len(visited or ()))
    pick = rng.choice(candidates)
    confidence = max(0.0, min(1.0, pick.anomaly_score / 2.0))
    return DispatchDecision(
        step=1,
        action=DispatchAction(agent_type=agent_type, target_service=pick.service_id, instance_id=pick.instance_id),
        policy_confidence=confidence,
    )


def baseline_b(
    scores: Iterable[NodeScore],
    agent_type: str = "log",
    visited: Optional[Set] = None,
) -> DispatchDecision:
    """Baseline B: threshold-only dispatch -- walk scores in arrival order
    (whatever order the scorer emitted them in, NOT sorted by rank or
    anomaly_score) and dispatch the first not-yet-visited node crossing the
    anomaly threshold (status == "anomalous", the same flag GraphSAGEScorer
    already sets). No priority/score-based ranking is used to pick among the
    candidates that cross threshold -- only their arrival order does.
    """
    for s in scores:
        if s.status != "anomalous":
            continue
        if visited and _node_key(s) in visited:
            continue
        confidence = max(0.0, min(1.0, s.anomaly_score / 2.0))
        return DispatchDecision(
            step=1,
            action=DispatchAction(agent_type=agent_type, target_service=s.service_id, instance_id=s.instance_id),
            policy_confidence=confidence,
        )
    raise ValueError("cannot dispatch without anomalous node scores")


def baseline_d_sequential(
    scores: Iterable[NodeScore], agent_type: str = "log", visited: Optional[Set] = None
) -> DispatchDecision:
    """Baseline D: sequential greedy -- the top-ranked service not yet
    visited. Over a step budget B this inspects ranks 1..B in order, so its
    solve rate equals the scorer's PR@B. It is the natural "engineer walks
    down the ranked list" baseline; Baseline C (no memory) is not, because it
    can never use steps 2..B.
    """
    return greedy_baseline_c(scores, agent_type=agent_type, visited=visited or set())


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
    node = ranked_scores[slot % n]
    return DispatchAction(agent_type=AGENT_TYPES[agent_idx], target_service=node.service_id, instance_id=node.instance_id)


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
        visited_vec[slot] = 1.0 if _node_key(score) in visited else 0.0
    return scores_vec + visited_vec


class PPODispatcher:
    """Thin adapter for trained PPO policies.

    Real Stable-Baselines3 policies can be wrapped by passing an object with a
    `predict(observation, deterministic=True)` method -- the same object
    `PPO.load(...)` returns. Until a policy is supplied, the adapter falls
    back to Baseline C so downstream consumers can integrate early.
    """

    def __init__(self, policy: Optional[object] = None, mask_visited: bool = False) -> None:
        """mask_visited=True applies an inference-time action mask: among
        actions whose decoded node is not yet visited, take the one the
        policy rates most probable. Needs an SB3 policy (uses
        policy.policy.get_distribution); the trained weights are unchanged.
        With nothing visited it is identical to deterministic predict()."""
        self.policy = policy
        self.mask_visited = mask_visited

    def choose(
        self,
        scores: Iterable[NodeScore],
        visited: Optional[Set] = None,
        step: int = 1,
    ) -> DispatchDecision:
        ranked = sorted(scores, key=lambda score: score.rank)
        if not ranked:
            raise ValueError("cannot dispatch without node scores")
        visited = visited or set()
        if self.policy is None:
            return greedy_baseline_c(ranked, visited=visited)
        observation = build_observation(ranked, visited)
        if self.mask_visited and visited and hasattr(self.policy, "policy"):
            return self._choose_masked(ranked, observation, visited, step)
        action_index, _ = self.policy.predict(observation, deterministic=True)
        action = decode_action(int(action_index), ranked)
        return DispatchDecision(step=step, action=action, policy_confidence=1.0)

    def _choose_masked(self, ranked, observation, visited, step: int) -> DispatchDecision:
        import numpy as np

        sb3_policy = self.policy.policy
        obs_tensor, _ = sb3_policy.obs_to_tensor(np.asarray(observation, dtype=np.float32))
        probs = sb3_policy.get_distribution(obs_tensor).distribution.probs[0].detach().cpu().numpy()
        best_index, best_prob, total = None, -1.0, 0.0
        for index in range(ACTION_SPACE_SIZE):
            node = ranked[(index % MAX_SERVICES) % len(ranked)]
            if _node_key(node) in visited:
                continue
            total += float(probs[index])
            if probs[index] > best_prob:
                best_index, best_prob = index, float(probs[index])
        if best_index is None:  # everything visited: fall back to the unmasked choice
            best_index = int(np.argmax(probs))
            best_prob, total = float(probs[best_index]), 1.0
        action = decode_action(best_index, ranked)
        return DispatchDecision(step=step, action=action, policy_confidence=best_prob / total if total else 0.0)

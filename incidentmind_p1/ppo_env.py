"""Gymnasium environment for training the PPO dispatch policy.

The environment wraps a set of IncidentGraphs (RE1 training incidents --
NEVER ShopMind, which is held out for post-training generalization
validation only). Each episode samples one incident, scores it with the
GNN/peer-z-score AnomalyScorer, and lets the agent choose (agent_type,
target_service) actions until it names the true root cause or exhausts the
step budget.

Reward shaping (fixed, matches the design already agreed for this project):
  +1.0  solving the incident (target_service == root_cause)
  -0.1  every step taken
  -0.5  re-investigating an already-visited service
  budget: 5 steps per episode

State/action space is fixed at MAX_SERVICES=12 (see dispatch.py) regardless
of the sampled incident's actual node count, so the same trained policy runs
unmodified on RE1 (<=12 nodes) and ShopMind (12 nodes) at inference time.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("install gymnasium to use DispatchEnv") from exc

from .contracts import IncidentGraph
from .dispatch import ACTION_SPACE_SIZE, MAX_SERVICES, build_observation, decode_action
from .scoring import AnomalyScorer

OBSERVATION_DIM = MAX_SERVICES * 2  # anomaly scores + visited one-hot
STEP_BUDGET = 5
STEP_PENALTY = -0.1
REPEAT_PENALTY = -0.5
SOLVE_REWARD = 1.0


class DispatchEnv(gym.Env):
    """Single-incident-per-episode dispatch environment."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        incidents: Sequence[IncidentGraph],
        scorer: Optional[AnomalyScorer] = None,
        step_budget: int = STEP_BUDGET,
        seed: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.incidents = list(incidents)
        if not self.incidents:
            raise ValueError("DispatchEnv requires at least one incident")
        self.scorer = scorer or AnomalyScorer()
        self.step_budget = step_budget

        self.action_space = spaces.Discrete(ACTION_SPACE_SIZE)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(OBSERVATION_DIM,), dtype=np.float32
        )

        self._rng = random.Random(seed)
        self._incident: Optional[IncidentGraph] = None
        self._ranked = None
        self._visited: set = set()
        self._steps = 0

    def reset(
        self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            self._rng.seed(seed)

        self._incident = self._rng.choice(self.incidents)
        ranked = self.scorer.score_graph(self._incident)
        self._ranked = sorted(ranked, key=lambda score: score.rank)
        self._visited = set()
        self._steps = 0

        observation = np.array(build_observation(self._ranked, self._visited), dtype=np.float32)
        info = {"incident_id": self._incident.incident_id, "root_cause": self._incident.root_cause}
        return observation, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        if self._incident is None or self._ranked is None:
            raise RuntimeError("call reset() before step()")

        action = int(action)
        dispatch_action = decode_action(action, self._ranked)
        target_service = dispatch_action.target_service

        self._steps += 1
        repeat = target_service in self._visited
        self._visited.add(target_service)

        solved = target_service == self._incident.root_cause

        reward = STEP_PENALTY
        if repeat:
            reward += REPEAT_PENALTY
        if solved:
            reward += SOLVE_REWARD

        terminated = solved
        truncated = (not solved) and self._steps >= self.step_budget

        observation = np.array(build_observation(self._ranked, self._visited), dtype=np.float32)
        info = {
            "incident_id": self._incident.incident_id,
            "agent_type": dispatch_action.agent_type,
            "target_service": target_service,
            "repeat": repeat,
            "solved": solved,
            "steps": self._steps,
        }
        return observation, reward, terminated, truncated, info

    def render(self) -> None:  # pragma: no cover - no visual rendering needed
        pass

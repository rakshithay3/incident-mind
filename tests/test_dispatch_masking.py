"""Baseline D (sequential greedy) and inference-time visited masking."""

import sys
from pathlib import Path

import pytest

from incidentmind_p1.contracts import NodeScore
from incidentmind_p1.dispatch import PPODispatcher, baseline_d_sequential, build_observation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _scores(n=6):
    return [NodeScore(service_id=f"s{i}", anomaly_score=1.0 - i * 0.1, embedding_dim=128,
                      status="anomalous", rank=i + 1) for i in range(n)]


def test_baseline_d_walks_down_the_ranking():
    scores, visited, picks = _scores(), set(), []
    for _ in range(4):
        target = baseline_d_sequential(scores, visited=visited).action.target_service
        picks.append(target)
        visited.add(target)
    assert picks == ["s0", "s1", "s2", "s3"]


def test_baseline_d_solve_rate_equals_pr_at_budget():
    import evaluate_ppo as ev
    from incidentmind_p1.contracts import IncidentGraph, ServiceNode

    class FixedScorer:
        def __init__(self, order):
            self.order = order

        def score_graph(self, incident):
            return [NodeScore(service_id=s, anomaly_score=1.0, embedding_dim=1, status="anomalous", rank=i + 1)
                    for i, s in enumerate(self.order)]

    nodes = [ServiceNode(service_id=f"s{i}", features={}) for i in range(8)]
    for rank_of_root, solved in ((1, True), (5, True), (6, False)):
        order = [f"s{i}" for i in range(8)]
        root = order[rank_of_root - 1]
        inc = IncidentGraph(incident_id="x", timestamp="", nodes=nodes, edges=[], root_cause=root)
        steps, ok = ev.run_episode_baseline_d(FixedScorer(order), inc, step_budget=5)
        assert ok is solved
        if solved:
            assert steps == rank_of_root


def test_mcnemar_matches_exact_binomial():
    import evaluate_ppo as ev

    x = [(1, True)] * 6 + [(5, False)] * 4
    y = [(5, False)] * 6 + [(5, False)] * 4
    assert ev.mcnemar(x, y) == (6, 0, pytest.approx(0.03125))
    assert ev.mcnemar(y, y)[2] is None


@pytest.fixture(scope="module")
def tiny_policy():
    pytest.importorskip("stable_baselines3")
    from stable_baselines3 import PPO

    from incidentmind_p1.loader import load_dataset
    from incidentmind_p1.ppo_env import DispatchEnv

    incidents = load_dataset(ROOT / "data" / "sample_rcaeval")
    return PPO("MlpPolicy", DispatchEnv(incidents, seed=0), n_steps=32, batch_size=16, seed=0, verbose=0)


def test_masked_equals_predict_when_nothing_visited(tiny_policy):
    scores = _scores()
    plain = PPODispatcher(tiny_policy).choose(scores, visited=set())
    masked = PPODispatcher(tiny_policy, mask_visited=True).choose(scores, visited=set())
    assert plain.action == masked.action


def test_masked_never_revisits(tiny_policy):
    scores = _scores()
    dispatcher = PPODispatcher(tiny_policy, mask_visited=True)
    visited = set()
    for step in range(1, len(scores) + 1):
        decision = dispatcher.choose(scores, visited=visited, step=step)
        assert decision.action.target_service not in visited
        assert 0.0 <= decision.policy_confidence <= 1.0
        visited.add(decision.action.target_service)
    assert visited == {s.service_id for s in scores}
    # all visited: falls back to the unmasked choice instead of crashing
    dispatcher.choose(scores, visited=visited, step=99)
    assert len(build_observation(scores, visited)) == 24

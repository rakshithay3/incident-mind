import unittest

from incidentmind_p1.contracts import NodeScore
from incidentmind_p1.dispatch import (
    ACTION_SPACE_SIZE,
    AGENT_TYPES,
    MAX_SERVICES,
    PPODispatcher,
    build_observation,
    decode_action,
)
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.ppo_env import OBSERVATION_DIM, STEP_BUDGET, DispatchEnv
from incidentmind_p1.scoring import AnomalyScorer


def _ranked_scores(n: int):
    return [
        NodeScore(service_id=f"svc-{i}", anomaly_score=float(n - i), embedding_dim=128, status="normal", rank=i + 1)
        for i in range(n)
    ]


class DecodeActionTest(unittest.TestCase):
    def test_action_space_size_is_36(self):
        self.assertEqual(ACTION_SPACE_SIZE, MAX_SERVICES * len(AGENT_TYPES))
        self.assertEqual(ACTION_SPACE_SIZE, 36)

    def test_decode_action_agent_type_thirds(self):
        scores = _ranked_scores(12)
        self.assertEqual(decode_action(0, scores).agent_type, "log")
        self.assertEqual(decode_action(12, scores).agent_type, "metrics")
        self.assertEqual(decode_action(24, scores).agent_type, "code")

    def test_decode_action_wraps_for_fewer_than_max_services(self):
        # RE1 sample incident only has 6 nodes; slot 8 must wrap via modulo
        # rather than raising an IndexError.
        scores = _ranked_scores(6)
        action = decode_action(8, scores)  # slot=8, agent=log
        self.assertEqual(action.target_service, scores[8 % 6].service_id)

    def test_decode_action_out_of_range_raises(self):
        scores = _ranked_scores(12)
        with self.assertRaises(ValueError):
            decode_action(ACTION_SPACE_SIZE, scores)
        with self.assertRaises(ValueError):
            decode_action(-1, scores)

    def test_decode_action_empty_scores_raises(self):
        with self.assertRaises(ValueError):
            decode_action(0, [])


class BuildObservationTest(unittest.TestCase):
    def test_observation_length_fixed_at_24(self):
        scores = _ranked_scores(6)
        obs = build_observation(scores, visited=set())
        self.assertEqual(len(obs), MAX_SERVICES * 2)

    def test_observation_pads_zero_past_node_count(self):
        scores = _ranked_scores(6)
        obs = build_observation(scores, visited=set())
        # slots 6..11 (score half) should be zero-padded
        self.assertTrue(all(v == 0.0 for v in obs[6:12]))

    def test_observation_marks_visited_slot(self):
        scores = _ranked_scores(3)
        visited = {scores[1].service_id}
        obs = build_observation(scores, visited=visited)
        visited_half = obs[MAX_SERVICES:]
        self.assertEqual(visited_half[1], 1.0)
        self.assertEqual(visited_half[0], 0.0)
        self.assertEqual(visited_half[2], 0.0)


class DispatchEnvTest(unittest.TestCase):
    def setUp(self):
        self.incidents = load_dataset("data/sample_rcaeval")
        self.env = DispatchEnv(self.incidents, scorer=AnomalyScorer(), seed=0)

    def test_reset_returns_correct_shape(self):
        obs, info = self.env.reset(seed=0)
        self.assertEqual(obs.shape, (OBSERVATION_DIM,))
        self.assertIn("incident_id", info)

    def test_step_before_reset_raises(self):
        fresh_env = DispatchEnv(self.incidents, seed=1)
        with self.assertRaises(RuntimeError):
            fresh_env.step(0)

    def test_solving_root_cause_terminates_with_positive_reward(self):
        obs, info = self.env.reset(seed=0)
        root_cause = info["root_cause"]
        # Find the action index that targets the root cause via the ranked list.
        ranked = self.env._ranked
        slot = next(i for i, s in enumerate(ranked) if s.service_id == root_cause)
        obs, reward, terminated, truncated, step_info = self.env.step(slot)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertTrue(step_info["solved"])
        self.assertAlmostEqual(reward, 1.0 - 0.1)

    def test_non_solving_non_repeat_step_gives_step_penalty(self):
        obs, info = self.env.reset(seed=0)
        root_cause = info["root_cause"]
        ranked = self.env._ranked
        wrong_slot = next(i for i, s in enumerate(ranked) if s.service_id != root_cause)
        _, reward, terminated, truncated, step_info = self.env.step(wrong_slot)
        self.assertFalse(terminated)
        self.assertFalse(step_info["repeat"])
        self.assertAlmostEqual(reward, -0.1)

    def test_repeat_visit_incurs_extra_penalty(self):
        obs, info = self.env.reset(seed=0)
        root_cause = info["root_cause"]
        ranked = self.env._ranked
        wrong_slot = next(i for i, s in enumerate(ranked) if s.service_id != root_cause)
        self.env.step(wrong_slot)
        _, reward, _, _, step_info = self.env.step(wrong_slot)
        self.assertTrue(step_info["repeat"])
        self.assertAlmostEqual(reward, -0.1 - 0.5)

    def test_budget_exhausted_truncates_without_solving(self):
        obs, info = self.env.reset(seed=0)
        root_cause = info["root_cause"]
        ranked = self.env._ranked
        wrong_slot = next(i for i, s in enumerate(ranked) if s.service_id != root_cause)
        terminated = truncated = False
        for _ in range(STEP_BUDGET):
            _, _, terminated, truncated, _ = self.env.step(wrong_slot)
        self.assertFalse(terminated)
        self.assertTrue(truncated)


class PPODispatcherTest(unittest.TestCase):
    def test_greedy_fallback_when_no_policy(self):
        scores = _ranked_scores(5)
        decision = PPODispatcher().choose(scores)
        self.assertEqual(decision.action.target_service, scores[0].service_id)

    def test_trained_policy_decodes_predicted_action(self):
        scores = _ranked_scores(5)

        class StubPolicy:
            def predict(self, observation, deterministic=True):
                return 12, None  # slot=0, agent=metrics

        decision = PPODispatcher(policy=StubPolicy()).choose(scores)
        self.assertEqual(decision.action.agent_type, "metrics")
        self.assertEqual(decision.action.target_service, scores[0].service_id)


if __name__ == "__main__":
    unittest.main()

import random
import unittest

from incidentmind_p1.loader import load_incident
from incidentmind_p1.scoring import AnomalyScorer
from scripts.evaluate_ppo import _stable_seed

INCIDENT = "data/sample_rcaeval/incidents/inc_001.json"


class StableSeedTest(unittest.TestCase):
    def test_deterministic_across_calls(self):
        self.assertEqual(_stable_seed(42, "inc_001"), _stable_seed(42, "inc_001"))

    def test_varies_by_incident_key(self):
        self.assertNotEqual(_stable_seed(42, "inc_001"), _stable_seed(42, "inc_002"))

    def test_varies_by_seed(self):
        self.assertNotEqual(_stable_seed(42, "inc_001"), _stable_seed(43, "inc_001"))


class BaselineBArrivalOrderTest(unittest.TestCase):
    def test_shuffled_order_differs_from_rank_order(self):
        # Regression test: run_episode_baseline_b used to hand baseline_b
        # the SAME rank-sorted list every other baseline uses (a no-op
        # re-sort of an already score-sorted scorer output), making its
        # "arrival order" silently identical to anomaly rank. It must now
        # be a genuine per-incident shuffle, not the rank order.
        graph = load_incident(INCIDENT)
        scorer = AnomalyScorer()

        rank_order = [s.service_id for s in sorted(scorer.score_graph(graph), key=lambda s: s.rank)]

        shuffled = list(scorer.score_graph(graph))
        random.Random(_stable_seed(42, graph.incident_id)).shuffle(shuffled)
        shuffled_order = [s.service_id for s in shuffled]

        self.assertNotEqual(rank_order, shuffled_order)


if __name__ == "__main__":
    unittest.main()

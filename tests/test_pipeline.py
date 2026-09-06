import unittest

from incidentmind_p1.dispatch import greedy_baseline_c
from incidentmind_p1.evaluation import evaluate_ranking
from incidentmind_p1.loader import load_dataset, load_incident, summarize_dataset
from incidentmind_p1.pipeline import run_inference
from incidentmind_p1.scoring import AnomalyScorer


INCIDENT = "data/sample_rcaeval/incidents/inc_001.json"


class PipelineTest(unittest.TestCase):
    def test_loads_rcaeval_graph(self):
        graph = load_incident(INCIDENT)
        self.assertEqual(graph.incident_id, "inc_001")
        self.assertEqual(len(graph.nodes), 6)
        self.assertEqual(len(graph.edges), 5)
        self.assertEqual(graph.root_cause, "auth-service")

    def test_dataset_summary_confirms_counts(self):
        summary = summarize_dataset(load_dataset("data/sample_rcaeval"))
        self.assertEqual(summary["incident_count"], 1)
        self.assertEqual(summary["node_counts"], [6])
        self.assertEqual(summary["edge_counts"], [5])

    def test_anomaly_scores_rank_faulty_node(self):
        graph = load_incident(INCIDENT)
        scorer = AnomalyScorer()
        scores = scorer.score_graph(graph)
        self.assertEqual(scores[0].service_id, "auth-service")
        self.assertEqual(scores[0].rank, 1)
        self.assertEqual(scores[0].embedding_dim, 128)

    def test_baseline_c_dispatches_top_ranked_service(self):
        graph = load_incident(INCIDENT)
        scores = AnomalyScorer().score_graph(graph)
        dispatch = greedy_baseline_c(scores)
        self.assertEqual(dispatch.action.agent_type, "log")
        self.assertEqual(dispatch.action.target_service, "auth-service")

    def test_handoff_json_contract(self):
        output = run_inference(INCIDENT).to_json()
        self.assertEqual(output["incident_id"], "inc_001")
        self.assertIn("nodes", output)
        self.assertIn("ppo_dispatch", output)
        self.assertIn("metrics", output)
        self.assertEqual(output["nodes"][0]["service_id"], "auth-service")
        self.assertEqual(output["metrics"]["pr_at_1"], 1.0)


if __name__ == "__main__":
    unittest.main()

import unittest
import os
import json
import export_metrics
import adjacency_export

class TestShopMindObservability(unittest.TestCase):
    def test_services_config(self):
        self.assertTrue(os.path.exists("services.json"))
        with open("services.json", "r") as f:
            cfg = json.load(f)
        self.assertIn("frontend", cfg)
        self.assertIn("api-gateway", cfg)
        self.assertIn("auth-service", cfg)
        self.assertEqual(cfg["auth-service"]["port"], 3001)

    def test_jaeger_traces_parsing(self):
        # Verify get_jaeger_metrics handles trace fetching failures gracefully
        mean, p99, err, calls = export_metrics.get_jaeger_metrics("non-existent-service", lookback_sec=1)
        self.assertEqual(mean, 0.0)
        self.assertEqual(p99, 0.0)
        self.assertEqual(err, 0.0)
        self.assertEqual(calls, 0)

    def test_graph_structural_validation(self):
        # Mock nodes and edges to verify structural checks find duplicate and disconnected items
        nodes = [
            {"service_id": "auth-service", "cpu_pct": 0.1, "mem_pct": 0.2, "mean_latency_ms": 10},
            {"service_id": "user-service", "cpu_pct": 0.1, "mem_pct": 0.2, "mean_latency_ms": 10},
            {"service_id": "auth-service", "cpu_pct": 0.1, "mem_pct": 0.2, "mean_latency_ms": 10} # duplicate
        ]
        edges = [
            {"source": "auth-service", "target": "postgres-primary"}
        ]
        report = adjacency_export.run_validation(nodes, edges, {"active": False}, [])
        self.assertFalse(report["validation_passed"])
        self.assertTrue(report["graph_validation"]["duplicate_nodes"])

if __name__ == "__main__":
    unittest.main()

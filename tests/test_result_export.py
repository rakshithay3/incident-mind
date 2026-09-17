import json
import unittest

from incidentmind_p1.contracts import NodeScore
from priority.cross_instance_queue import CrossInstancePriorityQueue
from priority.global_dispatch import GlobalPPODispatcher
from priority.result_export import build_multi_instance_result


class MultiInstanceResultExportTest(unittest.TestCase):
    def setUp(self):
        self.queue = CrossInstancePriorityQueue()
        self.queue.add_instance_scores("mac-a", [
            NodeScore("auth-service", 0.9, 128, "anomalous", 1),
            NodeScore("search-service", 0.95, 128, "anomalous", 2),
            NodeScore("cache", 0.1, 128, "normal", 3),
        ])
        self.queue.add_instance_scores("mac-b", [
            NodeScore("auth-service", 0.8, 128, "anomalous", 1),
        ])
        self.instances = [
            {"instance_id": "mac-a", "incident_id": "live_a", "fault_type": "cpu_stress",
             "target_service": "auth-service", "anomalous_count": 2, "status": "scored"},
            {"instance_id": "mac-b", "incident_id": "live_b", "fault_type": "network_delay",
             "target_service": "auth-service", "anomalous_count": 1, "status": "scored"},
        ]

    def test_queue_and_dispatch_shape(self):
        ranked = self.queue.ranked_snapshot()
        decisions = list(GlobalPPODispatcher(self.queue, policy=None).dispatch_all())
        result = build_multi_instance_result(self.instances, ranked, decisions)

        json.dumps(result)  # must be serialisable
        self.assertEqual(len(result["queue"]), 3)  # normal node excluded by queue
        self.assertEqual(len(result["dispatches"]), 3)

        top = result["queue"][0]
        self.assertEqual((top["instance_id"], top["service_id"]), ("mac-a", "auth-service"))
        self.assertEqual(top["impact_tier"], "high")
        self.assertEqual(top["priority_score"], 0.9)
        self.assertEqual(top["dispatch_step"], 1)

        # search-service has the higher raw score but is low tier -> last
        last = result["queue"][-1]
        self.assertEqual(last["service_id"], "search-service")
        self.assertAlmostEqual(last["priority_score"], 0.285)

        # same service name on two instances stays two distinct rows
        auth_rows = [q for q in result["queue"] if q["service_id"] == "auth-service"]
        self.assertEqual({q["instance_id"] for q in auth_rows}, {"mac-a", "mac-b"})


if __name__ == "__main__":
    unittest.main()

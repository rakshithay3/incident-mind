import unittest

from incidentmind_p1.contracts import NodeScore
from priority.cross_instance_queue import CrossInstancePriorityQueue
from priority.global_dispatch import GlobalPPODispatcher


def _score(service_id: str, anomaly_score: float, rank: int) -> NodeScore:
    return NodeScore(
        service_id=service_id,
        anomaly_score=anomaly_score,
        embedding_dim=128,
        status="anomalous",
        rank=rank,
    )


class RankedSnapshotTest(unittest.TestCase):
    def test_snapshot_is_globally_priority_ordered_across_instances(self):
        queue = CrossInstancePriorityQueue()
        # instance-A's #2 (weighted by impact) outranks instance-B's #1 once
        # impact-weighting is applied cross-instance -- auth-service is a
        # "high" tier, search-service is "low" (priority/impact_weights.py).
        queue.add_instance_scores("instance-A", [_score("auth-service", 0.9, 1)])
        queue.add_instance_scores("instance-B", [_score("search-service", 0.95, 1)])

        snapshot = queue.ranked_snapshot()

        self.assertEqual([n.service_id for n in snapshot], ["auth-service", "search-service"])
        self.assertEqual([n.rank for n in snapshot], [1, 2])
        self.assertEqual([n.instance_id for n in snapshot], ["instance-A", "instance-B"])

    def test_snapshot_does_not_mutate_the_queue(self):
        queue = CrossInstancePriorityQueue()
        queue.add_instance_scores("instance-A", [_score("auth-service", 0.9, 1)])
        queue.ranked_snapshot()
        self.assertEqual(len(queue), 1)


class GlobalPPODispatcherTest(unittest.TestCase):
    def test_dispatches_one_decision_per_node_across_all_instances(self):
        queue = CrossInstancePriorityQueue()
        queue.add_instance_scores("instance-A", [_score("auth-service", 0.9, 1)])
        queue.add_instance_scores("instance-B", [_score("auth-service", 0.8, 1)])

        dispatcher = GlobalPPODispatcher(queue)
        decisions = list(dispatcher.dispatch_all())

        # Same service_id on two different instances must not collapse into
        # one visited entry -- both get dispatched.
        self.assertEqual(len(decisions), 2)
        seen = {(d.action.instance_id, d.action.target_service) for d in decisions}
        self.assertEqual(seen, {("instance-A", "auth-service"), ("instance-B", "auth-service")})

    def test_walks_global_priority_order_with_greedy_fallback(self):
        queue = CrossInstancePriorityQueue()
        queue.add_instance_scores("instance-A", [_score("payment-service", 0.5, 1)])
        queue.add_instance_scores("instance-B", [_score("payment-service", 0.9, 1)])

        dispatcher = GlobalPPODispatcher(queue)
        decisions = list(dispatcher.dispatch_all())

        self.assertEqual(decisions[0].action.instance_id, "instance-B")
        self.assertEqual(decisions[1].action.instance_id, "instance-A")


if __name__ == "__main__":
    unittest.main()

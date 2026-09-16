"""
priority/cross_instance_queue.py -- global cross-instance priority queue.

Collects anomalous NodeScores from multiple ShopMind instances (tagged
with instance_id), applies impact-weight priority, and exposes them as
ONE global queue PPO dispatch can pull from sequentially -- regardless of
which physical instance a service belongs to. This is the missing piece
between per-instance scoring and true cross-instance triage.
"""

import dataclasses
import heapq
from typing import List, Optional, Tuple

from incidentmind_p1.contracts import NodeScore
from priority.impact_weights import get_impact_weight


class CrossInstancePriorityQueue:
    def __init__(self):
        self._heap = []
        self._counter = 0

    def add_instance_scores(self, instance_id: str, scores: List[NodeScore]) -> int:
        added = 0
        for s in scores:
            if s.status != "anomalous":
                continue
            weight = get_impact_weight(s.service_id)
            priority = s.anomaly_score * weight
            heapq.heappush(self._heap, (-priority, self._counter, instance_id, s))
            self._counter += 1
            added += 1
        return added

    def pop_next(self) -> Optional[Tuple[str, NodeScore]]:
        if not self._heap:
            return None
        _, _, instance_id, node = heapq.heappop(self._heap)
        return instance_id, node

    def __len__(self):
        return len(self._heap)

    def peek_all(self):
        return [(iid, node, -neg_p) for neg_p, _, iid, node in sorted(self._heap)]

    def ranked_snapshot(self) -> List[NodeScore]:
        """Non-destructive, globally priority-ordered view of every anomalous
        node currently queued across every connected instance, tagged with
        instance_id and re-ranked 1..N by priority_score (not left at each
        node's original per-instance rank). This is what lets it plug
        straight into PPODispatcher/build_observation/decode_action, which
        expect one rank-ordered candidate list -- so "top ranked" means top
        across all instances, not just whichever instance was scored first."""
        ordered = sorted(self._heap)
        return [
            dataclasses.replace(node, instance_id=instance_id, rank=new_rank)
            for new_rank, (_, _, instance_id, node) in enumerate(ordered, start=1)
        ]

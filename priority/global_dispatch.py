"""priority/global_dispatch.py -- lets PPO pull the next dispatch target
sequentially across every connected instance, not just one at a time.

CrossInstancePriorityQueue already merges anomalous NodeScores from every
instance into one priority_score-ordered view (ranked_snapshot()). This
module is the missing glue that feeds that globally-ranked, instance_id
-tagged list into PPODispatcher the same way a single incident's ranked
list is fed today -- so the trained policy's "top ranked" candidate is the
top-ranked node across ALL connected instances, and repeated calls walk
through every one of them in priority order via the same visited-tracking
PPODispatcher already uses.
"""

from __future__ import annotations

import dataclasses
from typing import Iterator, Optional, Set

from incidentmind_p1.contracts import DispatchDecision
from incidentmind_p1.dispatch import PPODispatcher
from priority.cross_instance_queue import CrossInstancePriorityQueue


class GlobalPPODispatcher:
    """Wraps PPODispatcher so each dispatch_next() call looks at a fresh
    global snapshot of the cross-instance queue and picks the next target,
    skipping nodes already dispatched this session (tracked by
    (instance_id, service_id), so same-named services on different
    instances are never confused with each other)."""

    def __init__(self, queue: CrossInstancePriorityQueue, policy: Optional[object] = None):
        self.queue = queue
        self._dispatcher = PPODispatcher(policy)
        self._visited: Set = set()

    def dispatch_next(self, step: int = 1) -> Optional[DispatchDecision]:
        ranked = self.queue.ranked_snapshot()
        # The policy only sees MAX_SERVICES (12) rank slots, so with more
        # nodes than that across instances anything ranked 13th or lower was
        # unreachable. Hand it only the not-yet-dispatched nodes, re-ranked
        # 1..N, so the 12-slot window slides down the global list.
        ranked = [
            dataclasses.replace(node, rank=new_rank)
            for new_rank, node in enumerate(
                (n for n in ranked if (n.instance_id, n.service_id) not in self._visited), start=1
            )
        ]
        if not ranked:
            return None
        decision = self._dispatcher.choose(ranked, visited=set(), step=step)
        self._visited.add((decision.action.instance_id, decision.action.target_service))
        return decision

    def dispatch_all(self) -> Iterator[DispatchDecision]:
        """Yield one DispatchDecision per anomalous node currently queued,
        in global priority order, across every connected instance.

        Bounded at len(self.queue) iterations rather than looping until
        self._visited covers every node: a policy is never guaranteed to
        avoid re-dispatching an already-visited node (build_observation only
        nudges it away from repeats, it doesn't forbid them), so bounding on
        visited-set growth could spin forever on an imperfect policy."""
        total = len(self.queue)
        for step in range(1, total + 1):
            decision = self.dispatch_next(step)
            if decision is None:
                break
            yield decision

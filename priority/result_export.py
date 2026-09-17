"""
priority/result_export.py -- serialises a cross-instance dispatch run into
the JSON the dashboard's Priority Queue tab reads
(dashboard/public/multiInstanceResult.json).

Kept separate from cross_instance_dispatch_demo.py so the shape can be
unit-tested without torch / stable-baselines3 / a live receiver.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from priority.impact_weights import SERVICE_TIERS, get_impact_weight


def _key(instance_id, service_id):
    return f"{instance_id}::{service_id}"


def build_multi_instance_result(
    instances: List[Dict[str, Any]],
    ranked_queue: Iterable,
    decisions: Iterable,
) -> Dict[str, Any]:
    """
    instances     -- [{instance_id, incident_id, fault_type, target_service,
                       anomalous_count, status}] one per reporting instance
    ranked_queue  -- CrossInstancePriorityQueue.ranked_snapshot() (NodeScores
                     tagged with instance_id, rank 1..N by priority_score)
    decisions     -- DispatchDecisions in the order PPO produced them
    """
    decisions = list(decisions)

    dispatch_by_node = {}
    dispatches = []
    for i, d in enumerate(decisions):
        a = d.action
        entry = {
            "step": i + 1,
            "instance_id": a.instance_id,
            "target_service": a.target_service,
            "agent_type": a.agent_type,
            "policy_confidence": round(float(d.policy_confidence), 4),
        }
        dispatches.append(entry)
        dispatch_by_node.setdefault(_key(a.instance_id, a.target_service), entry)

    queue = []
    for s in ranked_queue:
        weight = get_impact_weight(s.service_id)
        d = dispatch_by_node.get(_key(s.instance_id, s.service_id))
        queue.append({
            "rank": int(s.rank),
            "instance_id": s.instance_id,
            "service_id": s.service_id,
            "anomaly_score": round(float(s.anomaly_score), 4),
            "impact_tier": SERVICE_TIERS.get(s.service_id, "default"),
            "impact_weight": weight,
            "priority_score": round(float(s.anomaly_score) * weight, 4),
            "dispatch_step": d["step"] if d else None,
            "agent_type": d["agent_type"] if d else None,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instances": instances,
        "queue": queue,
        "dispatches": dispatches,
    }

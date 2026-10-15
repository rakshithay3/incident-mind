"""
multi_fault.py -- multi-fault detection (extension item 4).

GraphSAGEScorer already tags each NodeScore with status="anomalous" when
anomaly_score >= threshold (default 0.5). Prior to this, only the single
PPO dispatch target (top-1) was ever surfaced. This surfaces every node
above threshold, so a genuine multi-service incident is reported as such
instead of only the highest-ranked node. investigate_faults() then runs the
agents on each flagged service so every fault gets its own report.
"""

from typing import Callable, Dict, List, Optional, Sequence

from incidentmind_p1.contracts import NodeScore


def detect_multi_fault(scores: List[NodeScore]) -> List[NodeScore]:
    anomalous = [s for s in scores if s.status == "anomalous"]
    return sorted(anomalous, key=lambda s: s.rank)


def investigate_faults(
    flagged: Sequence[NodeScore],
    investigations: Dict[str, dict],
    investigate: Callable[[str], dict],
) -> Optional[List[dict]]:
    """One RCA report per flagged service when 2+ nodes are flagged; None for
    a single-fault run, so callers leave the result unchanged.

    investigations maps service -> run_investigation() result for services
    the agents already ran on (the PPO target, re-investigation rounds); those
    are reused, and investigate(service) runs the agents on the rest (each new
    result is added to investigations)."""
    if len(flagged) < 2:
        return None
    reports = []
    for s in flagged:
        if s.service_id not in investigations:
            investigations[s.service_id] = investigate(s.service_id)
        reports.append({
            "service": s.service_id,
            "score": s.anomaly_score,
            "report": investigations[s.service_id].get("report"),
        })
    return reports

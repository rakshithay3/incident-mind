"""
multi_fault.py -- multi-fault detection (extension item 4).

GraphSAGEScorer already tags each NodeScore with status="anomalous" when
anomaly_score >= threshold (default 0.5). Prior to this, only the single
PPO dispatch target (top-1) was ever surfaced. This surfaces every node
above threshold, so a genuine multi-service incident is reported as such
instead of only the highest-ranked node.
"""

from typing import List

from incidentmind_p1.contracts import NodeScore


def detect_multi_fault(scores: List[NodeScore]) -> List[NodeScore]:
    anomalous = [s for s in scores if s.status == "anomalous"]
    return sorted(anomalous, key=lambda s: s.rank)

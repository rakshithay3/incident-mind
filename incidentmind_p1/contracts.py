"""Typed contracts shared across P1 (GNN/PPO), P2 (LLM agents), and downstream
consumers (Vismitha's dashboard).

This is the single source of truth for DispatchAction / AgentType. Previously
schemas/contracts.py (P2) defined its own TypedDict version of DispatchAction
that was incompatible with this dataclass version -- P2 code should import
from here instead of maintaining a separate copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple, TypedDict


FEATURES = ("cpu", "memory", "latency", "error_rate", "p99_latency")
DEFAULT_EMBEDDING_DIM = 128

AgentType = Literal["log", "metrics", "code"]
Severity = Literal["low", "medium", "high", "unknown"]


@dataclass(frozen=True)
class ServiceNode:
    service_id: str
    features: Mapping[str, float]
    label: Optional[str] = None

    def feature_vector(self, feature_names: Sequence[str] = FEATURES) -> List[float]:
        return [float(self.features.get(name, 0.0)) for name in feature_names]


@dataclass(frozen=True)
class IncidentGraph:
    incident_id: str
    timestamp: str
    nodes: List[ServiceNode]
    edges: List[Tuple[str, str]]
    root_cause: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def service_ids(self) -> List[str]:
        return [node.service_id for node in self.nodes]

    def validate(self) -> None:
        if not self.incident_id:
            raise ValueError("incident_id is required")
        if not self.nodes:
            raise ValueError("at least one service node is required")
        service_ids = set(self.service_ids)
        if len(service_ids) != len(self.nodes):
            raise ValueError("service_id values must be unique per incident")
        for source, target in self.edges:
            if source not in service_ids or target not in service_ids:
                raise ValueError(f"edge references unknown service: {source}->{target}")
        if self.root_cause and self.root_cause not in service_ids:
            raise ValueError(f"root_cause not present in graph: {self.root_cause}")


@dataclass(frozen=True)
class NodeScore:
    service_id: str
    anomaly_score: float
    embedding_dim: int
    status: str
    rank: int

    def to_json(self) -> Dict[str, Any]:
        return {
            "service_id": self.service_id,
            "anomaly_score": round(float(self.anomaly_score), 6),
            "embedding_dim": int(self.embedding_dim),
            "status": self.status,
            "rank": int(self.rank),
        }


@dataclass(frozen=True)
class DispatchAction:
    """Request sent to a specialist agent (log/metrics/code).

    Canonical version -- P2 agent code (pipeline.py, agents/*) should import
    this instead of defining a separate TypedDict. Use attribute access
    (action.agent_type), not dict access (action["agent_type"]).
    """

    agent_type: AgentType
    target_service: str

    def to_json(self) -> Dict[str, str]:
        return {"agent_type": self.agent_type, "target_service": self.target_service}


@dataclass(frozen=True)
class DispatchDecision:
    step: int
    action: DispatchAction
    policy_confidence: float

    def to_json(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "action": self.action.to_json(),
            "policy_confidence": round(float(self.policy_confidence), 6),
        }


@dataclass(frozen=True)
class EvaluationMetrics:
    pr_at_1: float
    pr_at_3: float
    pr_at_5: float
    mttd_steps: int

    def to_json(self) -> Dict[str, Any]:
        return {
            "pr_at_1": round(float(self.pr_at_1), 6),
            "pr_at_3": round(float(self.pr_at_3), 6),
            "pr_at_5": round(float(self.pr_at_5), 6),
            "mttd_steps": int(self.mttd_steps),
        }


@dataclass(frozen=True)
class DispatchOutput:
    incident_id: str
    timestamp: str
    nodes: List[NodeScore]
    ppo_dispatch: DispatchDecision
    metrics: EvaluationMetrics

    def to_json(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "timestamp": self.timestamp,
            "nodes": [node.to_json() for node in self.nodes],
            "ppo_dispatch": self.ppo_dispatch.to_json(),
            "metrics": self.metrics.to_json(),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def precision_at_k(ranked_service_ids: Iterable[str], root_cause: Optional[str], k: int) -> float:
    if not root_cause:
        return 0.0
    top_k = list(ranked_service_ids)[:k]
    return 1.0 if root_cause in top_k else 0.0


# --------------------------------------------------------------------------
# P2 agent / report types (originally schemas/contracts.py, Dharunya).
# Moved here so DispatchAction/AgentType have exactly one definition. These
# stay as TypedDicts since that's how agents/*.py and report_agent.py already
# consume them -- only DispatchAction itself needed to become a dataclass for
# compatibility with PPO's DispatchDecision output.
# --------------------------------------------------------------------------


class AgentFinding(TypedDict):
    """Standard output from Log, Metrics, and Code agents."""

    agent_type: AgentType
    target_service: str
    finding: str
    severity: Severity
    confidence: float
    evidence: List[str]


class EvidenceBundle(TypedDict):
    """Collection of specialist-agent findings."""

    findings: List[AgentFinding]


class EvidenceSummary(TypedDict):
    """Condensed evidence used by the Report Agent."""

    agent_type: AgentType
    summary: str


class ReportText(TypedDict):
    """Bilingual report text."""

    en: str
    hi: str


class RCAReport(TypedDict):
    """Final IncidentMind RCA report."""

    incident_id: str
    root_cause_service: str
    confidence_score: float
    evidence_summary: List[EvidenceSummary]
    suggested_fix: str
    estimated_blast_radius: List[str]
    report_text: ReportText

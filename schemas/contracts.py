from typing import TypedDict, List, Literal


AgentType = Literal["log", "metrics", "code"]
Severity = Literal["low", "medium", "high", "unknown"]


class DispatchAction(TypedDict):
    """
    Request sent to a specialist agent.

    This is the interface that the PPO policy
    will eventually produce.
    """

    agent_type: AgentType
    target_service: str


class AgentFinding(TypedDict):
    """
    Standard output from Log, Metrics, and Code agents.
    """

    agent_type: AgentType
    target_service: str
    finding: str
    severity: Severity
    confidence: float
    evidence: List[str]


class EvidenceBundle(TypedDict):
    """
    Collection of specialist-agent findings.
    """

    findings: List[AgentFinding]


class EvidenceSummary(TypedDict):
    """
    Condensed evidence used by the Report Agent.
    """

    agent_type: AgentType
    summary: str


class ReportText(TypedDict):
    """
    Bilingual report text.
    """

    en: str
    hi: str


class RCAReport(TypedDict):
    """
    Final IncidentMind RCA report.
    """

    incident_id: str
    root_cause_service: str
    confidence_score: float
    evidence_summary: List[EvidenceSummary]
    suggested_fix: str
    estimated_blast_radius: List[str]
    report_text: ReportText
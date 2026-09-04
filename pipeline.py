from agents.log_agent import investigate as investigate_logs
from agents.metrics_agent import investigate as investigate_metrics
from agents.code_agent import investigate as investigate_code
from agents.report_agent import generate_report

from schemas.contracts import DispatchAction


SUPPORTED_AGENTS = {"log", "metrics", "code"}


def validate_action(action: DispatchAction):
    """
    Validate a DispatchAction before sending it to an agent.
    """

    if "agent_type" not in action:
        raise ValueError("DispatchAction is missing 'agent_type'.")

    if "target_service" not in action:
        raise ValueError("DispatchAction is missing 'target_service'.")

    if action["agent_type"] not in SUPPORTED_AGENTS:
        raise ValueError(
            f"Unsupported agent type: {action['agent_type']}"
        )

    if not action["target_service"]:
        raise ValueError("target_service cannot be empty.")


def dispatch(action: DispatchAction):
    """
    Route a DispatchAction to the appropriate specialist agent.
    """

    validate_action(action)

    agent_type = action["agent_type"]

    if agent_type == "log":
        return investigate_logs(action)

    elif agent_type == "metrics":
        return investigate_metrics(action)

    elif agent_type == "code":
        return investigate_code(action)

    raise ValueError(f"Unsupported agent type: {agent_type}")


def investigate_incident(actions):
    """
    Run specialist agents and create an evidence bundle.
    """

    findings = []

    for action in actions:
        result = dispatch(action)
        findings.append(result)

    return {
        "findings": findings
    }


def run_investigation(actions, incident_id="inc_001"):
    """
    Run the complete IncidentMind investigation.

    Flow:

    DispatchAction
        ↓
    Specialist Agents
        ↓
    Evidence Bundle
        ↓
    Report Agent
        ↓
    Final RCA Report
    """

    evidence_bundle = investigate_incident(actions)

    report = generate_report(
        evidence_bundle,
        incident_id=incident_id
    )

    return {
        "evidence_bundle": evidence_bundle,
        "report": report
    }
from agents.log_agent import investigate as investigate_logs
from agents.metrics_agent import investigate as investigate_metrics
from agents.code_agent import investigate as investigate_code
from agents.report_agent import generate_report
from schemas.contracts import DispatchAction
import json
from pathlib import Path


SUPPORTED_AGENTS = {"log", "metrics", "code"}


def validate_action(action: DispatchAction):
    """Validate a dispatch action before sending it to an agent."""

    if not action.agent_type:
        raise ValueError(
            "DispatchAction is missing 'agent_type'."
        )

    if not action.target_service:
        raise ValueError(
            "DispatchAction is missing 'target_service'."
        )

    if action.agent_type not in SUPPORTED_AGENTS:
        raise ValueError(
            f"Unsupported agent type: {action.agent_type}"
        )

    if not action.target_service.strip():
        raise ValueError(
            "target_service cannot be empty."
        )


def dispatch(
    action: DispatchAction,
    telemetry_path=None,
    log_path=None,
    code_path=None
):
    """
    Dispatch an investigation action to the correct P2 agent.

    Parameters:
        action:
            P1 DispatchAction.

        telemetry_path:
            Optional ShopMind telemetry_series.json path
            used by Metrics Agent.

        log_path:
            Optional ShopMind log file path
            used by Log Agent.

        code_path:
            Optional ShopMind repository path
            used by Code Agent.
    """

    validate_action(action)

    agent_type = action.agent_type

    # -------------------------
    # LOG AGENT
    # -------------------------
    if agent_type == "log":
        return investigate_logs(
            action,
            log_path=log_path
        )

    # -------------------------
    # METRICS AGENT
    # -------------------------
    elif agent_type == "metrics":
        return investigate_metrics(
            action,
            telemetry_path=telemetry_path
        )

    # -------------------------
    # CODE AGENT
    # -------------------------
    elif agent_type == "code":
        return investigate_code(
            action,
            repo_path=code_path
        )

    raise ValueError(
        f"Unsupported agent type: {agent_type}"
    )


def investigate_incident(
    actions,
    telemetry_path=None,
    log_path=None,
    code_path=None
):
    """
    Run all requested investigation actions.

    Returns an Evidence Bundle containing
    findings from Log, Metrics, and/or Code agents.
    """

    findings = []

    for action in actions:

        result = dispatch(
            action,
            telemetry_path=telemetry_path,
            log_path=log_path,
            code_path=code_path
        )

        findings.append(result)

    return {
        "findings": findings
    }


def run_investigation(
    actions,
    incident_id="inc_001",
    telemetry_path=None,
    log_path=None,
    code_path=None
):
    """
    Run the complete P2 investigation pipeline.
    """

    evidence_bundle = investigate_incident(
        actions,
        telemetry_path=telemetry_path,
        log_path=log_path,
        code_path=code_path
    )

    report = generate_report(
        evidence_bundle,
        incident_id=incident_id
    )

    # Save structured RCA report.
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f"{incident_id}_report.json"

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(f"\nRCA report saved to: {output_file}")

    return {
        "evidence_bundle": evidence_bundle,
        "report": report
    }
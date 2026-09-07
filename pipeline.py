from pathlib import Path

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

    if not action.agent_type:
        raise ValueError("DispatchAction is missing 'agent_type'.")

    if not action.target_service:
        raise ValueError("DispatchAction is missing 'target_service'.")

    if action.agent_type not in SUPPORTED_AGENTS:
        raise ValueError(
            f"Unsupported agent type: {action.agent_type}"
        )

    if not action.target_service.strip():
        raise ValueError("target_service cannot be empty.")


def dispatch(
    action: DispatchAction,
    telemetry_path=None,
    log_path=None,
    code_path=None,
):
    """
    Dispatch an investigation request to the appropriate P2 agent.

    Log Agent:
        Retrieves live Docker logs itself and falls back to
        sample_data/logs.txt when Docker is unavailable.

    Metrics Agent:
        Retrieves live service metrics itself and falls back to
        sample_data/metrics.json when live telemetry is unavailable.

    Code Agent:
        Analyzes Git changes from the supplied repository path.
    """

    validate_action(action)

    agent_type = action.agent_type

    # ---------------------------------------------------------
    # LOG AGENT
    # ---------------------------------------------------------
    if agent_type == "log":
        # Pass log_path through so ShopMind incident replay actually
        # reaches the agent instead of silently falling back to
        # sample_data/logs.txt every time.
        return investigate_logs(action, log_path=log_path)

    # ---------------------------------------------------------
    # METRICS AGENT
    # ---------------------------------------------------------
    elif agent_type == "metrics":
        # Pass telemetry_path through so ShopMind incident replay
        # actually reaches the agent instead of silently falling back
        # to sample_data/metrics.json every time.
        return investigate_metrics(action, telemetry_path=telemetry_path)

    # ---------------------------------------------------------
    # CODE AGENT
    # ---------------------------------------------------------
    elif agent_type == "code":
        # Code Agent supports an optional repo_path.
        return investigate_code(
            action,
            repo_path=code_path,
        )

    raise ValueError(
        f"Unsupported agent type: {agent_type}"
    )


def investigate_incident(
    actions,
    telemetry_path=None,
    log_path=None,
    code_path=None,
):
    """
    Run all requested investigation agents and combine
    their findings into an Evidence Bundle.
    """

    findings = []

    for action in actions:
        result = dispatch(
            action,
            telemetry_path=telemetry_path,
            log_path=log_path,
            code_path=code_path,
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
    code_path=None,
):
    """
    Run the complete IncidentMind investigation pipeline.

    Flow:

        DispatchAction
              ↓
        Investigation Agents
        ┌────────┼────────┐
        ↓        ↓        ↓
       Log    Metrics    Code
        └────────┼────────┘
                 ↓
          Evidence Bundle
                 ↓
            Report Agent
                 ↓
             RCA Report
                 ↓
        output/<incident_id>_report.json

    The optional telemetry_path/log_path/code_path arguments are
    retained for compatibility with existing tests and scripts.
    """

    # ---------------------------------------------------------
    # 1. Run investigation agents
    # ---------------------------------------------------------
    evidence_bundle = investigate_incident(
        actions,
        telemetry_path=telemetry_path,
        log_path=log_path,
        code_path=code_path,
    )

    # ---------------------------------------------------------
    # 2. Generate structured RCA report
    # ---------------------------------------------------------
    report = generate_report(
        evidence_bundle,
        incident_id=incident_id,
    )

    # ---------------------------------------------------------
    # 3. Save structured RCA report
    # ---------------------------------------------------------
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f"{incident_id}_report.json"

    import json

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(f"RCA report saved to: {output_file}")

    return {
        "evidence_bundle": evidence_bundle,
        "report": report,
    }
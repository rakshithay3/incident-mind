import json
from pathlib import Path

import ollama

from config import OLLAMA_MODEL, TEMPERATURE
from shopmind_log_adapter import create_log_evidence


LOG_FILE = "sample_data/logs.txt"


def retrieve_logs(target_service, n=20, log_path=None):
    """
    Retrieve the most recent N log lines.

    If log_path is provided, use the supplied ShopMind log file.
    Otherwise, use the existing sample log file.
    """

    source_file = Path(log_path) if log_path else Path(LOG_FILE)

    if not source_file.exists():
        raise FileNotFoundError(
            f"Log file not found: {source_file}"
        )

    # ShopMind logs must be sanitized before reaching the LLM.
    if log_path:
        evidence = create_log_evidence(
            source_file,
            max_lines=n
        )
        return evidence["logs"]

    # Existing sample-data behavior.
    with open(source_file, "r") as file:
        lines = file.readlines()

    # Remove empty lines.
    lines = [
        line.strip()
        for line in lines
        if line.strip()
    ]

    # Find logs related to the target service.
    service_lines = [
        line
        for line in lines
        if target_service.lower() in line.lower()
    ]

    # Use service-specific logs when available.
    if service_lines:
        return service_lines[-n:]

    # Otherwise return the latest N logs.
    return lines[-n:]


def investigate(action, log_path=None):
    """
    Investigate logs for a target service.

    Existing usage:
        investigate(action)

    ShopMind usage:
        investigate(
            action,
            log_path="../shopmind/datasets/incident_002/api-gateway.log"
        )

    Output:
        Structured AgentFinding.
    """

    target_service = action.target_service

    # Retrieve recent logs.
    recent_logs = retrieve_logs(
        target_service,
        n=20,
        log_path=log_path
    )

    if recent_logs:
        log_text = "\n".join(recent_logs)
    else:
        log_text = "No usable log evidence was found."

    prompt = f"""
You are the Log Agent in an automated
incident investigation system.

Target service:
{target_service}

Analyze the following log evidence:

{log_text}

Determine whether the supplied logs indicate:

ERROR
WARNING
NORMAL
INSUFFICIENT_EVIDENCE

Identify the most important error or warning message
only when one is actually present.

Return ONLY valid JSON using exactly this structure:

{{
    "finding": "short explanation of what the logs indicate",
    "severity": "low, medium, or high",
    "confidence": 0.0,
    "evidence": [
        "log message supporting the finding"
    ]
}}

Rules:

1. Focus on evidence relevant to {target_service}.
2. Do not invent log messages, errors, warnings, or failures.
3. Evidence must come directly from the supplied logs.
4. Confidence must be between 0.0 and 1.0.
5. If there is an ERROR, prioritize it.
6. If there is no ERROR but there is a WARNING,
   report the warning.
7. If everything appears normal, report that the logs
   appear normal.
8. If the supplied logs do not contain enough evidence
   to determine abnormal behavior, report
   "insufficient evidence" rather than guessing.
9. Do not infer the injected fault type.
10. Do not claim a root cause unless the supplied logs
    explicitly support that conclusion.
"""

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        options={
            "temperature": TEMPERATURE
        }
    )

    content = response["message"]["content"].strip()

    # Remove accidental markdown code fences.
    if content.startswith("```"):
        content = content.replace("```json", "", 1)
        content = content.replace("```", "")
        content = content.strip()

    # Convert LLaMA response to JSON.
    try:
        result = json.loads(content)

    except json.JSONDecodeError:
        result = {
            "finding": content,
            "severity": "unknown",
            "confidence": 0.0,
            "evidence": []
        }

    # Normalize severity to the allowed values.
    severity = str(
        result.get("severity", "unknown")
    ).lower()

    if severity == "normal":
        severity = "low"

    if severity not in {
        "low",
        "medium",
        "high",
        "unknown"
    }:
        severity = "unknown"

    # Normalize confidence.
    try:
        confidence = float(
            result.get("confidence", 0.0)
        )
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence)
    )

    # Normalize evidence.
    evidence = result.get("evidence", [])

    if not isinstance(evidence, list):
        evidence = [str(evidence)]

    # Return standard AgentFinding structure.
    return {
        "agent_type": "log",
        "target_service": target_service,
        "finding": result.get("finding", ""),
        "severity": severity,
        "confidence": confidence,
        "evidence": evidence
    }
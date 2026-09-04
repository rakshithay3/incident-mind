import json
import ollama

from config import OLLAMA_MODEL, TEMPERATURE


LOG_FILE = "sample_data/logs.txt"


def retrieve_logs(target_service, n=20):
    """
    Retrieve the most recent N log lines
    for the target service.
    """

    with open(LOG_FILE, "r") as file:
        lines = file.readlines()

    # Remove empty lines
    lines = [
        line.strip()
        for line in lines
        if line.strip()
    ]

    # Find logs related to the target service
    service_lines = [
        line
        for line in lines
        if target_service.lower() in line.lower()
    ]

    # Use service-specific logs when available
    if service_lines:
        return service_lines[-n:]

    # Otherwise return the latest N logs
    return lines[-n:]


def investigate(action):
    """
    Investigate logs for a target service.

    Input:
        {
            "agent_type": "log",
            "target_service": "auth-service"
        }

    Output:
        Structured evidence finding.
    """

    target_service = action["target_service"]

    # Retrieve recent logs
    recent_logs = retrieve_logs(
        target_service,
        n=20
    )

    log_text = "\n".join(recent_logs)

    prompt = f"""
You are the Log Agent in an automated
incident investigation system.

Target service:
{target_service}

Analyze the following recent log lines:

{log_text}

Determine whether the logs indicate:

ERROR
WARNING
NORMAL

Identify the most important error or warning message.

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

1. Focus only on {target_service}.
2. Do not invent log messages.
3. Evidence must come from the supplied logs.
4. Confidence must be between 0.0 and 1.0.
5. If there is an ERROR, prioritize it.
6. If there is no ERROR but there is a WARNING,
   report the warning.
7. If everything is normal, report that the logs
   appear normal.
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

    # Remove accidental markdown code fences
    if content.startswith("```"):
        content = content.replace("```json", "", 1)
        content = content.replace("```", "")
        content = content.strip()

    # Convert LLaMA response to JSON
    try:
        result = json.loads(content)

    except json.JSONDecodeError:
        result = {
            "finding": content,
            "severity": "unknown",
            "confidence": 0.0,
            "evidence": []
        }

    # Return standard AgentFinding structure
    return {
        "agent_type": "log",
        "target_service": target_service,
        "finding": result.get("finding", ""),
        "severity": result.get("severity", "unknown"),
        "confidence": result.get("confidence", 0.0),
        "evidence": result.get("evidence", [])
    }
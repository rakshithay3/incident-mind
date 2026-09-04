import json
import ollama

from config import OLLAMA_MODEL, TEMPERATURE


METRICS_FILE = "sample_data/metrics.json"


def investigate(action):
    """
    Investigate metrics for a specific service.

    Args:
        target_service (str): Name of the service to investigate.

    Returns:
        dict: Structured evidence produced by the Metrics Agent.
    """
    target_service = action["target_service"]

    with open(METRICS_FILE, "r") as file:
        all_metrics = json.load(file)

    if target_service not in all_metrics:
        return {
            "agent_type": "metrics",
            "target_service": target_service,
            "finding": "No metrics found for target service.",
            "severity": "unknown",
            "confidence": 0.0,
            "evidence": []
        }

    metrics = all_metrics[target_service]

    prompt = f"""
You are the Metrics Agent in an automated incident investigation system.

Target service:
{target_service}

Analyze the following service metrics:

{json.dumps(metrics, indent=2)}

Compare the baseline values with the current values.

Identify abnormal behavior that could indicate an incident.

Return ONLY valid JSON using exactly this structure:

{{
    "finding": "short description of the main finding",
    "severity": "low, medium, or high",
    "confidence": 0.0,
    "evidence": [
        "specific metric evidence"
    ]
}}

Rules:
- Focus only on the target service.
- Compare current values with baseline values.
- Do not invent metrics.
- Evidence must come from the supplied metrics.
- Confidence must be between 0.0 and 1.0.
- Keep the finding concise.
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

    content = response["message"]["content"]

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "finding": content,
            "severity": "unknown",
            "confidence": 0.0,
            "evidence": []
        }

    return {
        "agent_type": "metrics",
        "target_service": target_service,
        "finding": result.get("finding", ""),
        "severity": result.get("severity", ""),
        "confidence": result.get("confidence", 0.0),
        "evidence": result.get("evidence", [])
    }
import subprocess
from config import OLLAMA_MODEL, OLLAMA_HOST, TEMPERATURE
import requests


def get_git_diff():
    """Get the latest code/config changes from Git."""

    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Git diff failed: {result.stderr}")

    return result.stdout


def investigate(target_service):
    """Investigate recent Git changes for a service."""

    diff = get_git_diff()

    if not diff.strip():
        return {
            "agent_type": "code",
            "target_service": target_service,
            "finding": "No recent code changes detected.",
            "severity": "low",
            "confidence": 0.9,
            "evidence": []
        }

    prompt = f"""
You are a code investigation agent in an incident investigation system.

Target service: {target_service}

Analyze the following Git diff.

GIT DIFF:
{diff}

Determine whether the change could have contributed to an incident.

Return ONLY valid JSON in this format:

{{
    "finding": "short explanation",
    "severity": "low|medium|high",
    "confidence": 0.0,
    "evidence": ["specific evidence from the diff"]
}}
"""

    response = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "temperature": TEMPERATURE,
            "stream": False
        },
        timeout=120
    )

    response.raise_for_status()

    result = response.json()["response"]

    import json

    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        parsed = {
            "finding": result,
            "severity": "medium",
            "confidence": 0.5,
            "evidence": [diff]
        }

    return {
        "agent_type": "code",
        "target_service": target_service,
        "finding": parsed.get("finding", ""),
        "severity": parsed.get("severity", "medium"),
        "confidence": parsed.get("confidence", 0.0),
        "evidence": parsed.get("evidence", [])
    }
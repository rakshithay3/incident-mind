import subprocess
import json
from pathlib import Path

import requests

from config import OLLAMA_MODEL, OLLAMA_HOST, TEMPERATURE


def get_git_diff(repo_path=None):
    """Get the latest Git changes from the specified repository."""

    if not repo_path:
        raise ValueError(
            "get_git_diff() requires an explicit repo_path -- refusing to "
            "fall back to the current working directory, since that risks "
            "diffing an unrelated repo."
        )

    cwd = Path(repo_path).resolve()

    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Git diff failed: {result.stderr}"
        )

    return result.stdout


def investigate(action, repo_path=None):
    """
    Investigate recent Git changes for a service.

    repo_path can be used for ShopMind, for example:
        repo_path="../shopmind"
    """

    target_service = action.target_service
    # No repo configured -- skip rather than silently diffing
    # whatever directory the script happened to be launched from.
    if not repo_path:
        return {
            "agent_type": "code",
            "target_service": target_service,
            "finding": (
                "No code repository path was configured for this run -- "
                "skipping Code Agent analysis rather than risk reporting "
                "on the wrong codebase."
            ),
            "severity": "low",
            "confidence": 1.0,
            "evidence": []
        }

    diff = get_git_diff(repo_path)

    # No changes at all.
    if not diff.strip():
        return {
            "agent_type": "code",
            "target_service": target_service,
            "finding": "No recent code changes detected in the supplied repository.",
            "severity": "low",
            "confidence": 0.9,
            "evidence": []
        }

    # Check whether the diff contains references to the target service.
    target_tokens = {
        target_service.lower(),
        target_service.replace("-service", "").lower()
    }

    diff_lower = diff.lower()

    relevant_to_service = any(
        token and token in diff_lower
        for token in target_tokens
    )

    # If the diff is unrelated to the target service,
    # do NOT allow the LLM to invent a connection.
    if not relevant_to_service:
        return {
            "agent_type": "code",
            "target_service": target_service,
            "finding": (
                "Recent code changes were detected, but the supplied "
                "diff does not contain evidence directly related to "
                f"{target_service}."
            ),
            "severity": "low",
            "confidence": 0.95,
            "evidence": []
        }

    prompt = f"""
You are the Code Agent in an automated
incident investigation system.

Target service:
{target_service}

Analyze ONLY the following Git diff.

GIT DIFF:
{diff}

Determine whether the code changes could have
contributed to an incident affecting {target_service}.

Return ONLY valid JSON:

{{
    "finding": "short explanation",
    "severity": "low|medium|high",
    "confidence": 0.0,
    "evidence": [
        "specific evidence directly from the diff"
    ]
}}

Rules:

1. Focus ONLY on {target_service}.
2. Do not invent code changes.
3. Evidence must come directly from the diff.
4. Confidence must be between 0.0 and 1.0.
5. Do not infer missing metrics, errors, or failures
   unless explicitly shown in the diff.
6. Do not claim that a code change caused an incident
   unless the diff provides direct supporting evidence.
7. If the change is potentially related but causality
   is uncertain, explicitly say so.
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

    result = response.json()["response"].strip()

    # Remove markdown code fences.
    if result.startswith("```"):
        result = result.replace("```json", "", 1)
        result = result.replace("```", "")
        result = result.strip()

    try:
        parsed = json.loads(result)

    except json.JSONDecodeError:
        parsed = {
            "finding": result,
            "severity": "medium",
            "confidence": 0.5,
            "evidence": []
        }

    severity = str(
        parsed.get("severity", "medium")
    ).lower()

    if severity not in {"low", "medium", "high"}:
        severity = "medium"

    return {
        "agent_type": "code",
        "target_service": target_service,
        "finding": parsed.get("finding", ""),
        "severity": severity,
        "confidence": parsed.get("confidence", 0.0),
        "evidence": parsed.get("evidence", [])
    }
import json
import ollama

from config import OLLAMA_MODEL, TEMPERATURE


CODE_DIFF_FILE = "sample_data/code_diff.txt"


def investigate(action):
    """
    Investigate recent code changes for a specific service.

    Args:
        action (dict): DispatchAction containing agent_type
                       and target_service.

    Returns:
        dict: Structured evidence produced by the Code Agent.
    """

    target_service = action["target_service"]

    with open(CODE_DIFF_FILE, "r") as file:
        code_diff = file.read()

    prompt = f"""
You are the Code Agent in an automated incident investigation system.

Target service:
{target_service}

Analyze the following Git diff:

{code_diff}

Identify code changes that could be risky or could contribute to
an incident affecting the target service.

Pay particular attention to:
- Configuration changes
- Database changes
- Authentication changes
- Connection handling
- Retry logic
- API changes
- Resource limits
- Concurrency changes
- Changes that could increase failures or reduce availability

Return ONLY valid JSON using exactly this structure:

{{
    "finding": "short description of the main risky change",
    "severity": "low, medium, or high",
    "confidence": 0.0,
    "evidence": [
        "specific code change supporting the finding"
    ]
}}

Rules:
- Focus on the target service.
- Do not invent code changes.
- Evidence must come directly from the supplied Git diff.
- Confidence must be between 0.0 and 1.0.
- If there is no meaningful risky change, say so.
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
        "agent_type": "code",
        "target_service": target_service,
        "finding": result.get("finding", ""),
        "severity": result.get("severity", ""),
        "confidence": result.get("confidence", 0.0),
        "evidence": result.get("evidence", [])
    }
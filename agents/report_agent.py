import json
import ollama

from config import OLLAMA_MODEL, TEMPERATURE


def generate_report(evidence_bundle, incident_id="inc_001"):
    """
    Generate a final RCA report from specialist-agent findings.

    Args:
        evidence_bundle (dict): Findings from Log, Metrics, and Code agents.
        incident_id (str): Unique identifier for the incident.

    Returns:
        dict: Structured RCA report.
    """

    findings = evidence_bundle.get("findings", [])

    prompt = f"""
You are the Report Agent in an automated incident investigation system.

Incident ID:
{incident_id}

The following specialist agents investigated the incident:

{json.dumps(findings, indent=2)}

Analyze ALL findings together.

Your task is to determine the most likely root cause of the incident.

Consider:
1. Log evidence
2. Metrics abnormalities
3. Risky code changes
4. Relationships between the evidence
5. Which service is most likely responsible
6. What downstream services may be affected

Return ONLY valid JSON using exactly this structure:

{{
    "incident_id": "{incident_id}",
    "root_cause_service": "service name",
    "confidence_score": 0.0,
    "evidence_summary": [
        {{
            "agent_type": "log",
            "summary": "summary of relevant log evidence"
        }},
        {{
            "agent_type": "metrics",
            "summary": "summary of relevant metric evidence"
        }},
        {{
            "agent_type": "code",
            "summary": "summary of relevant code evidence"
        }}
    ],
    "suggested_fix": "specific recommended fix",
    "estimated_blast_radius": [
        "affected-service"
    ],
    "report_text": {{
        "en": "English RCA explanation",
        "hi": "Hindi RCA explanation"
    }}
}}

Rules:
- Use only evidence provided by the specialist agents.
- Do not invent facts.
- The root cause must be supported by the evidence.
- confidence_score must be between 0.0 and 1.0.
- Keep evidence summaries concise.
- Provide a practical suggested fix.
- estimated_blast_radius should contain services supported by the evidence.
- The Hindi report should accurately communicate the same conclusion as the English report.
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

    # Remove markdown code fences if the model returns them.
    if content.startswith("```"):
        content = content.replace("```json", "", 1)
        content = content.replace("```", "")
        content = content.strip()

    try:
        report = json.loads(content)

    except json.JSONDecodeError:
        report = {
            "incident_id": incident_id,
            "root_cause_service": "unknown",
            "confidence_score": 0.0,
            "evidence_summary": [],
            "suggested_fix": "Unable to generate structured report.",
            "estimated_blast_radius": [],
            "report_text": {
                "en": content,
                "hi": ""
            }
        }

    return report
import json

import ollama

from config import OLLAMA_MODEL, TEMPERATURE


def _clean_json_response(content):
    """
    Clean an LLM response and extract the first valid JSON object.
    """

    content = content.strip()

    # Remove Markdown code fences if present.
    if "```json" in content:
        content = content.replace("```json", "", 1)

    if "```" in content:
        content = content.replace("```", "")

    content = content.strip()

    # If the model added text before the JSON,
    # locate the first JSON object.
    start = content.find("{")

    if start == -1:
        return content

    content = content[start:]

    # Find the matching closing brace.
    depth = 0
    in_string = False
    escape = False

    for index, char in enumerate(content):

        if escape:
            escape = False
            continue

        if char == "\\":
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if not in_string:

            if char == "{":
                depth += 1

            elif char == "}":
                depth -= 1

                if depth == 0:
                    return content[:index + 1]

    return content


def _normalize_report(report, incident_id):
    """
    Normalize and validate the report structure returned by Llama.
    """

    if not isinstance(report, dict):
        report = {}

    root_cause_service = report.get(
        "root_cause_service",
        "unknown"
    )

    confidence_score = report.get(
        "confidence_score",
        0.0
    )

    evidence_summary = report.get(
        "evidence_summary",
        []
    )

    suggested_fix = report.get(
        "suggested_fix",
        "No evidence-based fix can be recommended yet."
    )

    estimated_blast_radius = report.get(
        "estimated_blast_radius",
        []
    )

    report_text = report.get(
        "report_text",
        {}
    )

    # Normalize confidence.
    try:
        confidence_score = float(confidence_score)
    except (TypeError, ValueError):
        confidence_score = 0.0

    confidence_score = max(
        0.0,
        min(1.0, confidence_score)
    )

    # Normalize evidence summary.
    if not isinstance(evidence_summary, list):
        evidence_summary = [str(evidence_summary)]

    # Normalize blast radius.
    if not isinstance(estimated_blast_radius, list):
        estimated_blast_radius = [
            str(estimated_blast_radius)
        ]

    # Normalize bilingual report.
    if not isinstance(report_text, dict):
        report_text = {}

    english_text = report_text.get("en", "")
    hindi_text = report_text.get("hi", "")

    return {
        "incident_id": incident_id,
        "root_cause_service": root_cause_service,
        "confidence_score": confidence_score,
        "evidence_summary": evidence_summary,
        "suggested_fix": suggested_fix,
        "estimated_blast_radius": estimated_blast_radius,
        "report_text": {
            "en": english_text,
            "hi": hindi_text
        }
    }


def generate_report(evidence_bundle, incident_id="inc_001"):
    """
    Generate an evidence-grounded bilingual RCA report.

    Input:
        evidence_bundle = {
            "findings": [
                {
                    "agent_type": "metrics",
                    "target_service": "auth-service",
                    "finding": "...",
                    "severity": "medium",
                    "confidence": 0.8,
                    "evidence": [...]
                }
            ]
        }

    Output:
        {
            "incident_id": "...",
            "root_cause_service": "...",
            "confidence_score": 0.0,
            "evidence_summary": [...],
            "suggested_fix": "...",
            "estimated_blast_radius": [...],
            "report_text": {
                "en": "...",
                "hi": "..."
            }
        }
    """

    findings = evidence_bundle.get("findings", [])

    if not isinstance(findings, list):
        findings = []

    # Convert evidence into a readable but explicit input for Llama.
    evidence_text = json.dumps(
        findings,
        indent=2,
        ensure_ascii=False
    )

    prompt = f"""
You are the Report Agent in an automated
incident investigation system.

Your job is to create a conservative,
evidence-grounded Root Cause Analysis (RCA).

Incident ID:
{incident_id}

The following findings were produced by
independent investigation agents:

{evidence_text}

IMPORTANT PRINCIPLE:

Only make claims that are directly supported
by the supplied agent findings.

Do NOT invent:
- errors
- failures
- vulnerabilities
- code defects
- configuration problems
- authorization bypasses
- performance problems
- root causes
- affected services
- fixes

If the evidence is insufficient to identify
a root cause, explicitly report:

"unknown"

for root_cause_service and explain that
there is insufficient evidence.

A service being investigated does NOT
automatically mean that it is the root cause.

A high confidence value from one agent alone
does NOT prove a root cause.

Do not treat an injected fault type as evidence.

ROOT CAUSE RULE:

Only identify a root-cause service when the
available findings provide clear supporting
evidence.

Prefer agreement between independent evidence
sources such as logs, metrics, code, or traces.

If evidence sources disagree or are weak,
use:

"unknown"

Do not turn a symptom into a root cause.

For example:

Bad:
"CPU increased, therefore the service has
an inefficient algorithm."

Good:
"CPU utilization increased during the failure
window, but the available evidence is
insufficient to determine the underlying cause."

SUGGESTED FIX RULE:

Only recommend a specific fix when the
evidence supports it.

If the root cause is unknown, recommend
continued investigation rather than inventing
a specific remediation.

BLAST RADIUS RULE:

Only include services explicitly supported
by the findings.

Do not invent downstream services.

CONFIDENCE RULE:

The confidence score must represent confidence
in the ROOT CAUSE conclusion, not merely
confidence in an individual observation.

If the root cause is unknown, confidence
should normally be low.

BILINGUAL REPORT:

The English and Hindi reports must communicate
the same conclusion.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "incident_id": "{incident_id}",
    "root_cause_service": "service-name or unknown",
    "confidence_score": 0.0,
    "evidence_summary": [
        {{
            "agent_type": "log",
            "summary": "evidence-based summary"
        }}
    ],
    "suggested_fix": "evidence-based recommendation",
    "estimated_blast_radius": [
        "service-name"
    ],
    "report_text": {{
        "en": "English RCA report",
        "hi": "Hindi RCA report"
    }}
}}

Additional rules:

1. confidence_score must be between 0.0 and 1.0.
2. evidence_summary must only summarize supplied findings.
3. Do not add evidence that is not present.
4. root_cause_service must be "unknown" when evidence is insufficient.
5. Do not claim that normal logs prove the service is healthy.
6. Do not claim a fault type unless the evidence supports it.
7. Do not infer a security vulnerability from normal authentication logs.
8. Do not convert small metric changes into a serious diagnosis.
9. If only one weak evidence source is available, prefer "unknown".
10. English and Hindi must express the same RCA conclusion.
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

    content = _clean_json_response(content)

    try:
        report = json.loads(content)

    except json.JSONDecodeError:
        report = {
            "incident_id": incident_id,
            "root_cause_service": "unknown",
            "confidence_score": 0.0,
            "evidence_summary": [
                {
                    "agent_type": "system",
                    "summary": (
                        "The Report Agent could not parse "
                        "a valid structured response."
                    )
                }
            ],
            "suggested_fix": (
                "No specific fix can be recommended "
                "until valid evidence is available."
            ),
            "estimated_blast_radius": [],
            "report_text": {
                "en": content,
                "hi": content
            }
        }

    return _normalize_report(
        report,
        incident_id
    )
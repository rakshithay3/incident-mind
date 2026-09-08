import json
import time

import ollama

from config import OLLAMA_MODEL, OLLAMA_HOST, TEMPERATURE


# =========================================================
# Clean JSON response
# =========================================================

def _clean_json_response(content):
    """
    Clean an LLM response and extract the first valid JSON object.
    """

    if not isinstance(content, str):
        return ""

    content = content.strip()

    # Remove Markdown code fences.
    if content.startswith("```json"):
        content = content[len("```json"):].strip()

    elif content.startswith("```"):
        content = content[3:].strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    # Find the first JSON object.
    start = content.find("{")

    if start == -1:
        return content

    content = content[start:]

    # Find matching closing brace while respecting strings.
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


# =========================================================
# Normalize report
# =========================================================

def _normalize_report(report, incident_id):
    """
    Normalize and validate the structured RCA report.

    Guarantees the final report follows the IncidentMind
    RCA schema even if the LLM response is incomplete.
    """

    if not isinstance(report, dict):
        report = {}

    # -----------------------------------------------------
    # Incident ID
    # -----------------------------------------------------

    normalized_incident_id = report.get(
        "incident_id",
        incident_id
    )

    if not normalized_incident_id:
        normalized_incident_id = incident_id

    # -----------------------------------------------------
    # Root cause service
    # -----------------------------------------------------

    root_cause_service = report.get(
        "root_cause_service",
        "unknown"
    )

    if not isinstance(root_cause_service, str):
        root_cause_service = "unknown"

    root_cause_service = root_cause_service.strip()

    if not root_cause_service:
        root_cause_service = "unknown"

    # -----------------------------------------------------
    # Confidence
    # -----------------------------------------------------

    confidence_score = report.get(
        "confidence_score",
        0.0
    )

    try:
        confidence_score = float(
            confidence_score
        )

    except (TypeError, ValueError):
        confidence_score = 0.0

    confidence_score = max(
        0.0,
        min(1.0, confidence_score)
    )

    # Unknown root cause should have low confidence.
    if root_cause_service.lower() == "unknown":
        confidence_score = min(
            confidence_score,
            0.35
        )

    # -----------------------------------------------------
    # Evidence summary
    # -----------------------------------------------------

    evidence_summary = report.get(
        "evidence_summary",
        []
    )

    if not isinstance(evidence_summary, list):
        evidence_summary = [
            {
                "agent_type": "system",
                "summary": str(
                    evidence_summary
                )
            }
        ]

    normalized_evidence = []

    for item in evidence_summary:

        if isinstance(item, dict):

            agent_type = item.get(
                "agent_type",
                "unknown"
            )

            summary = item.get(
                "summary",
                ""
            )

            normalized_evidence.append(
                {
                    "agent_type": str(
                        agent_type
                    ),
                    "summary": str(
                        summary
                    )
                }
            )

        else:

            normalized_evidence.append(
                {
                    "agent_type": "unknown",
                    "summary": str(item)
                }
            )

    # -----------------------------------------------------
    # Suggested fix
    # -----------------------------------------------------

    suggested_fix = report.get(
        "suggested_fix",
        "No evidence-based fix can be recommended yet."
    )

    if suggested_fix is None:

        suggested_fix = (
            "No evidence-based fix can be "
            "recommended yet."
        )

    if not isinstance(
        suggested_fix,
        str
    ):
        suggested_fix = str(
            suggested_fix
        )

    # -----------------------------------------------------
    # Blast radius
    # -----------------------------------------------------

    estimated_blast_radius = report.get(
        "estimated_blast_radius",
        []
    )

    if not isinstance(
        estimated_blast_radius,
        list
    ):

        estimated_blast_radius = [
            str(estimated_blast_radius)
        ]

    normalized_blast_radius = []

    for service in estimated_blast_radius:

        if service is None:
            continue

        service = str(
            service
        ).strip()

        if (
            service
            and service
            not in normalized_blast_radius
        ):
            normalized_blast_radius.append(
                service
            )

    # -----------------------------------------------------
    # Bilingual report
    # -----------------------------------------------------

    report_text = report.get(
        "report_text",
        {}
    )

    if not isinstance(
        report_text,
        dict
    ):
        report_text = {}

    english_text = report_text.get(
        "en",
        ""
    )

    hindi_text = report_text.get(
        "hi",
        ""
    )

    if english_text is None:
        english_text = ""

    if hindi_text is None:
        hindi_text = ""

    # -----------------------------------------------------
    # Final normalized report
    # -----------------------------------------------------

    return {
        "incident_id": normalized_incident_id,

        "root_cause_service":
            root_cause_service,

        "confidence_score":
            confidence_score,

        "evidence_summary":
            normalized_evidence,

        "suggested_fix":
            suggested_fix,

        "estimated_blast_radius":
            normalized_blast_radius,

        "report_text": {
            "en": str(
                english_text
            ),
            "hi": str(
                hindi_text
            )
        }
    }


# =========================================================
# Generate Report
# =========================================================

def generate_report(
    evidence_bundle,
    incident_id="inc_001"
):
    """
    Generate an evidence-grounded bilingual RCA report.
    """

    # -----------------------------------------------------
    # Validate Evidence Bundle
    # -----------------------------------------------------

    if not isinstance(
        evidence_bundle,
        dict
    ):
        evidence_bundle = {}

    findings = evidence_bundle.get(
        "findings",
        []
    )

    if not isinstance(
        findings,
        list
    ):
        findings = []

    # Keep only dictionary findings.
    findings = [
        finding
        for finding in findings
        if isinstance(
            finding,
            dict
        )
    ]

    # -----------------------------------------------------
    # Prepare evidence
    # -----------------------------------------------------

    evidence_text = json.dumps(
        findings,
        indent=2,
        ensure_ascii=False
    )

    # -----------------------------------------------------
    # Report Agent prompt
    # -----------------------------------------------------

    prompt = f"""
You are the Report Agent in an automated
incident investigation system.

Create one conservative Root Cause Analysis
from the supplied agent findings.

Incident ID:
{incident_id}

AGENT FINDINGS:
{evidence_text}

IMPORTANT RULES:

1. Use ONLY evidence contained in AGENT FINDINGS.

2. Do not invent errors, failures, vulnerabilities,
   code defects, configuration problems, fixes,
   affected services, or fault types.

3. Do not use the target service alone as proof
   of root cause.

4. Do not treat CPU, memory, latency, or error-rate
   anomalies alone as proof of root cause.

5. If multiple independent findings support the
   SAME service and are causally consistent,
   that service may be selected as root cause.

6. If evidence is insufficient or conflicting,
   use "unknown".

7. If root_cause_service is "unknown",
   confidence_score must normally be <= 0.35.

8. estimated_blast_radius may contain ONLY services
   explicitly supported by the findings.

9. English and Hindi must communicate exactly
   the same conclusion.

10. Return ONLY valid JSON.

OUTPUT:

{{
    "incident_id": "{incident_id}",
    "root_cause_service": "service-name or unknown",
    "confidence_score": 0.0,
    "evidence_summary": [
        {{
            "agent_type": "metrics",
            "summary": "evidence-based summary"
        }}
    ],
    "suggested_fix": "evidence-based recommendation",
    "estimated_blast_radius": [],
    "report_text": {{
        "en": "English RCA report",
        "hi": "Hindi RCA report"
    }}
}}
"""

    # -----------------------------------------------------
    # Call Ollama
    # -----------------------------------------------------

    print(
        "  Sending request to Ollama...",
        flush=True
    )

    report_start = time.time()

    try:

        client = ollama.Client(
            host=OLLAMA_HOST,
            timeout=120
        )

        response = client.chat(
            model=OLLAMA_MODEL,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            format="json",

            options={
                "temperature": TEMPERATURE,

                # Limit generated tokens so the
                # Report Agent cannot generate indefinitely.
                "num_predict": 350
            }
        )

    except Exception as exc:

        print(
            f"  Report Agent Ollama error: "
            f"{type(exc).__name__}: {exc}",
            flush=True
        )

        return _normalize_report(
            {
                "incident_id": incident_id,
                "root_cause_service": "unknown",
                "confidence_score": 0.0,
                "evidence_summary": [
                    {
                        "agent_type": "system",
                        "summary": (
                            "Report Agent Ollama request "
                            "failed or timed out."
                        )
                    }
                ],
                "suggested_fix": (
                    "Retry the Report Agent after "
                    "verifying Ollama availability."
                ),
                "estimated_blast_radius": [],
                "report_text": {
                    "en": (
                        "The Report Agent could not "
                        "complete the RCA because the "
                        "LLM request failed or timed out."
                    ),
                    "hi": (
                        "एलएलएम अनुरोध विफल होने या "
                        "समय समाप्त होने के कारण "
                        "रिपोर्ट एजेंट RCA पूरा नहीं कर सका।"
                    )
                }
            },
            incident_id
        )

    elapsed = (
        time.time() - report_start
    )

    print(
        f"  Ollama response received in "
        f"{elapsed:.1f}s",
        flush=True
    )

    # -----------------------------------------------------
    # Extract response content
    # -----------------------------------------------------

    try:

        content = response[
            "message"
        ][
            "content"
        ].strip()

    except (
        KeyError,
        TypeError,
        AttributeError
    ):

        content = ""

    print(
        "\n=== RAW REPORT AGENT RESPONSE ===",
        flush=True
    )

    print(
        content,
        flush=True
    )

    print(
        "=== END RAW RESPONSE ===\n",
        flush=True
    )

    content = _clean_json_response(
        content
    )

    # -----------------------------------------------------
    # Parse JSON
    # -----------------------------------------------------

    try:

        report = json.loads(
            content
        )

    except json.JSONDecodeError:

        report = {
            "incident_id":
                incident_id,

            "root_cause_service":
                "unknown",

            "confidence_score":
                0.0,

            "evidence_summary": [
                {
                    "agent_type":
                        "system",

                    "summary": (
                        "The Report Agent could "
                        "not parse a valid "
                        "structured response."
                    )
                }
            ],

            "suggested_fix": (
                "No specific fix can be "
                "recommended until a valid "
                "structured RCA response "
                "is available."
            ),

            "estimated_blast_radius":
                [],

            "report_text": {
                "en": (
                    "The Report Agent did not "
                    "return valid structured JSON."
                ),

                "hi": (
                    "रिपोर्ट एजेंट ने मान्य "
                    "संरचित JSON प्रतिक्रिया "
                    "नहीं दी।"
                )
            }
        }

    # -----------------------------------------------------
    # Normalize final report
    # -----------------------------------------------------

    return _normalize_report(
        report,
        incident_id
    )
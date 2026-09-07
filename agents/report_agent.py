import json

import ollama

from config import OLLAMA_MODEL, TEMPERATURE


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

    # Find the matching closing brace while respecting strings.
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
    Normalize and validate the structured RCA report.

    This function guarantees that the final report follows
    the IncidentMind RCA schema even if the LLM response is
    incomplete or contains incorrect field types.
    """

    if not isinstance(report, dict):
        report = {}

    # ---------------------------------------------------------
    # Incident ID
    # ---------------------------------------------------------

    normalized_incident_id = report.get(
        "incident_id",
        incident_id
    )

    if not normalized_incident_id:
        normalized_incident_id = incident_id

    # ---------------------------------------------------------
    # Root cause service
    # ---------------------------------------------------------

    root_cause_service = report.get(
        "root_cause_service",
        "unknown"
    )

    if not isinstance(root_cause_service, str):
        root_cause_service = "unknown"

    root_cause_service = root_cause_service.strip()

    if not root_cause_service:
        root_cause_service = "unknown"

    # ---------------------------------------------------------
    # Confidence
    # ---------------------------------------------------------

    confidence_score = report.get(
        "confidence_score",
        0.0
    )

    try:
        confidence_score = float(confidence_score)
    except (TypeError, ValueError):
        confidence_score = 0.0

    confidence_score = max(
        0.0,
        min(1.0, confidence_score)
    )

    # If root cause is unknown, confidence should remain low.
    if root_cause_service.lower() == "unknown":
        confidence_score = min(confidence_score, 0.35)

    # ---------------------------------------------------------
    # Evidence summary
    # ---------------------------------------------------------

    evidence_summary = report.get(
        "evidence_summary",
        []
    )

    if not isinstance(evidence_summary, list):
        evidence_summary = [
            {
                "agent_type": "system",
                "summary": str(evidence_summary)
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
                    "agent_type": str(agent_type),
                    "summary": str(summary)
                }
            )

        else:
            normalized_evidence.append(
                {
                    "agent_type": "unknown",
                    "summary": str(item)
                }
            )

    # ---------------------------------------------------------
    # Suggested fix
    # ---------------------------------------------------------

    suggested_fix = report.get(
        "suggested_fix",
        "No evidence-based fix can be recommended yet."
    )

    if suggested_fix is None:
        suggested_fix = (
            "No evidence-based fix can be recommended yet."
        )

    if not isinstance(suggested_fix, str):
        suggested_fix = str(suggested_fix)

    # ---------------------------------------------------------
    # Blast radius
    # ---------------------------------------------------------

    estimated_blast_radius = report.get(
        "estimated_blast_radius",
        []
    )

    if not isinstance(estimated_blast_radius, list):
        estimated_blast_radius = [
            str(estimated_blast_radius)
        ]

    normalized_blast_radius = []

    for service in estimated_blast_radius:

        if service is None:
            continue

        service = str(service).strip()

        if service and service not in normalized_blast_radius:
            normalized_blast_radius.append(service)

    # ---------------------------------------------------------
    # Bilingual report
    # ---------------------------------------------------------

    report_text = report.get(
        "report_text",
        {}
    )

    if not isinstance(report_text, dict):
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

    return {
        "incident_id": normalized_incident_id,
        "root_cause_service": root_cause_service,
        "confidence_score": confidence_score,
        "evidence_summary": normalized_evidence,
        "suggested_fix": suggested_fix,
        "estimated_blast_radius": normalized_blast_radius,
        "report_text": {
            "en": str(english_text),
            "hi": str(hindi_text)
        }
    }


def generate_report(
    evidence_bundle,
    incident_id="inc_001"
):
    """
    Generate an evidence-grounded bilingual RCA report.

    Input:
        evidence_bundle = {
            "findings": [
                {
                    "agent_type": "log",
                    "target_service": "auth-service",
                    "finding": "...",
                    "severity": "high",
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

    # ---------------------------------------------------------
    # Validate Evidence Bundle
    # ---------------------------------------------------------

    if not isinstance(evidence_bundle, dict):
        evidence_bundle = {}

    findings = evidence_bundle.get(
        "findings",
        []
    )

    if not isinstance(findings, list):
        findings = []

    # Keep only dictionary findings.
    findings = [
        finding
        for finding in findings
        if isinstance(finding, dict)
    ]

    # ---------------------------------------------------------
    # Prepare evidence for the Report Agent
    # ---------------------------------------------------------

    evidence_text = json.dumps(
        findings,
        indent=2,
        ensure_ascii=False
    )

    prompt = f"""
You are the Report Agent in an automated
incident investigation system.

Your task is to synthesize findings from
independent Log, Metrics, and Code agents
into one conservative Root Cause Analysis.

Incident ID:
{incident_id}

==================================================
AGENT FINDINGS
==================================================

{evidence_text}

==================================================
CORE RCA PRINCIPLE
==================================================

You must distinguish between:

1. OBSERVATION
   Something directly observed by an agent.

2. SYMPTOM
   A measurable or logged effect of the incident.

3. ROOT CAUSE
   The service or change that is supported as
   the underlying cause by multiple pieces of
   evidence.

Do NOT automatically treat a symptom as a root cause.

For example:

Observation:
"CPU utilization increased."

This does NOT prove:

"An inefficient algorithm caused the incident."

Similarly:

Observation:
"Error rate increased."

This does NOT automatically prove:

"A code defect caused the incident."

==================================================
ROOT CAUSE DECISION RULE
==================================================

Use the following hierarchy.

RULE 1:
If two or more independent evidence sources
support the SAME service and the findings are
consistent, that service may be identified as
the root cause.

For example:

Log Agent:
"auth-service returned repeated connection errors."

Metrics Agent:
"auth-service latency and error rate increased."

These findings together may support:

"auth-service"

as the root-cause service.

RULE 2:
If only one agent provides evidence, identify
a root cause ONLY if that evidence is explicit
and strong enough to establish causality.

Otherwise use:

"unknown"

RULE 3:
If different agents point to different services
and the evidence does not establish a causal
relationship between them, use:

"unknown"

RULE 4:
If Metrics only reports abnormal CPU, memory,
latency, or error rate, treat that as a symptom
unless another finding connects the anomaly to
a specific root cause.

RULE 5:
If Code Agent reports a change but the change
does not clearly affect the target service or
incident symptoms, do NOT use that code change
as the root cause.

RULE 6:
A high confidence score from an individual agent
does NOT automatically establish the root cause.

RULE 7:
The target_service field alone does NOT prove
that the service is the root cause.

RULE 8:
Do not identify a root cause merely because
a service experienced an injected fault.

Do not use fault_type as evidence unless the
supplied findings independently support it.

==================================================
EVIDENCE PRIORITY
==================================================

Prefer evidence in this general order:

1. Explicit errors directly connected to the
   investigated service.

2. Agreement between independent agents.

3. Code changes directly connected to the
   observed incident symptoms.

4. Strong metric anomalies correlated with
   the incident window.

5. Weak or isolated observations.

Never manufacture missing evidence.

==================================================
CONFLICT HANDLING
==================================================

If findings conflict:

- explain the conflict;
- do not choose a root cause arbitrarily;
- use "unknown" if causality cannot be established.

Example:

Log:
"auth-service connection refused."

Metrics:
"payment-service latency increased."

Code:
"No relevant payment-service change."

Do NOT automatically conclude that auth-service
caused the payment-service incident.

Instead explain that the evidence indicates
an auth-service error and payment-service
degradation, but does not establish causality.

==================================================
SUGGESTED FIX
==================================================

Only recommend a specific remediation when
the evidence supports the underlying issue.

If root cause is unknown:

recommend further investigation.

Good:

"Correlate auth-service connection errors
with payment-service request traces to establish
whether the dependency failure caused the
observed degradation."

Bad:

"Rewrite the authentication algorithm."

Do not invent configuration changes,
code defects, vulnerabilities, or architecture
problems.

==================================================
BLAST RADIUS
==================================================

estimated_blast_radius may contain ONLY services
explicitly supported by the supplied findings.

Do not invent downstream services.

If the evidence does not establish a blast radius,
return an empty list.

==================================================
CONFIDENCE SCORE
==================================================

confidence_score represents confidence in the
ROOT CAUSE conclusion.

It does NOT represent confidence in individual
agent observations.

Suggested interpretation:

0.00 - 0.30:
Root cause unknown or very weak evidence.

0.31 - 0.60:
Some supporting evidence but significant
uncertainty remains.

0.61 - 0.80:
Multiple consistent evidence sources support
the same root cause.

0.81 - 1.00:
Strong independent evidence clearly supports
the same root cause.

Do not use a high confidence score merely because
one agent reported high confidence.

If root_cause_service is "unknown", normally keep
confidence_score at or below 0.35.

==================================================
EVIDENCE SUMMARY
==================================================

Summarize each supplied finding.

Do not invent new evidence.

Each summary must contain:

- agent_type
- summary

==================================================
BILINGUAL REPORT
==================================================

The English and Hindi reports must communicate
the SAME conclusion.

Do not introduce additional claims in Hindi.

If the root cause is unknown, both reports must
clearly state that the available evidence is
insufficient to establish a root cause.

==================================================
OUTPUT FORMAT
==================================================

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

==================================================
STRICT RULES
==================================================

1. Return valid JSON only.

2. confidence_score must be between 0.0 and 1.0.

3. evidence_summary may contain ONLY information
   present in the supplied agent findings.

4. Do not invent errors.

5. Do not invent failures.

6. Do not invent vulnerabilities.

7. Do not invent code defects.

8. Do not invent configuration problems.

9. Do not invent affected services.

10. Do not invent fixes.

11. Do not infer a security vulnerability from
    normal authentication logs.

12. Do not treat normal successful requests as
    proof that a service is healthy.

13. Do not convert small metric changes into a
    serious diagnosis.

14. Do not claim a fault type unless supported
    by valid evidence.

15. Do not identify a root cause when evidence
    sources disagree without causal support.

16. Prefer "unknown" over an unsupported claim.

17. If multiple independent findings consistently
    support the same service and causal explanation,
    synthesize them rather than automatically
    returning "unknown".

18. English and Hindi must express the same
    conclusion.
"""

    # ---------------------------------------------------------
    # Call Llama
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Clean LLM response
    # ---------------------------------------------------------

    content = _clean_json_response(content)

    # ---------------------------------------------------------
    # Parse JSON
    # ---------------------------------------------------------

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
                "until a valid structured RCA response "
                "is available."
            ),
            "estimated_blast_radius": [],
            "report_text": {
                "en": (
                    "The Report Agent did not return "
                    "valid structured JSON."
                ),
                "hi": (
                    "रिपोर्ट एजेंट ने मान्य संरचित JSON "
                    "प्रतिक्रिया नहीं दी।"
                )
            }
        }

    # ---------------------------------------------------------
    # Normalize final report
    # ---------------------------------------------------------

    return _normalize_report(
        report,
        incident_id
    )
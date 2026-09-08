import json
from pathlib import Path

import ollama

from config import OLLAMA_MODEL, OLLAMA_HOST, TEMPERATURE


# =========================================================
# Default metrics file
# =========================================================

DEFAULT_METRICS_PATH = Path(
    "sample_data/metrics.json"
)


# =========================================================
# Load sample metrics
# =========================================================

def load_metrics(metrics_path):
    """Load metrics JSON from a file."""

    path = Path(metrics_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Metrics file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


# =========================================================
# Load ShopMind telemetry
# =========================================================

def load_shopmind_telemetry(telemetry_path):
    """
    Load ShopMind telemetry_series.json.

    The fault_type and target_service fields are retained
    for evaluation/use by the pipeline.

    IMPORTANT:
    fault_type is never included in the LLM prompt.
    """

    path = Path(
        telemetry_path
    )

    if not path.exists():
        raise FileNotFoundError(
            f"ShopMind telemetry file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    required_fields = [
        "incident_id",
        "target_service",
        "fault_type",
        "baseline_history",
        "failure_history",
    ]

    for field in required_fields:

        if field not in data:
            raise ValueError(
                "ShopMind telemetry is missing "
                f"required field: {field}"
            )

    return data


# =========================================================
# Summarize ShopMind telemetry
# =========================================================

def summarize_shopmind_telemetry(data):
    """
    Convert ShopMind telemetry into compact
    service-level baseline vs failure summaries.

    IMPORTANT:
    fault_type is intentionally NOT included in
    the metrics summary sent to the LLM.
    """

    baseline_history = data.get(
        "baseline_history",
        []
    )

    failure_history = data.get(
        "failure_history",
        []
    )

    services = {}

    # -----------------------------------------------------
    # Collect baseline measurements
    # -----------------------------------------------------

    for snapshot in baseline_history:

        for node in snapshot.get(
            "nodes",
            []
        ):

            service_id = node.get(
                "service_id"
            )

            if not service_id:
                continue

            services.setdefault(
                service_id,
                {
                    "baseline": [],
                    "failure": [],
                }
            )

            services[
                service_id
            ][
                "baseline"
            ].append(node)

    # -----------------------------------------------------
    # Collect failure measurements
    # -----------------------------------------------------

    for snapshot in failure_history:

        for node in snapshot.get(
            "nodes",
            []
        ):

            service_id = node.get(
                "service_id"
            )

            if not service_id:
                continue

            services.setdefault(
                service_id,
                {
                    "baseline": [],
                    "failure": [],
                }
            )

            services[
                service_id
            ][
                "failure"
            ].append(node)

    # -----------------------------------------------------
    # Average helper
    # -----------------------------------------------------

    def average(records, field):

        values = []

        for record in records:

            value = record.get(
                field
            )

            if isinstance(
                value,
                (int, float)
            ):
                values.append(value)

        if not values:
            return 0.0

        return sum(values) / len(values)

    # -----------------------------------------------------
    # Build summary
    # -----------------------------------------------------

    summary = []

    for service_id, service_data in services.items():

        baseline_records = (
            service_data["baseline"]
        )

        failure_records = (
            service_data["failure"]
        )

        baseline = {
            "cpu_pct": average(
                baseline_records,
                "cpu_pct"
            ),

            "mem_pct": average(
                baseline_records,
                "mem_pct"
            ),

            "error_rate": average(
                baseline_records,
                "error_rate"
            ),

            "mean_latency_ms": average(
                baseline_records,
                "mean_latency_ms"
            ),

            "p99_latency_ms": average(
                baseline_records,
                "p99_latency_ms"
            ),
        }

        failure = {
            "cpu_pct": average(
                failure_records,
                "cpu_pct"
            ),

            "mem_pct": average(
                failure_records,
                "mem_pct"
            ),

            "error_rate": average(
                failure_records,
                "error_rate"
            ),

            "mean_latency_ms": average(
                failure_records,
                "mean_latency_ms"
            ),

            "p99_latency_ms": average(
                failure_records,
                "p99_latency_ms"
            ),
        }

        # -------------------------------------------------
        # Calculate changes
        # -------------------------------------------------

        changes = {
            "cpu_pct_change": (
                failure["cpu_pct"]
                - baseline["cpu_pct"]
            ),

            "mem_pct_change": (
                failure["mem_pct"]
                - baseline["mem_pct"]
            ),

            "error_rate_change": (
                failure["error_rate"]
                - baseline["error_rate"]
            ),

            "mean_latency_ms_change": (
                failure["mean_latency_ms"]
                - baseline["mean_latency_ms"]
            ),

            "p99_latency_ms_change": (
                failure["p99_latency_ms"]
                - baseline["p99_latency_ms"]
            ),
        }

        summary.append(
            {
                "service_id": service_id,
                "baseline": baseline,
                "failure": failure,
                "changes": changes,
            }
        )

    return {
        "incident_id": data[
            "incident_id"
        ],

        "target_service": data[
            "target_service"
        ],

        "metrics": summary,
    }


# =========================================================
# Build ShopMind prompt
# =========================================================

def build_shopmind_prompt(
    action,
    telemetry_summary
):
    """
    Build the LLM prompt for ShopMind telemetry.

    The ground-truth fault_type is deliberately excluded.
    """

    target_service = (
        action.target_service
    )

    metrics_json = json.dumps(
        telemetry_summary,
        indent=2,
        ensure_ascii=False
    )

    return f"""
You are a Metrics Investigation Agent in an
automated incident root-cause analysis system.

Target service:
{target_service}

Investigate the incident using ONLY the
telemetry provided below.

The telemetry contains baseline measurements
and measurements during the failure window.

Compare baseline and failure metrics.

Pay particular attention to:

- CPU utilization
- Memory utilization
- Error rate
- Mean latency
- P99 latency
- Changes between baseline and failure

IMPORTANT:

1. Report observations only.
2. Do not assume the cause.
3. Do not invent evidence.
4. Do not use fault_type.
5. Do not claim that a metric anomaly proves
   a specific fault or root cause.
6. Focus on the target service.
7. Return ONE JSON object only.
8. The evidence array must contain specific
   measurements from the telemetry.
9. Confidence represents confidence that the
   reported metric anomaly is real, NOT confidence
   that the metric anomaly is the root cause.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "finding": "short explanation of observed metric behavior",
    "severity": "low|medium|high|unknown",
    "confidence": 0.0,
    "evidence": [
        "specific metric evidence"
    ]
}}

Telemetry:

{metrics_json}
"""


# =========================================================
# Extract JSON safely
# =========================================================

def _extract_json_objects(content):
    """
    Extract JSON objects from an LLM response.

    This is intentionally robust because a local model
    may sometimes return multiple JSON objects despite
    being instructed to return only one.
    """

    if not isinstance(
        content,
        str
    ):
        return []

    content = content.strip()

    # Remove Markdown fences.
    if content.startswith(
        "```json"
    ):
        content = content[
            len("```json"):
        ].strip()

    elif content.startswith(
        "```"
    ):
        content = content[
            3:
        ].strip()

    if content.endswith(
        "```"
    ):
        content = content[
            :-3
        ].strip()

    decoder = json.JSONDecoder()

    objects = []

    index = 0

    while index < len(content):

        start = content.find(
            "{",
            index
        )

        if start == -1:
            break

        try:

            obj, end = decoder.raw_decode(
                content[start:]
            )

            if isinstance(
                obj,
                dict
            ):
                objects.append(obj)

            index = (
                start + end
            )

        except json.JSONDecodeError:

            index = start + 1

    return objects


# =========================================================
# Normalize multiple LLM outputs
# =========================================================

def _normalize_llm_result(
    content
):
    """
    Convert one or more LLM JSON objects into
    one standard Metrics Agent result.

    If the model accidentally returns multiple
    findings, their evidence is combined instead
    of being discarded.
    """

    objects = _extract_json_objects(
        content
    )

    if not objects:

        return {
            "finding": (
                content.strip()
                if isinstance(
                    content,
                    str
                )
                else ""
            ),

            "severity": "unknown",

            "confidence": 0.0,

            "evidence": [],
        }

    # -----------------------------------------------------
    # If exactly one object was returned
    # -----------------------------------------------------

    if len(objects) == 1:

        result = objects[0]

        return {
            "finding": str(
                result.get(
                    "finding",
                    ""
                )
            ),

            "severity": str(
                result.get(
                    "severity",
                    "unknown"
                )
            ).lower(),

            "confidence": _safe_confidence(
                result.get(
                    "confidence",
                    0.0
                )
            ),

            "evidence": _normalize_evidence(
                result.get(
                    "evidence",
                    []
                )
            ),
        }

    # -----------------------------------------------------
    # Multiple objects
    # -----------------------------------------------------

    findings = []
    evidence = []
    severities = []
    confidences = []

    for result in objects:

        finding = result.get(
            "finding"
        )

        if finding:
            findings.append(
                str(finding)
            )

        severity = str(
            result.get(
                "severity",
                "unknown"
            )
        ).lower()

        if severity in {
            "low",
            "medium",
            "high",
        }:
            severities.append(
                severity
            )

        confidence = _safe_confidence(
            result.get(
                "confidence",
                0.0
            )
        )

        confidences.append(
            confidence
        )

        evidence.extend(
            _normalize_evidence(
                result.get(
                    "evidence",
                    []
                )
            )
        )

    # Remove duplicate evidence.
    unique_evidence = []

    for item in evidence:

        if item not in unique_evidence:
            unique_evidence.append(
                item
            )

    # Combine findings.
    combined_finding = (
        " ".join(findings)
    ).strip()

    # Choose highest severity.
    if "high" in severities:
        combined_severity = "high"

    elif "medium" in severities:
        combined_severity = "medium"

    elif "low" in severities:
        combined_severity = "low"

    else:
        combined_severity = "unknown"

    # Average confidence, bounded.
    if confidences:
        combined_confidence = (
            sum(confidences)
            / len(confidences)
        )
    else:
        combined_confidence = 0.0

    return {
        "finding": combined_finding,

        "severity": combined_severity,

        "confidence": round(
            combined_confidence,
            4
        ),

        "evidence": unique_evidence,
    }


# =========================================================
# Helpers
# =========================================================

def _safe_confidence(value):

    try:
        value = float(value)

    except (
        TypeError,
        ValueError
    ):
        return 0.0

    return max(
        0.0,
        min(
            1.0,
            value
        )
    )


def _normalize_evidence(evidence):

    if not isinstance(
        evidence,
        list
    ):
        evidence = [
            evidence
        ]

    normalized = []

    for item in evidence:

        if item is None:
            continue

        text = str(
            item
        ).strip()

        if text:
            normalized.append(
                text
            )

    return normalized


# =========================================================
# Investigate
# =========================================================

def investigate(
    action,
    telemetry_path=None
):
    """
    Investigate a service using either:

    1. Existing sample_data/metrics.json
    2. Real ShopMind telemetry_series.json
    """

    target_service = (
        action.target_service
    )

    # -----------------------------------------------------
    # LOAD DATA
    # -----------------------------------------------------

    if telemetry_path:

        shopmind_data = (
            load_shopmind_telemetry(
                telemetry_path
            )
        )

        metrics_data = (
            summarize_shopmind_telemetry(
                shopmind_data
            )
        )

        prompt = build_shopmind_prompt(
            action,
            metrics_data
        )

    else:

        metrics_data = load_metrics(
            DEFAULT_METRICS_PATH
        )

        prompt = f"""
You are a Metrics Investigation Agent in an
automated incident root-cause analysis system.

Target service:
{target_service}

Analyze the following metrics.

Determine whether the target service shows
abnormal behavior.

Report observations only.

Do not invent evidence.
Do not assume the cause.

Return ONLY ONE valid JSON object:

{{
    "finding": "short explanation",
    "severity": "low|medium|high|unknown",
    "confidence": 0.0,
    "evidence": [
        "specific evidence from the metrics"
    ]
}}

Metrics:

{json.dumps(
    metrics_data,
    indent=2,
    ensure_ascii=False
)}
"""

    # -----------------------------------------------------
    # CALL OLLAMA
    # -----------------------------------------------------

    print(
        "  Metrics Agent: sending request to Ollama...",
        flush=True
    )

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
                    "content": prompt,
                }
            ],

            # Force structured JSON output.
            format="json",

            options={
                "temperature": TEMPERATURE,

                # Prevent unnecessarily long generation.
                "num_predict": 250,
            }
        )

    except Exception as exc:

        print(
            "  Metrics Agent Ollama error: "
            f"{type(exc).__name__}: {exc}",
            flush=True
        )

        return {
            "agent_type": "metrics",

            "target_service":
                target_service,

            "finding": (
                "Metrics Agent could not "
                "complete the LLM request."
            ),

            "severity": "unknown",

            "confidence": 0.0,

            "evidence": [],
        }

    # -----------------------------------------------------
    # Extract content
    # -----------------------------------------------------

    try:

        content = (
            response[
                "message"
            ][
                "content"
            ]
            .strip()
        )

    except (
        KeyError,
        TypeError,
        AttributeError
    ):

        content = ""

    # -----------------------------------------------------
    # Parse and normalize
    # -----------------------------------------------------

    result = _normalize_llm_result(
        content
    )

    # -----------------------------------------------------
    # Validate severity
    # -----------------------------------------------------

    severity = str(
        result.get(
            "severity",
            "unknown"
        )
    ).lower()

    if severity not in {
        "low",
        "medium",
        "high",
        "unknown",
    }:
        severity = "unknown"

    # -----------------------------------------------------
    # Validate confidence
    # -----------------------------------------------------

    confidence = _safe_confidence(
        result.get(
            "confidence",
            0.0
        )
    )

    # -----------------------------------------------------
    # Return standard AgentFinding
    # -----------------------------------------------------

    return {
        "agent_type": "metrics",

        "target_service":
            target_service,

        "finding": str(
            result.get(
                "finding",
                ""
            )
        ),

        "severity": severity,

        "confidence": confidence,

        "evidence": _normalize_evidence(
            result.get(
                "evidence",
                []
            )
        ),
    }
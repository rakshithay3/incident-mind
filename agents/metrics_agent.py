import json
from pathlib import Path

import ollama

from config import OLLAMA_MODEL, TEMPERATURE


# Default metrics file used by the existing P2/sample-data workflow.
DEFAULT_METRICS_PATH = Path("sample_data/metrics.json")


def load_metrics(metrics_path):
    """Load metrics JSON from a file."""
    path = Path(metrics_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Metrics file not found: {path}"
        )

    with path.open("r") as f:
        return json.load(f)


def load_shopmind_telemetry(telemetry_path):
    """
    Load ShopMind telemetry_series.json.

    The fault_type and target_service fields are retained in the
    loaded data for evaluation/use by the pipeline, but fault_type
    must NOT be included in the LLM investigation prompt.
    """
    path = Path(telemetry_path)

    if not path.exists():
        raise FileNotFoundError(
            f"ShopMind telemetry file not found: {path}"
        )

    with path.open("r") as f:
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
                f"ShopMind telemetry is missing required field: {field}"
            )

    return data


def summarize_shopmind_telemetry(data):
    """
    Convert ShopMind telemetry into a compact service-level
    baseline vs failure summary.

    IMPORTANT:
    fault_type is intentionally NOT returned in the metrics
    summary that will be sent to the LLM.
    """

    baseline_history = data.get("baseline_history", [])
    failure_history = data.get("failure_history", [])

    services = {}

    # Collect baseline measurements.
    for snapshot in baseline_history:
        for node in snapshot.get("nodes", []):
            service_id = node.get("service_id")

            if not service_id:
                continue

            services.setdefault(
                service_id,
                {
                    "baseline": [],
                    "failure": [],
                },
            )

            services[service_id]["baseline"].append(node)

    # Collect failure measurements.
    for snapshot in failure_history:
        for node in snapshot.get("nodes", []):
            service_id = node.get("service_id")

            if not service_id:
                continue

            services.setdefault(
                service_id,
                {
                    "baseline": [],
                    "failure": [],
                },
            )

            services[service_id]["failure"].append(node)

    def average(records, field):
        values = []

        for record in records:
            value = record.get(field)

            if isinstance(value, (int, float)):
                values.append(value)

        if not values:
            return 0.0

        return sum(values) / len(values)

    summary = []

    for service_id, service_data in services.items():

        baseline_records = service_data["baseline"]
        failure_records = service_data["failure"]

        baseline = {
            "cpu_pct": average(
                baseline_records,
                "cpu_pct",
            ),
            "mem_pct": average(
                baseline_records,
                "mem_pct",
            ),
            "error_rate": average(
                baseline_records,
                "error_rate",
            ),
            "mean_latency_ms": average(
                baseline_records,
                "mean_latency_ms",
            ),
            "p99_latency_ms": average(
                baseline_records,
                "p99_latency_ms",
            ),
        }

        failure = {
            "cpu_pct": average(
                failure_records,
                "cpu_pct",
            ),
            "mem_pct": average(
                failure_records,
                "mem_pct",
            ),
            "error_rate": average(
                failure_records,
                "error_rate",
            ),
            "mean_latency_ms": average(
                failure_records,
                "mean_latency_ms",
            ),
            "p99_latency_ms": average(
                failure_records,
                "p99_latency_ms",
            ),
        }

        # Calculate changes between baseline and failure.
        changes = {
            "cpu_pct_change": (
                failure["cpu_pct"] - baseline["cpu_pct"]
            ),
            "mem_pct_change": (
                failure["mem_pct"] - baseline["mem_pct"]
            ),
            "error_rate_change": (
                failure["error_rate"] - baseline["error_rate"]
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
        "incident_id": data["incident_id"],
        "target_service": data["target_service"],
        "metrics": summary,
    }


def build_shopmind_prompt(action, telemetry_summary):
    """
    Build the LLM prompt for ShopMind telemetry.

    The ground-truth fault_type is deliberately excluded.
    """

    target_service = action.target_service

    metrics_json = json.dumps(
        telemetry_summary,
        indent=2,
    )

    return f"""
You are a Metrics Investigation Agent in an automated
incident root-cause analysis system.

Target service:
{target_service}

You are investigating an incident using ONLY the telemetry
provided below.

The telemetry contains baseline measurements and measurements
during the failure window.

Compare baseline and failure metrics and determine whether the
target service shows abnormal behavior.

Pay particular attention to:

- CPU utilization
- Memory utilization
- Error rate
- Mean latency
- P99 latency
- Changes between baseline and failure

Do NOT assume the cause.
Do NOT invent evidence.
Do NOT use information that is not present in the telemetry.

Return ONLY valid JSON in exactly this format:

{{
    "finding": "short explanation of the observed metric anomaly",
    "severity": "low|medium|high|unknown",
    "confidence": 0.0,
    "evidence": [
        "specific metric evidence"
    ]
}}

Telemetry:

{metrics_json}
"""


def investigate(action, telemetry_path=None):
    """
    Investigate a service using either:

    1. Existing sample_data/metrics.json
    2. Real ShopMind telemetry_series.json

    Parameters:
        action:
            DispatchAction containing agent_type and target_service.

        telemetry_path:
            Optional path to ShopMind telemetry_series.json.
    """

    target_service = action.target_service

    # ---------------------------------------------------------
    # LOAD DATA
    # ---------------------------------------------------------

    if telemetry_path:

        shopmind_data = load_shopmind_telemetry(
            telemetry_path
        )

        metrics_data = summarize_shopmind_telemetry(
            shopmind_data
        )

        prompt = build_shopmind_prompt(
            action,
            metrics_data,
        )

    else:

        metrics_data = load_metrics(
            DEFAULT_METRICS_PATH
        )

        prompt = f"""
You are a Metrics Investigation Agent in an automated
incident root-cause analysis system.

Target service:
{target_service}

Analyze the following metrics.

Determine whether the target service shows abnormal
behavior that could contribute to an incident.

Return ONLY valid JSON in exactly this format:

{{
    "finding": "short explanation",
    "severity": "low|medium|high|unknown",
    "confidence": 0.0,
    "evidence": [
        "specific evidence from the metrics"
    ]
}}

Do not invent evidence.

Metrics:

{json.dumps(metrics_data, indent=2)}
"""

    # ---------------------------------------------------------
    # CALL OLLAMA
    # ---------------------------------------------------------

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        options={
            "temperature": TEMPERATURE,
        },
    )

    content = response["message"]["content"].strip()

    # ---------------------------------------------------------
    # PARSE LLM JSON
    # ---------------------------------------------------------

    try:
        result = json.loads(content)

    except json.JSONDecodeError:

        result = {
            "finding": content,
            "severity": "unknown",
            "confidence": 0.0,
            "evidence": [],
        }

    # ---------------------------------------------------------
    # RETURN STANDARD AGENT FINDING
    # ---------------------------------------------------------

    return {
        "agent_type": "metrics",
        "target_service": target_service,
        "finding": result.get(
            "finding",
            "",
        ),
        "severity": result.get(
            "severity",
            "unknown",
        ),
        "confidence": result.get(
            "confidence",
            0.0,
        ),
        "evidence": result.get(
            "evidence",
            [],
        ),
    }
import json
from pathlib import Path


def load_shopmind_incident(path):
    """
    Load a ShopMind telemetry_series.json file.

    Returns:
        dict containing incident metadata and telemetry history.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"ShopMind incident file not found: {path}"
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
                f"ShopMind incident is missing required field: {field}"
            )

    return data


def summarize_telemetry(data):
    """
    Convert ShopMind telemetry into a compact metrics summary
    suitable for the Metrics Agent.
    """

    baseline = data["baseline_history"]
    failure = data["failure_history"]

    services = {}

    for snapshot in baseline:
        for node in snapshot.get("nodes", []):
            service = node["service_id"]

            services.setdefault(
                service,
                {
                    "baseline": [],
                    "failure": [],
                }
            )

            services[service]["baseline"].append(node)

    for snapshot in failure:
        for node in snapshot.get("nodes", []):
            service = node["service_id"]

            services.setdefault(
                service,
                {
                    "baseline": [],
                    "failure": [],
                }
            )

            services[service]["failure"].append(node)

    def average(records, field):
        values = [
            record[field]
            for record in records
            if record.get(field) is not None
        ]

        if not values:
            return 0.0

        return sum(values) / len(values)

    summary = []

    for service, data_points in services.items():

        baseline_records = data_points["baseline"]
        failure_records = data_points["failure"]

        baseline_metrics = {
            "cpu_pct": average(baseline_records, "cpu_pct"),
            "mem_pct": average(baseline_records, "mem_pct"),
            "error_rate": average(baseline_records, "error_rate"),
            "mean_latency_ms": average(
                baseline_records,
                "mean_latency_ms"
            ),
            "p99_latency_ms": average(
                baseline_records,
                "p99_latency_ms"
            ),
        }

        failure_metrics = {
            "cpu_pct": average(failure_records, "cpu_pct"),
            "mem_pct": average(failure_records, "mem_pct"),
            "error_rate": average(failure_records, "error_rate"),
            "mean_latency_ms": average(
                failure_records,
                "mean_latency_ms"
            ),
            "p99_latency_ms": average(
                failure_records,
                "p99_latency_ms"
            ),
        }

        summary.append(
            {
                "service_id": service,
                "baseline": baseline_metrics,
                "failure": failure_metrics,
            }
        )

    return {
        "incident_id": data["incident_id"],
        "target_service": data["target_service"],
        "metrics": summary,
    }


if __name__ == "__main__":

    incident_path = (
        "../shopmind/"
        "datasets/incident_001/"
        "telemetry_series.json"
    )

    data = load_shopmind_incident(incident_path)

    summary = summarize_telemetry(data)

    print(json.dumps(summary, indent=2))
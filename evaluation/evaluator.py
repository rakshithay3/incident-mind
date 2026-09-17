import json
from pathlib import Path


def load_incident(incident_path):
    """
    Load one ShopMind incident telemetry file.
    """

    with open(incident_path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_prediction(incident, report):
    """
    Compare the predicted root cause with the
    ShopMind ground-truth target service.

    Ground truth is used ONLY for evaluation.
    It is never sent to the LLM.
    """

    target_service = incident.get("target_service")
    fault_type = incident.get("fault_type")

    predicted_service = report.get(
        "root_cause_service",
        "unknown"
    )

    confidence = report.get(
        "confidence_score",
        0.0
    )

    json_valid = isinstance(report, dict)

    correct = (
        predicted_service == target_service
    )

    unknown_prediction = (
        predicted_service == "unknown"
    )

    return {
        "incident_id": incident.get("incident_id"),
        "target_service": target_service,
        "fault_type": fault_type,
        "predicted_root_cause": predicted_service,
        "confidence": confidence,
        "correct": correct,
        "unknown_prediction": unknown_prediction,
        "json_valid": json_valid,
    }


def summarize_results(results):
    """
    Calculate aggregate evaluation metrics.
    """

    total = len(results)

    if total == 0:
        return {
            "total_incidents": 0,
            "accuracy": 0.0,
            "unknown_rate": 0.0,
            "json_validity": 0.0,
        }

    correct = sum(
        1 for r in results
        if r["correct"]
    )

    unknown = sum(
        1 for r in results
        if r["unknown_prediction"]
    )

    valid_json = sum(
        1 for r in results
        if r["json_valid"]
    )

    return {
        "total_incidents": total,
        "correct_predictions": correct,
        "accuracy": correct / total,
        "unknown_predictions": unknown,
        "unknown_rate": unknown / total,
        "valid_json_reports": valid_json,
        "json_validity": valid_json / total,
    }


def save_results(results, summary, output_path):
    """
    Save detailed results and aggregate metrics.
    """

    output = {
        "summary": summary,
        "incidents": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )
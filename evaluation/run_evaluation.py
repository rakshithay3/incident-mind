import json
import sys
import time
from pathlib import Path

# Allow imports from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agents.metrics_agent import investigate
from agents.report_agent import generate_report
from schemas.contracts import DispatchAction

from evaluation.evaluator import (
    load_incident,
    evaluate_prediction,
    summarize_results,
    save_results,
)


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

SHOPMIND_DATASET = (
    PROJECT_ROOT.parent
    / "shopmind"
    / "datasets"
)

RESULTS_DIR = (
    PROJECT_ROOT
    / "evaluation"
    / "results"
)


# ---------------------------------------------------------
# Run one incident
# ---------------------------------------------------------

def run_one_incident(incident_number):
    """
    Run Metrics Agent + Report Agent
    on one real ShopMind incident.
    """

    incident_id = f"incident_{incident_number:03d}"

    incident_path = (
        SHOPMIND_DATASET
        / incident_id
        / "telemetry_series.json"
    )

    print(
        f"  Loading dataset: {incident_path}",
        flush=True
    )

    if not incident_path.exists():
        raise FileNotFoundError(
            f"Missing dataset: {incident_path}"
        )

    incident = load_incident(
        incident_path
    )

    target_service = incident[
        "target_service"
    ]

    print(
        f"  Target service: {target_service}",
        flush=True
    )

    # -----------------------------------------------------
    # IMPORTANT:
    # target_service is used to select the telemetry.
    # Ground-truth fault_type is NOT sent to the LLM.
    # -----------------------------------------------------

    action = DispatchAction(
        agent_type="metrics",
        target_service=target_service,
    )

    # -----------------------------------------------------
    # Metrics Agent
    # -----------------------------------------------------

    print(
        "  Starting Metrics Agent...",
        flush=True
    )

    metrics_start = time.time()

    metrics_finding = investigate(
        action,
        telemetry_path=str(
            incident_path
        ),
    )

    metrics_time = (
        time.time() - metrics_start
    )

    print(
        f"  Metrics Agent finished in "
        f"{metrics_time:.1f}s",
        flush=True
    )

    # -----------------------------------------------------
    # Evidence Bundle
    # -----------------------------------------------------

    evidence_bundle = {
        "findings": [
            metrics_finding
        ]
    }

    # -----------------------------------------------------
    # Report Agent
    # -----------------------------------------------------

    print(
        "  Starting Report Agent...",
        flush=True
    )

    report_start = time.time()

    report = generate_report(
        evidence_bundle,
        incident_id=incident_id,
    )

    report_time = (
        time.time() - report_start
    )

    print(
        f"  Report Agent finished in "
        f"{report_time:.1f}s",
        flush=True
    )

    # -----------------------------------------------------
    # Evaluate
    # -----------------------------------------------------

    evaluation = evaluate_prediction(
        incident,
        report,
    )

    return {
        "incident": incident,
        "metrics_finding": metrics_finding,
        "report": report,
        "evaluation": evaluation,
        "timing": {
            "metrics_seconds": round(
                metrics_time,
                2
            ),
            "report_seconds": round(
                report_time,
                2
            ),
            "total_seconds": round(
                metrics_time + report_time,
                2
            ),
        },
    }


# ---------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------

def main():

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    results = []

    print(
        "=" * 70,
        flush=True
    )

    print(
        "IncidentMind Multi-Incident Evaluation",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    # -----------------------------------------------------
    # TEST ONLY INCIDENT 001 FIRST
    #
    # range(1, 2) = incident_001 only
    #
    # Later:
    # range(1, 7)   -> incidents 001-006
    # range(1, 101) -> incidents 001-100
    # -----------------------------------------------------

    incidents_to_run = range(1, 7)

    total_to_run = len(
        incidents_to_run
    )

    for number in incidents_to_run:

        incident_id = (
            f"incident_{number:03d}"
        )

        print(
            f"\n[{number}/{total_to_run}] "
            f"Running {incident_id}...",
            flush=True
        )

        incident_start = time.time()

        try:

            result = run_one_incident(
                number
            )

            evaluation = result[
                "evaluation"
            ]

            results.append(
                evaluation
            )

            status = (
                "CORRECT"
                if evaluation["correct"]
                else "WRONG"
            )

            print(
                f"  Target   : "
                f"{evaluation['target_service']}",
                flush=True
            )

            print(
                f"  Fault    : "
                f"{evaluation['fault_type']}",
                flush=True
            )

            print(
                f"  Predicted: "
                f"{evaluation['predicted_root_cause']}",
                flush=True
            )

            print(
                f"  Confidence: "
                f"{evaluation['confidence']}",
                flush=True
            )

            print(
                f"  Result   : {status}",
                flush=True
            )

            print(
                f"  Total time: "
                f"{time.time() - incident_start:.1f}s",
                flush=True
            )

            # -------------------------------------------------
            # Save individual incident result immediately
            # -------------------------------------------------

            individual_path = (
                RESULTS_DIR
                / f"{incident_id}.json"
            )

            with open(
                individual_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    result,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

            print(
                f"  Saved: {individual_path}",
                flush=True
            )

        except Exception as exc:

            print(
                f"  ERROR: {type(exc).__name__}: {exc}",
                flush=True
            )

            # Continue to the next incident
            # instead of stopping the entire evaluation.
            continue

    # ---------------------------------------------------------
    # Calculate summary
    # ---------------------------------------------------------

    summary = summarize_results(
        results
    )

    # ---------------------------------------------------------
    # Save overall summary
    # ---------------------------------------------------------

    summary_path = (
        RESULTS_DIR
        / "summary.json"
    )

    save_results(
        results,
        summary,
        summary_path
    )

    # ---------------------------------------------------------
    # Final output
    # ---------------------------------------------------------

    print(
        "\n" + "=" * 70,
        flush=True
    )

    print(
        "FINAL EVALUATION",
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    print(
        f"Total incidents : "
        f"{summary['total_incidents']}",
        flush=True
    )

    print(
        f"Correct         : "
        f"{summary['correct_predictions']}",
        flush=True
    )

    print(
        f"Accuracy        : "
        f"{summary['accuracy']:.2%}",
        flush=True
    )

    print(
        f"Unknown         : "
        f"{summary['unknown_predictions']}",
        flush=True
    )

    print(
        f"Unknown rate    : "
        f"{summary['unknown_rate']:.2%}",
        flush=True
    )

    print(
        f"Valid JSON      : "
        f"{summary['valid_json_reports']}",
        flush=True
    )

    print(
        f"JSON validity   : "
        f"{summary['json_validity']:.2%}",
        flush=True
    )

    print(
        f"\nResults saved to:",
        flush=True
    )

    print(
        summary_path,
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    main()
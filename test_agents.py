from pipeline import run_investigation, dispatch
from schemas.contracts import DispatchAction
from agents.log_agent import retrieve_logs
import json


# ==========================================
# DISPATCH ACTIONS
# ==========================================

actions = [
    DispatchAction(
        agent_type="log",
        target_service="auth-service"
    ),
    DispatchAction(
        agent_type="metrics",
        target_service="auth-service"
    ),
    DispatchAction(
        agent_type="code",
        target_service="auth-service"
    )
]


# ==========================================
# LOG RETRIEVAL TEST
# ==========================================

print("\n========================================")
print("          LOG RETRIEVAL TEST")
print("========================================")

recent_logs = retrieve_logs(
    "auth-service",
    n=5
)

print("Retrieved log lines:")

for line in recent_logs:
    print(line)


# ==========================================
# RUN COMPLETE INVESTIGATION
# ==========================================

result = run_investigation(
    actions,
    incident_id="inc_001"
)


# ==========================================
# SAVE FINAL RESULT
# ==========================================

with open("output/inc_001_report.json", "w") as file:
    json.dump(
        result,
        file,
        indent=4,
        ensure_ascii=False
    )

print("\n✓ Complete investigation saved to:")
print("  output/inc_001_report.json")


# ==========================================
# DISPLAY EVIDENCE BUNDLE
# ==========================================

print("\n========================================")
print("       INCIDENT EVIDENCE BUNDLE")
print("========================================")

for finding in result["evidence_bundle"]["findings"]:

    print(
        "\n---",
        finding["agent_type"].upper(),
        "AGENT ---"
    )

    print(
        "Target Service:",
        finding["target_service"]
    )

    print(
        "Finding:",
        finding["finding"]
    )

    print(
        "Severity:",
        finding["severity"]
    )

    print(
        "Confidence:",
        finding["confidence"]
    )

    print(
        "Evidence:",
        finding["evidence"]
    )


# ==========================================
# DISPLAY FINAL REPORT
# ==========================================

report = result["report"]

print("\n========================================")
print("             FINAL RCA REPORT")
print("========================================")

print("\nIncident ID:")
print(report["incident_id"])

print("\nRoot Cause Service:")
print(report["root_cause_service"])

print("\nConfidence Score:")
print(report["confidence_score"])

print("\nSuggested Fix:")
print(report["suggested_fix"])

print("\nEstimated Blast Radius:")
print(report["estimated_blast_radius"])

print("\nEnglish Report:")
print(report["report_text"]["en"])

print("\nHindi Report:")
print(report["report_text"]["hi"])


# ==========================================
# PIPELINE VALIDATION TESTS
# ==========================================

print("\n========================================")
print("       PIPELINE VALIDATION TESTS")
print("========================================")


# ------------------------------------------
# Test 1: Unsupported agent
# ------------------------------------------

try:
    invalid_action = DispatchAction(
        agent_type="unknown",
        target_service="auth-service"
    )

    dispatch(invalid_action)

except ValueError as error:
    print("✓ Invalid agent rejected:")
    print(" ", error)


# ------------------------------------------
# Test 2: Missing target service
# ------------------------------------------

try:
    DispatchAction(
        agent_type="log"
    )

except TypeError as error:
    print("\n✓ Missing target service rejected:")
    print(" ", error)


# ------------------------------------------
# Test 3: Empty target service
# ------------------------------------------

try:
    empty_action = DispatchAction(
        agent_type="log",
        target_service=""
    )

    dispatch(empty_action)

except ValueError as error:
    print("\n✓ Empty target service rejected:")
    print(" ", error)
from pipeline import run_investigation


def main():
    print("=" * 60)
    print("              INCIDENTMIND RCA DEMO")
    print("=" * 60)

    incident_id = "inc_001"
    target_service = "auth-service"

    print(f"\nIncident ID    : {incident_id}")
    print(f"Target Service : {target_service}")

    print("\nRunning IncidentMind agents...")
    print("✓ Log Agent")
    print("✓ Metrics Agent")
    print("✓ Code Agent")
    print("✓ Report Agent")

    # Specialist agents investigate the incident.
    # The Report Agent is invoked automatically by the pipeline.
    actions = [
        {
            "agent_type": "log",
            "target_service": target_service
        },
        {
            "agent_type": "metrics",
            "target_service": target_service
        },
        {
            "agent_type": "code",
            "target_service": target_service
        }
    ]

    # Run the complete RCA investigation.
    result = run_investigation(
        actions,
        incident_id=incident_id
    )

    report = result["report"]

    print("\n" + "=" * 60)
    print("                    FINAL RCA")
    print("=" * 60)

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

    print("\n" + "-" * 60)
    print("English Report:")
    print("-" * 60)
    print(report["report_text"]["en"])

    print("\n" + "-" * 60)
    print("Hindi Report:")
    print("-" * 60)
    print(report["report_text"]["hi"])

    print("\n" + "=" * 60)
    print("              INVESTIGATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
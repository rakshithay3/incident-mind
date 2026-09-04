from pipeline import run_investigation


def main():
    """Run a complete IncidentMind investigation."""

    actions = [
        {
            "agent_type": "log",
            "target_service": "auth-service",
        },
        {
            "agent_type": "metrics",
            "target_service": "auth-service",
        },
        {
            "agent_type": "code",
            "target_service": "auth-service",
        },
    ]

    result = run_investigation(
        actions,
        incident_id="inc_001",
    )

    report = result["report"]

    print("\n" + "=" * 50)
    print("INCIDENTMIND - INCIDENT REPORT")
    print("=" * 50)

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

    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
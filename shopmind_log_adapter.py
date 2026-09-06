from pathlib import Path


FAULT_MARKERS = (
    "Injecting fault:",
    "Rolling back fault:",
    "Fault state cleanly reset.",
    "Fault state:",
)


def sanitize_logs(log_path):
    """
    Read ShopMind Docker logs and remove fault-injection
    lifecycle messages so ground-truth fault information
    is not leaked to the LLM.
    """
    path = Path(log_path)

    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    lines = path.read_text(errors="ignore").splitlines()

    sanitized = []

    for line in lines:
        # Remove known fault-injection / reset messages.
        if any(marker.lower() in line.lower() for marker in FAULT_MARKERS):
            continue

        # Remove empty lines.
        if not line.strip():
            continue

        sanitized.append(line)

    return sanitized


def create_log_evidence(log_path, max_lines=100):
    """
    Convert ShopMind logs into a compact evidence block
    suitable for the Log Agent.
    """
    lines = sanitize_logs(log_path)

    # Keep the most recent lines if the log is large.
    lines = lines[-max_lines:]

    return {
        "log_path": str(log_path),
        "line_count": len(lines),
        "logs": lines,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python shopmind_log_adapter.py <log_file>")
        raise SystemExit(1)

    evidence = create_log_evidence(sys.argv[1])

    print("Sanitized log evidence")
    print("----------------------")
    print("Source:", evidence["log_path"])
    print("Lines:", evidence["line_count"])
    print()

    for line in evidence["logs"]:
        print(line)
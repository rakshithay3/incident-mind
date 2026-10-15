"""
notifications/rounds.py -- re-investigate when recovery polling fails.

Shared by replay_demo.main() and incident_watcher.run_pipeline(). After the
first investigation, poll recovery. If ShopMind is still broken, take a fresh
telemetry snapshot, re-score it with GraphSAGE, let PPO pick a service that
hasn't been investigated yet, run the agents on it and poll again -- up to
max_rounds rounds, stopping on the first recovery.

The callers inject the expensive parts (polling, scoring, PPO, agents) as
callables so the loop itself is testable without torch/Ollama/ShopMind.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from incidentmind_p1.dispatch import baseline_d_sequential


def run_recovery_rounds(
    target: str,
    investigation: Dict[str, Any],
    ranked: Sequence,
    *,
    wait: Callable[[int], Dict[str, Any]],
    rescore: Callable[[int], Optional[Sequence]],
    choose: Callable[[Sequence, set, int], Any],
    investigate: Callable[[str, int], Dict[str, Any]],
    max_rounds: int = 3,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """Round 1 is the investigation the caller already ran on `target`.

    wait(round_no)                  -> recovery dict (wait_for_recovery shape)
    rescore(round_no)               -> ranked NodeScores from a fresh snapshot,
                                       or None if no snapshot (keep the old ranking)
    choose(ranked, visited, step)   -> DispatchDecision
    investigate(target, round_no)   -> run_investigation() result

    Returns {"rounds", "recovered", "recovery", "investigation", "target",
    "decision" (None if round 1 was final), "ranked", "services_tried"}."""
    visited: List[str] = [target]
    rounds: List[Dict[str, Any]] = []
    decision = None
    round_no = 1
    while True:
        recovery = wait(round_no)
        rounds.append({
            "round": round_no,
            "target_service": target,
            "report_root_cause": (investigation.get("report") or {}).get("root_cause_service"),
            "recovery": recovery,
        })
        log(f"  [round {round_no}] {target} -> {recovery.get('outcome', 'recovered' if recovery.get('recovered') else 'not_recovered')}")
        if recovery.get("recovered") or round_no >= max_rounds:
            break

        try:
            fresh = rescore(round_no)
        except Exception as exc:
            log(f"  [round {round_no}] re-scoring failed ({type(exc).__name__}), keeping the previous ranking")
            fresh = None
        if fresh:
            ranked = sorted(fresh, key=lambda s: s.rank)
        if not any(s.service_id not in visited for s in ranked):
            log(f"  [round {round_no}] every ranked service already investigated, stopping")
            break

        step = round_no + 1
        decision = choose(ranked, set(visited), step)
        if decision.action.target_service in visited:
            # Unmasked policies can still land on a visited slot; walk down
            # the ranking instead so each round investigates something new.
            decision = baseline_d_sequential(ranked, agent_type=decision.action.agent_type, visited=set(visited))
        target = decision.action.target_service
        visited.append(target)
        log(f"  [round {step}] re-investigating {target}")
        investigation = investigate(target, step)
        round_no = step

    return {
        "rounds": rounds,
        "recovered": bool(rounds[-1]["recovery"].get("recovered")),
        "recovery": rounds[-1]["recovery"],
        "investigation": investigation,
        "target": target,
        "decision": decision,
        "ranked": list(ranked),
        "services_tried": visited,
    }


def notify_rounds_outcome(
    notifier,
    incident_id: str,
    outcome: Dict[str, Any],
    get_recipients: Callable[[], Dict[str, Any]],
    started_at: Optional[str],
    timeout_sec: float,
) -> List[Dict[str, Any]]:
    """Exactly one notification entry: the "back to normal" email if some
    round recovered, otherwise one not-recovered record naming every service
    tried."""
    if outcome["recovered"]:
        reported = (outcome["investigation"].get("report") or {}).get("root_cause_service")
        fresh = get_recipients()  # pick up anyone who registered meanwhile
        return [notifier.notify_restored(
            incident_id, fresh["recipients"],
            root_cause_service=reported if reported and reported != "unknown" else outcome["target"],
            started_at=started_at,
            restored_at=outcome["recovery"]["restored_at"],
            recipients_source=fresh["source"],
        )]
    return [notifier.notify_not_recovered(
        incident_id, outcome["recovery"]["still_unhealthy"], timeout_sec * len(outcome["rounds"]),
        services_tried=outcome["services_tried"],
    )]

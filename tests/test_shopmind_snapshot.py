"""The ShopMind benchmark/replay input must not depend on the label."""

import copy
import json
from pathlib import Path

from shopmind_snapshot import compile_telemetry, down_services

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo_replay_auth_cpu"
FEATS = ("cpu", "memory", "latency", "error_rate", "p99_latency")


def _node(sid, cpu=0.02, mem=0.1, lat=5.0, p99=20.0, err=0.0):
    return {"service_id": sid, "cpu_pct": cpu, "mem_pct": mem, "mean_latency_ms": lat,
            "p99_latency_ms": p99, "error_rate": err}


def _snap(ts, **overrides):
    nodes = []
    for sid in ("auth-service", "order-service", "payment-service"):
        nodes.append(overrides.get(sid, _node(sid)))
    return {"timestamp": ts, "nodes": nodes,
            "edges": [{"source": "order-service", "target": "payment-service", "call_count": 3},
                      {"source": "order-service", "target": "ghost-service", "call_count": 1}]}


def _telemetry(failure, target="auth-service", fault="cpu_stress"):
    return {"incident_id": "t", "target_service": target, "fault_type": fault,
            "baseline_history": [_snap(i) for i in range(5)], "failure_history": failure}


def _features(payload):
    return [(n["service_id"], tuple(n[k] for k in FEATS)) for n in payload["nodes"]]


def test_output_does_not_depend_on_target_or_fault_type():
    failure = [_snap(10), _snap(11, **{"payment-service": _node("payment-service", cpu=0.9)}), _snap(12)]
    base = compile_telemetry(_telemetry(copy.deepcopy(failure)))
    for target in ("order-service", "payment-service"):
        for fault in ("pod_crash", "network_delay"):
            other = compile_telemetry(_telemetry(copy.deepcopy(failure), target, fault))
            assert _features(other) == _features(base)
            assert other["timestamp"] == base["timestamp"]
            assert other["metadata"]["peak_index"] == base["metadata"]["peak_index"]


def test_peak_is_the_most_deviant_snapshot():
    failure = [_snap(10), _snap(11, **{"payment-service": _node("payment-service", cpu=0.9)}), _snap(12)]
    assert compile_telemetry(_telemetry(failure))["metadata"]["peak_index"] == 1


def test_sustained_null_is_a_crash_for_any_service_not_just_target():
    down = _node("payment-service", cpu=None, mem=None)
    failure = [_snap(10), _snap(11, **{"payment-service": down}), _snap(12, **{"payment-service": down}), _snap(13)]
    payload = compile_telemetry(_telemetry(failure, target="auth-service", fault="cpu_stress"))
    pay = next(n for n in payload["nodes"] if n["service_id"] == "payment-service")
    assert pay["error_rate"] == 1.0 and pay["cpu"] == 0.0
    assert payload["metadata"]["down_at_peak"] == ["payment-service"]


def test_single_null_scrape_is_backfilled_not_a_crash():
    blip = _node("payment-service", cpu=None, mem=None)
    failure = [_snap(10, **{"payment-service": _node("payment-service", cpu=0.5)}),
               _snap(11, **{"payment-service": blip}), _snap(12)]
    assert down_services(failure) == [set(), set(), set()]
    payload = compile_telemetry(_telemetry(failure, target="payment-service", fault="pod_crash"))
    pay = next(n for n in payload["nodes"] if n["service_id"] == "payment-service")
    assert pay["error_rate"] == 0.0


def test_edges_kept_and_unknown_endpoints_dropped():
    payload = compile_telemetry(_telemetry([_snap(10)]))
    assert payload["edges"] == [{"source": "order-service", "target": "payment-service", "call_count": 3}]


def test_replay_compile_keeps_the_call_graph():
    from replay_demo import compile_live_snapshot

    telemetry = json.loads((DEMO / "telemetry_series.json").read_text())
    graph = compile_live_snapshot(telemetry)
    assert len(graph.nodes) == 12
    assert len(graph.edges) == 16
    graph.validate()


def test_real_cpu_stress_incidents_pick_a_snapshot_inside_the_fault():
    for name in ("telemetry_series.json", "incident_022_frozen_raw_telemetry_series.json"):
        payload = compile_telemetry(json.loads((DEMO / name).read_text()))
        auth = next(n for n in payload["nodes"] if n["service_id"] == "auth-service")
        assert auth["cpu"] > 50.0, (name, auth)

"""Regression tests for the Sep 2026 code-review fixes."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from incidentmind_p1.contracts import NodeScore


def _score(sid, score, rank, instance_id=None):
    return NodeScore(service_id=sid, anomaly_score=score, embedding_dim=128,
                     status="anomalous", rank=rank, instance_id=instance_id)


# --- PriorityWeightedScorer keeps instance_id --------------------------------
def test_priority_scorer_keeps_instance_id():
    from priority.impact_weights import PriorityWeightedScorer

    class Fixed:
        def score_graph(self, incident):
            return [_score("search-service", 0.9, 1, "B"), _score("auth-service", 0.8, 2, "A")]

    out = PriorityWeightedScorer(Fixed()).score_graph(None)
    assert [(s.service_id, s.instance_id, s.rank) for s in out] == [
        ("auth-service", "A", 1), ("search-service", "B", 2)]


# --- GlobalPPODispatcher reaches nodes past the 12 PPO slots ---------------------
def test_global_dispatch_reaches_more_than_twelve_nodes():
    from priority.cross_instance_queue import CrossInstancePriorityQueue
    from priority.global_dispatch import GlobalPPODispatcher

    queue = CrossInstancePriorityQueue()
    for inst in ("A", "B"):
        queue.add_instance_scores(inst, [_score(f"svc-{i}", 1.0 - i / 100, i + 1) for i in range(10)])

    class AlwaysSlot0:  # a policy that only ever picks the top slot
        def predict(self, obs, deterministic=True):
            return 0, None

    decisions = list(GlobalPPODispatcher(queue, policy=AlwaysSlot0()).dispatch_all())
    picked = {(d.action.instance_id, d.action.target_service) for d in decisions}
    assert len(decisions) == 20 and len(picked) == 20


# --- receiver: path traversal, size limit, token ---------------------------------
@pytest.fixture()
def receiver(tmp_path, monkeypatch):
    import multi_instance_receiver as r

    monkeypatch.setattr(r, "RECEIVED_DIR", tmp_path / "recv")
    monkeypatch.setattr(r, "RECEIVER_TOKEN", None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), r.TelemetryReceiverHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield r, f"http://127.0.0.1:{server.server_port}/telemetry", tmp_path
    server.shutdown()


def _post(url, body, headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code


def test_receiver_accepts_valid_instance(receiver):
    r, url, tmp = receiver
    assert _post(url, {"instance_id": "laptop-2", "x": 1}) == 200
    assert list((tmp / "recv" / "laptop-2").glob("*.json"))


@pytest.mark.parametrize("bad", ["../../escape", "a/b", "", "..", 5, "x" * 65])
def test_receiver_rejects_unsafe_instance_ids(receiver, bad):
    r, url, tmp = receiver
    assert _post(url, {"instance_id": bad}) == 400
    assert not (tmp / "escape").exists()


def test_receiver_rejects_oversized_body(receiver, monkeypatch):
    r, url, _ = receiver
    monkeypatch.setattr(r, "MAX_BODY_BYTES", 100)
    assert _post(url, {"instance_id": "a", "pad": "x" * 200}) == 413


def test_receiver_token(receiver, monkeypatch):
    r, url, _ = receiver
    monkeypatch.setattr(r, "RECEIVER_TOKEN", "s3cret")
    assert _post(url, {"instance_id": "a"}) == 401
    assert _post(url, {"instance_id": "a"}, {"X-IM-Token": "s3cret"}) == 200


# --- pipeline tags where evidence came from ---------------------------------------
def test_pipeline_tags_sample_data(monkeypatch):
    import pipeline
    from schemas.contracts import DispatchAction

    monkeypatch.setattr(pipeline, "investigate_logs", lambda a, log_path=None: {"agent_type": "log"})
    monkeypatch.setattr(pipeline, "investigate_metrics", lambda a, telemetry_path=None: {"agent_type": "metrics"})
    a = DispatchAction(agent_type="log", target_service="auth-service")
    assert pipeline.dispatch(a)["evidence_source"] == "sample_data"
    assert pipeline.dispatch(a, log_path="x.log")["evidence_source"] == "incident_logs"
    m = DispatchAction(agent_type="metrics", target_service="auth-service")
    assert pipeline.dispatch(m, telemetry_path="t.json")["evidence_source"] == "incident_telemetry"

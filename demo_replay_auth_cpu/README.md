# ShopMind Live-Replay Demo Incident Package: `auth-service` `cpu_stress`

This package provides the **raw telemetry time-series** and **synchronized Docker container logs** for the live-replay demo pipeline (GNN $\rightarrow$ PPO $\rightarrow$ Ollama LLM Agents $\rightarrow$ Incident Post-Mortem Report).

---

## 📁 Package Contents

| Filename | Description | Source / Notes |
| :--- | :--- | :--- |
| **`telemetry_series.json`** | **RAW Telemetry Time-Series** input for `compile_incident()` | Fresh capture (10s baseline + 30s failure window). Synchronized with Docker logs below down to the second. |
| **`incident_022_frozen_raw_telemetry_series.json`** | **Original Benchmark Telemetry** from frozen 100-incident dataset | Exact input for `incident_022` from the formal evaluation run (PR@1 = 0.913). |
| **`auth-service.log`** | Target service Docker container logs | Captures chaos injection trigger, CPU spinner activity, and rollback. |
| **`api-gateway.log`** | Ingress API Gateway Docker logs | 765 live HTTP access logs across the baseline and failure window. |
| **`order-service.log`** | Upstream orchestrator Docker logs | 155 checkout saga transaction logs during the incident window. |
| **`user-service.log`** | Neighbor service Docker logs | Profile query logs for reference. |
| **`compiled_gnn_incident.json`** | Reference GNN 5-feature vector | Output of `compile_incident()` for instant pipeline testing. |

---

## 🔬 Telemetry Schema (Input to `compile_incident()`)
`telemetry_series.json` conforms strictly to the ShopMind generator contract:
```json
{
  "incident_id": "demo_live_replay_auth_cpu",
  "dataset_version": "2026.07",
  "target_service": "auth-service",
  "fault_type": "cpu_stress",
  "injected_at_epoch": 1788787164.71,
  "baseline_history": [ ... 10 snapshots ... ],
  "failure_history": [ ... 30 snapshots ... ]
}
```
Each snapshot contains the full 12-node topology with:
- `cpu_pct` (0–1 ratio)
- `mem_pct` (0–1 ratio)
- `mean_latency_ms` (ms)
- `p99_latency_ms` (ms)
- `error_rate` (0–1 ratio)

---

## 🤖 Feeding into Ollama LLM Post-Mortem Agents
For downstream incident explanation and root-cause post-mortems:
1. Pass `auth-service.log` (target) and `api-gateway.log` (ingress) directly into the agent context.
2. The logs contain explicit timestamps matching the anomaly spike in `telemetry_series.json`.
3. Demonstrates deterministic multi-modal verification: GNN identifies the graph node anomaly, Ollama LLM agent synthesizes textual logs for the evaluator.

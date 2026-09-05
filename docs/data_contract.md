# GNN Data Contract Specification — ShopMind Sandbox

This document defines the formal data contract interface between the ShopMind telemetry exporter pipeline and the downstream Graph Neural Network (GNN) Root Cause Analysis module.

---

## 1. Output Schema: `adjacency.json`

The GNN expects a single, JSON-formatted dependency graph snapshot representing the state of the 12-service topology.

```json
{
  "schema_version": "1.0",
  "dataset_version": "2026.07",
  "experiment_id": "expr_test_001",
  "timestamp": "2026-07-08T14:30:15.123Z",
  "nodes": [
    {
      "service_id": "auth-service",
      "cpu_pct": 0.42,
      "mem_pct": 0.61,
      "error_rate": 0.08,
      "mean_latency_ms": 120.5,
      "p99_latency_ms": 480.2,
      "timestamp": "2026-07-08T14:30:15.123Z"
    }
  ],
  "edges": [
    {
      "source": "api-gateway",
      "target": "auth-service",
      "call_count": 142,
      "timestamp": "2026-07-08T14:30:15.123Z"
    }
  ],
  "fault_injection": {
    "active": true,
    "fault_type": "network_delay",
    "target_service": "inventory-service",
    "injected_at": "2026-07-08T14:29:30.000Z",
    "scheduled_duration_sec": 30,
    "auto_rollback": true
  },
  "ground_truth_root_cause": "inventory-service"
}
```

---

## 2. Field Specifications

### Root Fields
- **`schema_version`** (string): The structural schema version (currently `"1.0"`).
- **`dataset_version`** (string): Version string of the current dataset build (e.g. `"2026.07"`).
- **`experiment_id`** (string): Identifier for the active injection incident.
- **`timestamp`** (string): ISO 8601 timestamp of the snapshot generation.
- **`ground_truth_root_cause`** (string): The target service ID representing the actual root cause of the failure. Set to `""` if no fault is active.

### Nodes (`nodes` array)
Each object in the array represents a service in the topology:
- **`service_id`** (string): The identifier matching the docker service (e.g. `"inventory-service"`).
- **`cpu_pct`** (float or null): CPU utilization ratio from $0.0$ to $1.0$ (scaled to single-threaded capacity). Can be `null` if the telemetry scraping request to the microservice fails or times out (indicating the container is unresponsive).
- **`mem_pct`** (float or null): RSS Memory usage ratio relative to a standard container limit of **512MB** ($0.0$ to $1.0$). Can be `null` if the telemetry scraping request fails or times out.
- **`error_rate`** (float): Ratio of HTTP error spans (status code $\ge 400$) to total spans over the rolling window ($0.0$ to $1.0$).
- **`mean_latency_ms`** (float): Mean span execution duration in milliseconds.
- **`p99_latency_ms`** (float): 99th percentile span execution duration in milliseconds.
- **`timestamp`** (string): Snapshot collection time.

---

## 3. Topology Specification: Static Edge List

The ShopMind microservice graph topology is governed by **16 static edges** representing all possible transaction routes and data dependencies. Dynamic call counts are mapped onto these edges by the telemetry pipeline:

| Source Node | Target Node | Relationship / Dependency Type |
| :--- | :--- | :--- |
| `frontend` | `api-gateway` | Client storefront traffic route |
| `api-gateway` | `auth-service` | User token validation and auth exchange |
| `api-gateway` | `user-service` | User profile retrieval |
| `api-gateway` | `order-service` | E-commerce checkout execution |
| `api-gateway` | `search-service` | Storefront catalog queries |
| `order-service` | `payment-service` | Transaction payment capture |
| `order-service` | `inventory-service` | Inventory stock deduction |
| `order-service` | `notification-service` | Transaction email triggers |
| `auth-service` | `postgres-primary` | Relational credential lookup |
| `user-service` | `postgres-primary` | Relational user profile storage |
| `order-service` | `postgres-primary` | Relational transaction log record |
| `payment-service` | `postgres-primary` | Relational payment status record |
| `inventory-service` | `postgres-primary` | Relational stock level update |
| `search-service` | `postgres-replica` | Relational catalog query reading |
| `auth-service` | `cache` | Session token validation caching (Redis) |
| `postgres-primary` | `postgres-replica` | Primary-to-Replica streaming replication |

---

## 4. Data Validation Report Schema: `validation_report.json`

The validator writes an audit report verifying the health and validity of the telemetry data:

```json
{
  "timestamp": "2026-08-22T16:39:48Z",
  "validation_passed": true,
  "metrics_validation": {
    "auth-service": {
      "cpu_vs_latency_spearman": 0.453,
      "cpu_vs_latency_insufficient_samples": false,
      "errors_vs_p99_spearman": 0.0,
      "errors_vs_p99_insufficient_samples": false,
      "metrics_flatlined": false
    }
  },
  "graph_validation": {
    "total_nodes": 12,
    "total_edges": 16,
    "disconnected_nodes": [],
    "duplicate_nodes": false
  },
  "fault_impact_validation": {
    "fault_active": true,
    "target_service": "inventory-service",
    "deviation_detected": true,
    "details": "inventory-service mean latency (81.49ms) is 56.6x baseline (1.44ms)"
  }
}
```

---

## 5. GNN Modeling Assumptions & Cascading Timeout Tradeoffs

### Network Delay Latency Asymmetry
When a `network_delay` (2s delay) is injected on a downstream service (e.g. `payment-service` or `inventory-service`):
- **Caller Node Signal**: The calling service (`order-service`) enforces a `1.5s` client-side timeout. It aborts the request and registers a massive latency spike (exactly `~1500ms` at `p99_latency_ms`) and a `500` error rate spike.
- **Target Node Signal**: Because the calling socket is destroyed at `1.5s`, the target service's subsequent response write throws a connection reset error in Node.js. This bypasses the tracing telemetry callback. Consequently, the target service itself will **not** show a latency spike in Jaeger (its latency remains clean/idle, e.g., `<2ms`).

> [!IMPORTANT]
> **Modeling Assumption**: For downstream `network_delay` faults, the ground-truth-labeled root cause node may exhibit healthy local telemetry features. The fault anomaly signature exists primarily on the caller/upstream node in the dependency graph. Graph-based GNN models must rely on multi-hop neighborhood aggregation to trace the root cause back to the target node.

### Downstream Evaluation Unit Alignment (RCAEval RE1 Specification)
To align with standard benchmark datasets (such as RCAEval RE1) and avoid distribution shifts in pre-trained GraphSAGE encoders, `package_evaluation.py` converts raw ShopMind telemetry units to the standard evaluation schema at the compilation boundary:
- **`cpu`**: Transformed from $0.0–1.0$ ratio to **$0–100\%$** (`cpu = cpu_pct * 100.0`).
- **`latency` / `p99_latency`**: Transformed from milliseconds to **seconds** (`latency = ms / 1000.0`).
- **`memory`**: Reconstructed from usage ratio to **absolute bytes** (`memory = mem_pct * mem_limit_bytes`) using each container's configured `mem_limit` (e.g. 384MB for application microservices, 512MB for Postgres).

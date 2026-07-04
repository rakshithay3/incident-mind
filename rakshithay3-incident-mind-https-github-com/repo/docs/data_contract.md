# P1 Data Contract

## RCAEval Input Incident

Each incident file should contain:

```json
{
  "incident_id": "inc_001",
  "timestamp": "2026-06-20T10:15:00Z",
  "root_cause": "auth-service",
  "nodes": [
    {
      "service_id": "auth-service",
      "features": {
        "cpu": 82.0,
        "memory": 71.0,
        "latency": 230.0,
        "error_rate": 0.18,
        "p99_latency": 710.0
      },
      "label": "faulty"
    }
  ],
  "edges": [
    { "source": "frontend", "target": "api-gateway" }
  ],
  "metadata": {
    "failure_type": "auth overload",
    "source": "RCAEval"
  }
}
```

Required node features:

| Field | Type | Notes |
| --- | --- | --- |
| `cpu` | float | CPU utilization or normalized CPU signal |
| `memory` | float | memory utilization |
| `latency` | float | mean request latency |
| `error_rate` | float | request error ratio |
| `p99_latency` | float | p99 request latency |

## P1 Output

This is the locked schema for Dharunya's PPO/agent orchestration and Vismitha's dashboard/PR@k leaderboard.

| Field | Type | Notes |
| --- | --- | --- |
| `anomaly_score` | float | cosine distance from rolling EMA baseline, approximately 0-2 |
| `rank` | integer | 1 is most anomalous; drives PR@k |
| `ppo_dispatch.action` | object | next agent call: `agent_type` and `target_service` |
| `policy_confidence` | float | PPO policy confidence, 0-1 |
| `mttd_steps` | integer | steps to detection for table generation |

## Branch Discipline

All P1 implementation should continue on `p1/gnn-graphsage`.

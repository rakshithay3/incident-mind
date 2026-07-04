# IncidentMind P1: GNN + PPO Backbone

This repository contains Rakshitha's P1 workstream for IncidentMind: RCAEval ingestion, GraphSAGE-ready anomaly scoring, PPO dispatch contract output, and Baseline C greedy dispatch.

The code is intentionally runnable with only the Python standard library for first-commit verification. When `torch`, `torch_geometric`, and `stable-baselines3` are available, the same contracts can be used by the real GraphSAGE and PPO training paths.

## What This Produces

The P1 handoff JSON consumed by Dharunya's agents and Vismitha's dashboard:

```json
{
  "incident_id": "inc_001",
  "timestamp": "2026-06-20T10:15:00Z",
  "nodes": [
    {
      "service_id": "auth-service",
      "anomaly_score": 0.87,
      "embedding_dim": 128,
      "status": "anomalous",
      "rank": 1
    }
  ],
  "ppo_dispatch": {
    "step": 1,
    "action": {
      "agent_type": "log",
      "target_service": "auth-service"
    },
    "policy_confidence": 0.91
  },
  "metrics": {
    "pr_at_1": 0.0,
    "pr_at_3": 1.0,
    "pr_at_5": 1.0,
    "mttd_steps": 4
  }
}
```

## Quick Start

```bash
python3 -m incidentmind_p1.cli score --incident data/sample_rcaeval/incidents/inc_001.json
python3 -m incidentmind_p1.cli validate --dataset data/sample_rcaeval
python3 -m incidentmind_p1.cli baseline-c --incident data/sample_rcaeval/incidents/inc_001.json
python3 -m unittest discover -s tests
```

## Roadmap Alignment

- Weeks 1-3: RCAEval data contract, loaders, GraphSAGE-ready graph objects, training loop skeleton.
- Weeks 4-7: anomaly scorer, PPO dispatch interface, fast inference output for dashboard and agents.
- Weeks 9-11: Baseline C, PR@k, MTTD, cross-app generalization hooks.

## Data Contract

See [docs/data_contract.md](docs/data_contract.md) for the exact input and output schemas.

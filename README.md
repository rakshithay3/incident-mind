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

## Full RE1 Run (VS Code / local shell)

The steps above only exercise the dummy fixture (`inc_001.json`). To reproduce
the real GraphSAGE training run on RCAEval RE1 (Online Boutique) locally:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Downloads RE1 (RE1-OB/SS/TT) via a local git clone of RCAEval and
#    converts the ~125 Online Boutique cases into incidentmind_p1 incident
#    JSONs under data/rcaeval_re1/incidents/. `pip install RCAEval` is
#    broken upstream, so this clones the source instead -- see
#    docs/data_contract.md.
python3 scripts/prepare_re1_data.py

# 2. Trains GraphSAGE (60/20/20 train/val/test split, FeatureStats fit only
#    on train) and reports PR@1 / PR@3 / PR@5 / MTTD against a random
#    baseline. Add --print-per-incident for the full per-incident report.
python3 scripts/train_and_evaluate.py --epochs 50 --print-per-incident
```

Expect the first run to take a few minutes: the RE1 download is a few
hundred MB, and `torch_geometric` install can be slow depending on your
platform's wheel availability. Re-running `prepare_re1_data.py` is a no-op
if `data/RE1/RE1-OB` already exists.

**Notes carried over from the Colab run:**
- FeatureStats must be fit once on the training split and reused at
  inference -- never refit on the incident being scored or on ShopMind.
- RE1's real file layout is `RE1-OB/{service}_{fault}/{instance}/data.csv`,
  not the `metrics.json` layout implied by some docs.
- The Online Boutique service dependency graph is hardcoded in
  `scripts/prepare_re1_data.py` (`ONLINE_BOUTIQUE_EDGES`) since RE1 does not
  ship topology data.

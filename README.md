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

## ShopMind Cross-Topology Evaluation

ShopMind (Archie's 12-service Docker testbed) is a held-out generalization
check only -- it is never used to fit `FeatureStats` or retrain GraphSAGE.
The evaluation dataset (`shopmind_evaluation_dataset.zip`) is packaged on
`archie/rakshithay3/incident-mind` and pulled locally, not committed here.

```bash
# 1. Pull and unzip the latest packaged ShopMind incidents
git fetch origin archie/rakshithay3/incident-mind
git show "origin/archie/rakshithay3/incident-mind:shopmind_evaluation_dataset.zip" \
    > /tmp/shopmind_evaluation_dataset.zip
unzip -o /tmp/shopmind_evaluation_dataset.zip -d ~/Desktop/shopmind_evaluation_dataset

# 2. Sanity-check that ShopMind's raw feature scales still match RE1's after
#    z-normalization with the RE1-fitted FeatureStats. Any row flagged
#    "FAR FROM N(0,1)" means the GraphSAGE checkpoint is seeing
#    out-of-distribution inputs -- fix the exporter before trusting any
#    downstream number.
python3 scripts/diagnose_feature_scale.py \
    --re1-dataset data/rcaeval_re1 \
    --shopmind-dataset ~/Desktop/shopmind_evaluation_dataset \
    --graphsage-model models/graphsage.pt

# 3. Run the full ShopMind evaluation (PPO vs Baseline C solve rate)
python3 scripts/evaluate_shopmind.py \
    --dataset ~/Desktop/shopmind_evaluation_dataset \
    --model models/ppo_dispatch.zip \
    --graphsage-model models/graphsage.pt

# 4. Break solve rate down by hop-distance between the scorer's top-ranked
#    node and the true root cause. This separates a genuine cross-topology /
#    cascading-failure generalization limit (solve rate high at hop=0,
#    dropping as hop-distance grows) from a lingering data/scale artifact
#    (solve rate low even at hop=0).
python3 scripts/diagnose_shopmind_failures.py \
    --dataset ~/Desktop/shopmind_evaluation_dataset \
    --model models/ppo_dispatch.zip \
    --graphsage-model models/graphsage.pt
```

**Known data-contract gotchas (fixed in `archie/rakshithay3/incident-mind`
commit `7d9c4f6`, tag `v1.0.0-eval-freeze`):** ShopMind's Prometheus export
uses different units than RE1 for three of the five features. If
`diagnose_feature_scale.py` flags any of these, check the exporter first:
- `cpu`: fraction (0-1) instead of percent (0-100)
- `latency` / `p99_latency`: milliseconds instead of seconds
- `memory`: usage/limit ratio instead of raw bytes -- this one cannot be
  fixed by a scale factor; it must be reconstructed as
  `mem_pct * mem_limit_bytes` using the `mem_limit` values declared per
  service in ShopMind's `docker-compose.yml`.

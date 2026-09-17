# IncidentMind

Automated root cause analysis for microservice incidents: a GraphSAGE GNN scores every service, a PPO policy decides which specialist agent to dispatch where, and LLaMA 3.2 3B agents (Log, Metrics, Code, Report) produce an evidence-grounded RCA report. Capstone project, Dept. of CSE, B.M.S. College of Engineering.

```
ShopMind telemetry --> GraphSAGE anomaly scores --> priority weighting --> PPO dispatch
      --> Log / Metrics / Code agents --> Report Agent --> email notification + dashboard
```

## Repository layout

This `integration` branch merges the four contributor branches (histories preserved).

| Path | What | Owner |
| --- | --- | --- |
| `incidentmind_p1/`, `scripts/`, `replay_demo.py`, `live_demo.py`, `live_inject_and_capture.py` | GraphSAGE + PPO pipeline, training, evaluation, demos | Rakshitha |
| `priority/`, `multi_fault.py`, `multi_instance_receiver.py`, `cross_instance_dispatch_demo.py` | Extension: priority-weighted dispatch, multi-fault, multi-instance | Rakshitha |
| `agents/`, `pipeline.py`, `schemas/`, `evaluation/`, `shopmind_adapter.py`, `sample_data/` | Multi-agent LLM investigation + 100-incident evaluation | Dharunya |
| `notifications/` | Extension: email hooks (dispatch threshold, report complete) | Dharunya's item |
| `services/`, `docker-compose.yml`, `export_metrics.py`, `package_evaluation.py`, `demo_replay_auth_cpu/` | ShopMind 12-service testbed, fault injection, telemetry export | Archie |
| `dashboard/` | React + Vite console | Vismitha |

Component READMEs: [P1](docs/README_p1.md) · [Agents](docs/README_agents.md) · [ShopMind](docs/README_shopmind.md) · Data contracts: [P1](docs/data_contract.md), [ShopMind exporter](docs/data_contract_shopmind.md) · [Demo runbook](docs/demo_runbook.md)

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2:3b
cd dashboard && npm install
```

Model checkpoints (`models/graphsage.pt`, `models/ppo_dispatch.zip`) and RE1 data are not in git.

## Run the demo (replay)

Tab 1:
```
ollama serve
```
Tab 2:
```
PYTHONPATH=. python3 replay_demo.py --incident-dir output/live_test_cpu_stress --graphsage-model models/graphsage.pt --ppo-model models/ppo_dispatch.zip --output demo_result.json
cp demo_result.json dashboard/public/demoResult.json
```
Tab 3:
```
cd dashboard && npm run dev
```

Multi-instance view: run `multi_instance_receiver.py`, have each instance POST telemetry, then
```
PYTHONPATH=. python3 cross_instance_dispatch_demo.py --output multi_instance_result.json
cp multi_instance_result.json dashboard/public/multiInstanceResult.json
```

## Email notifications

Set `IM_SMTP_USER`, `IM_SMTP_PASSWORD` (Gmail app password) and `IM_NOTIFY_TO`. Without them the notifier writes `.eml` files to `output/notifications/` instead of sending. Disable with `--no-notify`. Check creds with `PYTHONPATH=. python3 scripts/send_test_notification.py`.

## Tests

```
PYTHONPATH=. python3 -m unittest discover -s tests
```

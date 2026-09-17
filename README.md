# IncidentMind

Automated root cause analysis for microservice incidents: a GraphSAGE GNN scores every service, a PPO policy decides which specialist agent to dispatch where, and LLaMA 3.2 3B agents (Log, Metrics, Code, Report) produce an evidence-grounded RCA report. Capstone project, Dept. of CSE, B.M.S. College of Engineering.

```
ShopMind telemetry --> GraphSAGE anomaly scores --> priority weighting --> PPO dispatch
      --> Log / Metrics / Code agents --> Report Agent --> dashboard
      --> wait until ShopMind is back to baseline --> "we're back" email to ShopMind users
```

## Repository layout

| Path | What |
| --- | --- |
| `incidentmind_p1/`, `scripts/`, `replay_demo.py`, `live_demo.py`, `live_inject_and_capture.py` | GraphSAGE + PPO pipeline, training, evaluation, demos |
| `priority/`, `multi_fault.py`, `multi_instance_receiver.py`, `cross_instance_dispatch_demo.py` | Priority-weighted dispatch, multi-fault detection, multi-instance telemetry |
| `agents/`, `pipeline.py`, `schemas/`, `evaluation/`, `shopmind_adapter.py`, `sample_data/` | Multi-agent LLM investigation + 100-incident evaluation |
| `notifications/` | Recovery check + "ShopMind is back to normal" email to registered users |
| `services/`, `docker-compose.yml`, `export_metrics.py`, `package_evaluation.py`, `demo_replay_auth_cpu/` | ShopMind 12-service testbed, fault injection, telemetry export |
| `dashboard/` | React + Vite console |
| `paper/` | Paper draft and the evaluation scripts/results it cites |

Component READMEs: [GNN + PPO](docs/README_p1.md) · [Agents](docs/README_agents.md) · [ShopMind](docs/README_shopmind.md) · Data contracts: [GNN input/output](docs/data_contract.md), [ShopMind exporter](docs/data_contract_shopmind.md) · [Demo runbook](docs/demo_runbook.md)

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

## User notifications

After the RCA, `replay_demo.py` polls live ShopMind telemetry until every app service is back near its pre-fault baseline for 3 polls in a row, then emails every registered ShopMind user a short plain-language "we're back to normal" message (no RCA details). Guests and placeholder addresses (`@shopmind.io`, `@example.com`) are skipped, so register on ShopMind with a real email for a demo. If ShopMind isn't back within `--recovery-timeout` (default 180s), nobody is emailed.

Set `IM_SMTP_USER` and `IM_SMTP_PASSWORD` (Gmail app password). Without them the emails are written to `output/notifications/` instead of sent. `--no-notify` skips the wait and the email.

```
PYTHONPATH=. python3 scripts/send_test_notification.py --list-users
IM_NOTIFY_TO=you@gmail.com PYTHONPATH=. python3 scripts/send_test_notification.py
```

## Tests

```
PYTHONPATH=. python3 -m unittest discover -s tests
```

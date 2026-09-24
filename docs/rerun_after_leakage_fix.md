# Evaluation fixes (Sep 2026) — what changed and how to reproduce

Status: **done**. The paper numbers come from `paper/full_eval_labelfree.json`
and `paper/extra_eval_labelfree.json`.

## What was wrong
1. **Label leakage in ShopMind inputs.** The peak snapshot was chosen by
   up-weighting the injected target, and only the true target could be encoded
   as crashed. Fixed by `shopmind_snapshot.py`, the single label-free compiler
   used by `package_evaluation.py`, `replay_demo.py` and `live_demo.py`.
2. **Replay dropped the call graph** (`edges=[]`), turning GraphSAGE into a
   per-node MLP. Fixed; `paper/full_eval.py` also reports a no-edges ablation.
3. **Strawman dispatch baseline.** Greedy (C) had one guess in a 5-step budget.
   Added Baseline D (sequential greedy, solve rate = PR@5) and PPO with an
   inference-time visited mask, with exact McNemar tests.
4. **Data collection bugs** found while re-collecting:
   - services ran without `--expose-gc`, so memory_pressure was never freed
     and leaked into later incidents;
   - nginx kept stale container IPs after a restart, so no user traffic
     reached the services (`generate_dataset.py` now checks the gateway);
   - the failure window used a 2 s Jaeger lookback, which misses 2 s-delayed
     spans (now 10 s, same as the baseline);
   - Jaeger's unbounded in-memory store got it OOM-killed ~75 incidents in
     (now capped, restarts, and the generator stops if traces vanish).

## Results (100 re-collected incidents, label-free)
| | PR@1 | PR@3 | PR@5 |
|---|---|---|---|
| GraphSAGE | 0.48 [0.38, 0.58] | 0.57 | 0.66 |
| GraphSAGE, no edges | 0.48 | 0.50 | 0.51 |
| Peer z-score | 0.25 | 0.99 | 0.99 |

Per fault (GraphSAGE PR@1): CPU 0.96, delay 0.96, memory 0.00, crash 0.00.
Memory fails because every RE1 memory fault also drives the root cause above
80% CPU, so the model learned "high CPU" (setting only the target's CPU to 20%
lifts memory PR@1 to 0.92; setting only its memory to 450 MB changes nothing).

Dispatch solve rate (5 steps): D 0.66, PPO 0.53 (D-only 13, PPO-only 0,
p = 0.0002), PPO + mask 0.61 (vs D p = 0.38), C 0.48, A/B 0.35.
RE1 (unchanged): GraphSAGE PR@1 0.92, no edges 0.36.

## Reproduce (repo root, venv active)
```
unzip -o shopmind_raw_incidents.zip          # -> datasets/incident_*/telemetry_series.json
python3 package_evaluation.py                # -> shopmind_evaluation_dataset_labelfree.zip
mkdir -p ../sm_labelfree && unzip -o shopmind_evaluation_dataset_labelfree.zip -d ../sm_labelfree
PYTHONPATH=. python3 paper/full_eval.py --shopmind-dataset ../sm_labelfree > paper/full_eval_labelfree.json
PYTHONPATH=. python3 paper/extra_eval.py ../sm_labelfree > paper/extra_eval_labelfree.json
PYTHONPATH=. python3 paper/live_rescore.py > paper/live_rescore.json   # needs output/*/telemetry_series.json
```

## Re-collecting from scratch
```
docker compose up -d --build
caffeinate -i python3 generate_dataset.py --schedule evaluation_schedule.json
```
About 1.5 min per incident (~2.5 h for 100); re-running resumes where it
stopped. Every incident should show its fault on the target, a clean baseline
and non-empty traces.

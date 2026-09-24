# Re-running the paper numbers after the Sep 2026 review fixes

Branch `fix/eval-leakage`. Three things changed:

1. **ShopMind inputs no longer use the label.** `shopmind_snapshot.py` is the
   single compiler used by `package_evaluation.py`, `replay_demo.py` and
   `live_demo.py`. The peak snapshot and the crash encoding never read
   `target_service` or `fault_type`. A service counts as crashed when its
   `cpu_pct` is null for 2 or more consecutive polls, whichever service it is.
2. **Dispatch baselines.** Baseline D (sequential greedy: walk ranks 1..5;
   solve rate = PR@5) and PPO+mask (same trained policy, visited actions
   masked at inference, no retraining). McNemar is reported against C and D.
3. **Edges.** `replay_demo.py` now passes the snapshot's call graph (it used to
   pass `edges=[]`, which makes GraphSAGE a per-node MLP). `full_eval.py` also
   reports the same model scored without edges (`*_gs_noedges`).

## Commands (repo root, venv active)

```
# 1. rebuild the ShopMind set from the RAW incidents (incident_*/telemetry_series.json)
python3 package_evaluation.py --datasets-dir <folder with incident_001 ... incident_100>
#    -> shopmind_evaluation_dataset_labelfree.zip (old zip left untouched)
mkdir -p ../sm_labelfree && unzip -o shopmind_evaluation_dataset_labelfree.zip -d ../sm_labelfree

# 2. localisation + dispatch + edge ablation
PYTHONPATH=. python3 paper/full_eval.py --shopmind-dataset ../sm_labelfree > paper/full_eval_labelfree.json

# 3. bootstrap CIs, priority re-ranking, random baselines
PYTHONPATH=. python3 paper/extra_eval.py ../sm_labelfree > paper/extra_eval_labelfree.json

# optional: the old frozen set for a before/after row
PYTHONPATH=. python3 paper/full_eval.py --shopmind-dataset ../sm > paper/full_eval_old.json
```

No retraining is needed: GraphSAGE and PPO were trained on RE1 only, and RE1
inputs are unchanged. RE1 results should match the draft exactly; only the
ShopMind columns and the new rows move.

## Paper text that changes with the numbers
- Abstract/Results: ShopMind PR@k, per-fault numbers, dispatch table.
- The "z-score ranks crashed services top-3 in 96%" sentence: re-check it.
  The old encoding gave error_rate = 1.0 only to the true root cause.
- Dispatch: compare PPO against D, not only C. With the draft's own numbers,
  D would solve 70% (PR@5) against PPO's 57%.
- Live runs (Table live) were scored without edges; re-run them or say so.
- Add the no-edges row to the localisation table (it answers the "does the
  graph help?" question raised in related work).

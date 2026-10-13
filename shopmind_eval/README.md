# shopmind_eval/

| File | What it is |
|---|---|
| `full_eval.py` | Localisation (incl. no-edges ablation) and dispatch (A/B/C/D, PPO, PPO+mask, McNemar). |
| `extra_eval.py` | Bootstrap CIs, priority re-ranking, random baselines. |
| `live_rescore.py` | Re-scores captured live runs with vs without edges. |
| **`full_eval_labelfree.json`, `extra_eval_labelfree.json`** | **Current results.** |
| `live_rescore.json` | Live-run re-scoring used in the live table. |
| `full_eval_oldset.json` | New scripts on the OLD Sep 6 set (label-aware snapshots) -- before/after only. |

How the current numbers were produced: `docs/rerun_after_leakage_fix.md`.

# Incident watcher (`incident_watcher.py`)

A long-running process that watches ShopMind telemetry, notices a fault on its
own and runs the full IncidentMind pipeline (GraphSAGE -> PPO dispatch -> Log /
Metrics / Code agents -> Report Agent) on it, writing the result where the
dashboard polls for it. Nothing tells it that a fault was injected: the
storefront chaos button and `/inject-fault` stay exactly as they were.

## Run

Prerequisites: ShopMind stack up (`docker compose up -d`), `ollama serve` with
`llama3.2:3b`, and `models/graphsage.pt` + `models/ppo_dispatch.zip`.

```
PYTHONPATH=. python3 load_generator.py            # optional, realistic traffic
PYTHONPATH=. python3 incident_watcher.py          # watch + investigate
cd dashboard && npm run dev                       # turn on Live demo mode (2 s refresh)
```

Then press the chaos button on the storefront (or
`curl -X POST localhost:3001/inject-fault -H 'Content-Type: application/json' -d '{"type":"cpu_stress","duration_sec":30}'`).

`--dry-run --verbose` runs detection only (gate + GraphSAGE confirmation),
printing the gate score every poll, and writes nothing. Use it to check for
false positives on your traffic before a demo.

## How it decides

| Phase | What happens |
|---|---|
| warming | Every poll whose newest snapshot is healthy (gate not tripped, no missed scrape) goes into a rolling baseline (`--baseline-size`). After `--min-baseline` healthy snapshots it prints `armed`. |
| armed | **Gate:** newest snapshot scored with `shopmind_snapshot.snapshot_score` against `baseline_stats(baseline)`; trips when the max scaled deviation >= `--gate` or a service is down (cpu `None` in >= 2 of the last 3 polls). **Confirm:** if the gate trips, GraphSAGE scores `compile_telemetry({baseline_history, failure_history: last 3 polls})`; the poll counts when some node >= `--threshold`. `--confirm` counting polls in a row = incident. |
| capturing | `--capture-sec` more polls are appended to `failure_history` (which starts with the confirm window). Then `<out-dir>/auto_<epoch>/telemetry_series.json` (`target_service`/`fault_type` = `"unknown"`) and every service's docker log are written and the pipeline runs in a worker thread. |
| cooldown | No new incident until `--cooldown-healthy` healthy polls in a row (vs the pre-incident baseline) AND `--min-gap-sec` since the last incident started AND the investigation has finished. The baseline is then refilled from scratch. |

Gate units are the fixed per-field scales in `shopmind_snapshot._Z_FIELDS`:
gate 3.0 = 30 CPU points, 15% of the memory limit, +150 ms mean latency,
+600 ms p99 or +0.15 error rate above that service's baseline median.

## Output

1. Right after scoring + PPO dispatch: an interim result with
   `fault_injection_state: "active"` and `report: null`.
2. When the agents finish: the final result, overwriting the interim one.

Both go to `--output` (default `dashboard/public/demoResult.json`) and
`<out-dir>/<incident_id>/result.json`, written atomically (tmp + rename). The
schema is replay_demo.py's, plus `ground_truth` and `detection`
(`detected_at`, `detection_latency_sec`, thresholds).

### Ground truth (evaluation only)

At confirmation and again after capture the watcher does a best-effort
`GET /fault-status` on each app service. If exactly one service reports an
active fault, it fills `true_root_cause` / `injected_target` / `fault_type` and
computes `pr_at_1/3/5` against the raw GraphSAGE ranking. Otherwise those are
`"unknown"`, the metrics are 0 and `ground_truth` is `"unavailable"`. This is
never passed to the gate, GraphSAGE, PPO or the agents.

## Flags

| Flag | Default | |
|---|---|---|
| `--poll-sec` | 2.0 | poll interval |
| `--baseline-size` | 8 | rolling healthy baseline |
| `--min-baseline` | 5 | healthy snapshots before `armed` |
| `--gate` | 3.0 | gate threshold (scaled deviation) |
| `--threshold` | 0.5 | min GraphSAGE node score |
| `--confirm` | 2 | consecutive polls where gate AND GraphSAGE hold |
| `--capture-sec` | 20 | extra failure capture after confirmation |
| `--cooldown-healthy` | 5 | healthy polls before re-arming |
| `--min-gap-sec` | 60 | min seconds between incident starts |
| `--min-app-up` | 4 | fewer responding app services = "stack not up" (never an incident) |
| `--graphsage-model` / `--ppo-model` | `models/graphsage.pt` / `models/ppo_dispatch.zip` | |
| `--code-repo-path` | none | repo for the Code Agent |
| `--output` | `dashboard/public/demoResult.json` | |
| `--out-dir` | `output/watcher` | per-incident telemetry, logs, result |
| `--notify` | off | wait for recovery and email users, as replay_demo.py |
| `--once` | off | exit after the first incident finishes |
| `--dry-run` | off | detect and log only |
| `--verbose` | off | print the gate every poll |

## Limitations

- Start it while ShopMind is healthy: whatever the first `--min-baseline`
  healthy-looking polls show becomes "normal".
- A permanent shift (e.g. traffic doubles and stays) keeps tripping the gate;
  GraphSAGE usually filters it, but the baseline won't adapt until a healthy
  poll, so GraphSAGE runs every poll meanwhile.
- One incident at a time: a second, overlapping fault on another service
  during capture/investigation is folded into the first or suppressed.
- Detection latency is roughly `confirm x poll-sec` plus the time for the
  fault to show in `/metrics` / Jaeger (10 s lookback); faults shorter than
  that may be missed.
- Ctrl+C during an investigation abandons it; the interim result stays.
- `collect_all_telemetry` also appends to `metrics_history.jsonl`, as it does
  for every other caller.

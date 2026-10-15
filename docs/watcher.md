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

## Rule-based fallback (`--fallback`, off by default)

`--fallback` adds a **hand-written rule, separate from the learned model**. It
exists because GraphSAGE scores memory_pressure and pod_crash at 0.000 (see
Limitations), so those faults never confirm on the model alone.

With `--fallback` on:

- **Confirmation:** if the gate trips on `--confirm` consecutive polls (a
  sustained-down service always trips it) but GraphSAGE stays below
  `--threshold`, the incident is confirmed anyway. If GraphSAGE does reach the
  threshold on `--confirm` polls in a row, it is a normal `graphsage`
  detection, exactly as without the flag.
- **Ranking:** for a fallback incident, GraphSAGE is not used for the ranking.
  On the label-free peak snapshot, down services rank first, then the rest by
  their largest scaled deviation above baseline (the gate's units).
  `anomaly_score` is that deviation mapped to [0, 1]: down = 1.0,
  `deviation / (2 x --gate)` capped at 1.0, so a node is `anomalous` (>= 0.5)
  exactly when it alone would trip the gate. No priority re-weighting.
- **Dispatch:** PPO dispatches on that rule-based ranking (the trained policy is
  unchanged; it only sees different scores).
- **Result:** `"detection": "gate-fallback"` (vs `"graphsage"`) and
  `metrics.ranking: "gate_fallback"`, so the dashboard JSON says which path
  produced the ranking. Precision numbers from fallback incidents measure the
  rule, not GraphSAGE; don't mix them into GraphSAGE results.

The fallback is only as good as the fixed gate scales: it ranks whichever
service moved furthest from its own baseline, with no learned notion of
propagation, so a symptom service can outrank the cause.

## Output

1. Right after scoring + PPO dispatch: an interim result with
   `fault_injection_state: "active"` and `report: null`.
2. When the agents finish: the final result, overwriting the interim one.

Both go to `--output` (default `dashboard/public/demoResult.json`) and
`<out-dir>/<incident_id>/result.json`, written atomically (tmp + rename). The
schema is replay_demo.py's, plus `ground_truth`, `detection`
(`"graphsage"` or `"gate-fallback"`) and `detection_info` (`detected_at`,
`detection_latency_sec`, thresholds, `fallback_enabled`).

### Ground truth (evaluation only)

At confirmation and again after capture the watcher does a best-effort
`GET /fault-status` on each app service. If exactly one service reports an
active fault, it fills `true_root_cause` / `injected_target` / `fault_type` and
computes `pr_at_1/3/5` against the raw GraphSAGE ranking (or the gate
ranking for a `gate-fallback` incident). Otherwise those are
`"unknown"`, the metrics are 0 and `ground_truth` is `"unavailable"`. This is
never passed to the gate, GraphSAGE, PPO or the agents. A pod_crash target
can't answer `/fault-status` while it crash-loops (and forgets the fault when
it restarts), so pod_crash incidents normally record `"unavailable"`.

## Flags

| Flag | Default | |
|---|---|---|
| `--poll-sec` | 2.0 | poll interval |
| `--baseline-size` | 30 | rolling healthy baseline |
| `--min-baseline` | 5 | healthy snapshots before `armed` |
| `--gate` | 3.0 | gate threshold (scaled deviation) |
| `--threshold` | 0.5 | min GraphSAGE node score |
| `--confirm` | 3 | consecutive polls where gate AND GraphSAGE hold |
| `--capture-sec` | 20 | extra failure capture after confirmation |
| `--cooldown-healthy` | 5 | healthy polls before re-arming |
| `--min-gap-sec` | 60 | min seconds between incident starts |
| `--min-app-up` | 4 | fewer responding app services = "stack not up" (never an incident) |
| `--fallback` | off | rule-based: confirm on the gate alone and rank by gate deviation when GraphSAGE stays below `--threshold` |
| `--graphsage-model` / `--ppo-model` | `models/graphsage.pt` / `models/ppo_dispatch.zip` | |
| `--code-repo-path` | none | repo for the Code Agent |
| `--output` | `dashboard/public/demoResult.json` | |
| `--out-dir` | `output/watcher` | per-incident telemetry, logs, result |
| `--notify` | off | wait for recovery and email users, as replay_demo.py |
| `--allow-simulated-email` | off | really email users after a `--simulate-recovery` run (otherwise `.eml` drafts only) |
| `--once` | off | exit after the first incident finishes |
| `--dry-run` | off | detect and log only |
| `--verbose` | off | print the gate every poll |

## Limitations

- **GraphSAGE misses memory_pressure and pod_crash.** In live tests (Oct 2026)
  the gate tripped within 4 s for both (search-service memory 10% -> 57%;
  inventory-service down for ~28 s), but GraphSAGE scored every node 0.000,
  so neither was confirmed. cpu_stress (1.000) and network_delay (0.92) are
  caught in 3-12 s. Without `--fallback`, those two fault types are not
  detected on their own.
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

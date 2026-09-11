import { STATIC_EDGES } from './topology'

// Converts the raw JSON written by live_demo.py OR replay_demo.py
// (--output demo_result.json) into the exact shape every dashboard
// component reads. Keep this the ONLY place that knows about the demo
// scripts' output formats -- if either format changes, this is the one
// file to update.
//
// live_demo.py uses "injected_target"; replay_demo.py uses
// "true_root_cause" (both scripts now also write "injected_target" for
// consistency, but this falls back either way).
export function transformDemoResult(raw) {
  const rootCauseService = raw.injected_target ?? raw.true_root_cause ?? null

  return {
    incident_id: raw.incident_id,
    timestamp: raw.timestamp ?? '',
    fault_type: raw.fault_type,
    injected_target: rootCauseService,
    // nodes shape matches directly either way -- replay_demo.py just omits
    // embedding_dim, which no component actually reads.
    nodes: raw.nodes,
    // Neither script's output is guaranteed to include real call-graph
    // edges (live_demo.py has them from Jaeger; replay_demo.py doesn't
    // capture edges at all) -- fall back to the static topology so the
    // graph always renders something.
    edges: raw.edges && raw.edges.length > 0 ? raw.edges : STATIC_EDGES,
    fault_injection_state: raw.fault_injection_state ?? 'resolved',
    metrics: raw.metrics ?? { pr_at_1: 0, pr_at_3: 0, pr_at_5: 0 },
    ppo_dispatch: raw.ppo_dispatch ?? null,
    evidence_bundle: raw.evidence_bundle ?? null,
    report: raw.report ?? null
  }
}

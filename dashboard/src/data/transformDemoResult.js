import { STATIC_EDGES } from './topology'
import { impactTier, impactWeight } from './impactWeights'

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
    ppo_dispatch: normalizeDispatch(raw.ppo_dispatch),
    multi_fault_detected: raw.multi_fault_detected ?? [],
    evidence_bundle: raw.evidence_bundle ?? null,
    report: raw.report ?? null,
    // Recovery check + "ShopMind is back" user email (notifications/).
    // Missing on runs made before those existed, or with --no-notify.
    recovery: raw.recovery ?? null,
    notifications: Array.isArray(raw.notifications) ? raw.notifications : []
  }
}

// replay_demo.py writes ppo_dispatch flat ({agent_type, target_service,
// policy_confidence}); DispatchDecision.to_json() nests it under "action"
// with a "step". Components read the nested form, so normalise here.
function normalizeDispatch(d) {
  if (!d) return null
  const action = d.action ?? {
    agent_type: d.agent_type,
    target_service: d.target_service,
    instance_id: d.instance_id ?? null
  }
  return { step: d.step ?? 1, action, policy_confidence: d.policy_confidence ?? 0 }
}

// multiInstanceResult.json from cross_instance_dispatch_demo.py --output.
export function transformMultiInstanceResult(raw) {
  return {
    source: 'multi',
    generated_at: raw.generated_at ?? null,
    instances: raw.instances ?? [],
    queue: raw.queue ?? [],
    dispatches: raw.dispatches ?? []
  }
}

// Fallback when no multi-instance run exists: treat the loaded incident as
// one instance and apply the same priority weighting the backend uses.
export function deriveSingleInstanceQueue(incident) {
  const target = incident.ppo_dispatch?.action?.target_service
  const queue = incident.nodes
    .filter(n => n.status === 'anomalous')
    .map(n => {
      const weight = impactWeight(n.service_id)
      return {
        instance_id: 'local',
        service_id: n.service_id,
        anomaly_score: n.anomaly_score,
        impact_tier: impactTier(n.service_id),
        impact_weight: weight,
        priority_score: n.anomaly_score * weight
      }
    })
    .sort((a, b) => b.priority_score - a.priority_score)
    .map((row, i) => {
      const dispatched = row.service_id === target
      return {
        ...row,
        rank: i + 1,
        dispatch_step: dispatched ? 1 : null,
        agent_type: dispatched ? incident.ppo_dispatch.action.agent_type : null
      }
    })

  return {
    source: 'single',
    generated_at: incident.timestamp || null,
    instances: [
      {
        instance_id: 'local',
        incident_id: incident.incident_id,
        fault_type: incident.fault_type,
        target_service: incident.injected_target,
        anomalous_count: queue.length,
        status: 'scored'
      }
    ],
    queue,
    dispatches: []
  }
}

// Latest "ShopMind is back" email status for this incident, if any.
export function restoredNotification(incident) {
  const matches = (incident.notifications ?? []).filter(n => n.event === 'service_restored')
  return matches.length ? matches[matches.length - 1] : null
}

// Mirrors priority/impact_weights.py exactly -- priority_score =
// anomaly_score * impact_weight. If the Python tiers change, update this too.
// Only used to derive a single-instance queue when no
// multiInstanceResult.json has been generated yet; real multi-instance runs
// ship tier/weight/priority precomputed by the backend.

export const TIER_WEIGHTS = { high: 1.0, medium: 0.6, low: 0.3 }
export const DEFAULT_WEIGHT = 0.6

export const SERVICE_TIERS = {
  'auth-service': 'high',
  'payment-service': 'high',
  'order-service': 'high',
  'postgres-primary': 'high',
  'user-service': 'medium',
  'inventory-service': 'medium',
  'api-gateway': 'medium',
  cache: 'medium',
  'postgres-replica': 'medium',
  'search-service': 'low',
  'notification-service': 'low',
  frontend: 'low'
}

export function impactTier(serviceId) {
  return SERVICE_TIERS[serviceId] ?? 'default'
}

export function impactWeight(serviceId) {
  return TIER_WEIGHTS[SERVICE_TIERS[serviceId]] ?? DEFAULT_WEIGHT
}

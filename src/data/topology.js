// Canonical ShopMind topology — sourced from Archie's services.json and
// export_metrics.py static_edges. This is the REAL 12-service list.
//
// NOTE: mockIncident.js used a different, invented service list
// (product-service, cart-service, checkout-service, recommendation-service)
// that does not exist in ShopMind. Those names never appear in live data —
// keep this file, not mockIncident's list, as the source of truth for
// service names once real data is wired in.

export const SHOPMIND_SERVICES = [
  'frontend',
  'api-gateway',
  'auth-service',
  'user-service',
  'order-service',
  'payment-service',
  'inventory-service',
  'notification-service',
  'search-service',
  'cache',
  'postgres-primary',
  'postgres-replica'
]

// Static call-graph edges (source -> target). Real call_count values are
// filled in per-incident from live_demo.py's output (Jaeger-derived). This
// list is only the fallback shape used before any real result is loaded.
export const STATIC_EDGES = [
  { source: 'frontend', target: 'api-gateway', call_count: 1 },
  { source: 'api-gateway', target: 'auth-service', call_count: 1 },
  { source: 'api-gateway', target: 'user-service', call_count: 1 },
  { source: 'api-gateway', target: 'order-service', call_count: 1 },
  { source: 'api-gateway', target: 'search-service', call_count: 1 },
  { source: 'order-service', target: 'payment-service', call_count: 1 },
  { source: 'order-service', target: 'inventory-service', call_count: 1 },
  { source: 'order-service', target: 'notification-service', call_count: 1 },
  { source: 'auth-service', target: 'postgres-primary', call_count: 1 },
  { source: 'user-service', target: 'postgres-primary', call_count: 1 },
  { source: 'order-service', target: 'postgres-primary', call_count: 1 },
  { source: 'payment-service', target: 'postgres-primary', call_count: 1 },
  { source: 'inventory-service', target: 'postgres-primary', call_count: 1 },
  { source: 'search-service', target: 'postgres-replica', call_count: 1 },
  { source: 'auth-service', target: 'cache', call_count: 1 },
  { source: 'postgres-primary', target: 'postgres-replica', call_count: 1 }
]

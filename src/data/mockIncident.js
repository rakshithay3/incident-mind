// Mock data — matches the Data Contract exactly (see roadmap doc, "Expected GNN Output Shape").
// Replace this file's export with the live GNN feed once Rakshitha's embeddings are ready.
// Every downstream component reads ONLY this shape, so the swap should be a one-line change.

export const SHOPMIND_SERVICES = [
  'api-gateway',
  'auth-service',
  'user-service',
  'product-service',
  'cart-service',
  'checkout-service',
  'payment-service',
  'inventory-service',
  'order-service',
  'notification-service',
  'search-service',
  'recommendation-service'
]

export const mockIncident = {
  incident_id: 'inc_001',
  timestamp: '2026-06-20T10:15:00Z',
  nodes: [
    { service_id: 'auth-service', anomaly_score: 1.42, embedding_dim: 128, status: 'anomalous', rank: 1 },
    { service_id: 'api-gateway', anomaly_score: 0.91, embedding_dim: 128, status: 'anomalous', rank: 2 },
    { service_id: 'user-service', anomaly_score: 0.63, embedding_dim: 128, status: 'anomalous', rank: 3 },
    { service_id: 'checkout-service', anomaly_score: 0.34, embedding_dim: 128, status: 'normal', rank: 4 },
    { service_id: 'payment-service', anomaly_score: 0.29, embedding_dim: 128, status: 'normal', rank: 5 },
    { service_id: 'cart-service', anomaly_score: 0.22, embedding_dim: 128, status: 'normal', rank: 6 },
    { service_id: 'order-service', anomaly_score: 0.18, embedding_dim: 128, status: 'normal', rank: 7 },
    { service_id: 'product-service', anomaly_score: 0.15, embedding_dim: 128, status: 'normal', rank: 8 },
    { service_id: 'inventory-service', anomaly_score: 0.14, embedding_dim: 128, status: 'normal', rank: 9 },
    { service_id: 'search-service', anomaly_score: 0.11, embedding_dim: 128, status: 'normal', rank: 10 },
    { service_id: 'recommendation-service', anomaly_score: 0.09, embedding_dim: 128, status: 'normal', rank: 11 },
    { service_id: 'notification-service', anomaly_score: 0.05, embedding_dim: 128, status: 'normal', rank: 12 }
  ],
  edges: [
    { source: 'api-gateway', target: 'auth-service', call_count: 142 },
    { source: 'api-gateway', target: 'user-service', call_count: 118 },
    { source: 'api-gateway', target: 'product-service', call_count: 210 },
    { source: 'api-gateway', target: 'search-service', call_count: 96 },
    { source: 'auth-service', target: 'user-service', call_count: 87 },
    { source: 'user-service', target: 'cart-service', call_count: 74 },
    { source: 'cart-service', target: 'checkout-service', call_count: 61 },
    { source: 'checkout-service', target: 'payment-service', call_count: 58 },
    { source: 'checkout-service', target: 'order-service', call_count: 55 },
    { source: 'order-service', target: 'inventory-service', call_count: 49 },
    { source: 'order-service', target: 'notification-service', call_count: 33 },
    { source: 'product-service', target: 'inventory-service', call_count: 45 },
    { source: 'product-service', target: 'recommendation-service', call_count: 28 },
    { source: 'search-service', target: 'product-service', call_count: 40 }
  ],
  fault_injection_state: 'active',
  metrics: {
    pr_at_1: 0.0,
    pr_at_3: 1.0,
    pr_at_5: 1.0
  }
}

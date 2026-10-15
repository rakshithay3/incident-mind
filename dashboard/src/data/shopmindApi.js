// Admin fault-injection client for the ShopMind services.
//
// Calls go through the ShopMind api-gateway (nginx, port 80), which routes
// /api/<name>/... to each service. In dev, vite.config.js proxies
// /shopmind-api -> http://localhost:80 so the browser never makes a
// cross-origin request (the services send no CORS headers). For another
// deployment set VITE_SHOPMIND_API (e.g. https://shopmind.example.com).

const BASE = (import.meta.env?.VITE_SHOPMIND_API || '/shopmind-api').replace(/\/$/, '')

// Gateway route name per service (matches services/api-gateway/nginx.conf).
export const SERVICES = [
  { id: 'auth-service', route: 'auth' },
  { id: 'user-service', route: 'user' },
  { id: 'order-service', route: 'order' },
  { id: 'payment-service', route: 'payment' },
  { id: 'inventory-service', route: 'inventory' },
  { id: 'notification-service', route: 'notification' },
  { id: 'search-service', route: 'search' }
]

export const FAULT_TYPES = [
  { id: 'cpu_stress', label: 'CPU stress' },
  { id: 'memory_pressure', label: 'Memory pressure' },
  { id: 'network_delay', label: 'Network delay' },
  { id: 'pod_crash', label: 'Pod crash' }
]

const url = (route, action) => `${BASE}/api/${route}/${action}`

async function call(route, action, method, body, timeoutMs = 4000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(url(route, action), {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal
    })
    let data = null
    try { data = await res.json() } catch { /* non-JSON body */ }
    return { ok: res.ok, status: res.status, data }
  } finally {
    clearTimeout(timer)
  }
}

export function injectFault(route, type, durationSec, config = {}) {
  return call(route, 'inject-fault', 'POST', { type, duration_sec: durationSec, config })
}

export function resetService(route) {
  return call(route, 'reset', 'POST', {})
}

// Resolves to the service's active-fault object, or null if unreachable
// (a crashed pod will not answer until Docker restarts it).
export async function faultStatus(route) {
  try {
    const r = await call(route, 'fault-status', 'GET', null, 2500)
    return r.ok ? r.data : null
  } catch {
    return null
  }
}

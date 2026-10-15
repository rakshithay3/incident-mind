import { useCallback, useEffect, useState } from 'react'
import { FAULT_TYPES, SERVICES, faultStatus, injectFault, resetService } from '../../data/shopmindApi'

// Admin-only: trigger and clear faults on the live ShopMind microservices
// (POST /inject-fault and /reset through the api-gateway), and watch each
// service's active-fault state.

const STATUS_POLL_MS = 3000

function useServiceStatus() {
  const [status, setStatus] = useState({}) // service id -> fault object | null (unreachable)
  const refresh = useCallback(async () => {
    const entries = await Promise.all(SERVICES.map(async s => [s.id, await faultStatus(s.route)]))
    setStatus(Object.fromEntries(entries))
  }, [])
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, STATUS_POLL_MS)
    return () => clearInterval(t)
  }, [refresh])
  return [status, refresh]
}

export default function FaultInjectionTab() {
  const [service, setService] = useState(SERVICES[0].id)
  const [type, setType] = useState(FAULT_TYPES[0].id)
  const [duration, setDuration] = useState(20)
  const [delayMs, setDelayMs] = useState(2000)
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState([])
  const [status, refresh] = useServiceStatus()

  const addLog = (text, level = 'info') =>
    setLog(l => [{ t: new Date().toLocaleTimeString(), text, level }, ...l].slice(0, 12))

  const routeOf = id => SERVICES.find(s => s.id === id).route

  const inject = async () => {
    const secs = Math.max(1, Math.min(600, Number(duration) || 20))
    setBusy(true)
    try {
      const config = type === 'network_delay' ? { delayMs: Number(delayMs) || 2000 } : {}
      const r = await injectFault(routeOf(service), type, secs, config)
      if (r.ok) addLog(`${type} injected into ${service} for ${secs}s`, 'ok')
      else addLog(`${service}: ${r.data?.error ?? `rejected (${r.status})`}`, 'err')
    } catch (e) {
      addLog(`${service}: could not reach gateway (${e.message}). Is ShopMind running?`, 'err')
    } finally {
      setBusy(false)
      refresh()
    }
  }

  const reset = async id => {
    try {
      const r = await resetService(routeOf(id))
      if (r.ok) addLog(`${id} reset`, 'ok')
      else addLog(`${id}: reset failed (${r.status})`, 'err')
    } catch (e) {
      addLog(`${id}: could not reach service (${e.message})`, 'err')
    }
    refresh()
  }

  return (
    <div className="tab-panel">
      <span className="section-label">Inject a fault</span>
      <form className="inject-form" onSubmit={e => { e.preventDefault(); inject() }}>
        <label className="field">
          <span className="field-label">Service</span>
          <select className="field-input" value={service} onChange={e => setService(e.target.value)}>
            {SERVICES.map(s => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Fault type</span>
          <select className="field-input" value={type} onChange={e => setType(e.target.value)}>
            {FAULT_TYPES.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Duration (s)</span>
          <input className="field-input" type="number" min="1" max="600" value={duration}
            onChange={e => setDuration(e.target.value)} />
        </label>
        {type === 'network_delay' && (
          <label className="field">
            <span className="field-label">Delay (ms)</span>
            <input className="field-input" type="number" min="100" max="10000" step="100" value={delayMs}
              onChange={e => setDelayMs(e.target.value)} />
          </label>
        )}
        <button className="inject-btn" type="submit" disabled={busy}>
          {busy ? 'Injecting…' : 'Inject fault'}
        </button>
      </form>

      <span className="section-label">Service status</span>
      <ul className="inject-status-list">
        {SERVICES.map(s => {
          const st = status[s.id]
          const unreachable = st === null
          const active = st?.active
          return (
            <li key={s.id} className="inject-status-row">
              <span className="mono">{s.id}</span>
              {unreachable && <span className="status-pill sev-unknown">unreachable</span>}
              {!unreachable && st !== undefined && !active && <span className="status-pill status-normal">healthy</span>}
              {active && (
                <span className="status-pill status-anomalous">
                  {st.fault_type} · {st.scheduled_duration_sec}s
                </span>
              )}
              <button className="signout-btn inject-reset" onClick={() => reset(s.id)}>Reset</button>
            </li>
          )
        })}
      </ul>

      {log.length > 0 && (
        <>
          <span className="section-label">Activity</span>
          <ul className="inject-log mono">
            {log.map((l, i) => (
              <li key={i} className={`inject-log-${l.level}`}>[{l.t}] {l.text}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

import { mockIncident } from '../../data/mockIncident'

// Wireframe only — real-time alert stream arrives once Archie's
// Prometheus/Jaeger exports are live (Weeks 3-5 sync point).

export default function AlertFeedTab() {
  const anomalous = mockIncident.nodes.filter(n => n.status === 'anomalous')

  return (
    <div className="tab-panel">
      <div className="wireframe-note">
        Wireframe — will stream live alerts once ShopMind telemetry is connected.
      </div>
      <ul className="alert-list">
        {anomalous.map(n => (
          <li key={n.service_id} className="alert-item">
            <span className="status-pill status-anomalous">alert</span>
            <span className="mono">{n.service_id}</span>
            <span className="alert-detail">anomaly score {n.anomaly_score.toFixed(2)}</span>
          </li>
        ))}
        {anomalous.length === 0 && <li className="alert-empty">No active alerts.</li>}
      </ul>
    </div>
  )
}

import CustomerNotification from '../CustomerNotification'

// Customer email status on top, then one row per anomalous service.
// Real-time alert streaming arrives once Archie's Prometheus/Jaeger exports
// are live.

export default function AlertFeedTab({ incident }) {
  const anomalous = [...incident.nodes]
    .filter(n => n.status === 'anomalous')
    .sort((a, b) => a.rank - b.rank)

  return (
    <div className="tab-panel">
      <CustomerNotification incident={incident} />
      <span className="section-label">Active alerts</span>
      <ul className="alert-list">
        {anomalous.map(n => (
          <li key={n.service_id} className="alert-item">
            <span className="status-pill status-anomalous">Alert</span>
            <span className="mono">{n.service_id}</span>
            <span className="alert-detail mono">score {n.anomaly_score.toFixed(2)}</span>
          </li>
        ))}
        {anomalous.length === 0 && <li className="alert-empty">No active alerts.</li>}
      </ul>
    </div>
  )
}

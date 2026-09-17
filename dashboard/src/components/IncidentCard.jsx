import NotificationStatus from './NotificationStatus'

// Summary card for the loaded incident: what happened, what IncidentMind
// concluded, and whether the on-call email went out.

export default function IncidentCard({ incident }) {
  const report = incident.report
  const dispatch = incident.ppo_dispatch
  const multi = incident.multi_fault_detected ?? []

  return (
    <div className="incident-card">
      <div className="incident-card-top">
        <div>
          <span className="rca-report-label">Incident</span>
          <span className="mono incident-card-id">{incident.incident_id}</span>
        </div>
        <div className="incident-card-tags">
          {incident.fault_type && <span className="incident-tag mono">{incident.fault_type}</span>}
          <span className="incident-tag mono">{incident.fault_injection_state}</span>
        </div>
      </div>

      <div className="incident-card-grid">
        <div>
          <span className="rca-report-label">Root cause</span>
          <span className="mono">{report?.root_cause_service ?? 'pending'}</span>
          {report && (
            <span className="rca-report-confidence mono"> {(report.confidence_score * 100).toFixed(0)}%</span>
          )}
        </div>
        <div>
          <span className="rca-report-label">PPO dispatch</span>
          <span className="mono">
            {dispatch ? `${dispatch.action.agent_type} → ${dispatch.action.target_service}` : 'none'}
          </span>
        </div>
        <div>
          <span className="rca-report-label">Anomalous nodes</span>
          <span className="mono">
            {multi.length > 0 ? multi.length : incident.nodes.filter(n => n.status === 'anomalous').length}
          </span>
          {multi.length > 1 && <span className="incident-multi mono"> multi-fault</span>}
        </div>
      </div>

      <NotificationStatus notifications={incident.notifications} />
    </div>
  )
}

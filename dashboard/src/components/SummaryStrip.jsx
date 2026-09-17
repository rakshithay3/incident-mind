import { notifySummary } from './CustomerNotification'

// Four headline numbers above the graph -- what a demo audience needs in the
// first five seconds: what broke, what IncidentMind blamed, how wide it is,
// and whether shoppers were told it's fixed.

export default function SummaryStrip({ incident }) {
  const report = incident.report
  const anomalous = incident.nodes.filter(n => n.status === 'anomalous').length
  const multi = incident.multi_fault_detected?.length ?? 0
  const dispatch = incident.ppo_dispatch?.action
  const notify = notifySummary(incident)
  const confidence = report ? `${Math.round(report.confidence_score * 100)}% confidence` : null

  return (
    <section className="summary-strip" aria-label="Incident summary">
      <div className="stat">
        <div className="stat-label">Incident</div>
        <div className="stat-value mono">{incident.incident_id}</div>
        <div className="stat-sub">{incident.fault_type ?? 'unknown fault'}</div>
      </div>
      <div className="stat">
        <div className="stat-label">Root cause</div>
        <div className="stat-value mono stat-accent">{report?.root_cause_service ?? dispatch?.target_service ?? '—'}</div>
        <div className="stat-sub">
          {confidence ?? (dispatch ? `PPO sent ${dispatch.agent_type} agent · report pending` : 'no report yet')}
        </div>
      </div>
      <div className="stat">
        <div className="stat-label">Anomalous services</div>
        <div className="stat-value">
          {anomalous}
          <span className="instance-muted"> / {incident.nodes.length}</span>
        </div>
        <div className="stat-sub">{multi > 1 ? `multi-fault · ${multi} above threshold` : 'single fault'}</div>
      </div>
      <div className="stat">
        <div className="stat-label">Customer email</div>
        <div className="stat-value">
          <span className={`status-pill notify-${notify.cls}`} style={{ fontSize: 13, padding: '3px 10px' }}>{notify.label}</span>
        </div>
        <div className="stat-sub">{notify.sub}</div>
      </div>
    </section>
  )
}

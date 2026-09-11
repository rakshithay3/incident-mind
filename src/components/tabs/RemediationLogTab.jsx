// Agent dispatch trace: which agent was sent after which service, the PPO
// policy's confidence in that dispatch, and what each specialist agent
// (Log / Metrics / Code) found. Shapes come straight from
// incidentmind_p1/contracts.py -- DispatchDecision (ppo_dispatch) and
// EvidenceBundle.findings (evidence_bundle), both already passed through
// unchanged by transformDemoResult.js.

const SEVERITY_CLASS = {
  low: 'sev-low',
  medium: 'sev-medium',
  high: 'sev-high',
  unknown: 'sev-unknown'
}

export default function RemediationLogTab({ incident }) {
  const dispatch = incident.ppo_dispatch
  const findings = incident.evidence_bundle?.findings ?? []

  if (!dispatch && findings.length === 0) {
    return (
      <div className="tab-panel">
        <div className="wireframe-note">
          No dispatch trace yet for this incident -- once the PPO orchestrator
          and specialist agents run, this tab will list which agent went
          where and what it found.
        </div>
        <div className="wireframe-box">
          <span className="wireframe-box-label">[ agent dispatch trace placeholder ]</span>
        </div>
      </div>
    )
  }

  return (
    <div className="tab-panel">
      {dispatch && (
        <div className="dispatch-decision">
          <span className="rca-section-label">PPO dispatch decision</span>
          <div className="dispatch-decision-row mono">
            step {dispatch.step} → dispatched <strong>{dispatch.action?.agent_type}</strong> agent
            to <strong>{dispatch.action?.target_service}</strong>
            <span className="dispatch-confidence"> (policy confidence {(dispatch.policy_confidence * 100).toFixed(0)}%)</span>
          </div>
        </div>
      )}

      {findings.length > 0 && (
        <ul className="dispatch-log">
          {findings.map((f, i) => (
            <li key={i} className="dispatch-log-item">
              <div className="dispatch-log-header">
                <span className="mono dispatch-agent">{f.agent_type} agent</span>
                <span className="mono dispatch-target">{f.target_service}</span>
                <span className={`status-pill ${SEVERITY_CLASS[f.severity] ?? 'sev-unknown'}`}>
                  {f.severity}
                </span>
                <span className="dispatch-confidence mono">{(f.confidence * 100).toFixed(0)}%</span>
              </div>
              <p className="dispatch-finding">{f.finding}</p>
              {f.evidence?.length > 0 && (
                <ul className="dispatch-evidence">
                  {f.evidence.map((e, j) => (
                    <li key={j} className="mono">{e}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

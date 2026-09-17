import { useState } from 'react'

// Ranked root-cause list overlaid with the full RCA report once one is
// available (RCAReport shape from schemas/contracts.py -- incident_id,
// root_cause_service, confidence_score, evidence_summary, suggested_fix,
// estimated_blast_radius, report_text: { en, hi }).
// Falls back to the rank-only wireframe when no report has been generated
// yet for this incident (e.g. mock data, or a run where the Report Agent
// hasn't finished).

export default function RCAPanelTab({ incident }) {
  const [lang, setLang] = useState('en')
  const ranked = [...incident.nodes].sort((a, b) => a.rank - b.rank).slice(0, 5)
  const report = incident.report

  return (
    <div className="tab-panel">
      <ol className="rca-list">
        {ranked.map(n => (
          <li key={n.service_id} className={n.service_id === report?.root_cause_service ? 'rca-hit' : ''}>
            <span className="mono">#{n.rank}</span> {n.service_id}
            <span className="rca-score mono"> score {n.anomaly_score.toFixed(2)}</span>
          </li>
        ))}
      </ol>

      {!report && (
        <div className="wireframe-note">
          No RCA report yet for this incident -- once the Report Agent runs
          (Dharunya's pipeline), the root cause narrative, suggested fix, and
          blast radius will render here automatically.
        </div>
      )}

      {report && (
        <div className="rca-report">
          <div className="rca-report-header">
            <div>
              <span className="rca-report-label">Root cause</span>
              <span className="mono rca-report-value">{report.root_cause_service}</span>
              <span className="rca-report-confidence mono">
                confidence {(report.confidence_score * 100).toFixed(0)}%
              </span>
            </div>
            {report.report_text?.hi && (
              <div className="lang-toggle">
                <button
                  className={lang === 'en' ? 'lang-btn active' : 'lang-btn'}
                  onClick={() => setLang('en')}
                >
                  EN
                </button>
                <button
                  className={lang === 'hi' ? 'lang-btn active' : 'lang-btn'}
                  onClick={() => setLang('hi')}
                >
                  HI
                </button>
              </div>
            )}
          </div>

          <p className="rca-report-text">
            {report.report_text?.[lang] ?? report.report_text?.en ?? 'No report text.'}
          </p>

          {report.suggested_fix && (
            <div className="rca-section">
              <span className="rca-section-label">Suggested fix</span>
              <p>{report.suggested_fix}</p>
            </div>
          )}

          {report.estimated_blast_radius?.length > 0 && (
            <div className="rca-section">
              <span className="rca-section-label">Estimated blast radius</span>
              <div className="blast-radius-list">
                {report.estimated_blast_radius.map(svc => (
                  <span key={svc} className="blast-radius-chip mono">{svc}</span>
                ))}
              </div>
            </div>
          )}

          {report.evidence_summary?.length > 0 && (
            <div className="rca-section">
              <span className="rca-section-label">Evidence</span>
              <ul className="evidence-summary-list">
                {report.evidence_summary.map((e, i) => (
                  <li key={i}>
                    <span className="mono evidence-agent">{e.agent_type}</span> {e.summary}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

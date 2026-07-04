import { mockIncident } from '../../data/mockIncident'

// Wireframe only — the real PR@k leaderboard (k=1,3,5) using RCAEval
// published numbers as placeholder data lands in Weeks 4-7.

export default function EvaluationTab() {
  const { pr_at_1, pr_at_3, pr_at_5 } = mockIncident.metrics

  return (
    <div className="tab-panel">
      <div className="wireframe-note">
        Wireframe — full leaderboard (Baseline A/B/C vs IncidentMind) comes in Weeks 4-7.
      </div>
      <div className="pr-cards">
        <div className="pr-card">
          <span className="pr-label">PR@1</span>
          <span className="pr-value mono">{pr_at_1.toFixed(2)}</span>
        </div>
        <div className="pr-card">
          <span className="pr-label">PR@3</span>
          <span className="pr-value mono">{pr_at_3.toFixed(2)}</span>
        </div>
        <div className="pr-card">
          <span className="pr-label">PR@5</span>
          <span className="pr-value mono">{pr_at_5.toFixed(2)}</span>
        </div>
      </div>
    </div>
  )
}

import { useMemo } from 'react'
import { useEvaluationSummary } from '../../hooks/useEvaluationSummary'

// Leaderboard tab. Two data sources feed it:
//  1. incident.metrics -- per-incident pr_at_1/3/5 for whichever incident is
//     currently loaded in the dashboard (from live_demo.py / replay_demo.py).
//  2. the committed 100-incident evaluation run (evaluation/results/
//     summary.json) -- real root-cause accuracy for the IncidentMind
//     condition, broken down by fault type.
//
// There is no Baseline A/B/C data in the repo yet (no baseline agent runs
// have been committed on any branch), so the comparison table only has one
// real column. The other three render as "not yet run" -- filling them with
// placeholder numbers would misrepresent the paper's central comparison.

function computeFaultTypeBreakdown(incidents) {
  const byFault = {}
  for (const inc of incidents) {
    const key = inc.fault_type ?? 'unknown'
    byFault[key] = byFault[key] ?? { total: 0, correct: 0 }
    byFault[key].total += 1
    if (inc.correct) byFault[key].correct += 1
  }
  return Object.entries(byFault)
    .map(([faultType, { total, correct }]) => ({
      faultType,
      total,
      correct,
      accuracy: total > 0 ? correct / total : 0
    }))
    .sort((a, b) => b.total - a.total)
}

export default function EvaluationTab({ incident }) {
  const { pr_at_1, pr_at_3, pr_at_5 } = incident.metrics
  const { summary, status, baselineFiles } = useEvaluationSummary()

  const faultBreakdown = useMemo(() => {
    if (!summary?.incidents) return []
    return computeFaultTypeBreakdown(summary.incidents)
  }, [summary])

  return (
    <div className="tab-panel">
      <div className="rca-section-label">This incident</div>
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

      <div className="rca-section-label eval-section-spacer">
        Baseline comparison ({summary?.summary?.total_incidents ?? '?'} ShopMind incidents)
      </div>
      <table className="leaderboard-table">
        <thead>
          <tr>
            <th>Condition</th>
            <th>Root-cause accuracy</th>
            <th>Unknown rate</th>
            <th>JSON validity</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="mono">IncidentMind</td>
            {status === 'ready' ? (
              <>
                <td className="mono">{(summary.summary.accuracy * 100).toFixed(0)}%</td>
                <td className="mono">{(summary.summary.unknown_rate * 100).toFixed(0)}%</td>
                <td className="mono">{(summary.summary.json_validity * 100).toFixed(0)}%</td>
              </>
            ) : (
              <td colSpan={3} className="eval-pending">
                {status === 'loading' ? 'loading…' : 'evaluation summary not found'}
              </td>
            )}
          </tr>
          {['Baseline A', 'Baseline B', 'Baseline C'].map(name => (
            <tr key={name} className="eval-row-pending">
              <td className="mono">{name}</td>
              <td colSpan={3} className="eval-pending">not yet run</td>
            </tr>
          ))}
        </tbody>
      </table>

      {faultBreakdown.length > 0 && (
        <>
          <div className="rca-section-label eval-section-spacer">Accuracy by fault type (IncidentMind)</div>
          <table className="leaderboard-table">
            <thead>
              <tr>
                <th>Fault type</th>
                <th>Incidents</th>
                <th>Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {faultBreakdown.map(row => (
                <tr key={row.faultType}>
                  <td className="mono">{row.faultType}</td>
                  <td className="mono">{row.total}</td>
                  <td className="mono">{(row.accuracy * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {baselineFiles.length === 0 && (
        <div className="wireframe-note eval-note-spacer">
          Baseline A/B/C runs aren't in the repo yet. Wilcoxon significance
          testing and the paper's Table 2 need those before they can be real
          numbers rather than placeholders.
        </div>
      )}
    </div>
  )
}

// Static panel: ranks all 12 services by anomaly_score, highest first.
// This is the plain-text companion to the graph — useful once the graph
// gets crowded, and it's what a screen reader / narrow viewport falls back to.

export default function NodeListPanel({ nodes }) {
  const ranked = [...nodes].sort((a, b) => a.rank - b.rank)
  const max = Math.max(1, ...nodes.map(n => n.anomaly_score))

  return (
    <div className="panel node-list-panel">
      <div className="panel-header">
        <h2>Services</h2>
        <span className="panel-subtitle">ranked by anomaly score</span>
      </div>
      <div className="table-scroll">
      <table className="node-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Service</th>
            <th>Score</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map(n => (
            <tr key={n.service_id} className={n.status === 'anomalous' ? 'row-anomalous' : ''}>
              <td className="mono instance-muted">{n.rank}</td>
              <td className="mono">{n.service_id}</td>
              <td>
                <div className="score-cell">
                  <div className="score-bar">
                    <div className="score-fill" style={{ width: `${(n.anomaly_score / max) * 100}%` }} />
                  </div>
                  <span className="mono">{n.anomaly_score.toFixed(2)}</span>
                </div>
              </td>
              <td>
                <span className={`status-pill status-${n.status}`}>{n.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  )
}

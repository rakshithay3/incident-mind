// Static panel: ranks all 12 services by anomaly_score, highest first.
// This is the plain-text companion to the graph — useful once the graph
// gets crowded, and it's what a screen reader / narrow viewport falls back to.

export default function NodeListPanel({ nodes }) {
  const ranked = [...nodes].sort((a, b) => a.rank - b.rank)

  return (
    <div className="panel node-list-panel">
      <div className="panel-header">
        <h2>Node List</h2>
        <span className="panel-subtitle">ranked by anomaly score</span>
      </div>
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
              <td className="mono">{n.rank}</td>
              <td>{n.service_id}</td>
              <td className="mono">{n.anomaly_score.toFixed(2)}</td>
              <td>
                <span className={`status-pill status-${n.status}`}>{n.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

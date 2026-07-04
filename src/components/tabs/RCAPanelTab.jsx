import { mockIncident } from '../../data/mockIncident'

// Wireframe only — ranked root-cause list + graph overlay comes together
// once the GALR-paper-referenced layout is designed (Weeks 4-7).

export default function RCAPanelTab() {
  const ranked = [...mockIncident.nodes].sort((a, b) => a.rank - b.rank).slice(0, 3)

  return (
    <div className="tab-panel">
      <div className="wireframe-note">
        Wireframe — will overlay ranked root causes on the service graph.
      </div>
      <ol className="rca-list">
        {ranked.map(n => (
          <li key={n.service_id}>
            <span className="mono">#{n.rank}</span> {n.service_id}
            <span className="rca-score mono"> score {n.anomaly_score.toFixed(2)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

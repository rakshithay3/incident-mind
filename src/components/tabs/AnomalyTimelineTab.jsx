// Wireframe only — becomes a real time-series once mock anomaly scores
// are swapped for Rakshitha's GNN output (Weeks 4-7 sync point).

export default function AnomalyTimelineTab() {
  return (
    <div className="tab-panel">
      <div className="wireframe-note">
        Wireframe — placeholder for a scrollable anomaly-score-over-time chart per service.
      </div>
      <div className="wireframe-box">
        <span className="wireframe-box-label">[ time-series chart placeholder ]</span>
      </div>
    </div>
  )
}

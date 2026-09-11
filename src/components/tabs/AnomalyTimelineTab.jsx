import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

// True time-series charting needs historical anomaly-score snapshots per
// service, and neither live_demo.py nor replay_demo.py currently emit that
// (the data contract carries one anomaly_score per node per incident, not a
// series). Rather than fake a time axis, this renders the real current
// snapshot as a sorted bar chart -- once an upstream script starts emitting
// a `history: [{ timestamp, anomaly_score }]` array per node, swap the data
// source here for a real line chart; the layout below already assumes one
// row per service so that swap is small.

export default function AnomalyTimelineTab({ incident }) {
  const svgRef = useRef(null)
  const width = 640
  const rowHeight = 28
  const nodes = [...incident.nodes].sort((a, b) => b.anomaly_score - a.anomaly_score)
  const height = nodes.length * rowHeight + 10

  useEffect(() => {
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const maxScore = Math.max(1, ...nodes.map(n => n.anomaly_score))
    const x = d3.scaleLinear().domain([0, maxScore]).range([120, width - 60])

    const rows = svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('transform', (_, i) => `translate(0, ${i * rowHeight + 5})`)

    rows
      .append('text')
      .text(d => d.service_id)
      .attr('x', 0)
      .attr('y', rowHeight / 2 + 4)
      .attr('class', 'mono timeline-label')

    rows
      .append('rect')
      .attr('x', 120)
      .attr('y', 4)
      .attr('height', rowHeight - 10)
      .attr('width', d => x(d.anomaly_score) - 120)
      .attr('fill', d => (d.status === 'anomalous' ? '#E8544B' : '#3FB88A'))
      .attr('opacity', d => (d.status === 'anomalous' ? 0.9 : 0.5))

    rows
      .append('text')
      .text(d => d.anomaly_score.toFixed(2))
      .attr('x', d => x(d.anomaly_score) + 8)
      .attr('y', rowHeight / 2 + 4)
      .attr('class', 'mono timeline-value')
  }, [incident.nodes])

  return (
    <div className="tab-panel">
      <div className="wireframe-note">
        Snapshot of current anomaly scores, sorted highest-first. Becomes a
        true over-time chart once per-node history snapshots are exposed
        upstream (see comment in this file).
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="timeline-chart" />
    </div>
  )
}

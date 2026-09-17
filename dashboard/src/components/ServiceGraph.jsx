import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

// Renders the 12-node ShopMind service dependency graph.
// Color encodes anomaly_score (per the MAD-CMC / MADMM feature-group mapping
// noted in the roadmap — this file is the first pass, refine the scale once
// the real feature groupings are finalized with Rakshitha).

function nodeFill(d) {
  // Theme tokens (not hex) so the graph follows light/dark mode. Mixing
  // red into green reads as muddy brown, so colour follows status and
  // score only sets how strong the colour is.
  const t = Math.min(Math.max(d.anomaly_score, 0), 1)
  return d.status === 'anomalous'
    ? `color-mix(in srgb, var(--danger) ${Math.round(65 + 35 * t)}%, var(--surface))`
    : `color-mix(in srgb, var(--node-ok) ${Math.round(55 + 45 * t)}%, var(--surface))`
}

export default function ServiceGraph({ nodes, edges, width = 640, height = 420 }) {
  const svgRef = useRef(null)

  useEffect(() => {
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const nodeData = nodes.map(d => ({ ...d }))
    const linkData = edges.map(d => ({ ...d }))

    const simulation = d3
      .forceSimulation(nodeData)
      .force('link', d3.forceLink(linkData).id(d => d.service_id).distance(90).strength(0.6))
      .force('charge', d3.forceManyBody().strength(-260))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(34))

    const link = svg
      .append('g')
      .selectAll('line')
      .data(linkData)
      .join('line')
      .attr('class', 'graph-link')
      .attr('stroke-width', d => Math.max(1, Math.log(d.call_count ?? 1) - 2))

    const node = svg
      .append('g')
      .selectAll('g')
      .data(nodeData)
      .join('g')
      .attr('class', d => `graph-node ${d.status === 'anomalous' ? 'is-anomalous' : ''}`)
      .call(
        d3
          .drag()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0)
            d.fx = null
            d.fy = null
          })
      )

    node
      .append('circle')
      .attr('r', d => (d.status === 'anomalous' ? 15 : 11))
      .style('fill', nodeFill)
      .attr('class', d => (d.status === 'anomalous' ? 'pulse-ring' : ''))

    node
      .append('text')
      .text(d => d.service_id)
      .attr('x', 0)
      .attr('y', d => (d.status === 'anomalous' ? 28 : 24))
      .attr('text-anchor', 'middle')
      .attr('class', 'graph-label')

    node
      .append('title')
      .text(d => `${d.service_id}\nscore: ${d.anomaly_score.toFixed(2)}\nrank: ${d.rank}`)

    simulation.on('tick', () => {
      // keep nodes (and their labels) inside the viewBox
      for (const d of nodeData) {
        d.x = Math.max(60, Math.min(width - 60, d.x))
        d.y = Math.max(24, Math.min(height - 36, d.y))
      }
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y)

      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    return () => simulation.stop()
  }, [nodes, edges, width, height])

  return (
    <>
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="service-graph" role="img" aria-label="Service dependency graph">
        {/* populated by d3 */}
      </svg>
      <div className="graph-legend">
        <span><i className="legend-dot" style={{ background: 'var(--node-ok)' }} />normal</span>
        <span><i className="legend-dot" style={{ background: 'var(--danger)' }} />anomalous</span>
        <span>drag nodes to rearrange</span>
      </div>
    </>
  )
}

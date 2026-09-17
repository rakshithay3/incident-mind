import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

// Renders the 12-node ShopMind service dependency graph.
// Color encodes anomaly_score (per the MAD-CMC / MADMM feature-group mapping
// noted in the roadmap — this file is the first pass, refine the scale once
// the real feature groupings are finalized with Rakshitha).

function scoreToColor(score) {
  // 0 -> calm teal, ~1.4+ -> alert coral. Interpolated, not stepped,
  // so partial anomalies read as "warming up" rather than binary on/off.
  const t = Math.min(score / 1.4, 1)
  return d3.interpolateRgb('#3FB88A', '#E8544B')(t)
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
      .attr('stroke', '#24304A')
      .attr('stroke-opacity', 0.8)
      .selectAll('line')
      .data(linkData)
      .join('line')
      .attr('stroke-width', d => Math.max(1, Math.log(d.call_count) - 2))

    const node = svg
      .append('g')
      .selectAll('g')
      .data(nodeData)
      .join('g')
      .attr('class', 'graph-node')
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
      .attr('r', d => (d.status === 'anomalous' ? 16 : 12))
      .attr('fill', d => scoreToColor(d.anomaly_score))
      .attr('stroke', d => (d.status === 'anomalous' ? '#E8544B' : '#24304A'))
      .attr('stroke-width', d => (d.status === 'anomalous' ? 2 : 1))
      .attr('class', d => (d.status === 'anomalous' ? 'pulse-ring' : ''))

    node
      .append('text')
      .text(d => d.service_id)
      .attr('x', 0)
      .attr('y', 26)
      .attr('text-anchor', 'middle')
      .attr('class', 'graph-label')

    node
      .append('title')
      .text(d => `${d.service_id}\nscore: ${d.anomaly_score.toFixed(2)}\nrank: ${d.rank}`)

    simulation.on('tick', () => {
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
    <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="service-graph">
      {/* populated by d3 */}
    </svg>
  )
}

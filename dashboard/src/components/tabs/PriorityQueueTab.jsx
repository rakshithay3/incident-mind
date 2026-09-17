import { useMemo } from 'react'
import { deriveSingleInstanceQueue } from '../../data/transformDemoResult'

// Global cross-instance priority queue (extension items 2 + 3):
// every anomalous node from every connected ShopMind instance, ordered by
// priority_score = anomaly_score x impact_weight, with the PPO dispatch
// order.
//
// Source: multiInstanceResult.json when present, otherwise the loaded
// incident treated as a single instance.

export default function PriorityQueueTab({ incident, multiInstance }) {
  const data = useMemo(
    () => multiInstance ?? deriveSingleInstanceQueue(incident),
    [multiInstance, incident]
  )
  const maxPriority = Math.max(0.0001, ...data.queue.map(q => q.priority_score))
  const showInstance = data.source === 'multi'

  return (
    <div className="tab-panel">
      {data.source === 'single' && (
        <div className="wireframe-note">
          Single instance view, derived from the loaded incident. For the cross-instance
          queue run <span className="mono">cross_instance_dispatch_demo.py --output multi_instance_result.json</span> and
          copy it to <span className="mono">public/multiInstanceResult.json</span>.
        </div>
      )}

      <div className="instance-cards">
        {data.instances.map(inst => {
          const dispatched = data.queue.filter(q => q.instance_id === inst.instance_id && q.dispatch_step).length
          return (
            <div key={inst.instance_id} className={`instance-card ${inst.status === 'skipped' ? 'instance-skipped' : ''}`}>
              <div className="instance-card-head">
                <span className="mono instance-id">{inst.instance_id}</span>
                <span className={`status-pill ${inst.status === 'skipped' ? 'sev-unknown' : 'status-normal'}`}>{inst.status}</span>
              </div>
              <div className="instance-card-body mono">
                <div>{inst.incident_id ?? '—'}</div>
                <div className="instance-muted">{inst.fault_type ?? 'unknown fault'}</div>
                <div>
                  {inst.anomalous_count} anomalous · {dispatched} dispatched
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="queue-table-wrap">
      <table className="leaderboard-table queue-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Service</th>
            <th>Tier</th>
            <th>Anomaly</th>
            <th>Priority</th>
            <th>PPO</th>
          </tr>
        </thead>
        <tbody>
          {data.queue.map(row => (
            <tr key={`${row.instance_id}:${row.service_id}`} className={row.dispatch_step === 1 ? 'queue-top' : ''}>
              <td className="mono">{row.rank}</td>
              <td className="mono">
                {row.service_id}
                {showInstance && <div className="queue-instance">{row.instance_id}</div>}
              </td>
              <td>
                <span className={`status-pill tier-${row.impact_tier}`} title={`impact weight ×${row.impact_weight}`}>
                  {row.impact_tier} ×{row.impact_weight}
                </span>
              </td>
              <td className="mono">
                {row.anomaly_score.toFixed(2)}
              </td>
              <td>
                <div className="priority-cell">
                  <div className="priority-bar">
                    <div className="priority-fill" style={{ width: `${(row.priority_score / maxPriority) * 100}%` }} />
                  </div>
                  <span className="mono">{row.priority_score.toFixed(2)}</span>
                </div>
              </td>
              <td className="mono">
                {row.dispatch_step ? `#${row.dispatch_step} ${row.agent_type}` : <span className="instance-muted">—</span>}
              </td>
            </tr>
          ))}
          {data.queue.length === 0 && (
            <tr>
              <td colSpan={6} className="eval-pending">No anomalous nodes queued.</td>
            </tr>
          )}
        </tbody>
      </table>
      </div>

      {data.generated_at && (
        <div className="queue-footnote mono">generated {new Date(data.generated_at).toLocaleString()}</div>
      )}
    </div>
  )
}

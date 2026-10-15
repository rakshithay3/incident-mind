// The signature element: a control-room status beacon.
// This is the thing someone watching the live demo glances at first —
// bigger and louder than any individual metric, because "is something
// happening right now" is the first question a live audience asks.

const STATE_COPY = {
  none: { label: 'No active incident', cls: 'beacon-none' },
  scheduled: { label: 'Fault scheduled', cls: 'beacon-scheduled' },
  active: { label: 'Fault active', cls: 'beacon-active' },
  resolved: { label: 'Resolved', cls: 'beacon-resolved' }
}

// simulated: recovery_sim scenario name when the recovery was scripted, not
// observed on live telemetry -- shown as a separate badge so nobody mistakes
// it for a real fix.
export default function FaultBeacon({ state = 'none', simulated = null }) {
  const copy = STATE_COPY[state] ?? STATE_COPY.none
  const label = simulated && state === 'resolved' ? 'Resolved (simulated)' : copy.label

  return (
    <>
      {simulated && (
        <span className="sim-badge" title="Scripted recovery scenario (--simulate-recovery), not live telemetry">
          Simulated: {simulated.replace('_', ' ')}
        </span>
      )}
      <div className={`fault-beacon ${copy.cls}`} role="status">
        <span className="beacon-dot" />
        <span className="beacon-label">{label}</span>
      </div>
    </>
  )
}

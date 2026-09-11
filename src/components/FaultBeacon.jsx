// The signature element: a control-room status beacon.
// This is the thing someone watching the live demo glances at first —
// bigger and louder than any individual metric, because "is something
// happening right now" is the first question a live audience asks.

const STATE_COPY = {
  none: { label: 'No active incident', dot: 'dot-none' },
  scheduled: { label: 'Fault scheduled', dot: 'dot-scheduled' },
  active: { label: 'Fault active', dot: 'dot-active' },
  resolved: { label: 'Resolved', dot: 'dot-resolved' }
}

export default function FaultBeacon({ state = 'none' }) {
  const copy = STATE_COPY[state] ?? STATE_COPY.none

  return (
    <div className="fault-beacon">
      <span className={`beacon-dot ${copy.dot}`} />
      <span className="beacon-label">{copy.label}</span>
    </div>
  )
}

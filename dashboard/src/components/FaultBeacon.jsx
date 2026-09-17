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

export default function FaultBeacon({ state = 'none' }) {
  const copy = STATE_COPY[state] ?? STATE_COPY.none

  return (
    <div className={`fault-beacon ${copy.cls}`} role="status">
      <span className="beacon-dot" />
      <span className="beacon-label">{copy.label}</span>
    </div>
  )
}

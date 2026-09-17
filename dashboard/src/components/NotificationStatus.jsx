import { latestNotification } from '../data/transformDemoResult'

// Email hook status from notifications/notifier.py.
//   sent     -- email delivered to SMTP
//   dry_run  -- no SMTP creds on the pipeline machine; saved as .eml instead
//   failed   -- SMTP error (pipeline kept running)
//   skipped  -- below priority threshold, duplicate, or notifications off

export const NOTIFY_STATUS = {
  sent: { label: 'sent', className: 'notify-sent' },
  dry_run: { label: 'dry run', className: 'notify-dry' },
  failed: { label: 'failed', className: 'notify-failed' },
  skipped: { label: 'not sent', className: 'notify-skipped' }
}

const EVENTS = [
  { id: 'dispatch_threshold', label: 'Dispatch alert' },
  { id: 'report_complete', label: 'RCA report email' }
]

export function NotifyPill({ status, title }) {
  if (!status) {
    return <span className="status-pill notify-none" title={title}>—</span>
  }
  const s = NOTIFY_STATUS[status] ?? { label: status, className: 'notify-skipped' }
  return (
    <span className={`status-pill ${s.className}`} title={title}>
      {s.label}
    </span>
  )
}

export default function NotificationStatus({ notifications }) {
  const hasAny = notifications?.length > 0

  return (
    <div className="notify-block">
      <span className="rca-section-label">Notifications</span>
      {!hasAny && (
        <div className="notify-empty">
          No notification data for this run (run predates the email hooks, or --no-notify).
        </div>
      )}
      {hasAny && (
        <ul className="notify-list">
          {EVENTS.map(ev => {
            const n = latestNotification(notifications, ev.id)
            const when = n?.timestamp ? new Date(n.timestamp).toLocaleTimeString() : null
            return (
              <li key={ev.id} className="notify-row">
                <span className="notify-event">{ev.label}</span>
                <NotifyPill status={n?.status} title={n?.reason ?? n?.subject ?? ''} />
                <span className="notify-meta mono">
                  {!n && 'not triggered'}
                  {n && n.status === 'sent' && `${n.recipients?.length ?? 1} recipient(s) · ${when}`}
                  {n && n.status !== 'sent' && (n.reason ?? when)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

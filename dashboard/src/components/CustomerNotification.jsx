import { ClockIcon, MailIcon } from './Icons'
import { restoredNotification } from '../data/transformDemoResult'

// Status of the "ShopMind is back to normal" email to registered ShopMind
// users (notifications/notifier.py). It only goes out after live telemetry
// confirms recovery (notifications/recovery.py).

export const NOTIFY_STATUS = {
  sent: { label: 'Sent', cls: 'sent', title: 'ShopMind users notified' },
  partial: { label: 'Partly sent', cls: 'partial', title: 'Some users notified' },
  dry_run: { label: 'Dry run', cls: 'dry', title: 'Email drafted, not sent' },
  failed: { label: 'Failed', cls: 'failed', title: 'Email could not be sent' },
  skipped: { label: 'Not sent', cls: 'skipped', title: 'Users not emailed' }
}

function fmtTime(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function fmtDuration(sec) {
  if (sec == null) return null
  if (sec < 60) return `${sec}s`
  const m = Math.round(sec / 60)
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`
}

export function notifySummary(incident) {
  const n = restoredNotification(incident)
  if (!n) return { label: 'No email data', cls: 'none', sub: 'run predates user emails or --no-notify' }
  const s = NOTIFY_STATUS[n.status] ?? NOTIFY_STATUS.skipped
  let sub = n.reason ?? ''
  if (n.status === 'sent' || n.status === 'partial') sub = `${n.sent_count} of ${n.recipients_count} users`
  if (n.status === 'dry_run') sub = `${n.recipients_count} drafted (no SMTP login)`
  return { label: s.label, cls: s.cls, sub }
}

export default function CustomerNotification({ incident }) {
  const n = restoredNotification(incident)
  const recovery = incident.recovery

  if (!n) {
    return (
      <div className="notice-card">
        <div className="notice-icon"><MailIcon /></div>
        <div>
          <div className="notice-head">
            <span className="notice-title">Customer email</span>
            <span className="status-pill notify-none">No data</span>
          </div>
          <div className="notice-body">
            This run has no user notification info (made before the recovery email existed, or run with --no-notify).
          </div>
        </div>
      </div>
    )
  }

  const s = NOTIFY_STATUS[n.status] ?? NOTIFY_STATUS.skipped
  const d = n.details ?? {}
  const restored = fmtTime(d.restored_at ?? recovery?.restored_at)
  const downtime = d.downtime_sec != null && d.downtime_sec <= 6 * 3600 ? fmtDuration(d.downtime_sec) : null

  let body
  if (n.status === 'sent') body = `Told ${n.sent_count} ShopMind user${n.sent_count === 1 ? '' : 's'} that ${d.affected_area ?? 'the site'} is working again.`
  else if (n.status === 'partial') body = `${n.sent_count} of ${n.recipients_count} emails went out. ${n.reason ?? ''}`
  else if (n.status === 'dry_run') body = `${n.recipients_count} email${n.recipients_count === 1 ? '' : 's'} drafted to output/notifications/ (no SMTP login set).`
  else body = n.reason ?? 'Users were not emailed.'

  return (
    <div className={`notice-card notice-${s.cls}`}>
      <div className="notice-icon">{n.status === 'skipped' && !recovery?.recovered ? <ClockIcon /> : <MailIcon />}</div>
      <div>
        <div className="notice-head">
          <span className="notice-title">{s.title}</span>
          <span className={`status-pill notify-${s.cls}`}>{s.label}</span>
        </div>
        <div className="notice-body">{body}</div>
        <div className="notice-meta">
          {restored && <span>Back to normal <strong>{restored}</strong></span>}
          {downtime && <span>Disruption <strong>{downtime}</strong></span>}
          {recovery?.polls != null && <span>Health checks <strong>{recovery.polls}</strong></span>}
          {d.recipients_source && <span>Users from <strong>{d.recipients_source}</strong></span>}
        </div>
      </div>
    </div>
  )
}

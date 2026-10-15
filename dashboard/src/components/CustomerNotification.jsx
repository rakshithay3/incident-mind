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

// recovery.outcome for a failed recovery (notifications/recovery.py)
export const RECOVERY_OUTCOME = {
  not_recovered: 'Not recovered',
  partial: 'Partly recovered',
  relapsed: 'Recovered, then relapsed'
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

export function roundOutcome(recovery) {
  if (!recovery) return 'unknown'
  return recovery.recovered ? 'recovered' : (recovery.outcome ?? 'not_recovered')
}

// "41 (37 + 4)" across re-investigation rounds; just the count for one round.
export function healthChecks(incident) {
  const rounds = incident.rounds ?? []
  if (rounds.length < 2) return incident.recovery?.polls ?? null
  const polls = rounds.map(r => r.recovery?.polls ?? 0)
  return `${polls.reduce((a, b) => a + b, 0)} (${polls.join(' + ')})`
}

// Why an email was drafted but not sent (notifier.py reason).
function dryRunReason(n) {
  return n.reason === 'SMTP credentials not set' ? 'no SMTP login set' : (n.reason ?? 'not sent')
}

// Re-investigation rounds: round 1 -> auth-service -> relapsed, ...
function RecoveryRounds({ rounds }) {
  if (!rounds || rounds.length < 2) return null
  return (
    <ol className="notice-rounds">
      {rounds.map(r => {
        const out = roundOutcome(r.recovery)
        return (
          <li key={r.round}>
            <span className="round-no">Round {r.round}</span>
            <span className="round-arrow">→</span>
            <strong>{r.target_service}</strong>
            <span className="round-arrow">→</span>
            <span className={`round-outcome ${out === 'recovered' ? 'ok' : 'bad'}`}>{out.replace('_', ' ')}</span>
          </li>
        )
      })}
    </ol>
  )
}

export function notifySummary(incident) {
  const n = restoredNotification(incident)
  if (!n) return { label: 'No email data', cls: 'none', sub: 'run predates user emails or --no-notify' }
  const s = NOTIFY_STATUS[n.status] ?? NOTIFY_STATUS.skipped
  let sub = n.reason ?? ''
  if (n.status === 'sent' || n.status === 'partial') sub = `${n.sent_count} of ${n.recipients_count} users`
  if (n.status === 'dry_run') sub = `${n.recipients_count} drafted (${dryRunReason(n)})`
  return { label: s.label, cls: s.cls, sub }
}

export default function CustomerNotification({ incident, isAdmin = false }) {
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
  const outcome = recovery && !recovery.recovered ? RECOVERY_OUTCOME[recovery.outcome] : null
  const checks = healthChecks(incident)
  const downtime = d.downtime_sec != null && d.downtime_sec <= 6 * 3600 ? fmtDuration(d.downtime_sec) : null

  let body
  if (n.status === 'sent') body = `Told ${n.sent_count} ShopMind user${n.sent_count === 1 ? '' : 's'} that ${d.affected_area ?? 'the site'} is working again.`
  else if (n.status === 'partial') body = `${n.sent_count} of ${n.recipients_count} emails went out. ${n.reason ?? ''}`
  else if (n.status === 'dry_run') body = `${n.recipients_count} email${n.recipients_count === 1 ? '' : 's'} drafted to output/notifications/ (${dryRunReason(n)}).`
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
        <RecoveryRounds rounds={incident.rounds} />
        <div className="notice-meta">
          {restored && <span>Back to normal <strong>{restored}</strong></span>}
          {outcome && <span>Outcome <strong>{outcome}</strong></span>}
          {downtime && <span>Disruption <strong>{downtime}</strong></span>}
          {checks != null && <span>Health checks <strong>{checks}</strong></span>}
          {incident.rounds?.length > 1 && <span>Rounds <strong>{incident.rounds.length}</strong></span>}
          {d.recipients_source && <span>Users from <strong>{d.recipients_source}</strong></span>}
          {isAdmin && recovery?.simulated && <span className="status-pill notify-skipped" title={`Scripted recovery scenario: ${recovery.simulated}`}>Simulated</span>}
        </div>
      </div>
    </div>
  )
}

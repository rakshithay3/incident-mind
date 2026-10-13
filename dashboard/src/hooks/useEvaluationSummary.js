import { useEffect, useState } from 'react'

// Loads the real evaluation run committed by Dharunya (evaluation/results/
// summary.json, 100 ShopMind incidents, single condition: IncidentMind).

export function useEvaluationSummary() {
  const [summary, setSummary] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    let cancelled = false

    fetch('/evaluationSummary.json', { cache: 'no-store' })
      .then(res => {
        if (!res.ok) throw new Error(`No evaluation summary yet (${res.status})`)
        return res.json()
      })
      .then(raw => {
        if (cancelled) return
        setSummary(raw)
        setStatus('ready')
      })
      .catch(() => {
        if (cancelled) return
        setStatus('missing')
      })

    return () => {
      cancelled = true
    }
  }, [])

  return { summary, status }
}

import { useEffect, useState } from 'react'

// Loads the real evaluation run committed by Dharunya (evaluation/results/
// summary.json, 100 ShopMind incidents, single condition: IncidentMind).
// There is currently no Baseline A/B/C data anywhere in the repo -- those
// conditions render as "not yet run" rather than invented numbers. Once
// baseline runs exist, drop their summary.json files alongside this one and
// list them in BASELINE_FILES below; no component change needed.
const BASELINE_FILES = []

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

  return { summary, status, baselineFiles: BASELINE_FILES }
}

import { useEffect, useState } from 'react'
import { transformMultiInstanceResult } from '../data/transformDemoResult'

// Polls /multiInstanceResult.json (copy of cross_instance_dispatch_demo.py
// --output) on the same interval as the incident feed. Returns null until a
// multi-instance run has been dropped into public/, in which case the
// Priority Queue tab derives a single-instance queue from the loaded
// incident instead.

export function useMultiInstanceData(refreshMs) {
  const [data, setData] = useState(null)

  useEffect(() => {
    let cancelled = false

    const fetchOnce = () =>
      fetch('/multiInstanceResult.json', { cache: 'no-store' })
        .then(res => {
          if (!res.ok) throw new Error(`No multi-instance result (${res.status})`)
          return res.json()
        })
        .then(raw => {
          if (!cancelled) setData(transformMultiInstanceResult(raw))
        })
        .catch(() => {
          if (!cancelled) setData(null)
        })

    fetchOnce()
    const interval = setInterval(fetchOnce, refreshMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [refreshMs])

  return data
}

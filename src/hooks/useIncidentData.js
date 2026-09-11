import { useCallback, useEffect, useRef, useState } from 'react'
import { mockIncident } from '../data/mockIncident'
import { transformDemoResult } from '../data/transformDemoResult'

// Loads the live incident result at runtime from /demoResult.json (served
// from the `public/` folder), polling on an interval so the dashboard stays
// current without a manual reload -- required once ShopMind is a live public
// site rather than a one-shot local run.
//
// Two refresh modes, matching the roadmap's Weeks 3-5 item:
//  - default: 5-minute interval, safe for normal/background monitoring.
//  - live demo mode: 2-second interval, for when someone is actually
//    watching a fault get injected in front of an audience and 5 minutes of
//    staleness would look broken.
//
// TO GO LIVE: after running
//   PYTHONPATH=. python3 live_demo.py --fault cpu_stress --output demo_result.json
// copy the resulting demo_result.json into public/demoResult.json. No code
// change needed -- this hook picks it up on the next poll.

const DEFAULT_REFRESH_MS = 5 * 60 * 1000
const LIVE_DEMO_REFRESH_MS = 2 * 1000

export function useIncidentData() {
  const [incident, setIncident] = useState(mockIncident)
  const [isLive, setIsLive] = useState(false)
  const [error, setError] = useState(null)
  const [liveDemoMode, setLiveDemoMode] = useState(false)
  const [refreshMs, setRefreshMs] = useState(DEFAULT_REFRESH_MS)

  const fetchOnce = useCallback((cancelledRef) => {
    fetch('/demoResult.json', { cache: 'no-store' })
      .then(res => {
        if (!res.ok) throw new Error(`No live result yet (${res.status})`)
        return res.json()
      })
      .then(raw => {
        if (cancelledRef.current) return
        setIncident(transformDemoResult(raw))
        setIsLive(true)
        setError(null)
      })
      .catch(err => {
        if (cancelledRef.current) return
        // Expected until the first real demo run is dropped in -- stay on
        // mock data rather than surfacing this as a dashboard error.
        setError(err.message)
        setIsLive(false)
      })
  }, [])

  useEffect(() => {
    const cancelledRef = { current: false }
    fetchOnce(cancelledRef)
    const interval = setInterval(() => fetchOnce(cancelledRef), refreshMs)
    return () => {
      cancelledRef.current = true
      clearInterval(interval)
    }
  }, [fetchOnce, refreshMs])

  const setLiveDemo = useCallback((on) => {
    setLiveDemoMode(on)
    setRefreshMs(on ? LIVE_DEMO_REFRESH_MS : DEFAULT_REFRESH_MS)
  }, [])

  return {
    incident,
    isLive,
    error,
    liveDemoMode,
    setLiveDemo,
    refreshMs,
    setRefreshMs
  }
}

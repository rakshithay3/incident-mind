import { useCallback, useEffect, useState } from 'react'
import ServiceGraph from './components/ServiceGraph'
import NodeListPanel from './components/NodeListPanel'
import FaultBeacon from './components/FaultBeacon'
import SummaryStrip from './components/SummaryStrip'
import TabNav from './components/TabNav'
import { MoonIcon, PulseIcon, SunIcon } from './components/Icons'
import AlertFeedTab from './components/tabs/AlertFeedTab'
import AnomalyTimelineTab from './components/tabs/AnomalyTimelineTab'
import RCAPanelTab from './components/tabs/RCAPanelTab'
import RemediationLogTab from './components/tabs/RemediationLogTab'
import EvaluationTab from './components/tabs/EvaluationTab'
import PriorityQueueTab from './components/tabs/PriorityQueueTab'
import { useIncidentData } from './hooks/useIncidentData'
import { useMultiInstanceData } from './hooks/useMultiInstanceData'

const TAB_COMPONENTS = {
  alerts: AlertFeedTab,
  queue: PriorityQueueTab,
  timeline: AnomalyTimelineTab,
  rca: RCAPanelTab,
  remediation: RemediationLogTab,
  evaluation: EvaluationTab
}

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('im-theme') || 'light'
    } catch {
      return 'light'
    }
  })
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('im-theme', theme)
    } catch {
      /* storage unavailable -- theme just won't persist */
    }
  }, [theme])
  const toggle = useCallback(() => setTheme(t => (t === 'dark' ? 'light' : 'dark')), [])
  return [theme, toggle]
}

export default function App() {
  const [activeTab, setActiveTab] = useState('alerts')
  const [theme, toggleTheme] = useTheme()
  const { incident, isLive, liveDemoMode, setLiveDemo, refreshMs } = useIncidentData()
  const multiInstance = useMultiInstanceData(refreshMs)
  const ActiveTabComponent = TAB_COMPONENTS[activeTab]
  const anomalous = incident.nodes.filter(n => n.status === 'anomalous').length

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark"><PulseIcon /></div>
          <div className="app-title">
            <span className="app-title-main">IncidentMind</span>
            <span className="app-title-sub">ShopMind operations console</span>
          </div>
        </div>
        <div className="header-controls">
          <span className={`source-pill ${isLive ? 'source-live' : ''}`}>
            <span className="source-dot" />
            {isLive ? 'Live result' : 'Mock data'} · every {liveDemoMode ? '2s' : '5 min'}
          </span>
          <label className="switch">
            <input type="checkbox" checked={liveDemoMode} onChange={e => setLiveDemo(e.target.checked)} />
            <span className="switch-track" />
            <span className="switch-text">Live demo</span>
          </label>
          <button
            className="icon-btn"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
          >
            {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>
          <FaultBeacon state={incident.fault_injection_state} />
        </div>
      </header>

      <SummaryStrip incident={incident} />

      <main className="app-main">
        <section className="graph-section">
          <div className="panel">
            <div className="panel-header">
              <h2>Service dependency graph</h2>
              <span className="panel-subtitle">
                {incident.nodes.length} services · {anomalous} anomalous
              </span>
            </div>
            <ServiceGraph nodes={incident.nodes} edges={incident.edges} />
          </div>
          <NodeListPanel nodes={incident.nodes} />
        </section>

        <section className="tabs-section">
          <div className="tabs-card">
            <TabNav activeTab={activeTab} onChange={setActiveTab} />
            <ActiveTabComponent incident={incident} multiInstance={multiInstance} />
          </div>
        </section>
      </main>
    </div>
  )
}

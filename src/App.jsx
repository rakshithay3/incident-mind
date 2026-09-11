import { useState } from 'react'
import ServiceGraph from './components/ServiceGraph'
import NodeListPanel from './components/NodeListPanel'
import FaultBeacon from './components/FaultBeacon'
import TabNav from './components/TabNav'
import AlertFeedTab from './components/tabs/AlertFeedTab'
import AnomalyTimelineTab from './components/tabs/AnomalyTimelineTab'
import RCAPanelTab from './components/tabs/RCAPanelTab'
import RemediationLogTab from './components/tabs/RemediationLogTab'
import EvaluationTab from './components/tabs/EvaluationTab'
import { useIncidentData } from './hooks/useIncidentData'

const TAB_COMPONENTS = {
  alerts: AlertFeedTab,
  timeline: AnomalyTimelineTab,
  rca: RCAPanelTab,
  remediation: RemediationLogTab,
  evaluation: EvaluationTab
}

export default function App() {
  const [activeTab, setActiveTab] = useState('alerts')
  const { incident, isLive, liveDemoMode, setLiveDemo } = useIncidentData()
  const ActiveTabComponent = TAB_COMPONENTS[activeTab]

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">
          <span className="app-title-main">IncidentMind</span>
          <span className="app-title-sub">
            ShopMind console · {isLive ? 'live result' : 'mock data'} ·{' '}
            refresh {liveDemoMode ? 'every 2s (live demo)' : 'every 5 min'}
          </span>
        </div>
        <div className="header-controls">
          <label className="live-demo-toggle mono">
            <input
              type="checkbox"
              checked={liveDemoMode}
              onChange={e => setLiveDemo(e.target.checked)}
            />
            Live demo mode
          </label>
          <FaultBeacon state={incident.fault_injection_state} />
        </div>
      </header>

      <main className="app-main">
        <section className="graph-section">
          <div className="panel">
            <div className="panel-header">
              <h2>Service Dependency Graph</h2>
              <span className="panel-subtitle">
                {incident.nodes.length} nodes · {isLive ? incident.fault_type : 'mock topology'}
              </span>
            </div>
            <ServiceGraph nodes={incident.nodes} edges={incident.edges} />
          </div>
          <NodeListPanel nodes={incident.nodes} />
        </section>

        <section className="tabs-section">
          <TabNav activeTab={activeTab} onChange={setActiveTab} />
          <ActiveTabComponent incident={incident} />
        </section>
      </main>
    </div>
  )
}

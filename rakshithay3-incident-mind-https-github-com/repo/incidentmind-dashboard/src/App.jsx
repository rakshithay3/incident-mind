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
import { mockIncident } from './data/mockIncident'

const TAB_COMPONENTS = {
  alerts: AlertFeedTab,
  timeline: AnomalyTimelineTab,
  rca: RCAPanelTab,
  remediation: RemediationLogTab,
  evaluation: EvaluationTab
}

export default function App() {
  const [activeTab, setActiveTab] = useState('alerts')
  const ActiveTabComponent = TAB_COMPONENTS[activeTab]

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">
          <span className="app-title-main">IncidentMind</span>
          <span className="app-title-sub">ShopMind console · p3/dashboard</span>
        </div>
        <FaultBeacon state={mockIncident.fault_injection_state} />
      </header>

      <main className="app-main">
        <section className="graph-section">
          <div className="panel">
            <div className="panel-header">
              <h2>Service Dependency Graph</h2>
              <span className="panel-subtitle">12 nodes · hardcoded topology</span>
            </div>
            <ServiceGraph nodes={mockIncident.nodes} edges={mockIncident.edges} />
          </div>
          <NodeListPanel nodes={mockIncident.nodes} />
        </section>

        <section className="tabs-section">
          <TabNav activeTab={activeTab} onChange={setActiveTab} />
          <ActiveTabComponent />
        </section>
      </main>
    </div>
  )
}

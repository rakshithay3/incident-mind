// adminOnly tabs are hidden from the user role (the evaluation tab breaks
// results down by injected fault type and shows the benchmark runs).
export const TABS = [
  { id: 'alerts', label: 'Alerts' },
  { id: 'queue', label: 'Priority queue' },
  { id: 'timeline', label: 'Anomalies' },
  { id: 'rca', label: 'RCA' },
  { id: 'remediation', label: 'Agents' },
  { id: 'evaluation', label: 'Evaluation', adminOnly: true },
  { id: 'inject', label: 'Fault injection', adminOnly: true }
]

export default function TabNav({ activeTab, onChange, isAdmin = false }) {
  const visible = TABS.filter(tab => isAdmin || !tab.adminOnly)
  return (
    <nav className="tab-nav" role="tablist">
      {visible.map(tab => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`tab-button ${activeTab === tab.id ? 'tab-active' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}

export const TABS = [
  { id: 'alerts', label: 'Alerts' },
  { id: 'queue', label: 'Priority queue' },
  { id: 'timeline', label: 'Anomalies' },
  { id: 'rca', label: 'RCA' },
  { id: 'remediation', label: 'Agents' },
  { id: 'evaluation', label: 'Evaluation' }
]

export default function TabNav({ activeTab, onChange }) {
  return (
    <nav className="tab-nav" role="tablist">
      {TABS.map(tab => (
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

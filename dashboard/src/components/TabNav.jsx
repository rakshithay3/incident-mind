export const TABS = [
  { id: 'alerts', label: 'Alert Feed' },
  { id: 'timeline', label: 'Anomaly Timeline' },
  { id: 'rca', label: 'RCA Panel' },
  { id: 'remediation', label: 'Remediation Log' },
  { id: 'evaluation', label: 'Evaluation' }
]

export default function TabNav({ activeTab, onChange }) {
  return (
    <nav className="tab-nav">
      {TABS.map(tab => (
        <button
          key={tab.id}
          className={`tab-button ${activeTab === tab.id ? 'tab-active' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}

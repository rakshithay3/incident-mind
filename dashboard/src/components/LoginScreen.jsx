import { useState } from 'react'
import { authenticate } from '../data/auth'
import { PulseIcon } from './Icons'

// One login page, two roles. The role switch decides which account the
// credentials are checked against, so a user login can never open the admin
// console and vice versa.

const ROLES = [
  { id: 'user', label: 'User', hint: 'Monitor service health, alerts and root-cause reports.' },
  { id: 'admin', label: 'Admin', hint: 'Full console, including fault injection and evaluation.' }
]

export default function LoginScreen({ onLogin }) {
  const [role, setRole] = useState('user')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const submit = e => {
    e.preventDefault()
    const session = authenticate(role, username, password)
    if (!session) {
      setError(`Incorrect ${role} username or password.`)
      return
    }
    setError('')
    onLogin(session)
  }

  const pickRole = id => {
    setRole(id)
    setError('')
  }

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <div className="brand login-brand">
          <div className="brand-mark"><PulseIcon /></div>
          <div className="app-title">
            <span className="app-title-main">IncidentMind</span>
            <span className="app-title-sub">ShopMind operations console</span>
          </div>
        </div>

        <div className="role-switch" role="tablist" aria-label="Sign in as">
          {ROLES.map(r => (
            <button
              key={r.id}
              type="button"
              role="tab"
              aria-selected={role === r.id}
              className={`role-option ${role === r.id ? 'role-active' : ''}`}
              onClick={() => pickRole(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <p className="login-hint">{ROLES.find(r => r.id === role).hint}</p>

        <label className="field">
          <span className="field-label">Username</span>
          <input
            className="field-input"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>
        <label className="field">
          <span className="field-label">Password</span>
          <input
            className="field-input"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <div className="login-error" role="alert">{error}</div>}

        <button className="login-submit" type="submit">
          Sign in as {role === 'admin' ? 'admin' : 'user'}
        </button>
      </form>
    </div>
  )
}

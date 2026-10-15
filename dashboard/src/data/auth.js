// Front-end-only role login for the ShopMind operations console.
//
// IMPORTANT: this is a demo gate, not real security. The accounts below ship
// inside the JavaScript bundle, so anyone who opens dev tools can read them.
// It keeps the user view and the admin view separate for the demo; before a
// public deployment, move the check to the backend (FastAPI/Express) and have
// it return a signed token instead.
//
// Override the defaults at build time with a dashboard/.env file:
//   VITE_USER_NAME=...   VITE_USER_PASSWORD=...
//   VITE_ADMIN_NAME=...  VITE_ADMIN_PASSWORD=...

const env = import.meta.env ?? {}

export const ACCOUNTS = {
  user: {
    role: 'user',
    username: env.VITE_USER_NAME || 'user',
    password: env.VITE_USER_PASSWORD || 'user123',
    display: 'Operator'
  },
  admin: {
    role: 'admin',
    username: env.VITE_ADMIN_NAME || 'admin',
    password: env.VITE_ADMIN_PASSWORD || 'admin123',
    display: 'Administrator'
  }
}

const SESSION_KEY = 'im-session'

// Returns the session ({ role, username, display }) or null on bad credentials.
// The role chosen on the login form must match the account.
export function authenticate(role, username, password) {
  const acct = ACCOUNTS[role]
  if (!acct) return null
  if (username.trim() !== acct.username || password !== acct.password) return null
  return { role: acct.role, username: acct.username, display: acct.display }
}

export function loadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    return s && (s.role === 'user' || s.role === 'admin') ? s : null
  } catch {
    return null
  }
}

export function saveSession(session) {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    /* storage unavailable -- session just won't survive a reload */
  }
}

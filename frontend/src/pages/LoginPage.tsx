import { FormEvent, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  bootstrapAdmin,
  getAuthBootstrapNeeded,
  loginWithPassword,
  setAuthRole,
  setAuthToken,
} from '../api/client'
import './login.css'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [bootstrapNeeded, setBootstrapNeeded] = useState<boolean>(false)
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    getAuthBootstrapNeeded()
      .then(resp => setBootstrapNeeded(!!resp.bootstrap_needed))
      .catch(() => setBootstrapNeeded(false))
      .finally(() => setLoading(false))
  }, [])

  const redirectPath = (location.state as any)?.from?.pathname || '/'

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const resp = await loginWithPassword(username, password)
      setAuthToken(resp.access_token)
      setAuthRole(resp.user.role)
      const nextPath = resp.user.role === 'photographer' ? '/photography' : redirectPath
      navigate(nextPath, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBootstrap = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setSubmitting(true)
    try {
      await bootstrapAdmin({ username, password, display_name: displayName || undefined })
      const resp = await loginWithPassword(username, password)
      setAuthToken(resp.access_token)
      setAuthRole(resp.user.role)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create admin account')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div className="staff-login">Loading authentication...</div>
  }

  return (
    <div className="staff-login">
      <form className="staff-login-card" onSubmit={bootstrapNeeded ? handleBootstrap : handleLogin}>
        <div className="staff-login-brand">
          <img src="/assets/rw-watermark-logo.png" alt="RacquetWar" />
        </div>
        <div className="staff-login-body">
          <h1>{bootstrapNeeded ? 'Create Admin Account' : 'Staff Login'}</h1>
          <p>
            {bootstrapNeeded
              ? 'Set up the first secure admin account for tournament management.'
              : 'Tournament directors and admins. Public draws and schedules stay open without a login.'}
          </p>

          {error && <div className="staff-login-error">{error}</div>}

          <label htmlFor="staff-username">Username</label>
          <input id="staff-username" value={username} onChange={e => setUsername(e.target.value)} required autoComplete="username" />

          {bootstrapNeeded && (
            <>
              <label htmlFor="staff-display-name">Display Name (optional)</label>
              <input id="staff-display-name" value={displayName} onChange={e => setDisplayName(e.target.value)} autoComplete="name" />
            </>
          )}

          <label htmlFor="staff-password">Password</label>
          <input id="staff-password" type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} autoComplete={bootstrapNeeded ? 'new-password' : 'current-password'} />

          {bootstrapNeeded && (
            <>
              <label htmlFor="staff-confirm-password">Confirm Password</label>
              <input id="staff-confirm-password" type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required minLength={8} autoComplete="new-password" />
            </>
          )}

          <button type="submit" disabled={submitting}>
            {submitting ? 'Please wait...' : bootstrapNeeded ? 'Create Admin Account' : 'Log In'}
          </button>
        </div>
      </form>
    </div>
  )
}


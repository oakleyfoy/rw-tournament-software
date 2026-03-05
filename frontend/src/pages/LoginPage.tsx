import { FormEvent, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  bootstrapAdmin,
  getAuthBootstrapNeeded,
  loginWithPassword,
  setAuthToken,
} from '../api/client'

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
      navigate(redirectPath, { replace: true })
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
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create admin account')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div style={{ padding: 40, textAlign: 'center' }}>Loading authentication...</div>
  }

  return (
    <div style={{ minHeight: '100vh', background: '#eef3f8', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <form
        onSubmit={bootstrapNeeded ? handleBootstrap : handleLogin}
        style={{
          width: 420,
          maxWidth: '94vw',
          background: '#fff',
          border: '1px solid #d8e1ee',
          borderRadius: 10,
          padding: 24,
          boxShadow: '0 6px 20px rgba(0,0,0,0.06)',
        }}
      >
        <h2 style={{ marginTop: 0, marginBottom: 8, color: '#12336b' }}>
          {bootstrapNeeded ? 'Create Admin Account' : 'Staff Login'}
        </h2>
        <div style={{ color: '#5f6f84', marginBottom: 16, fontSize: 13 }}>
          {bootstrapNeeded
            ? 'Set up the first secure admin account for tournament management.'
            : 'Tournament Directors/Admins only. Public users can use draws/schedule links.'}
        </div>

        {error && (
          <div style={{ background: '#ffebee', color: '#b71c1c', border: '1px solid #ffcdd2', borderRadius: 6, padding: 10, marginBottom: 12, fontSize: 13 }}>
            {error}
          </div>
        )}

        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Username</label>
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          required
          style={{ width: '100%', padding: '9px 10px', marginBottom: 12, borderRadius: 6, border: '1px solid #c9d6e8' }}
        />

        {bootstrapNeeded && (
          <>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Display Name (optional)</label>
            <input
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              style={{ width: '100%', padding: '9px 10px', marginBottom: 12, borderRadius: 6, border: '1px solid #c9d6e8' }}
            />
          </>
        )}

        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Password</label>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          minLength={8}
          style={{ width: '100%', padding: '9px 10px', marginBottom: 12, borderRadius: 6, border: '1px solid #c9d6e8' }}
        />

        {bootstrapNeeded && (
          <>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Confirm Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              style={{ width: '100%', padding: '9px 10px', marginBottom: 12, borderRadius: 6, border: '1px solid #c9d6e8' }}
            />
          </>
        )}

        <button
          type="submit"
          disabled={submitting}
          style={{
            width: '100%',
            marginTop: 4,
            border: 'none',
            borderRadius: 6,
            background: '#123d85',
            color: '#fff',
            padding: '10px 12px',
            fontWeight: 700,
            cursor: submitting ? 'default' : 'pointer',
            opacity: submitting ? 0.75 : 1,
          }}
        >
          {submitting ? 'Please wait...' : bootstrapNeeded ? 'Create Admin Account' : 'Log In'}
        </button>
      </form>
    </div>
  )
}


import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSettings, saveSettings, getTheme, themes, applyTheme } from '../utils/settings'
import {
  AuthUser,
  createAuthUser,
  getAuthMe,
  listAuthUsers,
  updateAuthUser,
} from '../api/client'
import './Settings.css'

function Settings() {
  const navigate = useNavigate()
  const [currentThemeId, setCurrentThemeId] = useState<string>('')
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [me, setMe] = useState<AuthUser | null>(null)
  const [users, setUsers] = useState<AuthUser[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [creatingUser, setCreatingUser] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newDisplayName, setNewDisplayName] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'director'>('director')

  useEffect(() => {
    const settings = getSettings()
    setCurrentThemeId(settings.theme)
    setSettingsLoaded(true)

    getAuthMe()
      .then((u) => setMe(u))
      .catch(() => setMe(null))
  }, [])

  const loadUsers = async () => {
    setUsersLoading(true)
    setUsersError(null)
    try {
      const list = await listAuthUsers()
      setUsers(list)
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setUsersLoading(false)
    }
  }

  useEffect(() => {
    if (settingsLoaded && currentThemeId) {
      const theme = getTheme(currentThemeId)
      if (theme) {
        applyTheme(theme)
      }
    }
  }, [currentThemeId, settingsLoaded])

  useEffect(() => {
    if (me?.role === 'admin') {
      loadUsers()
    }
  }, [me?.role])

  const handleThemeChange = (themeId: string) => {
    setCurrentThemeId(themeId)
    const newSettings = getSettings()
    newSettings.theme = themeId
    saveSettings(newSettings)
    
    const theme = getTheme(themeId)
    if (theme) {
      applyTheme(theme)
    }
  }

  const handleBack = () => {
    navigate('/tournaments')
  }

  const handleRestartServer = () => {
    // Show instructions since browsers can't execute files directly
    const instructions = 
      'To forcefully restart the backend server:\n\n' +
      '1. Open Windows Explorer\n' +
      '2. Navigate to: backend/restart_server.bat\n' +
      '3. Double-click the file to run it\n\n' +
      'This will:\n' +
      '• Forcefully kill ALL Python processes (python.exe, pythonw.exe)\n' +
      '• Forcefully kill ALL processes on port 8000\n' +
      '• Start a fresh backend server with debug logging\n\n' +
      'Path: backend/restart_server.bat\n\n' +
      'This ensures the server loads the latest code changes.'
    
    alert(instructions)
  }

  const handleCreateUser = async () => {
    if (!newUsername || !newPassword) {
      setUsersError('Username and password are required')
      return
    }
    setCreatingUser(true)
    setUsersError(null)
    try {
      await createAuthUser({
        username: newUsername,
        password: newPassword,
        display_name: newDisplayName || undefined,
        role: newRole,
      })
      setNewUsername('')
      setNewDisplayName('')
      setNewPassword('')
      setNewRole('director')
      await loadUsers()
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to create user')
    } finally {
      setCreatingUser(false)
    }
  }

  const handleToggleActive = async (user: AuthUser) => {
    setUsersError(null)
    try {
      await updateAuthUser(user.id, { is_active: !user.is_active })
      await loadUsers()
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to update user')
    }
  }

  if (!settingsLoaded) {
    return <div className="container"><div className="loading">Loading settings...</div></div>
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1>Settings</h1>
        <button className="btn btn-primary" onClick={handleBack}>
          Back to Tournaments
        </button>
      </div>

      <div className="card">
        <h2 className="section-title">Color Theme</h2>
        <div className="theme-selector">
          {themes.map((theme) => (
            <div
              key={theme.id}
              className={`theme-option ${currentThemeId === theme.id ? 'active' : ''}`}
              onClick={() => handleThemeChange(theme.id)}
            >
              <div className="theme-preview">
                <div 
                  className="theme-preview-color" 
                  style={{ backgroundColor: theme.colors.background }}
                >
                  <div 
                    className="theme-preview-card"
                    style={{ backgroundColor: theme.colors.cardBackground }}
                  >
                    <div 
                      className="theme-preview-button"
                      style={{ backgroundColor: theme.colors.primaryButton }}
                    />
                  </div>
                </div>
              </div>
              <div className="theme-name">{theme.name}</div>
              {currentThemeId === theme.id && (
                <div className="theme-checkmark">✓</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="card server-management">
        <h2 className="section-title">Server Management</h2>
        <div className="server-management-content">
          <p className="server-management-description">
            Restart the backend server to apply code changes or fix connection issues.
            This will stop all Python processes, clear port 8000, and start a fresh server.
          </p>
          <button 
            className="btn btn-secondary server-restart-btn" 
            onClick={handleRestartServer}
          >
            Open Restart Script
          </button>
          <p className="server-management-note">
            Note: The script file is located at <code>backend/restart_server.bat</code>.
            You can also double-click it directly in Windows Explorer.
          </p>
        </div>
      </div>

      {me?.role === 'admin' && (
        <div className="card">
          <h2 className="section-title">Admin Users</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
            <input
              placeholder="Username"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid #c9d6e8' }}
            />
            <input
              placeholder="Display name (optional)"
              value={newDisplayName}
              onChange={(e) => setNewDisplayName(e.target.value)}
              style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid #c9d6e8' }}
            />
            <input
              placeholder="Password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid #c9d6e8' }}
            />
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as 'admin' | 'director')}
              style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid #c9d6e8' }}
            >
              <option value="director">Director</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div style={{ marginBottom: 10 }}>
            <button className="btn btn-primary" onClick={handleCreateUser} disabled={creatingUser}>
              {creatingUser ? 'Creating...' : 'Create User'}
            </button>
          </div>
          {usersError && (
            <div style={{ background: '#ffebee', color: '#b71c1c', border: '1px solid #ffcdd2', borderRadius: 6, padding: 10, marginBottom: 10 }}>
              {usersError}
            </div>
          )}
          <div style={{ border: '1px solid #dfe6f2', borderRadius: 8, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#f4f7fb' }}>
                  <th style={{ textAlign: 'left', padding: 8 }}>Username</th>
                  <th style={{ textAlign: 'left', padding: 8 }}>Display Name</th>
                  <th style={{ textAlign: 'left', padding: 8 }}>Role</th>
                  <th style={{ textAlign: 'left', padding: 8 }}>Status</th>
                  <th style={{ textAlign: 'left', padding: 8 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {usersLoading ? (
                  <tr><td colSpan={5} style={{ padding: 12 }}>Loading users...</td></tr>
                ) : users.length === 0 ? (
                  <tr><td colSpan={5} style={{ padding: 12 }}>No users found.</td></tr>
                ) : users.map((u) => (
                  <tr key={u.id} style={{ borderTop: '1px solid #edf1f6' }}>
                    <td style={{ padding: 8 }}>{u.username}</td>
                    <td style={{ padding: 8 }}>{u.display_name || '—'}</td>
                    <td style={{ padding: 8, textTransform: 'capitalize' }}>{u.role}</td>
                    <td style={{ padding: 8, color: u.is_active ? '#2e7d32' : '#c62828' }}>
                      {u.is_active ? 'Active' : 'Disabled'}
                    </td>
                    <td style={{ padding: 8 }}>
                      <button className="btn btn-secondary" onClick={() => handleToggleActive(u)}>
                        {u.is_active ? 'Disable' : 'Enable'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export default Settings


import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSettings, saveSettings, getTheme, themes, Theme, applyTheme } from '../utils/settings'
import './Settings.css'

function Settings() {
  const navigate = useNavigate()
  const [currentThemeId, setCurrentThemeId] = useState<string>('')
  const [settingsLoaded, setSettingsLoaded] = useState(false)

  useEffect(() => {
    const settings = getSettings()
    setCurrentThemeId(settings.theme)
    setSettingsLoaded(true)
  }, [])

  useEffect(() => {
    if (settingsLoaded && currentThemeId) {
      const theme = getTheme(currentThemeId)
      if (theme) {
        applyTheme(theme)
      }
    }
  }, [currentThemeId, settingsLoaded])

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
    </div>
  )
}

export default Settings


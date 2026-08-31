import { ReactNode, useCallback, useEffect, useState } from 'react'
import './displayBoard.css'

export function DisplayLoadingState() {
  return (
    <div className="display-loading" data-testid="display-loading">
      <div className="display-loading-copy">Loading tournament display…</div>
      <div className="display-skeleton" aria-hidden>
        <div className="display-skeleton-card" />
        <div className="display-skeleton-card" />
        <div className="display-skeleton-card" />
      </div>
    </div>
  )
}

export function DisplayShell({
  tournamentName,
  title,
  subtitle,
  nowLocal,
  refreshing,
  error,
  hasData,
  onRefresh,
  children,
}: {
  tournamentName: string
  title: string
  subtitle?: string
  nowLocal?: string
  refreshing: boolean
  error: string | null
  hasData: boolean
  onRefresh: () => void
  children: ReactNode
}) {
  const [kiosk, setKiosk] = useState(false)

  const setFullscreen = useCallback((enabled: boolean) => {
    setKiosk(enabled)
    if (typeof document === 'undefined') return
    if (enabled) {
      void document.documentElement.requestFullscreen?.().catch(() => undefined)
    } else if (document.fullscreenElement) {
      void document.exitFullscreen?.().catch(() => undefined)
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && kiosk) setFullscreen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [kiosk, setFullscreen])

  return (
    <div className="display-root">
      <header className={kiosk ? 'display-header display-header-kiosk' : 'display-header'}>
        <div>
          <div className="display-kicker">{tournamentName}</div>
          <h1 className="display-title">{title}</h1>
          {subtitle ? <div className="display-subtitle">{subtitle}</div> : null}
        </div>
        <div className="display-actions">
          {nowLocal ? <div className="display-clock">{nowLocal}</div> : null}
          {refreshing ? <div className="display-status">Refreshing</div> : null}
          {error && hasData ? (
            <div className="display-status display-status-error" data-testid="display-connection-issue">
              Connection issue — retrying
            </div>
          ) : null}
          {!kiosk ? (
            <>
              <button type="button" className="display-btn" onClick={onRefresh} data-testid="display-refresh">
                Refresh
              </button>
              <button
                type="button"
                className="display-btn"
                onClick={() => setFullscreen(true)}
                data-testid="display-fullscreen"
              >
                Full Screen
              </button>
            </>
          ) : null}
        </div>
      </header>
      <main className={kiosk ? 'display-body display-body-kiosk' : 'display-body'}>{children}</main>
    </div>
  )
}

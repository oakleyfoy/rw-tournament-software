import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  getTournament,
  updateTournament,
  getPublicDrawsList,
  Tournament,
  PublicDrawsListResponse,
} from '../../api/client'

type PanelOption = {
  key: string
  label: string
  path: string
  kind: 'draw' | 'board'
}

type SharedScreenConfig = {
  panels: string[]
}

const DRAW_REFRESH_MS = 30_000
const PANEL_GAP_PX = 10

function parseConfig(raw: string | null | undefined): SharedScreenConfig | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || !Array.isArray(parsed.panels)) return null
    return {
      panels: parsed.panels.filter((v: unknown): v is string => typeof v === 'string').slice(0, 4),
    }
  } catch {
    return null
  }
}

function normalizePanels(panels: string[]): string[] {
  return [...panels.slice(0, 4), '', '', '', ''].slice(0, 4)
}

function EmptyPanel() {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#90a4ae',
      fontSize: 18,
      textAlign: 'center',
      padding: 20,
      boxSizing: 'border-box',
      backgroundColor: '#fff',
    }}>
      Panel not selected
    </div>
  )
}

function FitPanelFrame({
  title,
  src,
}: {
  title: string
  src: string
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [frameStyle, setFrameStyle] = useState({
    width: 1280,
    height: 720,
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  })

  const recomputeScale = useCallback(() => {
    const container = containerRef.current
    const iframe = iframeRef.current
    if (!container || !iframe) return

    let contentWidth = 1280
    let contentHeight = 720

    try {
      const doc = iframe.contentDocument
      if (doc) {
        const html = doc.documentElement
        const body = doc.body
        contentWidth = Math.max(
          html?.scrollWidth || 0,
          html?.offsetWidth || 0,
          body?.scrollWidth || 0,
          body?.offsetWidth || 0,
          1280
        )
        contentHeight = Math.max(
          html?.scrollHeight || 0,
          html?.offsetHeight || 0,
          body?.scrollHeight || 0,
          body?.offsetHeight || 0,
          720
        )
      }
    } catch {
      // Same-origin pages are expected, but keep a safe fallback size.
    }

    const containerWidth = Math.max(container.clientWidth, 1)
    const containerHeight = Math.max(container.clientHeight, 1)
    const scale = Math.min(containerWidth / contentWidth, containerHeight / contentHeight)
    const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1
    const scaledWidth = contentWidth * safeScale
    const scaledHeight = contentHeight * safeScale

    setFrameStyle({
      width: contentWidth,
      height: contentHeight,
      scale: safeScale,
      offsetX: Math.max((containerWidth - scaledWidth) / 2, 0),
      offsetY: Math.max((containerHeight - scaledHeight) / 2, 0),
    })
  }, [])

  useEffect(() => {
    recomputeScale()
    const observer = new ResizeObserver(() => recomputeScale())
    if (containerRef.current) observer.observe(containerRef.current)
    pollRef.current = setInterval(recomputeScale, 3000)
    return () => {
      observer.disconnect()
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [recomputeScale, src])

  return (
    <div
      ref={containerRef}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        backgroundColor: '#fff',
      }}
    >
      <iframe
        ref={iframeRef}
        title={title}
        src={src}
        onLoad={recomputeScale}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: frameStyle.width,
          height: frameStyle.height,
          border: 'none',
          backgroundColor: '#fff',
          transform: `translate(${frameStyle.offsetX}px, ${frameStyle.offsetY}px) scale(${frameStyle.scale})`,
          transformOrigin: 'top left',
        }}
      />
    </div>
  )
}

export default function TournamentDeskSharedScreenPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = Number(tournamentId)
  const initialKiosk =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('kiosk') === '1'

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [draws, setDraws] = useState<PublicDrawsListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedMessage, setSavedMessage] = useState<string>('')
  const [panelKeys, setPanelKeys] = useState<string[]>(['', '', '', ''])
  const [kioskMode, setKioskMode] = useState<boolean>(initialKiosk)
  const [drawRefreshTick, setDrawRefreshTick] = useState<number>(0)
  const [squareSize, setSquareSize] = useState<number>(320)
  const initializedRef = useRef(false)
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const gridHostRef = useRef<HTMLDivElement | null>(null)

  const setKiosk = useCallback((enabled: boolean) => {
    setKioskMode(enabled)
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    if (enabled) params.set('kiosk', '1')
    else params.delete('kiosk')
    const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`
    window.history.replaceState(null, '', next)
  }, [])

  useEffect(() => {
    if (!tid) return
    setLoading(true)
    setError(null)
    Promise.all([getTournament(tid), getPublicDrawsList(tid)])
      .then(([tournamentResp, drawsResp]) => {
        setTournament(tournamentResp)
        setDraws(drawsResp)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load shared screen settings'))
      .finally(() => setLoading(false))
  }, [tid])

  const panelOptions = useMemo<PanelOption[]>(() => {
    if (!tid) return []
    const options: PanelOption[] = [
      {
        key: 'court_management_board',
        label: 'Court Management Board View',
        path: `/desk/t/${tid}/board?kiosk=1`,
        kind: 'board',
      },
      {
        key: 'checkin_management_board',
        label: 'Check-In Display',
        path: `/desk/t/${tid}/checkin-board?kiosk=1`,
        kind: 'board',
      },
    ]

    if (!draws) return options

    draws.events.forEach((event) => {
      if (event.has_waterfall) {
        options.push({
          key: `waterfall:${event.event_id}`,
          label: `${event.name} Waterfall`,
          path: `/t/${tid}/draws/${event.event_id}/waterfall`,
          kind: 'draw',
        })
      }
      if (event.has_round_robin) {
        options.push({
          key: `roundrobin:${event.event_id}`,
          label: `${event.name} Round Robin`,
          path: `/t/${tid}/draws/${event.event_id}/roundrobin`,
          kind: 'draw',
        })
      }
      event.divisions.forEach((division) => {
        options.push({
          key: `bracket:${event.event_id}:${division.code}`,
          label: `${event.name} ${division.label}`,
          path: `/t/${tid}/draws/${event.event_id}/bracket/${division.code}`,
          kind: 'draw',
        })
      })
    })

    return options
  }, [draws, tid])

  const optionMap = useMemo(() => new Map(panelOptions.map((opt) => [opt.key, opt])), [panelOptions])

  useEffect(() => {
    if (!tournament || panelOptions.length === 0 || initializedRef.current) return
    const saved = parseConfig(tournament.shared_screen_config_json)
    if (saved && saved.panels.length > 0) {
      setPanelKeys(normalizePanels(saved.panels.map((key) => (optionMap.has(key) ? key : '')).filter(Boolean)))
    } else {
      setPanelKeys(normalizePanels(panelOptions.slice(0, 4).map((opt) => opt.key)))
    }
    initializedRef.current = true
  }, [tournament, panelOptions, optionMap])

  const selectedPanels = useMemo(
    () => panelKeys.map((key) => optionMap.get(key) || null),
    [panelKeys, optionMap]
  )

  useEffect(() => {
    const hasDrawPanels = selectedPanels.some((panel) => panel?.kind === 'draw')
    if (!hasDrawPanels) {
      if (refreshRef.current) clearInterval(refreshRef.current)
      refreshRef.current = null
      return
    }
    refreshRef.current = setInterval(() => {
      setDrawRefreshTick((tick) => tick + 1)
    }, DRAW_REFRESH_MS)
    return () => {
      if (refreshRef.current) clearInterval(refreshRef.current)
      refreshRef.current = null
    }
  }, [selectedPanels])

  useEffect(() => {
    const el = document.documentElement
    if (kioskMode && !document.fullscreenElement) {
      void el.requestFullscreen?.().catch(() => undefined)
    }
    if (!kioskMode && document.fullscreenElement) {
      void document.exitFullscreen?.().catch(() => undefined)
    }
  }, [kioskMode])

  useEffect(() => {
    const recomputeGrid = () => {
      const host = gridHostRef.current
      if (!host) return
      const width = host.clientWidth
      const height = host.clientHeight
      const next = Math.max(
        Math.floor(Math.min((width - PANEL_GAP_PX) / 2, (height - PANEL_GAP_PX) / 2)),
        120
      )
      setSquareSize(next)
    }

    recomputeGrid()
    const observer = new ResizeObserver(recomputeGrid)
    if (gridHostRef.current) observer.observe(gridHostRef.current)
    window.addEventListener('resize', recomputeGrid)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', recomputeGrid)
    }
  }, [])

  const handlePanelChange = (index: number, value: string) => {
    setPanelKeys((prev) => {
      const next = [...prev]
      next[index] = value
      return next
    })
    setSavedMessage('')
  }

  const handleSave = async () => {
    if (!tid) return
    try {
      setSaving(true)
      setError(null)
      const payload = JSON.stringify({
        panels: panelKeys.filter(Boolean),
      })
      const updated = await updateTournament(tid, { shared_screen_config_json: payload })
      setTournament(updated)
      setSavedMessage('Saved')
      window.setTimeout(() => setSavedMessage(''), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save shared screen settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div style={{ padding: 24, color: '#666' }}>Loading shared screen settings...</div>
  }

  if (error && !tournament) {
    return <div style={{ padding: 24, color: '#c62828' }}>{error}</div>
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0d1b3e',
      color: '#fff',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {!kioskMode && (
        <div style={{
          padding: '14px 18px',
          borderBottom: '1px solid rgba(255,255,255,0.12)',
          backgroundColor: '#1a237e',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 16,
          flexWrap: 'wrap',
        }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 800 }}>{tournament?.name || 'Shared Screen'}</div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)' }}>
              Shared TV screen: 4 equal square panels. Draw panels refresh every 30 seconds.
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '8px 12px',
                fontSize: 13,
                fontWeight: 700,
                borderRadius: 6,
                border: 'none',
                backgroundColor: '#2e7d32',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              {saving ? 'Saving...' : 'Save Layout'}
            </button>
            <button
              onClick={() => setKiosk(true)}
              style={{
                padding: '8px 12px',
                fontSize: 13,
                fontWeight: 700,
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.3)',
                backgroundColor: '#1565c0',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              Open Kiosk Mode
            </button>
            {savedMessage ? <span style={{ fontSize: 12, color: '#c8e6c9' }}>{savedMessage}</span> : null}
          </div>
        </div>
      )}

      {!kioskMode && (
        <div style={{
          padding: '14px 18px',
          backgroundColor: 'rgba(255,255,255,0.06)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 10,
        }}>
          {panelKeys.map((value, index) => (
            <label key={index} style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#dbe7ff' }}>Panel {index + 1}</span>
              <select
                value={value}
                onChange={(e) => handlePanelChange(index, e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: 6,
                  border: '1px solid #90a4ae',
                  backgroundColor: '#fff',
                  color: '#263238',
                }}
              >
                <option value="">None</option>
                {panelOptions.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}

      {error && (
        <div style={{ padding: '8px 18px', color: '#ffcdd2', fontSize: 13 }}>
          {error}
        </div>
      )}

      <div style={{ flex: 1, padding: kioskMode ? 8 : 12, minHeight: 0 }}>
        {selectedPanels.every((panel) => panel == null) ? (
          <div style={{
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'rgba(255,255,255,0.6)',
            fontSize: 20,
            textAlign: 'center',
          }}>
            Choose at least one panel for the shared screen.
          </div>
        ) : (
          <div
            ref={gridHostRef}
            style={{
              height: '100%',
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 0,
            }}
          >
            <div style={{
              width: squareSize * 2 + PANEL_GAP_PX,
              height: squareSize * 2 + PANEL_GAP_PX,
              display: 'grid',
              gridTemplateColumns: `${squareSize}px ${squareSize}px`,
              gridTemplateRows: `${squareSize}px ${squareSize}px`,
              gap: PANEL_GAP_PX,
            }}>
              {selectedPanels.map((panel, idx) => {
                const iframeSrc = panel
                  ? (panel.kind === 'draw'
                    ? `${panel.path}${panel.path.includes('?') ? '&' : '?'}tv_refresh=${drawRefreshTick}`
                    : panel.path)
                  : ''
                const frameKey = panel
                  ? `${panel.key}:${panel.kind === 'draw' ? drawRefreshTick : 'live'}`
                  : `empty-${idx}`

                return (
                  <div
                    key={frameKey}
                    style={{
                      backgroundColor: '#fff',
                      borderRadius: 8,
                      overflow: 'hidden',
                      boxShadow: '0 2px 10px rgba(0,0,0,0.25)',
                    }}
                  >
                    {panel ? (
                      <FitPanelFrame title={panel.label} src={iframeSrc} />
                    ) : (
                      <EmptyPanel />
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

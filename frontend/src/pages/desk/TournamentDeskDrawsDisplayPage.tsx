import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getPublicDrawsList, PublicDrawsListResponse } from '../../api/client'

type DrawPanel = {
  key: string
  label: string
  path: string
}

const ROTATION_MS = 20_000
const PANEL_GAP_PX = 10

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
      No draw selected
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

export default function TournamentDeskDrawsDisplayPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = Number(tournamentId)
  const initialKiosk =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('kiosk') === '1'

  const [draws, setDraws] = useState<PublicDrawsListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [kioskMode, setKioskMode] = useState<boolean>(initialKiosk)
  const [rotationTick, setRotationTick] = useState(0)
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
    getPublicDrawsList(tid)
      .then((resp) => setDraws(resp))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load draws display'))
      .finally(() => setLoading(false))
  }, [tid])

  const drawPanels = useMemo<DrawPanel[]>(() => {
    if (!draws) return []
    const panels: DrawPanel[] = []
    draws.events.forEach((event) => {
      if (event.has_waterfall) {
        panels.push({
          key: `waterfall:${event.event_id}`,
          label: `${event.name} Waterfall`,
          path: `/t/${tid}/draws/${event.event_id}/waterfall?display_fit=1`,
        })
      }
      if (event.has_round_robin) {
        panels.push({
          key: `roundrobin:${event.event_id}`,
          label: `${event.name} Round Robin`,
          path: `/t/${tid}/draws/${event.event_id}/roundrobin`,
        })
      }
      event.divisions.forEach((division) => {
        panels.push({
          key: `bracket:${event.event_id}:${division.code}`,
          label: `${event.name} ${division.label}`,
          path: `/t/${tid}/draws/${event.event_id}/bracket/${division.code}`,
        })
      })
    })
    return panels
  }, [draws, tid])

  const panelsPerPage = Math.min(Math.max(drawPanels.length, 1), 2)

  useEffect(() => {
    if (drawPanels.length <= panelsPerPage) {
      if (refreshRef.current) clearInterval(refreshRef.current)
      refreshRef.current = null
      return
    }
    refreshRef.current = setInterval(() => {
      setRotationTick((tick) => tick + 1)
    }, ROTATION_MS)
    return () => {
      if (refreshRef.current) clearInterval(refreshRef.current)
      refreshRef.current = null
    }
  }, [drawPanels.length, panelsPerPage])

  useEffect(() => {
    const el = document.documentElement
    if (kioskMode && !document.fullscreenElement) {
      void el.requestFullscreen?.().catch(() => undefined)
    }
    if (!kioskMode && document.fullscreenElement) {
      void document.exitFullscreen?.().catch(() => undefined)
    }
  }, [kioskMode])

  const visiblePanels = useMemo(() => {
    if (drawPanels.length === 0) return [] as (DrawPanel | null)[]
    if (drawPanels.length <= panelsPerPage) {
      return drawPanels.slice(0, panelsPerPage)
    }
    const start = (rotationTick * panelsPerPage) % drawPanels.length
    return Array.from({ length: panelsPerPage }, (_value, index) => drawPanels[(start + index) % drawPanels.length])
  }, [drawPanels, rotationTick, panelsPerPage])

  if (loading) {
    return <div style={{ padding: 24, color: '#666' }}>Loading draws display...</div>
  }

  if (error) {
    return <div style={{ padding: 24, color: '#c62828' }}>{error}</div>
  }

  return (
    <div style={{
      height: '100vh',
      minHeight: '100vh',
      backgroundColor: '#0d1b3e',
      color: '#fff',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
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
            <div style={{ fontSize: 20, fontWeight: 800 }}>{draws?.tournament_name || 'Draws Display'}</div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)' }}>
              {drawPanels.length > panelsPerPage
                ? `Rotating ${panelsPerPage} draw panels every 20 seconds.`
                : `Showing up to ${panelsPerPage} draw panel${panelsPerPage === 1 ? '' : 's'} at a time.`}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button
              onClick={() => setRotationTick((tick) => tick + 1)}
              style={{
                padding: '8px 12px',
                fontSize: 13,
                fontWeight: 700,
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.3)',
                backgroundColor: '#455a64',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              {`Next ${panelsPerPage}`}
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
          </div>
        </div>
      )}

      <div style={{ flex: 1, height: '100%', padding: kioskMode ? 8 : 12, minHeight: 0 }}>
        {visiblePanels.length === 0 ? (
          <div style={{
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'rgba(255,255,255,0.6)',
            fontSize: 20,
            textAlign: 'center',
          }}>
            No draw panels are available for this tournament.
          </div>
        ) : (
          <div
            style={{
              height: '100%',
              width: '100%',
              display: 'flex',
              flexDirection: visiblePanels.length === 1 ? 'column' : 'row',
              gap: PANEL_GAP_PX,
              minHeight: 0,
            }}
          >
            {visiblePanels.map((panel, idx) => {
              const iframeSrc = panel
                ? `${panel.path}${panel.path.includes('?') ? '&' : '?'}tv_rotation=${rotationTick}`
                : ''
              const frameKey = panel ? `${panel.key}:${rotationTick}` : `empty-${idx}`
              return (
                <div
                  key={frameKey}
                  style={{
                    backgroundColor: '#fff',
                    borderRadius: 8,
                    overflow: 'hidden',
                    boxShadow: '0 2px 10px rgba(0,0,0,0.25)',
                    flex: 1,
                    width: 0,
                    height: '100%',
                    minWidth: 0,
                    minHeight: 0,
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
        )}
      </div>
    </div>
  )
}

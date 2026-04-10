import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { getDeskSnapshot, DeskSnapshotResponse, DeskMatchItem, ReadyQueueItem } from '../../api/client'

const STAGE_COLORS: Record<string, string> = {
  WF: '#1a237e',
  RR: '#2e7d32',
  BRACKET: '#3949ab',
  CONS: '#e65100',
  PLACEMENT: '#6a1b9a',
}

const EVENT_COLORS: Record<string, string> = { W: '#9c27b0', M: '#1565c0', MX: '#00796b' }
const REFRESH_INTERVAL_MS = 20_000

function eventAbbrev(name: string): string {
  if (!name) return ''
  const lower = name.toLowerCase()
  const letter = lower.includes('women') ? 'W'
    : lower.includes('men') || lower.includes('man') ? 'M'
    : lower.includes('mixed') || lower.includes('mix') ? 'MX'
    : name.charAt(0).toUpperCase()
  const tier = name.match(/\b([A-D])\b/i)?.[1]?.toUpperCase() || ''
  return `${letter}${tier}`
}

function LiveDot() {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      fontSize: 11,
      fontWeight: 800,
      color: '#d32f2f',
      textTransform: 'uppercase',
      letterSpacing: 0.4,
      animation: 'board-pulse 2s ease-in-out infinite',
    }}>
      <span style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        backgroundColor: '#d32f2f',
      }} />
      LIVE
    </span>
  )
}

function CurrentCourtCard({ courtName, match }: { courtName: string; match: DeskMatchItem }) {
  const stageColor = STAGE_COLORS[match.stage] || '#757575'
  const abbr = eventAbbrev(match.event_name || '')
  const prefix = abbr.replace(/[A-D]$/, '')
  const eventBg = EVENT_COLORS[prefix] || '#616161'

  return (
    <div style={{
      borderRadius: 8,
      backgroundColor: '#fff',
      overflow: 'hidden',
      boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '5px 10px',
        fontSize: 14,
        fontWeight: 800,
        textAlign: 'center',
        letterSpacing: 0.3,
      }}>
        {courtName}
      </div>
      <div style={{ padding: '7px 9px', backgroundColor: '#fff8f0', minHeight: 92 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 2,
          gap: 6,
        }}>
          <div style={{
            fontSize: 9,
            fontWeight: 700,
            color: '#e65100',
            textTransform: 'uppercase',
            letterSpacing: 0.6,
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}>
            Now Playing
            {match.status === 'IN_PROGRESS' && <LiveDot />}
            {match.status === 'PAUSED' && (
              <span style={{ fontSize: 8, fontWeight: 700, color: '#c62828', letterSpacing: 0.8 }}>Paused</span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#555' }}>#{match.match_number}</span>
            {abbr ? (
              <span style={{
                fontSize: 9,
                fontWeight: 700,
                color: '#fff',
                backgroundColor: eventBg,
                padding: '1px 5px',
                borderRadius: 3,
                textTransform: 'uppercase',
              }}>
                {abbr}
              </span>
            ) : null}
            <span style={{
              fontSize: 9,
              fontWeight: 700,
              color: '#fff',
              backgroundColor: stageColor,
              padding: '1px 5px',
              borderRadius: 3,
              textTransform: 'uppercase',
            }}>
              {match.stage}
            </span>
          </div>
        </div>
        <div style={{
          fontWeight: 700,
          fontSize: 15,
          color: '#1a1a1a',
          lineHeight: 1.15,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {match.team1_display || 'TBD'}
        </div>
        <div style={{
          fontWeight: 700,
          fontSize: 15,
          color: '#1a1a1a',
          lineHeight: 1.15,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {match.team2_display || 'TBD'}
        </div>
        <div style={{ marginTop: 4, fontSize: 10, color: '#607d8b' }}>
          {match.day_label} {match.scheduled_time || ''}
        </div>
      </div>
    </div>
  )
}

function ReadyQueuePanel({ queue }: { queue: ReadyQueueItem[] }) {
  return (
    <div style={{
      borderRadius: 8,
      backgroundColor: '#fff',
      overflow: 'hidden',
      boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
    }}>
      <div style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '5px 10px',
        fontSize: 14,
        fontWeight: 800,
        letterSpacing: 0.3,
      }}>
        On Deck
      </div>
      {queue.length === 0 ? (
        <div style={{ padding: 12, color: '#888', fontSize: 12 }}>No ready matches yet.</div>
      ) : (
        <div style={{ overflow: 'auto', minHeight: 0 }}>
          {queue.map((rq, idx) => (
            <div
              key={rq.match_id}
              style={{
                padding: '7px 9px',
                borderTop: idx === 0 ? 'none' : '1px solid #eef2f5',
                backgroundColor: idx % 2 === 0 ? '#fff' : '#fbfcfe',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginBottom: 2 }}>
                <div style={{ fontWeight: 700, color: '#263238', fontSize: 11, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {idx + 1}. {rq.event_name}
                </div>
                <div style={{ fontSize: 10, color: '#607d8b', fontWeight: 700, flexShrink: 0 }}>
                  Match #{rq.match_number}
                </div>
              </div>
              <div style={{ fontSize: 12, color: '#334155', lineHeight: 1.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {rq.team1_display}
              </div>
              <div style={{ fontSize: 10, color: '#94a3b8', lineHeight: 1.1 }}>
                vs
              </div>
              <div style={{ fontSize: 12, color: '#334155', lineHeight: 1.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {rq.team2_display}
              </div>
              <div style={{ marginTop: 3, fontSize: 9, color: '#90a4ae' }}>
                {rq.day_label} {rq.scheduled_time || ''}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function TournamentDeskCheckinBoardPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = Number(tournamentId)
  const initialKiosk =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('kiosk') === '1'

  const [data, setData] = useState<DeskSnapshotResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string>('')
  const [kioskMode, setKioskMode] = useState<boolean>(initialKiosk)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const setKiosk = useCallback((enabled: boolean) => {
    setKioskMode(enabled)
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    if (enabled) params.set('kiosk', '1')
    else params.delete('kiosk')
    const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`
    window.history.replaceState(null, '', next)
  }, [])

  const fetchData = useCallback(async () => {
    try {
      const snap = await getDeskSnapshot(tid)
      setData(snap)
      setError(null)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e: any) {
      setError(e?.message || 'Failed to load check-in board data')
    }
  }, [tid])

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchData])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && kioskMode) setKiosk(false)
      if (e.key.toLowerCase() === 'k') setKiosk(!kioskMode)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [kioskMode, setKiosk])

  useEffect(() => {
    const el = document.documentElement
    if (kioskMode && !document.fullscreenElement) {
      void el.requestFullscreen?.().catch(() => undefined)
    }
    if (!kioskMode && document.fullscreenElement) {
      void document.exitFullscreen?.().catch(() => undefined)
    }
  }, [kioskMode])

  if (error) {
    return (
      <div style={{
        height: '100vh',
        backgroundColor: '#0d1b3e',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{ color: '#fff', fontSize: 24, textAlign: 'center' }}>
          <div style={{ marginBottom: 8 }}>{error}</div>
          <div style={{ fontSize: 14, color: '#aaa' }}>Auto-retrying...</div>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div style={{
        height: '100vh',
        backgroundColor: '#0d1b3e',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{ color: '#fff', fontSize: 20 }}>Loading check-in board...</div>
      </div>
    )
  }

  const visibleBoardCourts = data.board_by_court.filter(slot => Boolean(slot.now_playing))

  return (
    <div style={{
      height: '100vh',
      backgroundColor: '#0d1b3e',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <style>{`
        @keyframes board-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>

      {!kioskMode && (
        <div style={{
          backgroundColor: '#1a237e',
          color: '#fff',
          padding: '6px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 18, fontWeight: 800 }}>{data.tournament_name}</span>
            <span style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 3,
              backgroundColor: 'rgba(255,255,255,0.15)',
              color: 'rgba(255,255,255,0.7)',
              textTransform: 'uppercase',
              letterSpacing: 0.8,
            }}>
              Check-In Management Board
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.55)' }}>
              Updated {lastUpdated}
            </span>
          </div>
        </div>
      )}

      <div style={{
        flex: 1,
        padding: kioskMode ? 6 : 8,
        overflow: 'hidden',
        minHeight: 0,
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: kioskMode ? '2.7fr 0.9fr' : '2.45fr 0.95fr',
          gap: 8,
          height: '100%',
          minHeight: 0,
        }}>
          <div style={{
            borderRadius: 8,
            backgroundColor: 'rgba(255,255,255,0.06)',
            padding: 6,
            overflow: 'auto',
            minHeight: 0,
          }}>
            {visibleBoardCourts.length === 0 ? (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'rgba(255,255,255,0.45)',
                fontSize: 20,
                textAlign: 'center',
              }}>
                No courts with matches currently playing
              </div>
            ) : (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
                gap: 8,
              }}>
                {visibleBoardCourts.map((slot) => (
                  <CurrentCourtCard key={slot.court_name} courtName={slot.court_name} match={slot.now_playing!} />
                ))}
              </div>
            )}
          </div>

          <div style={{ minHeight: 0, overflow: 'hidden' }}>
            <ReadyQueuePanel queue={data.ready_queue} />
          </div>
        </div>
      </div>

      {!kioskMode && (
        <div style={{ position: 'fixed', right: 10, bottom: 10, zIndex: 10 }}>
          <button
            onClick={() => setKiosk(true)}
            style={{
              padding: '7px 12px',
              fontSize: 12,
              fontWeight: 700,
              borderRadius: 6,
              border: '1px solid #90caf9',
              backgroundColor: '#1565c0',
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            Kiosk Mode
          </button>
        </div>
      )}
    </div>
  )
}

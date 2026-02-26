import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { getDeskSnapshot, DeskSnapshotResponse, DeskMatchItem, BoardCourtSlot } from '../../api/client'

const STAGE_COLORS: Record<string, string> = {
  WF: '#1a237e',
  RR: '#2e7d32',
  BRACKET: '#3949ab',
  CONS: '#e65100',
  PLACEMENT: '#6a1b9a',
}

const REFRESH_INTERVAL_MS = 20_000

const EVENT_COLORS: Record<string, string> = { W: '#9c27b0', M: '#1565c0', MX: '#00796b' }

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
      gap: 5,
      fontSize: 14,
      fontWeight: 800,
      color: '#d32f2f',
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      animation: 'board-pulse 2s ease-in-out infinite',
    }}>
      <span style={{
        width: 10,
        height: 10,
        borderRadius: '50%',
        backgroundColor: '#d32f2f',
      }} />
      LIVE
    </span>
  )
}

function MatchSlot({
  label,
  match,
  variant,
}: {
  label: string
  match: DeskMatchItem | null
  variant: 'now' | 'next' | 'deck'
}) {
  const colors = {
    now:  { label: '#e65100', bg: '#fff8f0' },
    next: { label: '#1a237e', bg: '#f5f6ff' },
    deck: { label: '#888',   bg: '#fafafa' },
  }
  const c = colors[variant]
  const teamSize = variant === 'now' ? 19 : variant === 'next' ? 15 : 14

  if (!match) {
    return (
      <div style={{ padding: '3px 12px', backgroundColor: c.bg }}>
        <div style={{
          fontSize: 11,
          fontWeight: 700,
          color: c.label,
          textTransform: 'uppercase',
          letterSpacing: 0.8,
          marginBottom: 1,
        }}>
          {label}
        </div>
        <div style={{ fontSize: 15, color: '#ccc', fontStyle: 'italic' }}>—</div>
      </div>
    )
  }

  const stageColor = STAGE_COLORS[match.stage] || '#757575'

  return (
    <div style={{ padding: '3px 12px', backgroundColor: c.bg }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 1,
      }}>
        <div style={{
          fontSize: 11,
          fontWeight: 700,
          color: c.label,
          textTransform: 'uppercase',
          letterSpacing: 0.8,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}>
          {label}
          {variant === 'now' && match.status === 'IN_PROGRESS' && <LiveDot />}
          {variant === 'now' && match.status === 'PAUSED' && (
            <span style={{ fontSize: 9, fontWeight: 700, color: '#c62828', letterSpacing: 1 }}>PAUSED</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#555' }}>#{match.match_number}</span>
          {(() => {
            const abbr = eventAbbrev(match.event_name || '')
            const prefix = abbr.replace(/[A-D]$/, '')
            const bg = EVENT_COLORS[prefix] || '#616161'
            return abbr ? (
              <span style={{
                fontSize: 12, fontWeight: 700, color: '#fff',
                backgroundColor: bg, padding: '2px 6px', borderRadius: 3,
                textTransform: 'uppercase',
              }}>{abbr}</span>
            ) : null
          })()}
          <span style={{
            fontSize: 12,
            fontWeight: 700,
            color: '#fff',
            backgroundColor: stageColor,
            padding: '2px 6px',
            borderRadius: 3,
            textTransform: 'uppercase',
          }}>
            {match.stage}
          </span>
        </div>
      </div>
      <div style={{
        fontWeight: 700,
        fontSize: teamSize,
        color: '#1a1a1a',
        lineHeight: 1.25,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {match.team1_display || 'TBD'}
      </div>
      <div style={{
        fontWeight: 700,
        fontSize: teamSize,
        color: '#1a1a1a',
        lineHeight: 1.25,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {match.team2_display || 'TBD'}
      </div>
      {variant !== 'now' && match.scheduled_time && (
        <div style={{ fontSize: 11, color: '#999', marginTop: 1 }}>
          {match.scheduled_time}
        </div>
      )}
    </div>
  )
}

function CourtCard({ slot }: { slot: BoardCourtSlot }) {
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
        padding: '5px 12px',
        fontSize: 15,
        fontWeight: 800,
        textAlign: 'center',
        letterSpacing: 0.3,
      }}>
        {slot.court_name}
      </div>
      <MatchSlot label="Now Playing" match={slot.now_playing} variant="now" />
      <div style={{ height: 1, backgroundColor: '#e0e0e0' }} />
      <MatchSlot label="Up Next" match={slot.up_next} variant="next" />
      <div style={{ height: 1, backgroundColor: '#eee' }} />
      <MatchSlot label="On Deck" match={slot.on_deck} variant="deck" />
    </div>
  )
}

export default function TournamentDeskBoardPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = Number(tournamentId)

  const [data, setData] = useState<DeskSnapshotResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string>('')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const snap = await getDeskSnapshot(tid)
      setData(snap)
      setError(null)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e: any) {
      setError(e?.message || 'Failed to load board data')
    }
  }, [tid])

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchData])

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
        <div style={{ color: '#fff', fontSize: 20 }}>Loading board...</div>
      </div>
    )
  }

  const isStaffFallback = data.version_status !== 'FINAL' && data.version_status !== 'final'
  const deskDraft = data.version_status === 'draft' || data.version_status === 'DRAFT'

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

      {/* Header */}
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
            color: 'rgba(255,255,255,0.6)',
            textTransform: 'uppercase',
            letterSpacing: 0.8,
          }}>
            Read-only Board
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {isStaffFallback && !deskDraft && (
            <span style={{ fontSize: 10, color: '#ffcc80', fontStyle: 'italic' }}>
              Displaying latest schedule (not published)
            </span>
          )}
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>
            Updated {lastUpdated}
          </span>
        </div>
      </div>

      {/* Court grid */}
      <div style={{
        flex: 1,
        padding: 10,
        overflow: 'auto',
        minHeight: 0,
      }}>
        {data.board_by_court.length === 0 ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: 'rgba(255,255,255,0.4)',
            fontSize: 20,
          }}>
            No courts configured
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))',
            gap: 10,
          }}>
            {data.board_by_court.map((slot) => (
              <CourtCard key={slot.court_name} slot={slot} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

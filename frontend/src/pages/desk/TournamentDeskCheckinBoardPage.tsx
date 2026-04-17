import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  getDeskSnapshot,
  DeskSnapshotResponse,
  DeskMatchItem,
  ReadyQueueItem,
  CheckInMatchItem,
} from '../../api/client'

const STAGE_COLORS: Record<string, string> = {
  WF: '#1a237e',
  RR: '#2e7d32',
  BRACKET: '#3949ab',
  CONS: '#e65100',
  PLACEMENT: '#6a1b9a',
}

const EVENT_COLORS: Record<string, string> = { W: '#9c27b0', M: '#1565c0', MX: '#00796b' }
const REFRESH_INTERVAL_MS = 10_000

const SLOT_TINTS = [
  { accent: '#0d47a1', border: '#90caf9', bg: '#e3f2fd' },
  { accent: '#1565c0', border: '#81d4fa', bg: '#e1f5fe' },
  { accent: '#2e7d32', border: '#a5d6a7', bg: '#e8f5e9' },
  { accent: '#ef6c00', border: '#ffcc80', bg: '#fff3e0' },
  { accent: '#6a1b9a', border: '#ce93d8', bg: '#f3e5f5' },
  { accent: '#455a64', border: '#b0bec5', bg: '#eceff1' },
] as const

function getSlotTint(index: number | null) {
  if (index == null || index < 0) return null
  return SLOT_TINTS[index % SLOT_TINTS.length]
}

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

function Badge({ label, bg, color }: { label: string; bg: string; color: string }) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '1px 6px',
      borderRadius: 999,
      backgroundColor: bg,
      color,
      fontSize: 9,
      fontWeight: 800,
      textTransform: 'uppercase',
      letterSpacing: 0.35,
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

function EventBadge({ name }: { name: string }) {
  const abbr = eventAbbrev(name || '')
  const prefix = abbr.replace(/[A-D]$/, '')
  const bg = EVENT_COLORS[prefix] || '#616161'
  if (!abbr) return null
  return <Badge label={abbr} bg={bg} color="#fff" />
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

function formatReadyQueueLabel(rq: ReadyQueueItem): string {
  const code = (rq.match_code || '').toUpperCase()
  const isWf = code.includes('_WF_')
  const division = code.includes('BWW') || code.includes('POOLA')
    ? 'Div I'
    : code.includes('BWL') || code.includes('POOLB')
      ? 'Div II'
      : code.includes('BLW') || code.includes('POOLC')
        ? 'Div III'
        : code.includes('BLL') || code.includes('POOLD')
          ? 'Div IV'
          : code.includes('POOLE')
            ? 'Div V'
            : ''
  if (isWf) return `${rq.event_name} WF`
  return division ? `${rq.event_name} ${division}` : rq.event_name
}

function parseApiTimestampMs(iso?: string | null): number | null {
  if (!iso) return null
  const hasOffset = /(?:Z|[+-]\d{2}:\d{2})$/i.test(iso)
  const normalized = hasOffset ? iso : `${iso}Z`
  const ms = Date.parse(normalized)
  if (Number.isNaN(ms)) return null
  return ms
}

function formatStartedAtLabel(iso?: string | null, timeZone?: string | null): string | null {
  const ms = parseApiTimestampMs(iso)
  if (ms == null) return null
  const date = new Date(ms)
  try {
    return date.toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: timeZone || undefined,
    })
  } catch {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
}

function formatElapsedLabel(startIso?: string | null, endIso?: string | null, nowMs?: number): string | null {
  const start = parseApiTimestampMs(startIso)
  if (start == null) return null
  const end = endIso ? parseApiTimestampMs(endIso) : (nowMs ?? Date.now())
  if (end == null || end <= start) return '0:00'
  const totalSeconds = Math.floor((end - start) / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function CheckInReadyDisplayCard({
  rq,
  titleLabel,
  headerRightTop,
  queueElapsedLabel,
  deskMatch,
  slotTintIndex,
}: {
  rq: ReadyQueueItem
  titleLabel: string
  headerRightTop: string
  queueElapsedLabel: string | null
  deskMatch?: DeskMatchItem
  slotTintIndex: number | null
}) {
  const tint = getSlotTint(slotTintIndex)
  const accentColor = tint?.accent || '#0d47a1'
  const footerBg = tint?.bg || '#eef4ff'

  return (
    <div style={{
      borderRadius: 5,
      backgroundColor: '#fff',
      overflow: 'hidden',
      border: `1px solid ${tint?.border || '#90caf9'}`,
      boxShadow: '0 1px 3px rgba(15, 23, 42, 0.06)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        backgroundColor: accentColor,
        color: '#fff',
        padding: '3px 5px',
        fontSize: 9,
        fontWeight: 700,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 3,
        minWidth: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, minWidth: 0, overflow: 'hidden' }}>
          <span style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>{titleLabel}</span>
          <EventBadge name={rq.event_name} />
          {deskMatch && (
            <Badge label={deskMatch.stage} bg={STAGE_COLORS[deskMatch.stage] || '#757575'} color="#fff" />
          )}
        </div>
        <span style={{ fontSize: 8, fontWeight: 700, opacity: 0.92, whiteSpace: 'nowrap', flexShrink: 0 }}>
          #{rq.match_number}
        </span>
      </div>
      <div style={{ backgroundColor: '#fff', padding: '3px 4px 4px', minHeight: 30, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div style={{
            fontSize: 7,
            fontWeight: 700,
            color: '#607d8b',
            letterSpacing: 0.2,
            marginBottom: 1,
          }}>
          {headerRightTop}
        </div>
        {queueElapsedLabel && (
          <div style={{ fontSize: 7, fontWeight: 700, color: '#455a64', marginBottom: 1 }}>
            Q: {queueElapsedLabel}
          </div>
        )}
        <div style={{
          fontWeight: 700,
          fontSize: 9,
          color: '#1a1a1a',
          lineHeight: 1.1,
        }}>
          {rq.team1_display}
        </div>
        <div style={{ color: '#999', fontSize: 7, margin: '0 0 1px' }}>vs</div>
        <div style={{
          fontWeight: 700,
          fontSize: 9,
          color: '#1a1a1a',
          lineHeight: 1.1,
        }}>
          {rq.team2_display}
        </div>
      </div>
      <div style={{ backgroundColor: footerBg, height: 2 }} />
    </div>
  )
}

function CurrentCourtCard({
  courtName,
  match,
  slotLabel,
  startAtLabel,
  elapsedLabel,
}: {
  courtName: string
  match: DeskMatchItem
  slotLabel: string | null
  startAtLabel: string | null
  elapsedLabel: string | null
}) {
  const stageColor = STAGE_COLORS[match.stage] || '#757575'

  return (
    <div style={{
      borderRadius: 6,
      backgroundColor: '#fff',
      overflow: 'hidden',
      border: '1px solid #d7dee5',
      boxShadow: '0 1px 3px rgba(15, 23, 42, 0.06)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '3px 6px',
        fontSize: 10,
        fontWeight: 700,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 3,
        minWidth: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, minWidth: 0, overflow: 'hidden' }}>
          <span style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>{courtName.replace(/^Court\s+/i, 'Ct ')}</span>
          <EventBadge name={match.event_name} />
          <Badge label={match.stage} bg={stageColor} color="#fff" />
        </div>
        <span style={{ fontSize: 10, fontWeight: 700, opacity: 0.9, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {slotLabel ? slotLabel.split(' ').slice(-2).join('\u00a0') : ''}
        </span>
      </div>
      <div style={{ backgroundColor: '#fff', padding: '4px 5px 5px', minHeight: 44, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 4,
            marginBottom: 2,
            flexWrap: 'wrap',
          }}>
            <div style={{
              fontSize: 7,
              fontWeight: 700,
              color: '#e65100',
              textTransform: 'uppercase',
              letterSpacing: 0.3,
              display: 'flex',
              alignItems: 'center',
              gap: 3,
            }}>
              Currently Playing
              {match.status === 'IN_PROGRESS' && <LiveDot />}
              {match.status === 'PAUSED' && (
                <span style={{ fontSize: 7, fontWeight: 700, color: '#c62828', letterSpacing: 0.5 }}>Paused</span>
              )}
            </div>
            <div style={{ fontSize: 8, fontWeight: 700, color: '#455a64' }}>#{match.match_number}</div>
          </div>
          <div style={{ color: '#1a1a1a', fontSize: 10, fontWeight: 700, lineHeight: 1.15 }}>
            {match.team1_display || 'TBD'}
          </div>
          <div style={{ color: '#999', fontSize: 7, margin: '1px 0' }}>vs</div>
          <div style={{ color: '#1a1a1a', fontSize: 10, fontWeight: 700, lineHeight: 1.15 }}>
            {match.team2_display || 'TBD'}
          </div>
          {(startAtLabel || elapsedLabel) && (
            <div style={{ marginTop: 2, fontSize: 7, color: '#607d8b' }}>
              {startAtLabel && <span>▶ {startAtLabel}</span>}
              {startAtLabel && elapsedLabel && <span style={{ margin: '0 3px' }}>·</span>}
              {elapsedLabel && <span>{elapsedLabel}</span>}
            </div>
          )}
        </div>
      </div>
      <div style={{ backgroundColor: '#fff3e0', height: 3 }} />
    </div>
  )
}

function WaitingMatchCard({
  match,
  slotLabel,
}: {
  match: CheckInMatchItem
  slotLabel: string
}) {
  return (
    <div style={{
      border: '1px solid #d7dee5',
      borderRadius: 8,
      padding: '10px 12px',
      backgroundColor: '#fff',
      boxShadow: '0 1px 3px rgba(15, 23, 42, 0.06)',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
        marginBottom: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: '#334155' }}>{slotLabel}</span>
          <span style={{ fontSize: 12, color: '#607d8b', fontWeight: 700 }}>
            Match #{match.match_number}
          </span>
          <EventBadge name={match.event_name} />
        </div>
        <div style={{ fontSize: 12, color: '#607d8b', fontWeight: 700 }}>
          {match.day_label}{match.scheduled_time ? ` · ${match.scheduled_time}` : ''}
        </div>
      </div>
      <div style={{ display: 'grid', gap: 4 }}>
        <div style={{ fontSize: 20, fontWeight: 800, color: '#1a1a1a', lineHeight: 1.15 }}>
          {match.side_a.team_display || 'TBD'}
        </div>
        <div style={{ fontSize: 12, color: '#90a4ae', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          vs
        </div>
        <div style={{ fontSize: 20, fontWeight: 800, color: '#1a1a1a', lineHeight: 1.15 }}>
          {match.side_b.team_display || 'TBD'}
        </div>
      </div>
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
  const [clockNowMs, setClockNowMs] = useState(() => Date.now())
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
    intervalRef.current = setInterval(() => {
      setClockNowMs(Date.now())
      void fetchData()
    }, REFRESH_INTERVAL_MS)
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

  const snapshot = data

  const slotSections = useMemo(() => {
    type Section = { key: string; label: string; matches: CheckInMatchItem[] }
    if (!snapshot) return [] as Section[]
    if ((snapshot.checkin_slot_options || []).length > 0) {
      return (snapshot.checkin_slot_options || []).map((opt) => ({
        key: opt.slot_key,
        label: opt.label,
        matches: (snapshot.checkin_slot_rows?.[opt.slot_key] || [])
          .slice()
          .sort((a, b) => a.match_number - b.match_number),
      }))
    }

    const byKey = new Map<string, Section>()
    ;(snapshot.checkin_matches || []).forEach((cm) => {
      const key = `checkin|${cm.day_label}|${(cm.sort_time || cm.scheduled_time || '').slice(0, 5)}`
      const label = `${cm.day_label}${cm.scheduled_time ? ` ${cm.scheduled_time}` : ''}`.trim()
      if (!byKey.has(key)) byKey.set(key, { key, label, matches: [] })
      byKey.get(key)!.matches.push(cm)
    })
    return Array.from(byKey.values())
  }, [snapshot])

  const slotLabelByKey = useMemo(() => {
    const map = new Map<string, string>()
    slotSections.forEach((section) => map.set(section.key, section.label))
    return map
  }, [slotSections])

  const slotKeyByMatchId = useMemo(() => {
    const map = new Map<number, string>()
    slotSections.forEach((section) => {
      section.matches.forEach((cm) => {
        if (!map.has(cm.match_id)) map.set(cm.match_id, section.key)
      })
    })
    return map
  }, [slotSections])

  const waitingGroups = useMemo(
    () =>
      slotSections
        .map((section, index) => ({
          key: section.key,
          label: section.label,
          tintIndex: index,
          matches: section.matches.filter((cm) => !cm.match_ready),
        }))
        .filter((section) => section.matches.length > 0),
    [slotSections]
  )

  const readyCards = useMemo(
    () =>
      (snapshot?.ready_queue || []).map((rq) => {
        const slotKey = slotKeyByMatchId.get(rq.match_id) || null
        const slotIndex = slotKey ? slotSections.findIndex((section) => section.key === slotKey) : -1
        const slotLabel = slotKey ? (slotLabelByKey.get(slotKey) || null) : null
        return {
          rq,
          slotTintIndex: slotIndex >= 0 ? slotIndex : null,
          headerTop: (slotLabel || `${rq.day_label} ${rq.scheduled_time || ''}`.trim()) || '—',
          queueElapsedLabel: formatElapsedLabel(rq.ready_at, null, clockNowMs),
          deskMatch: (snapshot?.matches || []).find((m) => m.match_id === rq.match_id),
        }
      }),
    [clockNowMs, snapshot, slotKeyByMatchId, slotLabelByKey, slotSections]
  )

  const currentCards = useMemo(
    () =>
      (snapshot?.board_by_court || [])
        .filter((slot) => Boolean(slot.now_playing))
        .map((slot) => {
          const match = slot.now_playing!
          const slotKey = slotKeyByMatchId.get(match.match_id) || null
          const slotLabel = slotKey ? (slotLabelByKey.get(slotKey) || null) : null
          return {
            courtName: slot.court_name,
            match,
            slotLabel,
            startAtLabel: formatStartedAtLabel(match.started_at, snapshot?.tournament_timezone || null),
            elapsedLabel: formatElapsedLabel(match.started_at, match.completed_at, clockNowMs),
          }
        }),
    [clockNowMs, snapshot, slotKeyByMatchId, slotLabelByKey]
  )

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

  if (!snapshot) {
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
              Player Check-In Display
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
        padding: kioskMode ? 10 : 12,
        overflow: 'hidden',
        minHeight: 0,
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: kioskMode ? '1.45fr 1fr' : '1.35fr 1fr',
          gap: 12,
          height: '100%',
          minHeight: 0,
        }}>
          <div style={{
            borderRadius: 8,
            backgroundColor: 'rgba(255,255,255,0.06)',
            padding: 10,
            overflow: 'auto',
            minHeight: 0,
          }}>
            <div style={{
              color: '#fff',
              fontSize: kioskMode ? 22 : 20,
              fontWeight: 800,
              marginBottom: 10,
              letterSpacing: 0.2,
            }}>
              Waiting For Check-In
            </div>
            {waitingGroups.length === 0 ? (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: 240,
                color: 'rgba(255,255,255,0.45)',
                fontSize: 20,
                textAlign: 'center',
              }}>
                Nothing is waiting for check-in right now
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 12 }}>
                {waitingGroups.map((group) => {
                  const tint = getSlotTint(group.tintIndex)
                  return (
                    <div
                      key={group.key}
                      style={{
                        borderRadius: 10,
                        overflow: 'hidden',
                        backgroundColor: '#f8fbff',
                        border: `1px solid ${tint?.border || '#d7dee5'}`,
                        boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
                      }}
                    >
                      <div style={{
                        backgroundColor: tint?.accent || '#1a237e',
                        color: '#fff',
                        padding: '8px 12px',
                        fontSize: 16,
                        fontWeight: 800,
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: 10,
                        flexWrap: 'wrap',
                      }}>
                        <span>{group.label}</span>
                        <span style={{ fontSize: 12, opacity: 0.92 }}>
                          {group.matches.length} match{group.matches.length === 1 ? '' : 'es'}
                        </span>
                      </div>
                      <div style={{
                        padding: 10,
                        display: 'grid',
                        gridTemplateColumns: kioskMode ? 'repeat(2, minmax(0, 1fr))' : '1fr',
                        gap: 10,
                      }}>
                        {group.matches.map((match) => (
                          <WaitingMatchCard
                            key={match.match_id}
                            match={match}
                            slotLabel={group.label}
                          />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div style={{
            minHeight: 0,
            overflow: 'hidden',
            display: 'grid',
            gridTemplateRows: '1fr 1fr',
            gap: 12,
          }}>
            <div style={{
              borderRadius: 8,
              backgroundColor: 'rgba(255,255,255,0.06)',
              padding: 10,
              overflow: 'auto',
              minHeight: 0,
            }}>
              <div style={{
                color: '#fff',
                fontSize: kioskMode ? 20 : 18,
                fontWeight: 800,
                marginBottom: 10,
              }}>
                Ready To Go
              </div>
              {readyCards.length === 0 ? (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minHeight: 180,
                  color: 'rgba(255,255,255,0.45)',
                  fontSize: 18,
                  textAlign: 'center',
                }}>
                  No ready matches are waiting right now
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 6 }}>
                  {readyCards.map((card) => (
                    <CheckInReadyDisplayCard
                      key={card.rq.match_id}
                      rq={card.rq}
                      titleLabel={formatReadyQueueLabel(card.rq)}
                      headerRightTop={card.headerTop}
                      queueElapsedLabel={card.queueElapsedLabel}
                      deskMatch={card.deskMatch}
                      slotTintIndex={card.slotTintIndex}
                    />
                  ))}
                </div>
              )}
            </div>

            <div style={{
              borderRadius: 8,
              backgroundColor: 'rgba(255,255,255,0.06)',
              padding: 10,
              overflow: 'auto',
              minHeight: 0,
            }}>
              <div style={{
                color: '#fff',
                fontSize: kioskMode ? 20 : 18,
                fontWeight: 800,
                marginBottom: 10,
              }}>
                Currently Playing
              </div>
              {currentCards.length === 0 ? (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minHeight: 180,
                  color: 'rgba(255,255,255,0.45)',
                  fontSize: 18,
                  textAlign: 'center',
                }}>
                  No matches are currently playing
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 6 }}>
                  {currentCards.map((card) => (
                    <CurrentCourtCard
                      key={card.courtName}
                      courtName={card.courtName}
                      match={card.match}
                      slotLabel={card.slotLabel}
                      startAtLabel={card.startAtLabel}
                      elapsedLabel={card.elapsedLabel}
                    />
                  ))}
                </div>
              )}
            </div>
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

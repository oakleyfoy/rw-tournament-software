import { useEffect, useState, type CSSProperties, type DragEvent } from 'react'
import type { DeskMatchItem, SnapshotSlot } from '../../api/client'
import {
  autoStartDecision,
  earliestUnfinished,
  firstNameLines,
  formatSlotTime,
  readableSide,
  type DaySchedule,
  type ScheduleCell,
  type ScheduleCourt,
} from './courtSheet'

type Props = {
  schedule: DaySchedule
  days: string[]
  selectedDay: string
  onSelectDay: (day: string) => void
  checkinReadyByMatchId: ReadonlyMap<number, boolean>
  matches: DeskMatchItem[]
  nowMinutes: number | null
  isToday: boolean
  clockLabel: string
  syncedLabel: string
  isDraft: boolean
  busyMatchId: number | null
  canUndo: boolean
  onOpenMatch: (match: DeskMatchItem) => void
  onStart: (matchId: number) => void
  onActivate?: (matchId: number, slotId: number | null) => void
  onMove: (matchId: number, slotId: number) => void
  onSwap: (matchId: number, occupantId: number) => void
  onUndo: () => void
  onCourtState: (courtLabel: string, closed: boolean, note: string) => void
  onInteractionChange?: (active: boolean) => void
  rosterByTeam?: Record<number, { id: number; name: string }[]>
  notedPlayerIds?: number[]
  teamNotesById?: Record<number, string | null>
  onOpenNotes?: (players: { id: number; name: string }[], teamNotes: { label: string; body: string }[]) => void
  dayStarted?: boolean
  dayPaused?: boolean
  arrivedTeamIds?: number[]
  onStartDay?: () => void
  onSetPaused?: (paused: boolean) => void
  courtNotes?: Record<string, string>
  isCopy?: boolean
  testClock?: string | null
  onSetTestClock?: (time: string | null) => void
}

const LIVE = new Set(['IN_PROGRESS', 'PAUSED'])

function dayLabel(day: string): string {
  const date = new Date(`${day}T12:00:00`)
  if (Number.isNaN(date.getTime())) return day
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

function minutesFromSort(value: string): number | null {
  const [hourRaw, minuteRaw] = (value || '').split(':')
  const hour = Number(hourRaw)
  const minute = Number(minuteRaw || 0)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  return hour * 60 + minute
}

function elapsedLabel(startedAt: string | null, tick: number): string {
  if (!startedAt) return ''
  const started = new Date(startedAt).getTime()
  if (!Number.isFinite(started)) return ''
  const minutes = Math.max(0, Math.floor((tick - started) / 60000))
  if (minutes < 180) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} hr`
  return `${Math.floor(hours / 24)} d`
}

function participantsFor(match: DeskMatchItem, roster: Record<number, { id: number; name: string }[]>) {
  return [match.team1_id, match.team2_id].flatMap((teamId) => (teamId == null ? [] : roster[teamId] || []))
}

function courtMatches(schedule: DaySchedule, courtNumber: number): { court: ScheduleCourt; cells: ScheduleCell[] } {
  const index = schedule.courts.findIndex((court) => court.courtNumber === courtNumber)
  const court = schedule.courts[index]
  const cells = schedule.rows.flatMap((row) => {
    const cell = row.cells[index]
    return cell ? [cell] : []
  })
  return { court, cells }
}

export default function DesignatedCourtSheet(props: Props) {
  const {
    schedule, days, selectedDay, onSelectDay, matches, nowMinutes, clockLabel, syncedLabel,
    isDraft, canUndo, onOpenMatch, onMove, onSwap, onUndo, onCourtState, onInteractionChange,
    rosterByTeam = {}, notedPlayerIds = [], teamNotesById = {}, onOpenNotes,
    dayStarted = false, dayPaused = false, onStartDay, onSetPaused, courtNotes = {},
    isCopy = false, testClock = null, onSetTestClock,
  } = props
  const [dragMatchId, setDragMatchId] = useState<number | null>(null)
  const [courtPanel, setCourtPanel] = useState<number | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [tick, setTick] = useState(() => Date.now())
  const noted = new Set(notedPlayerIds)
  const courtCount = Math.max(schedule.courts.length, 1)
  const compact = courtCount >= 16
  const columns = `64px repeat(${courtCount}, minmax(0, 1fr))`

  useEffect(() => {
    const timer = window.setInterval(() => setTick(Date.now()), 30000)
    return () => window.clearInterval(timer)
  }, [])

  const hold = (active: boolean) => onInteractionChange?.(active)
  const matchById = new Map(matches.map((match) => [match.match_id, match]))
  const liveTeamIds = new Set<number>()
  for (const match of matches) {
    if (!LIVE.has((match.status || '').toUpperCase())) continue
    if (match.team1_id) liveTeamIds.add(match.team1_id)
    if (match.team2_id) liveTeamIds.add(match.team2_id)
  }

  const noteState = (match: DeskMatchItem) => {
    const players = participantsFor(match, rosterByTeam)
    const teamNotes = [match.team1_id, match.team2_id].flatMap((teamId, index) => {
      const body = teamId == null ? '' : (teamNotesById[teamId] || '')
      return body ? [{ label: index === 0 ? 'Team 1 note' : 'Team 2 note', body }] : []
    })
    return { players, teamNotes, hasNotes: players.some((player) => noted.has(player.id)) || teamNotes.length > 0 }
  }

  const dropOnSlot = (matchId: number, slot: SnapshotSlot, courtClosed: boolean) => {
    if (courtClosed || slot.is_active === false) return
    const match = matchById.get(matchId)
    if (!match || match.slot_id === slot.slot_id) return
    if (LIVE.has((match.status || '').toUpperCase())) return
    const occupantId = slot.assigned_match_id
    if (occupantId && occupantId !== match.match_id) {
      const occupant = matchById.get(occupantId)
      if (!window.confirm(`Swap #${match.match_number} with #${occupant?.match_number || occupantId}?`)) return
      onSwap(match.match_id, occupantId)
      return
    }
    onMove(match.match_id, slot.slot_id)
  }

  const dropOnLive = (matchId: number, court: ScheduleCourt) => {
    const match = matchById.get(matchId)
    if (!match || !isDraft || court.closed || court.unavailable) return
    if (LIVE.has((match.status || '').toUpperCase())) return
    const { cells } = courtMatches(schedule, court.courtNumber)
    const playing = cells.find((cell) => cell.match && LIVE.has((cell.match.status || '').toUpperCase()))
    if (playing) return
    const target = cells.find((cell) => cell.slot.start_time.slice(0, 5) === (match.sort_time || '').slice(0, 5))
    if (match.court_number !== court.courtNumber) {
      if (!target) return
      if (target.match && target.match.match_id !== match.match_id) {
        if (!window.confirm(`Swap #${match.match_number} with #${target.match.match_number}?`)) return
        onSwap(match.match_id, target.match.match_id)
        return
      }
      onMove(match.match_id, target.slot.slot_id)
    }
    const earliest = earliestUnfinished(cells.flatMap((cell) => (cell.match ? [cell.match] : [])))
    const scheduledMinutes = minutesFromSort(match.sort_time || '')
    const early = scheduledMinutes != null && nowMinutes != null && nowMinutes < scheduledMinutes - 15
    if (early && !window.confirm(`#${match.match_number} is before its 15-minute release window. Start it now?`)) return
    if (earliest && earliest.match_id !== match.match_id && (earliest.status || '').toUpperCase() !== 'FINAL') {
      if (!window.confirm(`#${earliest.match_number} is still assigned earlier on ${court.courtName}. Start #${match.match_number} anyway?`)) return
    }
    const slotId = match.court_number === court.courtNumber ? null : (target?.slot.slot_id ?? null)
    if (props.onActivate) props.onActivate(match.match_id, slotId)
    else props.onStart(match.match_id)
  }

  return (
    <div data-testid="court-sheet" style={{ background: '#f4f6f8', display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        {days.map((day) => (
          <button key={day} type="button" onClick={() => onSelectDay(day)} style={chip(selectedDay === day)}>{dayLabel(day)}</button>
        ))}
        {dayStarted ? (
          <span style={startedPill}>Day Started</span>
        ) : (
          <button type="button" disabled={!isDraft} onClick={onStartDay} style={startButton}>Start Day</button>
        )}
        {dayStarted && (
          <button type="button" disabled={!isDraft} onClick={() => onSetPaused?.(!dayPaused)} style={chip(dayPaused)}>
            {dayPaused ? 'Resume' : 'Pause'}
          </button>
        )}
        {isCopy && dayStarted && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 800, color: '#37474f' }}>
            Test clock
            <input
              type="time"
              value={testClock || ''}
              onChange={(event) => onSetTestClock?.(event.target.value || null)}
              style={{ fontSize: 12 }}
            />
            <span style={{ fontWeight: 700, color: '#b71c1c' }}>Texts off</span>
          </label>
        )}
        <button type="button" disabled={!canUndo || !isDraft} onClick={onUndo} style={chip(false)}>Undo Move</button>
        <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 800, color: '#37474f' }}>{clockLabel} · {syncedLabel}</span>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: columns, gap: 3, position: 'sticky', top: 0, zIndex: 3, background: '#f4f6f8', paddingBottom: 4 }}>
          <div style={corner}>Time</div>
          {schedule.courts.map((court) => (
            <button key={court.courtNumber} type="button" onClick={() => { setCourtPanel(court.courtNumber); setNoteDraft(courtNotes[court.courtLabel] || courtNotes[String(court.courtNumber)] || '') }} style={headerButton(court)}>
              {court.courtName.replace(/^Court\s+/i, '')}
            </button>
          ))}
          <div style={{ ...corner, fontSize: 9 }}>Now</div>
          {schedule.courts.map((court) => {
            const { cells } = courtMatches(schedule, court.courtNumber)
            return (
              <LiveCell
                key={`live-${court.courtNumber}`}
                court={court}
                cells={cells}
                compact={compact}
                tick={tick}
                dayStarted={dayStarted}
                dayPaused={dayPaused}
                nowMinutes={nowMinutes}
                liveTeamIds={liveTeamIds}
                matches={matches}
                noteFor={noteState}
                onOpen={onOpenMatch}
                onOpenNotes={onOpenNotes}
                onDrop={(matchId) => dropOnLive(matchId, court)}
                onDragState={hold}
              />
            )
          })}
        </div>

        <div style={{ fontSize: 11, fontWeight: 800, color: '#1a237e', padding: '6px 2px' }}>Today's schedule</div>
        <div style={{ display: 'grid', gridTemplateColumns: columns, gap: 3 }}>
          {schedule.rows.map((row) => (
            <div key={row.time} style={{ display: 'contents' }}>
              <div style={timeCell}>{row.timeLabel}</div>
              {row.cells.map((cell, index) => {
                const court = schedule.courts[index]
                const match = cell?.match || null
                const playing = match != null && LIVE.has((match.status || '').toUpperCase())
                return (
                  <div
                    key={`${row.time}-${court.courtNumber}`}
                    onDragOver={(event) => { if (dragMatchId) event.preventDefault() }}
                    onDrop={(event) => {
                      event.preventDefault()
                      const matchId = Number(event.dataTransfer.getData('text/match-id'))
                      if (cell) dropOnSlot(matchId, cell.slot, court.closed)
                      setDragMatchId(null)
                      hold(false)
                    }}
                    style={gridCellStyle(cell, court, playing)}
                  >
                    {playing && match ? (
                      <button type="button" onClick={() => onOpenMatch(match)} style={placeholderButton}>
                        ↑ Playing #{match.match_number}
                      </button>
                    ) : match ? (
                      <GridCard
                        match={match}
                        matches={matches}
                        compact={compact}
                        hasNotes={noteState(match).hasNotes}
                        onOpen={() => onOpenMatch(match)}
                        onNotes={() => {
                          const notes = noteState(match)
                          onOpenNotes?.(notes.players, notes.teamNotes)
                        }}
                        onDragStart={() => { setDragMatchId(match.match_id); hold(true) }}
                        onDragEnd={() => { setDragMatchId(null); hold(false) }}
                      />
                    ) : !cell || cell.slot.is_active === false ? (
                      <span style={{ fontSize: 10, fontWeight: 800, color: '#eceff1' }}>Unavailable</span>
                    ) : court.closed ? (
                      <span style={{ fontSize: 10, fontWeight: 800, color: '#b71c1c' }}>Closed</span>
                    ) : (
                      <span style={{ fontSize: 10, fontWeight: 800, color: '#1b5e20' }}>Open</span>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {courtPanel != null && (
        <CourtPanel
          schedule={schedule}
          courtNumber={courtPanel}
          note={noteDraft}
          onNote={setNoteDraft}
          onClose={() => { setCourtPanel(null); hold(false) }}
          onSave={(closed) => {
            const court = schedule.courts.find((row) => row.courtNumber === courtPanel)
            if (court) onCourtState(court.courtLabel, closed, noteDraft)
            setCourtPanel(null)
          }}
        />
      )}
    </div>
  )
}

function slotCovering(cells: ScheduleCell[], nowMinutes: number | null): ScheduleCell | null {
  const ordered = [...cells].sort((a, b) => (minutesFromSort(a.slot.start_time || '') ?? 0) - (minutesFromSort(b.slot.start_time || '') ?? 0))
  if (!ordered.length) return null
  if (nowMinutes == null) return ordered[0]
  let current = ordered[0]
  for (const cell of ordered) {
    if ((minutesFromSort(cell.slot.start_time || '') ?? 0) <= nowMinutes) current = cell
  }
  return current
}

function nextActiveLabel(cells: ScheduleCell[], afterMinutes: number): string {
  const next = [...cells]
    .filter((cell) => cell.slot.is_active !== false && (minutesFromSort(cell.slot.start_time || '') ?? 0) > afterMinutes)
    .sort((a, b) => (minutesFromSort(a.slot.start_time || '') ?? 0) - (minutesFromSort(b.slot.start_time || '') ?? 0))[0]
  return next ? formatSlotTime(next.slot.start_time) : ''
}

function LiveCell({
  court, cells, compact, tick, dayStarted, dayPaused, nowMinutes, liveTeamIds, matches, noteFor, onOpen, onOpenNotes, onDrop, onDragState,
}: {
  court: ScheduleCourt
  cells: ScheduleCell[]
  compact: boolean
  tick: number
  dayStarted: boolean
  dayPaused: boolean
  nowMinutes: number | null
  liveTeamIds: Set<number>
  matches: DeskMatchItem[]
  noteFor: (match: DeskMatchItem) => { players: { id: number; name: string }[]; teamNotes: { label: string; body: string }[]; hasNotes: boolean }
  onOpen: (match: DeskMatchItem) => void
  onOpenNotes?: (players: { id: number; name: string }[], teamNotes: { label: string; body: string }[]) => void
  onDrop: (matchId: number) => void
  onDragState: (active: boolean) => void
}) {
  const playing = cells.find((cell) => cell.match && LIVE.has((cell.match.status || '').toUpperCase()))?.match || null
  const upcoming = cells.flatMap((cell) => (cell.match ? [cell.match] : []))
  const earliest = earliestUnfinished(upcoming)
  if (playing) {
    const notes = noteFor(playing)
    const sideA = readableSide(playing, 'A', matches).label
    const sideB = readableSide(playing, 'B', matches).label
    return (
      <button type="button" onClick={() => onOpen(playing)} style={{ ...liveCard, background: '#ffe0b2' }}>
        <div style={liveTop}>
          <span>#{playing.match_number}</span>
          <span>
            {notes.hasNotes && (
              <span role="button" title="Player notes exist." onClick={(event) => { event.stopPropagation(); onOpenNotes?.(notes.players, notes.teamNotes) }} style={noteMark}>N</span>
            )}
            {' '}Playing
          </span>
        </div>
        <NameLines a={sideA} b={sideB} compact={compact} />
        <div style={liveMeta}>{playing.scheduled_time || ''} · {elapsedLabel(playing.started_at, tick)}</div>
      </button>
    )
  }
  if (court.closed) {
    return <div style={{ ...liveCard, background: '#ffcdd2', color: '#b71c1c' }}><b>CLOSED</b></div>
  }
  const focus = slotCovering(cells, nowMinutes)
  if (!focus || focus.slot.is_active === false) {
    const until = nextActiveLabel(cells, focus ? minutesFromSort(focus.slot.start_time || '') ?? -1 : -1)
    return (
      <div style={{ ...liveCard, background: '#37474f', color: '#eceff1' }}>
        <b>UNAVAILABLE</b>
        {until && <div style={liveMeta}>Until {until}</div>}
      </div>
    )
  }
  const onDragOver = (event: DragEvent) => event.preventDefault()
  const onDropEvent = (event: DragEvent) => {
    event.preventDefault()
    const matchId = Number(event.dataTransfer.getData('text/match-id'))
    if (matchId) onDrop(matchId)
    onDragState(false)
  }
  if (!earliest) {
    return <div onDragOver={onDragOver} onDrop={onDropEvent} style={{ ...liveCard, background: '#e8f5e9', color: '#1b5e20' }}><b>OPEN</b></div>
  }
  const earliestCell = cells.find((cell) => cell.match?.match_id === earliest.match_id)
  const decision = autoStartDecision({
    dayStarted,
    paused: dayPaused,
    courtClosed: false,
    slotActive: earliestCell?.slot.is_active !== false,
    status: earliest.status,
    teamsKnown: Boolean(earliest.team1_id && earliest.team2_id),
    feedersFinal: !earliest.source_match_a_id && !earliest.source_match_b_id || matches.filter((match) => match.match_id === earliest.source_match_a_id || match.match_id === earliest.source_match_b_id).every((match) => (match.status || '').toUpperCase() === 'FINAL'),
    participantBusy: Boolean((earliest.team1_id && liveTeamIds.has(earliest.team1_id)) || (earliest.team2_id && liveTeamIds.has(earliest.team2_id))),
    scheduledMinutes: minutesFromSort(earliest.sort_time || ''),
    nowMinutes,
  })
  const waiting = decision.reason === 'Awaiting result' || decision.reason === 'Player is on another court'
  const nextLabel = earliest.scheduled_time || formatSlotTime(earliest.sort_time || '')
  return (
    <div onDragOver={onDragOver} onDrop={onDropEvent} style={{ ...liveCard, background: waiting ? '#fff59d' : '#e8f5e9', color: waiting ? '#e65100' : '#1b5e20' }}>
      <b>{waiting ? 'WAITING' : 'OPEN'}</b>
      {!waiting && <div style={liveMeta}>Next: {nextLabel}</div>}
      {waiting && <div style={liveMeta}>{decision.reason === 'Awaiting result' ? 'Awaiting result' : 'Player is on another court'}</div>}
    </div>
  )
}

function GridCard({
  match, matches, compact, hasNotes, onOpen, onNotes, onDragStart, onDragEnd,
}: {
  match: DeskMatchItem
  matches: DeskMatchItem[]
  compact: boolean
  hasNotes: boolean
  onOpen: () => void
  onNotes: () => void
  onDragStart: () => void
  onDragEnd: () => void
}) {
  const status = (match.status || '').toUpperCase()
  const done = status === 'FINAL'
  const sideA = readableSide(match, 'A', matches)
  const sideB = readableSide(match, 'B', matches)
  const winnerA = done && match.winner_team_id != null && match.winner_team_id === match.team1_id
  const winnerB = done && match.winner_team_id != null && match.winner_team_id === match.team2_id
  return (
    <button
      type="button"
      draggable={!done}
      onDragStart={(event) => { event.dataTransfer.setData('text/match-id', String(match.match_id)); event.dataTransfer.effectAllowed = 'move'; onDragStart() }}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      style={{ ...cardButton, background: done ? '#eceff1' : '#e3f2fd' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 2, fontSize: compact ? 9 : 10, fontWeight: 800 }}>
        <span>#{match.match_number}</span>
        {hasNotes && <span role="button" title="Player notes exist." onClick={(event) => { event.stopPropagation(); onNotes() }} style={noteMark}>N</span>}
      </div>
      <NameLines a={sideA.label} b={sideB.label} compact={compact} emphasizeA={winnerA} emphasizeB={winnerB} />
      {done && <div style={{ fontSize: 10, fontWeight: 800 }}>{match.score_display || 'Completed'}</div>}
    </button>
  )
}

function NameLines({ a, b, compact, emphasizeA = false, emphasizeB = false }: { a: string; b: string; compact: boolean; emphasizeA?: boolean; emphasizeB?: boolean }) {
  const groups = [
    { lines: firstNameLines(a), emphasize: emphasizeA },
    { lines: firstNameLines(b), emphasize: emphasizeB },
  ]
  return (
    <div style={{ fontSize: compact ? 9 : 11, lineHeight: 1.15 }}>
      {groups.map((group, groupIndex) => (
        <div key={groupIndex}>
          {groupIndex > 0 && <div style={{ borderTop: '1px solid rgba(0,0,0,0.28)', margin: '2px 0' }} />}
          {group.lines.map((line, index) => (
            <div key={`${line}-${index}`} style={{ fontWeight: group.emphasize ? 900 : 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{line}</div>
          ))}
        </div>
      ))}
    </div>
  )
}

function CourtPanel({
  schedule, courtNumber, note, onNote, onClose, onSave,
}: {
  schedule: DaySchedule
  courtNumber: number
  note: string
  onNote: (value: string) => void
  onClose: () => void
  onSave: (closed: boolean) => void
}) {
  const court = schedule.courts.find((row) => row.courtNumber === courtNumber)
  if (!court) return null
  return (
    <div style={{ border: '1px solid #cfd8dc', borderRadius: 8, background: '#fff', padding: 10, display: 'grid', gap: 8 }}>
      <div style={{ fontWeight: 800 }}>{court.courtName}</div>
      <input value={note} onChange={(event) => onNote(event.target.value)} placeholder="Closure reason" style={{ padding: 6 }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" onClick={() => onSave(true)}>Close court</button>
        <button type="button" onClick={() => onSave(false)}>Open court</button>
        <button type="button" onClick={onClose}>Done</button>
      </div>
    </div>
  )
}

function chip(active: boolean): CSSProperties {
  return { border: '1px solid #1a237e', background: active ? '#1a237e' : '#fff', color: active ? '#fff' : '#1a237e', borderRadius: 6, padding: '4px 8px', fontSize: 12, fontWeight: 800, cursor: 'pointer' }
}

const startButton: CSSProperties = { border: 'none', background: '#2e7d32', color: '#fff', borderRadius: 6, padding: '4px 10px', fontSize: 12, fontWeight: 800, cursor: 'pointer' }
const startedPill: CSSProperties = { background: '#e8f5e9', color: '#1b5e20', borderRadius: 6, padding: '4px 10px', fontSize: 12, fontWeight: 800 }
const corner: CSSProperties = { background: '#1a237e', color: '#fff', fontSize: 10, fontWeight: 800, padding: '6px 2px', textAlign: 'center', borderRadius: 4 }
const timeCell: CSSProperties = { fontSize: 10, fontWeight: 800, color: '#37474f', padding: '4px 2px', textAlign: 'center' }
const liveCard: CSSProperties = { minHeight: 72, borderRadius: 6, padding: '4px 5px', textAlign: 'left', border: '1px solid rgba(0,0,0,0.08)', minWidth: 0, overflow: 'hidden' }
const liveTop: CSSProperties = { display: 'flex', justifyContent: 'space-between', fontSize: 10, fontWeight: 800 }
const liveMeta: CSSProperties = { fontSize: 9, fontWeight: 700, marginTop: 2 }
const cardButton: CSSProperties = { display: 'block', width: '100%', textAlign: 'left', border: '1px solid rgba(0,0,0,0.08)', borderRadius: 6, padding: '3px 4px', cursor: 'grab', minWidth: 0 }
const placeholderButton: CSSProperties = { width: '100%', border: 'none', background: 'transparent', color: '#e65100', fontWeight: 800, fontSize: 10, cursor: 'pointer', padding: 4 }
const noteMark: CSSProperties = { width: 14, height: 14, borderRadius: 3, background: '#f9a825', color: '#fff', fontSize: 9, fontWeight: 800, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }

function headerButton(court: ScheduleCourt): CSSProperties {
  const background = court.closed ? '#ffcdd2' : court.unavailable ? '#37474f' : '#e3f2fd'
  const color = court.unavailable && !court.closed ? '#eceff1' : '#1a237e'
  return { background, color, border: 'none', borderRadius: 4, fontSize: 10, fontWeight: 800, padding: '6px 2px', cursor: 'pointer', minWidth: 0 }
}

function gridCellStyle(cell: ScheduleCell | null, court: ScheduleCourt, playing: boolean): CSSProperties {
  let background = '#e8f5e9'
  if (!cell || cell.slot.is_active === false) background = '#37474f'
  else if (court.closed) background = '#ffcdd2'
  else if (playing) background = '#ffe0b2'
  else if (cell.match && (cell.match.status || '').toUpperCase() === 'FINAL') background = '#eceff1'
  else if (cell.match) background = '#e3f2fd'
  return { minHeight: 58, borderRadius: 6, padding: 2, minWidth: 0, background }
}

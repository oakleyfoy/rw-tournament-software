import { useEffect, useRef, useState, type CSSProperties } from 'react'
import type { DeskMatchItem, SnapshotSlot } from '../../api/client'
import { getCompactDivisionLabel } from '../../utils/matchDivisionLabel'
import {
  COURT_TONE,
  buildLiveCourts,
  cardStatus,
  cellTone,
  courtHeaderTone,
  isDelayed,
  liveBoardLayout,
  matchNeedsReassignment,
  readableSide,
  scheduleColumnLayout,
  slotAcceptsMove,
  summarizeDay,
  type CardStatus,
  type DaySchedule,
} from './courtSheet'

const STATUS_STYLE: Record<CardStatus, { bg: string; label: string }> = {
  playing: { bg: '#ffe0b2', label: 'In progress' },
  ready: { bg: '#c8e6c9', label: 'Ready to play' },
  waiting: { bg: '#fff59d', label: 'Waiting for players' },
  awaiting: { bg: '#fff59d', label: 'Awaiting result' },
  scheduled: { bg: '#e3f2fd', label: 'Scheduled' },
  completed: { bg: '#eceff1', label: 'Completed' },
  delayed: { bg: '#ffebee', label: 'Delayed' },
}

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
  onMove: (matchId: number, slotId: number) => void
  onSwap: (matchId: number, occupantId: number) => void
  onUndo: () => void
  onCourtState: (courtLabel: string, closed: boolean, note: string) => void
  onInteractionChange?: (active: boolean) => void
  rosterByTeam?: Record<number, { id: number; name: string }[]>
  notedPlayerIds?: number[]
  teamNotesById?: Record<number, string | null>
  onOpenNotes?: (players: { id: number; name: string }[], teamNotes: { label: string; body: string }[]) => void
}

function participantsFor(match: DeskMatchItem, roster: Record<number, { id: number; name: string }[]>) {
  return [match.team1_id, match.team2_id].flatMap((teamId) => (teamId == null ? [] : roster[teamId] || []))
}

function dayLabel(day: string): string {
  const date = new Date(`${day}T12:00:00`)
  if (Number.isNaN(date.getTime())) return day
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

function MatchCard({
  match,
  matches,
  checkinReady,
  nowMinutes,
  compact,
  reassign,
  onOpen,
  onDragStart,
  onDragEnd,
  hasNotes,
  onNotes,
}: {
  match: DeskMatchItem
  matches: DeskMatchItem[]
  checkinReady: boolean
  nowMinutes: number | null
  compact: boolean
  reassign?: boolean
  onOpen: () => void
  onDragStart?: () => void
  onDragEnd?: () => void
  hasNotes?: boolean
  onNotes?: () => void
}) {
  const status = cardStatus(match, checkinReady, nowMinutes)
  const delayed = isDelayed(match, nowMinutes)
  const tone = STATUS_STYLE[delayed ? 'delayed' : status]
  const sideA = readableSide(match, 'A', matches)
  const sideB = readableSide(match, 'B', matches)
  const division = getCompactDivisionLabel(match.match_code)
  return (
    <button
      type="button"
      draggable={(match.status || '').toUpperCase() !== 'FINAL'}
      onDragStart={(event) => {
        event.dataTransfer.setData('text/match-id', String(match.match_id))
        event.dataTransfer.effectAllowed = 'move'
        onDragStart?.()
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={onOpen}
      title={`${sideA.label} vs ${sideB.label}`}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        border: delayed ? '2px solid #c62828' : '1px solid rgba(0,0,0,0.12)',
        background: tone.bg,
        borderRadius: 6,
        padding: compact ? '3px 4px' : '6px 7px',
        cursor: 'grab',
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 4, fontSize: compact ? 9 : 10, fontWeight: 800 }}>
        <span>#{match.match_number}</span>
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {hasNotes && (
            <span
              role="button"
              title="Player notes exist."
              onClick={(event) => {
                event.stopPropagation()
                onNotes?.()
              }}
              style={{ width: 14, height: 14, borderRadius: 3, background: '#f9a825', color: '#fff', fontSize: 9, fontWeight: 800, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            >
              N
            </span>
          )}
          <span style={{ background: '#455a64', color: '#fff', borderRadius: 3, padding: '0 3px' }}>{division}</span>
        </span>
      </div>
      <div style={{ fontSize: compact ? 10 : 11, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sideA.label}</div>
      <div style={{ fontSize: compact ? 10 : 11, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sideB.label}</div>
      <div style={{ fontSize: 9, fontWeight: 800, marginTop: 2 }}>{delayed ? 'Delayed' : tone.label}{match.scheduled_time ? ` · ${match.scheduled_time}` : ''}{reassign ? ' · Reassign' : ''}</div>
    </button>
  )
}

export default function DesignatedCourtSheet(props: Props) {
  const {
    schedule, days, selectedDay, onSelectDay, checkinReadyByMatchId, matches,
    nowMinutes, isToday, clockLabel, syncedLabel, isDraft, busyMatchId, canUndo,
    onOpenMatch, onStart, onMove, onSwap, onUndo, onCourtState, onInteractionChange,
    rosterByTeam = {}, notedPlayerIds = [], teamNotesById = {}, onOpenNotes,
  } = props
  const noted = new Set(notedPlayerIds)
  const noteState = (match: DeskMatchItem) => {
    const players = participantsFor(match, rosterByTeam)
    const teamNotes = [match.team1_id, match.team2_id].flatMap((teamId, index) => {
      const body = teamId == null ? '' : (teamNotesById[teamId] || '')
      return body ? [{ label: index === 0 ? 'Team 1 note' : 'Team 2 note', body }] : []
    })
    const hasPlayerNote = players.some((player) => noted.has(player.id))
    return { players, teamNotes, hasNotes: hasPlayerNote || teamNotes.length > 0 }
  }
  const rootRef = useRef<HTMLDivElement | null>(null)
  const boardRef = useRef<HTMLDivElement | null>(null)
  const [view, setView] = useState<'schedule' | 'live'>('schedule')
  const [fitAll, setFitAll] = useState(true)
  const [showCompleted, setShowCompleted] = useState(false)
  const [dragMatchId, setDragMatchId] = useState<number | null>(null)
  const [hoverSlotId, setHoverSlotId] = useState<number | null>(null)
  const [courtPanel, setCourtPanel] = useState<number | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [box, setBox] = useState({ width: 1280, height: 640 })
  const summary = summarizeDay(schedule, checkinReadyByMatchId, isToday ? nowMinutes : null)
  const live = buildLiveCourts(schedule)
  const courtCount = Math.max(schedule.courts.length, 1)
  const compact = box.width / courtCount < 120
  const liveLayout = liveBoardLayout(box.width, box.height, schedule.courts.length)
  const columnLayout = scheduleColumnLayout(box.width, schedule.courts.length)

  useEffect(() => {
    const node = boardRef.current
    if (!node) return
    const measure = () => setBox({ width: node.clientWidth, height: node.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [view, schedule.day, schedule.courts.length])

  const hold = (active: boolean) => onInteractionChange?.(active)

  const hoverCell = () => {
    for (const row of schedule.rows) {
      for (let index = 0; index < row.cells.length; index += 1) {
        const cell = row.cells[index]
        if (cell?.slot.slot_id === hoverSlotId) return { cell, court: schedule.courts[index] }
      }
    }
    return null
  }
  const hovered = hoverCell()
  const hoverValid = hovered ? slotAcceptsMove(hovered.cell.slot, hovered.court.closed) : false

  const dropOnSlot = (matchId: number, slot: SnapshotSlot, courtClosed: boolean) => {
    if (!slotAcceptsMove(slot, courtClosed)) return
    const match = matches.find((row) => row.match_id === matchId)
    if (!match || match.slot_id === slot.slot_id) return
    const occupantId = slot.assigned_match_id
    if (occupantId && occupantId !== match.match_id) {
      const occupant = matches.find((row) => row.match_id === occupantId)
      const swap = window.confirm(`Swap #${match.match_number} with #${occupant?.match_number || occupantId}?`)
      if (!swap) return
      onSwap(match.match_id, occupantId)
      return
    }
    if (['IN_PROGRESS', 'PAUSED'].includes((match.status || '').toUpperCase())) {
      const ok = window.confirm(`Match #${match.match_number} is already playing. Move it anyway?`)
      if (!ok) return
    }
    onMove(match.match_id, slot.slot_id)
  }

  const requestFullscreen = () => {
    const node = rootRef.current
    if (!node) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else void node.requestFullscreen()
  }

  return (
    <div ref={rootRef} data-testid="court-sheet" style={{ background: '#f7f8fa', padding: 8, display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        {days.map((day) => (
          <button key={day} type="button" onClick={() => onSelectDay(day)} style={chip(selectedDay === day)}>
            {dayLabel(day)}
          </button>
        ))}
        <button type="button" onClick={() => setView('schedule')} style={chip(view === 'schedule')}>Full Schedule</button>
        <button type="button" onClick={() => setView('live')} style={chip(view === 'live')}>Live Courts</button>
        <button type="button" onClick={() => setFitAll((value) => !value)} style={chip(fitAll)}>Fit all courts</button>
        <button type="button" onClick={requestFullscreen} style={chip(false)}>Full screen</button>
        <button type="button" onClick={() => setShowCompleted((value) => !value)} style={chip(showCompleted)}>Completed in live view</button>
        <button type="button" disabled={!canUndo || !isDraft} onClick={onUndo} style={chip(false)}>Undo move</button>
        <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 700, color: '#455a64' }}>{clockLabel} · {syncedLabel}</span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 11, fontWeight: 800, color: '#37474f' }}>
        <span>{summary.totalCourts} courts</span>
        <span>{summary.openCourts} open</span>
        <span>{summary.inUse} in use</span>
        <span>{summary.closed} closed</span>
        <span>{summary.unavailable} unavailable</span>
        <span>{summary.inProgress} playing</span>
        <span>{summary.ready} ready</span>
        <span>{summary.waiting} waiting</span>
        <span>{summary.completed} completed</span>
        <span>{summary.remaining} remaining</span>
        <span>{summary.delayed} delayed</span>
      </div>

      {!columnLayout.fits && view === 'schedule' && fitAll && (
        <div style={{ fontSize: 11, fontWeight: 800, color: '#b71c1c' }}>
          {schedule.courts.length} courts need about {columnLayout.neededWidth}px of width. This board is {box.width}px wide.
        </div>
      )}
      {!liveLayout.fits && view === 'live' && (
        <div style={{ fontSize: 11, fontWeight: 800, color: '#b71c1c' }}>
          {schedule.courts.length} courts need about {liveLayout.neededWidth}×{liveLayout.neededHeight}px. This board is {box.width}×{box.height}.
        </div>
      )}
      {view === 'schedule' ? (
        <div ref={boardRef} data-testid="court-schedule-board" style={{ flex: 1, minHeight: 0, overflowX: fitAll ? 'hidden' : 'auto', overflowY: 'auto' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: fitAll
                ? `56px repeat(${courtCount}, minmax(0, 1fr))`
                : `56px repeat(${courtCount}, minmax(150px, 1fr))`,
              width: fitAll ? '100%' : 'max-content',
              minWidth: fitAll ? 0 : undefined,
              gap: 3,
            }}
          >
            <div style={headerCell}>Time</div>
            {schedule.courts.map((court, courtIndex) => {
              const playing = schedule.rows.some((row) => {
                const status = (row.cells[courtIndex]?.match?.status || '').toUpperCase()
                return status === 'IN_PROGRESS' || status === 'PAUSED'
              })
              const tone = COURT_TONE[courtHeaderTone(court, playing)]
              return (
              <button
                key={court.courtNumber}
                type="button"
                onClick={() => {
                  setCourtPanel(court.courtNumber)
                  setNoteDraft('')
                  hold(true)
                }}
                style={{
                  ...headerCell,
                  background: tone.bg,
                  color: tone.fg,
                  cursor: 'pointer',
                }}
              >
                {court.courtName}
                <div style={{ fontSize: 9 }}>{tone.label}</div>
              </button>
              )
            })}
            {schedule.rows.map((row) => {
              const rowMinutes = Number(row.time.slice(0, 2)) * 60 + Number(row.time.slice(3, 5))
              const current = isToday && nowMinutes != null && rowMinutes <= nowMinutes && nowMinutes < rowMinutes + 60
              return (
                <div key={row.time} style={{ display: 'contents' }}>
                  <div style={{ ...timeCell, boxShadow: current ? 'inset 3px 0 0 #1565c0' : undefined }}>{row.timeLabel}</div>
                  {row.cells.map((cell, index) => {
                    const court = schedule.courts[index]
                    const hot = cell?.slot.slot_id === hoverSlotId
                    const tone = COURT_TONE[cellTone(cell, court)]
                    return (
                      <div
                        key={`${row.time}-${court.courtNumber}`}
                        onDragOver={(event) => {
                          if (!cell) return
                          event.preventDefault()
                          const id = Number(event.dataTransfer.getData('text/match-id') || dragMatchId || 0)
                          if (id) setDragMatchId(id)
                          setHoverSlotId(cell.slot.slot_id)
                          hold(true)
                        }}
                        onDrop={(event) => {
                          event.preventDefault()
                          if (!cell) return
                          const id = Number(event.dataTransfer.getData('text/match-id'))
                          if (id) dropOnSlot(id, cell.slot, court.closed)
                          setHoverSlotId(null)
                          setDragMatchId(null)
                          hold(false)
                        }}
                        style={{
                          minHeight: compact ? 58 : 72,
                          minWidth: 0,
                          borderRadius: 6,
                          padding: 2,
                          background: hot ? (hoverValid ? '#a5d6a7' : '#ef9a9a') : tone.bg,
                          color: tone.fg,
                        }}
                      >
                        {cell?.match && (
                          <MatchCard
                            match={cell.match}
                            matches={matches}
                            checkinReady={Boolean(checkinReadyByMatchId.get(cell.match.match_id))}
                            nowMinutes={isToday ? nowMinutes : null}
                            compact={compact}
                            reassign={matchNeedsReassignment(cell, court)}
                            onDragStart={() => hold(true)}
                            onDragEnd={() => hold(false)}
                            onOpen={() => onOpenMatch(cell.match as DeskMatchItem)}
                            hasNotes={noteState(cell.match as DeskMatchItem).hasNotes}
                            onNotes={() => {
                              const state = noteState(cell.match as DeskMatchItem)
                              onOpenNotes?.(state.players, state.teamNotes)
                            }}
                          />
                        )}
                        {cell && !cell.match && (
                          <div style={{ fontSize: 10, fontWeight: 800, padding: 4 }}>{tone.label}</div>
                        )}
                        {!cell && <div style={{ fontSize: 10, fontWeight: 800, padding: 4 }}>UNAVAILABLE</div>}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <div
          ref={boardRef}
          data-testid="court-live-board"
          style={{
            flex: 1,
            minHeight: 0,
            overflow: liveLayout.fits ? 'hidden' : 'auto',
            display: 'grid',
            gridTemplateColumns: `repeat(${liveLayout.columns}, minmax(0, 1fr))`,
            gridTemplateRows: liveLayout.fits ? `repeat(${liveLayout.rows}, minmax(0, 1fr))` : undefined,
            gap: 6,
          }}
        >
          {live.map((column) => {
            const tone = COURT_TONE[courtHeaderTone(column.court, Boolean(column.playing))]
            const current = column.playing || column.upcoming[0] || null
            const laterCount = column.playing ? column.upcoming.length : Math.max(0, column.upcoming.length - 1)
            const currentCell = current
              ? schedule.rows.flatMap((row) => row.cells).find((cell) => cell?.match?.match_id === current.match_id) || null
              : null
            const currentCourtIndex = schedule.courts.findIndex((court) => court.courtNumber === column.court.courtNumber)
            return (
            <div
              key={column.court.courtNumber}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                const id = Number(event.dataTransfer.getData('text/match-id'))
                if (!id) return
                const sourceRow = schedule.rows.find((row) => row.cells.some((cell) => cell?.match?.match_id === id))
                const destIndex = schedule.courts.findIndex((court) => court.courtNumber === column.court.courtNumber)
                const dest = sourceRow?.cells[destIndex]
                if (dest) dropOnSlot(id, dest.slot, column.court.closed)
                hold(false)
              }}
              style={{ border: `2px solid ${tone.fg}`, borderRadius: 8, background: tone.bg, minWidth: 0, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
            >
              <button
                type="button"
                onClick={() => {
                  setCourtPanel(column.court.courtNumber)
                  hold(true)
                }}
                style={{ ...headerCell, width: '100%', background: tone.bg, color: tone.fg }}
              >
                {column.court.courtName}
                <div style={{ fontSize: 9 }}>{tone.label}</div>
              </button>
              <div style={{ padding: 4, display: 'grid', gap: 4, minHeight: 0 }}>
                {current ? (
                  <MatchCard
                    match={current}
                    matches={matches}
                    checkinReady={Boolean(checkinReadyByMatchId.get(current.match_id))}
                    nowMinutes={isToday ? nowMinutes : null}
                    compact={compact}
                    reassign={matchNeedsReassignment(currentCell, schedule.courts[currentCourtIndex] || column.court)}
                    onDragStart={() => hold(true)}
                    onDragEnd={() => hold(false)}
                    onOpen={() => onOpenMatch(current)}
                    hasNotes={noteState(current).hasNotes}
                    onNotes={() => {
                      const state = noteState(current)
                      onOpenNotes?.(state.players, state.teamNotes)
                    }}
                  />
                ) : (
                  <div style={{ fontSize: 12, fontWeight: 800, color: tone.fg, padding: 6 }}>{tone.label}</div>
                )}
                {!column.playing && current && cardStatus(current, Boolean(checkinReadyByMatchId.get(current.match_id)), isToday ? nowMinutes : null) === 'ready' && (
                  <button
                    type="button"
                    disabled={!isDraft || busyMatchId != null}
                    onClick={() => onStart(current.match_id)}
                    style={{ fontSize: 10, fontWeight: 800 }}
                  >
                    Start
                  </button>
                )}
                {laterCount > 0 && <div style={{ fontSize: 10, fontWeight: 800 }}>+{laterCount} later</div>}
                {showCompleted && column.completed.length > 0 && (
                  <div style={{ fontSize: 10, fontWeight: 800 }}>{column.completed.length} completed</div>
                )}
              </div>
            </div>
            )
          })}
        </div>
      )}

      {courtPanel != null && (
        <CourtPanel
          schedule={schedule}
          courtNumber={courtPanel}
          note={noteDraft}
          onNote={setNoteDraft}
          onClose={() => { setCourtPanel(null); hold(false) }}
          onSave={(closed) => {
            const court = schedule.courts.find((row) => row.courtNumber === courtPanel)
            if (!court) return
            onCourtState(court.courtLabel, closed, noteDraft)
            setCourtPanel(null)
            hold(false)
          }}
        />
      )}
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
  const affected = schedule.rows.flatMap((row) => {
    const index = schedule.courts.findIndex((item) => item.courtNumber === courtNumber)
    const match = row.cells[index]?.match
    if (!match || (match.status || '').toUpperCase() === 'FINAL') return []
    return [`#${match.match_number} · ${row.timeLabel}`]
  })
  return (
    <div style={{ border: '1px solid #cfd8dc', borderRadius: 8, background: '#fff', padding: 10, display: 'grid', gap: 8 }}>
      <div style={{ fontWeight: 800 }}>{court.courtName}</div>
      <div style={{ fontSize: 12 }}>{court.closed ? 'Closed' : court.unavailable ? 'Unavailable' : 'Open'}. Assigned matches stay on the schedule.</div>
      {affected.length > 0 && <div style={{ fontSize: 12 }}>{affected.join(' · ')}</div>}
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
  return {
    border: '1px solid #1a237e',
    background: active ? '#1a237e' : '#fff',
    color: active ? '#fff' : '#1a237e',
    borderRadius: 6,
    padding: '4px 8px',
    fontSize: 12,
    fontWeight: 800,
    cursor: 'pointer',
  }
}

const headerCell: CSSProperties = {
  position: 'sticky',
  top: 0,
  zIndex: 2,
  background: '#eceff1',
  fontSize: 11,
  fontWeight: 800,
  padding: '4px 2px',
  textAlign: 'center',
  border: 'none',
  minWidth: 0,
  overflow: 'hidden',
}

const timeCell: CSSProperties = {
  position: 'sticky',
  left: 0,
  zIndex: 1,
  background: '#fff',
  fontSize: 10,
  fontWeight: 800,
  padding: '4px 2px',
}

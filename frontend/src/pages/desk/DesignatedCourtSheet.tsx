import { useEffect, useRef, useState, type CSSProperties, type DragEvent, type ReactNode } from 'react'
import type { DeskMatchItem, SnapshotSlot } from '../../api/client'
import { TeamPhotoThumb } from '../../components/TeamPhotoThumb'
import MatchTextDialog, { type MatchTextPlayer, type MatchTextResult } from './MatchTextDialog'
import {
  activeTimeTint,
  autoStartDecision,
  compactScheduledTime,
  COMPLETED_CARD,
  courtOpenAt,
  divisionAbbreviation,
  drawAbbreviation,
  earliestUnfinished,
  elapsedMinutes,
  firstNameLines,
  formatElapsed,
  formatSlotTime,
  readableSide,
  SCHEDULED_CARD,
  settleClock,
  simulatedClockMs,
  type ClockHold,
  type DaySchedule,
  type ScheduleCell,
  type ScheduleCourt,
  type SlotCover,
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
  onMakeCourtAvailable?: (input: {
    dayDate: string
    courtNumber: number
    scope: 'slot' | 'range' | 'rest'
    action: 'open' | 'close'
    startTime: string
    endTime?: string
  }) => Promise<void>
  onRestoreCourtAvailability?: (input: { dayDate: string; courtNumber: number }) => Promise<string | null>
  onInteractionChange?: (active: boolean) => void
  rosterByTeam?: Record<number, { id: number; name: string; phone?: string | null; consent?: string | null; slot?: 1 | 2 }[]>
  onSendMatchText?: (players: MatchTextPlayer[], message: string) => Promise<MatchTextResult[]>
  notedPlayerIds?: number[]
  teamNotesById?: Record<number, string | null>
  onOpenNotes?: (
    players: { id: number; name: string; team?: 1 | 2 }[],
    teamNotes: { label: string; body: string }[],
    teamLabels?: { 1: string; 2: string },
  ) => void
  dayStarted?: boolean
  dayPaused?: boolean
  arrivedTeamIds?: number[]
  onStartDay?: () => void
  onSetPaused?: (paused: boolean) => void
  courtNotes?: Record<string, string>
  isCopy?: boolean
  testClock?: string | null
  simulatedAt?: string | null
  serverNow?: string | null
  clockFrozen?: boolean
  onSetTestClock?: (time: string | null) => void
  onAdvanceClock?: (minutes: number) => void
  onFreezeClock?: (frozen: boolean) => void
  canSimulate?: boolean
  onOpenSimulation?: () => void
  trophyPending?: number
  onOpenTrophies?: () => void
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

function elapsedLabel(startedAt: string | null, nowMs: number, isCopy: boolean, matchDay: string | null): { text: string; title: string } {
  const minutes = elapsedMinutes(startedAt, nowMs, matchDay, isCopy)
  if (minutes == null) {
    return { text: '—', title: 'This match was started before the test clock. Duplicate a fresh copy to rehearse it.' }
  }
  return { text: formatElapsed(minutes), title: '' }
}

function clockLabelFromMs(clockMs: number): string {
  const date = new Date(clockMs)
  const hour = date.getUTCHours()
  const minute = date.getUTCMinutes()
  const suffix = hour < 12 ? 'AM' : 'PM'
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${suffix}`
}

function courtMatches(schedule: DaySchedule, courtNumber: number): { court: ScheduleCourt; cells: ScheduleCell[]; covers: SlotCover[] } {
  const index = schedule.courts.findIndex((court) => court.courtNumber === courtNumber)
  const court = schedule.courts[index]
  const cells: ScheduleCell[] = []
  const covers: SlotCover[] = []
  for (const row of schedule.rows) {
    const cell = row.cells[index]
    const minutes = minutesFromSort(row.time)
    if (minutes != null) covers.push({ minutes, active: Boolean(cell && cell.slot.is_active !== false) })
    if (cell) cells.push(cell)
  }
  return { court, cells, covers }
}

export default function DesignatedCourtSheet(props: Props) {
  const {
    schedule, days, selectedDay, onSelectDay, matches, nowMinutes, clockLabel, syncedLabel,
    isDraft, canUndo, onOpenMatch, onMove, onSwap, onUndo, onCourtState, onInteractionChange,
    rosterByTeam = {}, notedPlayerIds = [], teamNotesById = {}, onOpenNotes,
    dayStarted = false, dayPaused = false, onStartDay, onSetPaused, courtNotes = {},
    isCopy = false, testClock = null, simulatedAt = null, serverNow = null, clockFrozen = false,
    onSetTestClock, onAdvanceClock, onFreezeClock, canSimulate = false, onOpenSimulation,
    trophyPending = 0, onOpenTrophies, onMakeCourtAvailable, onRestoreCourtAvailability,
  } = props
  const [availabilityCourt, setAvailabilityCourt] = useState<{ court: ScheduleCourt; slot: SnapshotSlot } | null>(null)
  const [dragMatchId, setDragMatchId] = useState<number | null>(null)
  const [courtPanel, setCourtPanel] = useState<number | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [tick, setTick] = useState(() => Date.now())
  const [textMatch, setTextMatch] = useState<DeskMatchItem | null>(null)
  const clockState = useRef<ClockHold | null>(null)
  if (!isCopy) clockState.current = null
  else clockState.current = settleClock(clockState.current, simulatedClockMs(simulatedAt, serverNow, clockFrozen, tick), tick, clockFrozen)
  const clockMs = isCopy ? clockState.current?.operationalMs ?? null : null
  const liveMinutes = clockMs != null
    ? new Date(clockMs).getUTCHours() * 60 + new Date(clockMs).getUTCMinutes()
    : nowMinutes
  const clockText = clockMs != null ? clockLabelFromMs(clockMs) : (testClock || '')
  const noted = new Set(notedPlayerIds)
  const slotTimes = schedule.rows.map((row) => row.time)
  const courtCount = Math.max(schedule.courts.length, 1)
  const compact = courtCount >= 16
  const photoSize = courtCount >= 20 ? 18 : compact ? 22 : courtCount <= 6 ? 34 : 28
  const columns = `64px repeat(${courtCount}, minmax(0, 1fr))`

  useEffect(() => {
    const timer = window.setInterval(() => setTick(Date.now()), 1000)
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

  const textPlayers = (match: DeskMatchItem): MatchTextPlayer[] => {
    const fromTeam = (teamId: number | null, team: 1 | 2) => (
      teamId == null ? [] : (rosterByTeam[teamId] || []).map((player) => ({
        id: player.id,
        name: player.name,
        phone: player.phone || null,
        consent: player.consent || null,
        team,
      }))
    )
    return [...fromTeam(match.team1_id, 1), ...fromTeam(match.team2_id, 2)]
  }

  const noteState = (match: DeskMatchItem) => {
    const fromTeam = (teamId: number | null, team: 1 | 2) => (
      teamId == null ? [] : (rosterByTeam[teamId] || []).map((player) => ({ id: player.id, name: player.name, team }))
    )
    const players = [...fromTeam(match.team1_id, 1), ...fromTeam(match.team2_id, 2)]
    const teamNotes = [match.team1_id, match.team2_id].flatMap((teamId, index) => {
      const body = teamId == null ? '' : (teamNotesById[teamId] || '')
      return body ? [{ label: index === 0 ? 'Team 1 note' : 'Team 2 note', body }] : []
    })
    return {
      players,
      teamNotes,
      teamLabels: { 1: match.team1_display || 'Team 1', 2: match.team2_display || 'Team 2' } as { 1: string; 2: string },
      hasNotes: players.some((player) => noted.has(player.id)) || teamNotes.length > 0,
      showNotes: (match.status || '').toUpperCase() === 'FINAL' || LIVE.has((match.status || '').toUpperCase()) || players.length > 0,
    }
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
    const early = scheduledMinutes != null && liveMinutes != null && liveMinutes < scheduledMinutes - 15
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
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 800, color: '#37474f' }}>
            Test clock {clockText}
            <input
              type="time"
              aria-label="Set test clock"
              defaultValue={testClock || ''}
              key={testClock || 'clock'}
              onBlur={(event) => { if (event.target.value) onSetTestClock?.(event.target.value) }}
              style={{ fontSize: 12 }}
            />
            {[5, 15, 30].map((minutes) => (
              <button key={minutes} type="button" onClick={() => onAdvanceClock?.(minutes)} style={chip(false)}>+{minutes}m</button>
            ))}
            <button type="button" onClick={() => onFreezeClock?.(!clockFrozen)} style={chip(clockFrozen)}>
              {clockFrozen ? 'Resume clock' : 'Freeze clock'}
            </button>
            {canSimulate && <button type="button" onClick={onOpenSimulation} style={chip(false)}>Simulate Results</button>}
            <span style={{ fontWeight: 700, color: '#b71c1c' }}>Texts off</span>
          </span>
        )}
        <button type="button" disabled={!canUndo || !isDraft} onClick={onUndo} style={chip(false)}>Undo Move</button>
        {onOpenTrophies && (
          <button type="button" onClick={onOpenTrophies} aria-label="Trophy distribution" title="Trophy distribution" style={{ ...chip(false), display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <TrophyIcon gold />
            {trophyPending > 0 && <span style={{ fontWeight: 800, color: '#8a6d1d' }}>{trophyPending}</span>}
          </button>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 800, color: '#37474f' }}>{clockMs != null ? clockText : clockLabel} · {syncedLabel}</span>
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
            const { cells, covers } = courtMatches(schedule, court.courtNumber)
            return (
              <LiveCell
                key={`live-${court.courtNumber}`}
                court={court}
                cells={cells}
                covers={covers}
                compact={compact}
                photoSize={photoSize}
                tick={tick}
                isCopy={isCopy}
                clockMs={clockMs}
                dayStarted={dayStarted}
                dayPaused={dayPaused}
                nowMinutes={liveMinutes}
                liveTeamIds={liveTeamIds}
                matches={matches}
                noteFor={noteState}
                recipientCount={(match) => textPlayers(match).length}
                slotTimes={slotTimes}
                onOpen={onOpenMatch}
                onText={setTextMatch}
                onOpenNotes={onOpenNotes}
                onDrop={(matchId) => dropOnLive(matchId, court)}
                onDragState={hold}
                onUnavailable={(slot) => setAvailabilityCourt({ court, slot })}
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
                    style={gridCellStyle(cell, court, playing, slotTimes)}
                  >
                    {playing && match ? (
                      <button type="button" onClick={() => onOpenMatch(match)} style={{ ...placeholderButton, background: activeTimeTint(match.sort_time, slotTimes).bg, color: '#1a1a1a', border: `1px solid ${activeTimeTint(match.sort_time, slotTimes).border}` }}>
                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2 }}>
                          <span>↑ Playing {drawAbbreviation(match.event_name, match.match_code)}</span>
                          {match.championship_final && <TrophyIcon gold title="Championship Final — Trophy Match." />}
                        </span>
                      </button>
                    ) : match ? (
                      <GridCard
                        match={match}
                        matches={matches}
                        compact={compact}
                        photoSize={photoSize}
                        hasNotes={noteState(match).hasNotes}
                        showNotes={noteState(match).showNotes}
                        canText={textPlayers(match).length > 0}
                        onOpen={() => onOpenMatch(match)}
                        onText={() => setTextMatch(match)}
                        onNotes={() => {
                          const notes = noteState(match)
                          onOpenNotes?.(notes.players, notes.teamNotes, notes.teamLabels)
                        }}
                        onDragStart={() => { setDragMatchId(match.match_id); hold(true) }}
                        onDragEnd={() => { setDragMatchId(null); hold(false) }}
                      />
                    ) : !cell || cell.slot.is_active === false ? (
                      <button
                        type="button"
                        onClick={() => { if (cell) setAvailabilityCourt({ court, slot: cell.slot }) }}
                        style={{ width: '100%', border: 'none', background: 'transparent', color: '#eceff1', fontSize: 10, fontWeight: 800, cursor: cell ? 'pointer' : 'default', padding: 4 }}
                      >
                        Unavailable
                      </button>
                    ) : court.closed ? (
                      <span style={{ fontSize: 10, fontWeight: 800, color: '#b71c1c' }}>Closed</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => { if (cell) setAvailabilityCourt({ court, slot: cell.slot }) }}
                        style={{ width: '100%', border: 'none', background: 'transparent', color: '#1b5e20', fontSize: 10, fontWeight: 800, cursor: 'pointer', padding: 4 }}
                      >
                        Open
                      </button>
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
      {availabilityCourt && (
        <CourtAvailabilityDialog
          schedule={schedule}
          court={availabilityCourt.court}
          slot={availabilityCourt.slot}
          day={selectedDay}
          onClose={() => setAvailabilityCourt(null)}
          onMake={onMakeCourtAvailable}
          onRestore={onRestoreCourtAvailability}
        />
      )}
      {textMatch && (
        <MatchTextDialog
          drawLabel={drawAbbreviation(textMatch.event_name, textMatch.match_code)}
          team1Label={readableSide(textMatch, 'A', matches).label}
          team2Label={readableSide(textMatch, 'B', matches).label}
          players={textPlayers(textMatch)}
          isCopy={isCopy}
          onClose={() => setTextMatch(null)}
          onSend={props.onSendMatchText || (async (players) => players.map((player) => ({ playerId: player.id, status: isCopy ? 'dry_run' : 'failed', error: isCopy ? null : 'Texting is not available.' })))}
        />
      )}
    </div>
  )
}

function coveringCell(cells: ScheduleCell[], nowMinutes: number | null): ScheduleCell | null {
  const ordered = [...cells].sort((a, b) => a.slot.start_time.localeCompare(b.slot.start_time))
  if (!ordered.length) return null
  if (nowMinutes == null) return ordered[0]
  let cover = ordered[0]
  for (const cell of ordered) {
    const minutes = minutesFromSort(cell.slot.start_time)
    if (minutes != null && minutes <= nowMinutes) cover = cell
  }
  return cover
}

function untilLabel(minutes: number | null): string {
  if (minutes == null) return ''
  const hour = Math.floor(minutes / 60)
  const minute = minutes % 60
  const suffix = hour < 12 ? 'AM' : 'PM'
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${suffix}`
}

function LiveCell({
  court, cells, covers, compact, photoSize, tick, isCopy, clockMs, dayStarted, dayPaused, nowMinutes, liveTeamIds, matches, noteFor, recipientCount, slotTimes,   onOpen, onText, onOpenNotes, onDrop, onDragState, onUnavailable,
}: {
  court: ScheduleCourt
  cells: ScheduleCell[]
  covers: SlotCover[]
  compact: boolean
  photoSize: number
  tick: number
  isCopy: boolean
  clockMs: number | null
  dayStarted: boolean
  dayPaused: boolean
  nowMinutes: number | null
  liveTeamIds: Set<number>
  matches: DeskMatchItem[]
  noteFor: (match: DeskMatchItem) => { players: { id: number; name: string; team?: 1 | 2 }[]; teamNotes: { label: string; body: string }[]; teamLabels: { 1: string; 2: string }; hasNotes: boolean; showNotes: boolean }
  recipientCount: (match: DeskMatchItem) => number
  slotTimes: string[]
  onOpen: (match: DeskMatchItem) => void
  onText: (match: DeskMatchItem) => void
  onOpenNotes?: (players: { id: number; name: string; team?: 1 | 2 }[], teamNotes: { label: string; body: string }[], teamLabels?: { 1: string; 2: string }) => void
  onDrop: (matchId: number) => void
  onDragState: (active: boolean) => void
  onUnavailable?: (slot: SnapshotSlot) => void
}) {
  const playing = cells.find((cell) => cell.match && LIVE.has((cell.match.status || '').toUpperCase()))?.match || null
  const upcoming = cells.flatMap((cell) => (cell.match ? [cell.match] : []))
  const earliest = earliestUnfinished(upcoming)
  if (playing) {
    const notes = noteFor(playing)
    const sideA = readableSide(playing, 'A', matches).label
    const sideB = readableSide(playing, 'B', matches).label
    const tint = activeTimeTint(playing.sort_time, slotTimes)
    const elapsed = elapsedLabel(playing.started_at, isCopy && clockMs != null ? clockMs : tick, isCopy, playing.day_date)
    return (
      <button type="button" onClick={() => onOpen(playing)} style={{ ...liveCard, background: tint.bg, border: `1px solid ${tint.border}`, color: '#1a1a1a' }}>
        <CardHeading match={playing} compact={compact} trophy={playing.championship_final ? <TrophyIcon gold title="Championship Final — Trophy Match." /> : null} />
        <NameLines a={sideA} b={sideB} teamA={playing.team1_id} teamB={playing.team2_id} compact={compact} photoSize={photoSize} rrFinalTeamIds={playing.rr_final_team_ids} rrChampionTeamIds={playing.rr_champion_team_ids} rrRunnerUpTeamIds={playing.rr_runner_up_team_ids} />
        <div style={liveMeta}>{compactScheduledTime(playing.scheduled_time || playing.sort_time)}</div>
        <div style={liveMeta} title={elapsed.title}>{elapsed.text}</div>
        <CardActions compact={compact} canText={recipientCount(playing) > 0} showNotes hasNotes={notes.hasNotes} onText={() => onText(playing)} onNotes={() => onOpenNotes?.(notes.players, notes.teamNotes, notes.teamLabels)} />
      </button>
    )
  }
  if (court.closed) {
    return <div style={{ ...liveCard, background: '#ffcdd2', color: '#b71c1c' }}><b>CLOSED</b></div>
  }
  const availability = courtOpenAt(covers, nowMinutes)
  if (!availability.open) {
    const until = untilLabel(availability.untilMinutes)
    const cover = coveringCell(cells, nowMinutes)
    return (
      <button
        type="button"
        onClick={() => { if (cover) onUnavailable?.(cover.slot) }}
        style={{ ...liveCard, background: '#37474f', color: '#eceff1', cursor: 'pointer', width: '100%' }}
      >
        <b style={unavailableLabel}>UNAVAILABLE</b>
        {until && <div style={liveMeta}>Until {until}</div>}
      </button>
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
    const cover = coveringCell(cells, nowMinutes)
    return (
      <div
        onClick={() => { if (cover) onUnavailable?.(cover.slot) }}
        onDragOver={onDragOver}
        onDrop={onDropEvent}
        style={{ ...liveCard, background: '#e8f5e9', color: '#1b5e20', cursor: 'pointer' }}
      >
        <b>OPEN</b>
      </div>
    )
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
  const scheduledMinutes = minutesFromSort(earliest.sort_time || '')
  const inReleaseWindow = scheduledMinutes != null && nowMinutes != null && nowMinutes >= scheduledMinutes - 15
  const waiting = inReleaseWindow && (decision.reason === 'Awaiting result' || decision.reason === 'Player is on another court')
  const nextLabel = earliest.scheduled_time || formatSlotTime(earliest.sort_time || '')
  return (
    <div
      onClick={() => {
        const cover = coveringCell(cells, nowMinutes)
        if (cover) onUnavailable?.(cover.slot)
      }}
      onDragOver={onDragOver}
      onDrop={onDropEvent}
      style={{ ...liveCard, background: waiting ? '#fff59d' : '#e8f5e9', color: waiting ? '#e65100' : '#1b5e20', cursor: 'pointer' }}
    >
      <b>{waiting ? 'WAITING' : 'OPEN'}</b>
      {!waiting && <div style={liveMeta}>Next: {nextLabel}</div>}
      {waiting && <div style={liveMeta}>{decision.reason === 'Awaiting result' ? 'Awaiting result' : 'Player is on another court'}</div>}
    </div>
  )
}

function CardHeading({ match, compact, trophy = null }: { match: DeskMatchItem; compact: boolean; trophy?: ReactNode }) {
  const division = divisionAbbreviation(match.division_name, match.match_code)
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, fontSize: compact ? 9 : 10, fontWeight: 800, color: '#1a1a1a' }}>
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{drawAbbreviation(match.event_name, match.match_code)}</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, flex: '0 0 auto' }}>
        {trophy}
        {division && <span style={{ fontWeight: 700, color: '#37474f' }}>{division}</span>}
      </span>
    </div>
  )
}

function blockCardAction(event: { stopPropagation: () => void; preventDefault: () => void }) {
  event.stopPropagation()
  event.preventDefault()
}

function CardActions({ compact, canText, showNotes, hasNotes, onText, onNotes }: { compact: boolean; canText: boolean; showNotes: boolean; hasNotes: boolean; onText: () => void; onNotes: () => void }) {
  if (!canText && !showNotes) return null
  return (
    <div data-card-action style={{ display: 'flex', gap: 3, marginTop: 2 }}>
      {canText && <span role="button" aria-label="Text Players." title="Text Players." onMouseDown={blockCardAction} onClick={(event) => { blockCardAction(event); onText() }} style={iconButton(compact)}><TextBubbleIcon /></span>}
      {showNotes && <span role="button" aria-label={hasNotes ? 'Player Notes Exist' : 'Player Notes'} title={hasNotes ? 'Player Notes Exist' : 'Player Notes'} onMouseDown={blockCardAction} onClick={(event) => { blockCardAction(event); onNotes() }} style={noteMark(hasNotes, compact)}><NoteIcon /></span>}
    </div>
  )
}

function GridCard({
  match, matches, compact, photoSize, hasNotes, showNotes, canText, onOpen, onText, onNotes, onDragStart, onDragEnd,
}: {
  match: DeskMatchItem
  matches: DeskMatchItem[]
  compact: boolean
  photoSize: number
  hasNotes: boolean
  showNotes: boolean
  canText: boolean
  onOpen: () => void
  onText: () => void
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
  const tone = done ? COMPLETED_CARD : SCHEDULED_CARD
  return (
    <button
      type="button"
      draggable={!done}
      onDragStart={(event) => {
        if ((event.target as HTMLElement).closest('[data-card-action]')) {
          event.preventDefault()
          return
        }
        event.dataTransfer.setData('text/match-id', String(match.match_id))
        event.dataTransfer.effectAllowed = 'move'
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      style={{ ...cardButton, background: tone.bg, border: `1px solid ${tone.border}`, color: '#1a1a1a' }}
    >
      <CardHeading match={match} compact={compact} trophy={match.championship_final ? <TrophyIcon gold title="Championship Final — Trophy Match." /> : null} />
      <NameLines a={sideA.label} b={sideB.label} teamA={match.team1_id} teamB={match.team2_id} compact={compact} photoSize={photoSize} emphasizeA={winnerA} emphasizeB={winnerB} rrFinalTeamIds={match.rr_final_team_ids} rrChampionTeamIds={match.rr_champion_team_ids} rrRunnerUpTeamIds={match.rr_runner_up_team_ids} />
      {done && <div style={{ fontSize: compact ? 9 : 11, fontWeight: 800, color: '#1b5e20' }}>✓ {match.score_display || 'Completed'}</div>}
      <CardActions compact={compact} canText={canText} showNotes={showNotes} hasNotes={hasNotes} onText={onText} onNotes={onNotes} />
    </button>
  )
}

function NameLines({ a, b, teamA, teamB, compact, photoSize, emphasizeA = false, emphasizeB = false, rrFinalTeamIds = [], rrChampionTeamIds = [], rrRunnerUpTeamIds = [] }: { a: string; b: string; teamA: number | null; teamB: number | null; compact: boolean; photoSize: number; emphasizeA?: boolean; emphasizeB?: boolean; rrFinalTeamIds?: number[]; rrChampionTeamIds?: number[]; rrRunnerUpTeamIds?: number[] }) {
  const groups = [
    { lines: firstNameLines(a), teamId: teamA, emphasize: emphasizeA },
    { lines: firstNameLines(b), teamId: teamB, emphasize: emphasizeB },
  ]
  return (
    <div style={{ fontSize: compact ? 9 : 11, lineHeight: 1.15 }}>
      {groups.map((group, groupIndex) => (
        <div key={groupIndex}>
          {groupIndex > 0 && <div style={{ borderTop: '1px solid rgba(0,0,0,0.28)', margin: '2px 0' }} />}
          <div style={{ display: 'flex', alignItems: 'center', gap: 3, minWidth: 0 }}>
            {group.teamId != null && (
              <span data-card-action onMouseDown={blockCardAction} onClick={blockCardAction}>
                <TeamPhotoThumb teamId={group.teamId} size={photoSize} surface="dashboard" missing="hide" lazy enlargePreview />
              </span>
            )}
            <div style={{ minWidth: 0, flex: 1 }}>
              {group.lines.map((line, index) => (
                <div key={`${line}-${index}`} style={{ fontWeight: group.emphasize ? 900 : 700, color: group.emphasize ? '#1b5e20' : '#1a1a1a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{line}</div>
              ))}
            </div>
            {group.teamId != null && rrChampionTeamIds.includes(group.teamId) && <TrophyIcon tone="green" title="Champion — Trophy Awarded by Standings" />}
            {group.teamId != null && rrRunnerUpTeamIds.includes(group.teamId) && <TrophyIcon tone="green" title="Runner-Up — Trophy Awarded by Standings" />}
            {group.teamId != null && !rrChampionTeamIds.includes(group.teamId) && !rrRunnerUpTeamIds.includes(group.teamId) && rrFinalTeamIds.includes(group.teamId) && <TrophyIcon title="Final Round-Robin Match — Trophy Contender" />}
          </div>
        </div>
      ))}
    </div>
  )
}

function TrophyIcon({ gold = false, tone, title }: { gold?: boolean; tone?: 'gold' | 'silver' | 'green'; title?: string }) {
  const color = tone === 'green' ? '#2e7d32' : gold || tone === 'gold' ? '#c9a227' : '#90a4ae'
  return (
    <span title={title} aria-label={title} style={{ lineHeight: 0, flex: '0 0 auto' }}>
      <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden>
        <path fill={color} d="M7 3h10v2h3v3a5 5 0 01-4 4.9V14h2v2H6v-2h2v-1.1A5 5 0 014 8V5h3V3zm0 4H6v1a3 3 0 003 3V7zm10 0v4a3 3 0 003-3V7h-3zM8 18h8v2H8v-2z" />
      </svg>
    </span>
  )
}

function TextBubbleIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden>
      <path fill="currentColor" d="M5 3.5h14a2.5 2.5 0 012.5 2.5v8A2.5 2.5 0 0119 16.5H10.2L5.4 20.2A1 1 0 014 19.4V6A2.5 2.5 0 015 3.5z" />
    </svg>
  )
}

function NoteIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round">
      <path d="M7 3.5h8.2L19 7.2V20a1.2 1.2 0 01-1.2 1.2H7A1.2 1.2 0 015.8 20V4.7A1.2 1.2 0 017 3.5z" />
      <path d="M15 3.8V7.4h3.6" />
      <path d="M8.5 12.5h7M8.5 16h4.5" />
    </svg>
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
const liveMeta: CSSProperties = { fontSize: 9, fontWeight: 700, marginTop: 1, lineHeight: 1.15 }
const unavailableLabel: CSSProperties = { display: 'block', fontSize: 8, fontWeight: 800, lineHeight: 1.05, whiteSpace: 'normal', overflowWrap: 'anywhere' }
const cardButton: CSSProperties = { display: 'block', width: '100%', textAlign: 'left', border: '1px solid rgba(0,0,0,0.08)', borderRadius: 6, padding: '3px 4px', cursor: 'grab', minWidth: 0 }
const placeholderButton: CSSProperties = { width: '100%', border: 'none', background: 'transparent', color: '#e65100', fontWeight: 800, fontSize: 10, cursor: 'pointer', padding: 4 }
const noteMark = (active: boolean, compact: boolean): CSSProperties => ({ width: compact ? 16 : 18, height: compact ? 16 : 18, borderRadius: 4, background: active ? '#f9a825' : '#f7f7f7', color: active ? '#fff' : '#757575', border: active ? '1px solid #f9a825' : '1px solid #e0e0e0', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 })
const iconButton = (compact: boolean): CSSProperties => ({ width: compact ? 16 : 18, height: compact ? 16 : 18, borderRadius: 4, background: '#1a237e', color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 })

function headerButton(court: ScheduleCourt): CSSProperties {
  const background = court.closed ? '#ffcdd2' : court.unavailable ? '#37474f' : '#e3f2fd'
  const color = court.unavailable && !court.closed ? '#eceff1' : '#1a237e'
  return { background, color, border: 'none', borderRadius: 4, fontSize: 10, fontWeight: 800, padding: '6px 2px', cursor: 'pointer', minWidth: 0 }
}

function gridCellStyle(cell: ScheduleCell | null, court: ScheduleCourt, playing: boolean, times: string[]): CSSProperties {
  let background = '#e8f5e9'
  if (!cell || cell.slot.is_active === false) background = '#37474f'
  else if (playing && cell.match) background = activeTimeTint(cell.match.sort_time, times).bg
  else if (cell.match && (cell.match.status || '').toUpperCase() === 'FINAL') background = COMPLETED_CARD.bg
  else if (cell.match) background = SCHEDULED_CARD.bg
  else if (court.closed) background = '#ffcdd2'
  return { minHeight: 58, borderRadius: 6, padding: 2, minWidth: 0, background }
}

function formatDay(day: string): string {
  const parsed = new Date(`${day}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return day
  return parsed.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
}

function formatHhmm(value: string): string {
  const [hourText, minuteText] = value.split(':')
  const hour = Number(hourText)
  const minute = Number(minuteText)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return value
  const suffix = hour < 12 ? 'AM' : 'PM'
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${suffix}`
}

function CourtAvailabilityDialog({
  schedule, court, slot, day, onClose, onMake, onRestore,
}: {
  schedule: DaySchedule
  court: ScheduleCourt
  slot: SnapshotSlot
  day: string
  onClose: () => void
  onMake?: (input: {
    dayDate: string
    courtNumber: number
    scope: 'slot' | 'range' | 'rest'
    action: 'open' | 'close'
    startTime: string
    endTime?: string
  }) => Promise<void>
  onRestore?: (input: { dayDate: string; courtNumber: number }) => Promise<string | null>
}) {
  const index = schedule.courts.findIndex((row) => row.courtNumber === court.courtNumber)
  const cells = schedule.rows.map((row) => row.cells[index]).filter((cell): cell is ScheduleCell => cell != null)
  const originallyOpen = cells.filter((cell) => cell.slot.scheduled_active !== false)
  const firstOpen = originallyOpen[0]?.slot.start_time || null
  const overrideActive = cells.some((cell) => (cell.slot.scheduled_active !== false) !== (cell.slot.is_active !== false))
  const [scope, setScope] = useState<'slot' | 'range' | 'rest'>('slot')
  const [rangeEnd, setRangeEnd] = useState(slot.end_time)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const available = slot.is_active !== false
  const current = available ? 'Available' : 'Unavailable'

  const apply = async (action: 'open' | 'close') => {
    if (!onMake) return
    setBusy(true)
    setError(null)
    try {
      await onMake({
        dayDate: day,
        courtNumber: court.courtNumber,
        scope,
        action,
        startTime: slot.start_time,
        endTime: scope === 'range' ? rangeEnd : undefined,
      })
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : action === 'close' ? 'Could not close this court.' : 'Could not make this court available.')
    } finally {
      setBusy(false)
    }
  }

  const restore = async () => {
    if (!onRestore) return
    setBusy(true)
    setError(null)
    const message = await onRestore({ dayDate: day, courtNumber: court.courtNumber })
    setBusy(false)
    if (message) {
      setError(message)
      return
    }
    onClose()
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div style={{ width: 'min(420px, 100%)', background: '#fff', borderRadius: 12, padding: 16, boxShadow: '0 8px 24px rgba(0,0,0,0.2)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: '#1a237e' }}>{court.courtName}</div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ border: 'none', background: 'transparent', fontSize: 20, cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ marginTop: 8, fontSize: 13, color: '#455a64' }}>{formatDay(day)}</div>
        <div style={{ marginTop: 10, fontSize: 13 }}><b>Current status:</b> {current}</div>
        <div style={{ marginTop: 4, fontSize: 13 }}><b>Original schedule:</b> {firstOpen ? `Available from ${formatHhmm(firstOpen)}` : 'Not scheduled as available'}</div>
        {firstOpen && <div style={{ marginTop: 4, fontSize: 13 }}><b>Originally available:</b> {formatHhmm(firstOpen)}</div>}
        <div style={{ marginTop: 12, fontSize: 13, fontWeight: 800 }}>Apply to</div>
        <label style={{ display: 'block', marginTop: 6, fontSize: 13 }}>
          <input type="radio" checked={scope === 'slot'} onChange={() => setScope('slot')} /> This time slot ({formatHhmm(slot.start_time)})
        </label>
        <label style={{ display: 'block', marginTop: 6, fontSize: 13 }}>
          <input type="radio" checked={scope === 'range'} onChange={() => setScope('range')} /> A time range through
          <input type="time" value={rangeEnd.slice(0, 5)} onChange={(event) => { setRangeEnd(event.target.value); setScope('range') }} style={{ marginLeft: 8 }} />
        </label>
        <label style={{ display: 'block', marginTop: 6, fontSize: 13 }}>
          <input type="radio" checked={scope === 'rest'} onChange={() => setScope('rest')} /> The rest of this day
        </label>
        {error && <div style={{ marginTop: 10, color: '#c62828', fontSize: 13 }}>{error}</div>}
        {available ? (
          <button type="button" disabled={busy} onClick={() => { void apply('close') }} style={{ width: '100%', marginTop: 14, padding: '10px 12px', border: 'none', borderRadius: 8, background: '#37474f', color: '#fff', fontWeight: 800, cursor: 'pointer' }}>
            {busy ? 'Saving...' : 'Make Court Unavailable'}
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={() => { void apply('open') }} style={{ width: '100%', marginTop: 14, padding: '10px 12px', border: 'none', borderRadius: 8, background: '#2e7d32', color: '#fff', fontWeight: 800, cursor: 'pointer' }}>
            {busy ? 'Saving...' : 'Make Court Available'}
          </button>
        )}
        {overrideActive && (
          <button type="button" disabled={busy} onClick={() => { void restore() }} style={{ width: '100%', marginTop: 8, padding: '10px 12px', borderRadius: 8, border: '1px solid #b0bec5', background: '#fff', fontWeight: 700, cursor: 'pointer' }}>
            Restore Original Availability
          </button>
        )}
      </div>
    </div>
  )
}

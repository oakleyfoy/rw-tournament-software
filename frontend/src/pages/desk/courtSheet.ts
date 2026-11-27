import type { DeskMatchItem, SnapshotSlot } from '../../api/client'

const LIVE = new Set(['IN_PROGRESS', 'PAUSED'])

export type CardStatus =
  | 'playing'
  | 'ready'
  | 'waiting'
  | 'awaiting'
  | 'scheduled'
  | 'completed'
  | 'delayed'

export type ScheduleCourt = {
  courtNumber: number
  courtLabel: string
  courtName: string
  closed: boolean
  unavailable: boolean
}

export type ScheduleCell = {
  slot: SnapshotSlot
  match: DeskMatchItem | null
}

export type ScheduleRow = {
  time: string
  timeLabel: string
  cells: Array<ScheduleCell | null>
}

export type DaySchedule = {
  day: string
  courts: ScheduleCourt[]
  rows: ScheduleRow[]
}

export type LiveCourtCard = {
  court: ScheduleCourt
  playing: DeskMatchItem | null
  upcoming: DeskMatchItem[]
  completed: DeskMatchItem[]
}

export type OpsSummary = {
  totalCourts: number
  openCourts: number
  inUse: number
  closed: number
  unavailable: number
  inProgress: number
  ready: number
  waiting: number
  completed: number
  remaining: number
  delayed: number
}

export function courtLabelKey(name: string): string {
  return name.replace(/^Court\s+/i, '').trim().toLowerCase()
}

export function isDesignatedMatch(match: DeskMatchItem): boolean {
  return (match.court_assignment_mode || '').toUpperCase() === 'PREASSIGNED'
}

export function isOpeningMatch(match: DeskMatchItem): boolean {
  if (typeof match.is_opening === 'boolean') return match.is_opening
  return !match.source_match_a_id && !match.source_match_b_id
}

export function courtDisplayName(label: string, courtNumber: number): string {
  const trimmed = (label || '').trim() || String(courtNumber)
  if (trimmed.toLowerCase().startsWith('court')) return trimmed
  return `Court ${trimmed}`
}

export function formatSlotTime(value: string): string {
  const [hourRaw, minuteRaw] = (value || '').split(':')
  const hour = Number(hourRaw)
  const minute = Number(minuteRaw || 0)
  if (!Number.isFinite(hour)) return value
  const suffix = hour < 12 ? 'AM' : 'PM'
  const hour12 = hour % 12 || 12
  return `${hour12}:${String(minute).padStart(2, '0')} ${suffix}`
}

export function listScheduleDays(slots: SnapshotSlot[]): string[] {
  return Array.from(new Set((slots || []).map((slot) => slot.day_date))).sort()
}

export function tournamentToday(timeZone?: string | null, now = new Date()): string {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: timeZone || undefined }).format(now)
  } catch {
    return now.toISOString().slice(0, 10)
  }
}

export function pickDefaultDay(days: string[], timeZone?: string | null, now = new Date()): string {
  if (days.length === 0) return ''
  const today = tournamentToday(timeZone, now)
  return days.includes(today) ? today : days[0]
}

function closedKeys(labels: string[]): Set<string> {
  return new Set(labels.map((label) => courtLabelKey(label)))
}

function courtIsClosed(court: { courtLabel: string; courtNumber: number; courtName: string }, labels: string[]): boolean {
  const keys = closedKeys(labels)
  return keys.has(courtLabelKey(court.courtLabel))
    || keys.has(courtLabelKey(String(court.courtNumber)))
    || keys.has(courtLabelKey(court.courtName))
}

export function readableSide(
  match: DeskMatchItem,
  side: 'A' | 'B',
  matches: DeskMatchItem[],
): { label: string; detail: string | null } {
  const teamId = side === 'A' ? match.team1_id : match.team2_id
  const display = (side === 'A' ? match.team1_display : match.team2_display) || ''
  if (teamId) return { label: display || 'TBD', detail: null }
  const sourceId = side === 'A' ? match.source_match_a_id : match.source_match_b_id
  const seed = display.match(/^WFSEED:(\d+)/i)
  if (seed) return { label: `Seed ${Number(seed[1])}`, detail: null }
  const source = sourceId ? matches.find((row) => row.match_id === sourceId) : undefined
  const loser = /^(L\(|LOSER:)/i.test(display)
  if (source) {
    const where = [source.court_name, source.scheduled_time, source.status].filter(Boolean).join(' · ')
    return {
      label: `${loser ? 'Loser' : 'Winner'} of Match #${source.match_number}`,
      detail: where || null,
    }
  }
  if (/[_:]/.test(display) || /^(W\(|WINNER:|TBD:)/i.test(display)) {
    return { label: 'Awaiting previous result', detail: null }
  }
  return { label: display || 'TBD', detail: null }
}

export function isDelayed(match: DeskMatchItem, nowMinutes: number | null): boolean {
  const status = (match.status || '').toUpperCase()
  if (status === 'FINAL' || LIVE.has(status) || nowMinutes == null) return false
  const start = minutesFromTime(match.sort_time || '')
  return start != null && nowMinutes > start + 5
}

export function cardStatus(
  match: DeskMatchItem,
  checkinReady: boolean,
  _nowMinutes: number | null,
): CardStatus {
  const status = (match.status || '').toUpperCase()
  if (status === 'FINAL') return 'completed'
  if (LIVE.has(status)) return 'playing'
  const teamsKnown = Boolean(match.team1_id && match.team2_id)
  const needsCheckIn = isOpeningMatch(match) || Boolean(match.checkin_reset_pending)
  if (!teamsKnown) return 'awaiting'
  if (needsCheckIn && !checkinReady) return 'waiting'
  if (!needsCheckIn || checkinReady) return 'ready'
  return 'scheduled'
}

function minutesFromTime(value: string): number | null {
  const [hourRaw, minuteRaw] = value.split(':')
  const hour = Number(hourRaw)
  const minute = Number(minuteRaw || 0)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  return hour * 60 + minute
}

export function nowMinutesInZone(timeZone?: string | null, now = new Date()): number {
  try {
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: timeZone || undefined,
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(now)
    const hour = Number(parts.find((part) => part.type === 'hour')?.value || 0)
    const minute = Number(parts.find((part) => part.type === 'minute')?.value || 0)
    return hour * 60 + minute
  } catch {
    return now.getHours() * 60 + now.getMinutes()
  }
}

export function buildDaySchedule(args: {
  day: string
  slots: SnapshotSlot[]
  matches: DeskMatchItem[]
  closedCourtLabels: string[]
}): DaySchedule {
  const daySlots = (args.slots || []).filter((slot) => slot.day_date === args.day)
  const matchById = new Map((args.matches || []).map((match) => [match.match_id, match]))
  const matchBySlot = new Map<number, DeskMatchItem>()
  for (const match of args.matches || []) {
    if (match.slot_id != null) matchBySlot.set(match.slot_id, match)
  }

  const courtMap = new Map<number, ScheduleCourt>()
  for (const slot of daySlots) {
    if (!courtMap.has(slot.court_number)) {
      const courtName = courtDisplayName(slot.court_label, slot.court_number)
      courtMap.set(slot.court_number, {
        courtNumber: slot.court_number,
        courtLabel: slot.court_label,
        courtName,
        closed: false,
        unavailable: true,
      })
    }
    if (slot.is_active !== false) {
      const court = courtMap.get(slot.court_number)!
      court.unavailable = false
    }
  }
  const courts = Array.from(courtMap.values()).sort((a, b) => a.courtNumber - b.courtNumber)
  for (const court of courts) {
    court.closed = courtIsClosed(court, args.closedCourtLabels)
  }

  const times = Array.from(new Set(daySlots.map((slot) => slot.start_time))).sort()
  const slotAt = new Map<string, SnapshotSlot>()
  for (const slot of daySlots) slotAt.set(`${slot.start_time}|${slot.court_number}`, slot)

  const rows: ScheduleRow[] = times.map((time) => ({
    time,
    timeLabel: formatSlotTime(time),
    cells: courts.map((court) => {
      const slot = slotAt.get(`${time}|${court.courtNumber}`)
      if (!slot) return null
      const match = (slot.assigned_match_id != null ? matchById.get(slot.assigned_match_id) : undefined)
        || matchBySlot.get(slot.slot_id)
        || null
      return { slot, match }
    }),
  }))

  return { day: args.day, courts, rows }
}

function matchesOnCourt(schedule: DaySchedule, courtNumber: number): DeskMatchItem[] {
  const found: DeskMatchItem[] = []
  for (const row of schedule.rows) {
    const cell = row.cells[schedule.courts.findIndex((court) => court.courtNumber === courtNumber)]
    if (cell?.match) found.push(cell.match)
  }
  return found
}

export function buildLiveCourts(schedule: DaySchedule): LiveCourtCard[] {
  return schedule.courts.map((court) => {
    const matches = matchesOnCourt(schedule, court.courtNumber)
    const playing = matches.find((match) => LIVE.has((match.status || '').toUpperCase())) || null
    const upcoming = matches.filter((match) => {
      const status = (match.status || '').toUpperCase()
      return status !== 'FINAL' && match.match_id !== playing?.match_id
    })
    const completed = matches.filter((match) => (match.status || '').toUpperCase() === 'FINAL')
    return { court, playing, upcoming, completed }
  })
}

export function summarizeDay(
  schedule: DaySchedule,
  checkinReadyByMatchId: ReadonlyMap<number, boolean>,
  nowMinutes: number | null,
): OpsSummary {
  const seen = new Set<number>()
  let inProgress = 0
  let ready = 0
  let waiting = 0
  let completed = 0
  let remaining = 0
  let delayed = 0
  let inUse = 0
  let openCourts = 0
  for (const court of schedule.courts) {
    const matches = matchesOnCourt(schedule, court.courtNumber)
    const playing = matches.some((match) => LIVE.has((match.status || '').toUpperCase()))
    if (playing) inUse += 1
    else if (!court.closed && !court.unavailable) openCourts += 1
    for (const match of matches) {
      if (seen.has(match.match_id)) continue
      seen.add(match.match_id)
      const status = cardStatus(match, Boolean(checkinReadyByMatchId.get(match.match_id)), nowMinutes)
      if (status === 'completed') completed += 1
      else remaining += 1
      if (status === 'playing') inProgress += 1
      if (status === 'ready') ready += 1
      if (status === 'waiting' || status === 'awaiting') waiting += 1
      if (isDelayed(match, nowMinutes)) delayed += 1
    }
  }
  const closed = schedule.courts.filter((court) => court.closed).length
  const unavailable = schedule.courts.filter((court) => court.unavailable && !court.closed).length
  return {
    totalCourts: schedule.courts.length,
    openCourts,
    inUse,
    closed,
    unavailable,
    inProgress,
    ready,
    waiting,
    completed,
    remaining,
    delayed,
  }
}

export function slotAcceptsMove(slot: SnapshotSlot | null | undefined, courtClosed: boolean): boolean {
  if (!slot || slot.is_active === false || courtClosed) return false
  return true
}

export const COURT_TONE = {
  open: { bg: '#e8f5e9', fg: '#1b5e20', label: 'OPEN' },
  inUse: { bg: '#ffe0b2', fg: '#e65100', label: 'IN USE' },
  closed: { bg: '#ffcdd2', fg: '#b71c1c', label: 'CLOSED' },
  unavailable: { bg: '#37474f', fg: '#eceff1', label: 'UNAVAILABLE' },
} as const

export type CourtToneName = keyof typeof COURT_TONE

export function courtHeaderTone(court: ScheduleCourt, playing: boolean): CourtToneName {
  if (court.closed) return 'closed'
  if (playing) return 'inUse'
  if (court.unavailable) return 'unavailable'
  return 'open'
}

export function cellTone(cell: ScheduleCell | null, court: ScheduleCourt): CourtToneName {
  if (!cell || cell.slot.is_active === false) return 'unavailable'
  if (court.closed) return 'closed'
  const status = (cell.match?.status || '').toUpperCase()
  if (status === 'IN_PROGRESS' || status === 'PAUSED') return 'inUse'
  return 'open'
}

export function matchNeedsReassignment(cell: ScheduleCell | null, court: ScheduleCourt): boolean {
  if (!cell?.match) return false
  if ((cell.match.status || '').toUpperCase() === 'FINAL') return false
  return court.closed || cell.slot.is_active === false
}

export function liveBoardLayout(width: number, height: number, courtCount: number): {
  columns: number
  rows: number
  fits: boolean
  neededHeight: number
  neededWidth: number
} {
  const gap = 6
  const minW = 150
  const minH = 108
  if (courtCount <= 0 || width <= 0 || height <= 0) {
    return { columns: 1, rows: Math.max(courtCount, 1), fits: false, neededHeight: minH, neededWidth: minW }
  }
  for (let columns = 1; columns <= courtCount; columns += 1) {
    const rows = Math.ceil(courtCount / columns)
    const cardWidth = Math.floor((width - gap * (columns - 1)) / columns)
    const cardHeight = Math.floor((height - gap * (rows - 1)) / rows)
    if (cardWidth >= minW && cardHeight >= minH) {
      return {
        columns,
        rows,
        fits: true,
        neededHeight: rows * minH + gap * (rows - 1),
        neededWidth: columns * minW + gap * (columns - 1),
      }
    }
  }
  const maxCols = Math.max(1, Math.min(courtCount, Math.floor((width + gap) / (minW + gap))))
  const rows = Math.ceil(courtCount / maxCols)
  return {
    columns: maxCols,
    rows,
    fits: false,
    neededHeight: rows * minH + gap * Math.max(0, rows - 1),
    neededWidth: maxCols * minW + gap * Math.max(0, maxCols - 1),
  }
}

export const EARLY_START_MINUTES = 15

export function firstNameLines(label: string): string[] {
  const trimmed = (label || '').trim()
  if (!trimmed) return ['TBD']
  const winner = trimmed.match(/^winner of match #(\d+)/i)
  if (winner) return [`Winner #${winner[1]}`]
  const loser = trimmed.match(/^loser of match #(\d+)/i)
  if (loser) return [`Loser #${loser[1]}`]
  if (/^(winner|loser|seed|awaiting|tbd)/i.test(trimmed)) return [trimmed]
  const names = trimmed
    .split('/')
    .map((part) => part.trim().split(/\s+/).filter(Boolean)[0] || '')
    .filter(Boolean)
  return names.length > 0 ? names : [trimmed]
}

export function shortSideLabel(label: string): string {
  return firstNameLines(label).join(' / ')
}

export function releaseClockLabel(sortTime: string): string {
  const start = minutesFromTime(sortTime)
  if (start == null) return ''
  const release = Math.max(0, start - EARLY_START_MINUTES)
  const hour = Math.floor(release / 60)
  const minute = release % 60
  const suffix = hour < 12 ? 'AM' : 'PM'
  const hour12 = hour % 12 || 12
  return `${hour12}:${String(minute).padStart(2, '0')} ${suffix}`
}

export function drawAbbreviation(eventName: string | null | undefined, matchCode: string | null | undefined): string {
  const name = (eventName || '').replace(/['’]/g, '')
  const women = name.match(/\bwomen'?s?\s+([a-z0-9]+)/i)
  if (women) return `W${women[1].toUpperCase()}`
  const mixed = name.match(/\bmixed\s+([a-z0-9]+)/i)
  if (mixed) return `MX${mixed[1].toUpperCase()}`
  const men = name.match(/\bmen'?s?\s+([a-z0-9]+)/i)
  if (men) return `M${men[1].toUpperCase()}`
  const prefix = (matchCode || '').split('_')[0]
  if (prefix && !['WF', 'RR', 'CONS'].includes(prefix.toUpperCase())) return prefix.toUpperCase()
  return ''
}

export function divisionAbbreviation(divisionName: string | null | undefined, matchCode?: string | null): string {
  const fromName = abbreviateDivisionName(divisionName)
  if (fromName) return fromName
  return divisionFromMatchCode(matchCode)
}

function abbreviateDivisionName(divisionName: string | null | undefined): string {
  const text = divisionName || ''
  const roman = text.match(/division\s+([ivx]+|\d+)/i)
  if (roman) {
    const mapped: Record<string, string> = { '1': 'I', '2': 'II', '3': 'III', '4': 'IV', '5': 'V' }
    return `D${mapped[roman[1].toUpperCase()] || roman[1].toUpperCase()}`
  }
  const bracket = text.match(/bracket\s+([123])/i)
  if (bracket) return ['DI', 'DII', 'DIII'][Number(bracket[1]) - 1]
  return ''
}

function divisionFromMatchCode(matchCode: string | null | undefined): string {
  const tokens = (matchCode || '').toUpperCase().split('_').filter(Boolean)
  if (tokens.includes('BWW') || tokens.includes('B1')) return 'DI'
  if (tokens.includes('BWL') || tokens.includes('B2')) return 'DII'
  if (tokens.includes('BLW') || tokens.includes('B3')) return 'DIII'
  if (tokens.includes('BLL') || tokens.includes('DIV4')) return 'DIV'
  return ''
}

export type SlotCover = { minutes: number; active: boolean }

export const ACTIVE_TIME_TINTS = [
  { bg: '#fff8e1', border: '#f9a825' },
  { bg: '#f3e5f5', border: '#8e24aa' },
  { bg: '#fce4ec', border: '#c2185b' },
  { bg: '#e0f7fa', border: '#00838f' },
  { bg: '#fff3e0', border: '#ef6c00' },
  { bg: '#ede7f6', border: '#4527a0' },
  { bg: '#f9fbe7', border: '#827717' },
  { bg: '#e1f5fe', border: '#0277bd' },
] as const

export const COMPLETED_CARD = { bg: '#cfd8dc', border: '#78909c' }
export const SCHEDULED_CARD = { bg: '#e3f2fd', border: '#90caf9' }

export function activeTimeTint(sortTime: string | null | undefined, times: string[]): { bg: string; border: string } {
  const key = (sortTime || '').slice(0, 5)
  const ordered = [...new Set(times.map((time) => time.slice(0, 5)).filter(Boolean))].sort()
  const found = ordered.indexOf(key)
  return ACTIVE_TIME_TINTS[(found < 0 ? 0 : found) % ACTIVE_TIME_TINTS.length]
}

export function courtOpenAt(slots: SlotCover[], nowMinutes: number | null): { open: boolean; untilMinutes: number | null } {
  const ordered = [...slots].sort((a, b) => a.minutes - b.minutes)
  if (!ordered.length) return { open: false, untilMinutes: null }
  if (nowMinutes == null) {
    const first = ordered[0]
    if (first.active) return { open: true, untilMinutes: null }
    const next = ordered.find((slot) => slot.minutes > first.minutes && slot.active)
    return { open: false, untilMinutes: next ? next.minutes : null }
  }
  let cover = ordered[0]
  for (const slot of ordered) {
    if (slot.minutes <= nowMinutes) cover = slot
  }
  if (nowMinutes < cover.minutes || !cover.active) {
    const after = nowMinutes < cover.minutes ? nowMinutes : cover.minutes
    const next = ordered.find((slot) => slot.minutes > after && slot.active)
    return { open: false, untilMinutes: next ? next.minutes : null }
  }
  return { open: true, untilMinutes: null }
}

export function autoStartDecision(args: {
  dayStarted: boolean
  paused: boolean
  courtClosed: boolean
  slotActive: boolean
  status: string
  teamsKnown: boolean
  feedersFinal: boolean
  participantBusy: boolean
  scheduledMinutes: number | null
  nowMinutes: number | null
}): { start: boolean; reason: string } {
  if (!args.dayStarted) return { start: false, reason: 'Day has not started' }
  if (args.paused) return { start: false, reason: 'Automatic progression is paused' }
  const status = (args.status || 'SCHEDULED').toUpperCase()
  if (status === 'FINAL' || status === 'IN_PROGRESS' || status === 'PAUSED') return { start: false, reason: status }
  if (args.courtClosed) return { start: false, reason: 'Court is closed' }
  if (!args.slotActive) return { start: false, reason: 'Court is unavailable' }
  if (!args.teamsKnown || !args.feedersFinal) return { start: false, reason: 'Awaiting result' }
  if (args.participantBusy) return { start: false, reason: 'Player is on another court' }
  if (args.scheduledMinutes == null || args.nowMinutes == null) return { start: false, reason: 'Scheduled time is missing' }
  if (args.nowMinutes < args.scheduledMinutes - EARLY_START_MINUTES) return { start: false, reason: 'Not yet in the release window' }
  return { start: true, reason: 'Eligible to start' }
}

export function formatElapsed(minutes: number): string {
  return `${Math.max(0, Math.floor(minutes))}m`
}

export function compactScheduledTime(value: string | null | undefined): string {
  const text = (value || '').trim()
  if (!text) return ''
  if (/[AP]M$/i.test(text)) return text
  const [hourRaw, minuteRaw] = text.split(':')
  const hour = Number(hourRaw)
  const minute = Number(minuteRaw || 0)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return text
  const suffix = hour < 12 ? 'AM' : 'PM'
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${suffix}`
}

export function parseTimelineMs(value: string): number {
  const text = value.trim()
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(text)) return Date.parse(text)
  return Date.parse(`${text}Z`)
}

export function simulatedClockMs(simulatedAt: string | null, serverNow: string | null, frozen: boolean, tick: number): number | null {
  if (!simulatedAt || !serverNow) return null
  const base = parseTimelineMs(simulatedAt)
  const server = parseTimelineMs(serverNow)
  if (!Number.isFinite(base) || !Number.isFinite(server)) return null
  return frozen ? base : base + (tick - server)
}

export type ClockHold = { operationalMs: number; at: number; frozen: boolean }

export function settleClock(previous: ClockHold | null, sample: number | null, tick: number, frozen: boolean): ClockHold | null {
  if (previous && previous.at === tick && previous.frozen === frozen) return previous
  if (frozen) {
    if (sample == null) return previous
    return { operationalMs: sample, at: tick, frozen }
  }
  if (sample == null) {
    if (!previous) return null
    return { operationalMs: previous.operationalMs + (tick - previous.at), at: tick, frozen }
  }
  const projected = previous ? previous.operationalMs + (tick - previous.at) : null
  if (projected != null && sample + 1500 < projected) {
    return { operationalMs: projected, at: tick, frozen }
  }
  return { operationalMs: sample, at: tick, frozen }
}

export function elapsedMinutes(startedAt: string | null, nowMs: number, matchDay: string | null, isCopy: boolean): number | null {
  if (!startedAt) return 0
  const startedDay = startedAt.slice(0, 10)
  if (isCopy && matchDay && startedDay !== matchDay) return null
  const started = parseTimelineMs(startedAt)
  if (!Number.isFinite(started)) return 0
  return Math.max(0, Math.floor((nowMs - started) / 60000))
}

export function earliestUnfinished(matches: DeskMatchItem[]): DeskMatchItem | null {
  const ordered = [...matches].sort((a, b) => (a.sort_time || '').localeCompare(b.sort_time || '') || a.match_id - b.match_id)
  return ordered.find((match) => (match.status || '').toUpperCase() !== 'FINAL') || null
}

export function scheduleColumnLayout(width: number, courtCount: number): {
  columnWidth: number
  fits: boolean
  neededWidth: number
} {
  const timeCol = 56
  const gap = 3
  const minCol = 70
  const available = width - timeCol - gap * Math.max(0, courtCount)
  const columnWidth = courtCount > 0 ? Math.floor(available / courtCount) : 0
  return {
    columnWidth,
    fits: columnWidth >= minCol,
    neededWidth: timeCol + courtCount * minCol + gap * Math.max(0, courtCount),
  }
}

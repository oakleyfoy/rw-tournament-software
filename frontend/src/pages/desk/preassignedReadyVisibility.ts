import type {
  CheckInMatchItem,
  DeskMatchItem,
  ReadyAssignedItem,
  ReadyQueueItem,
} from '../../api/client'

export type PreassignedReadyStatusLabel =
  | 'Ready — Assigned Court'
  | 'Ready — Awaiting Opening Release'
  | 'Waiting for Court'
  | 'Waiting for Release'
  | 'Waiting for Scheduled Time'

/** Court-card status before staff release the opening slot. */
export const AWAITING_OPENING_RELEASE_LABEL: PreassignedReadyStatusLabel =
  'Ready — Awaiting Opening Release'

export type PreassignedReadyEntry = {
  matchId: number
  matchNumber: number
  matchCode: string
  eventName: string
  courtName: string
  dayLabel: string
  scheduledTime: string | null
  sortTime: string | null
  dayDate: string | null
  courtNumber: number | null
  team1Display: string
  team2Display: string
  statusLabel: PreassignedReadyStatusLabel
  courtOccupied: boolean
  deskMatch: DeskMatchItem
  checkinMatch: CheckInMatchItem | null
  slotKey: string | null
  isOpening: boolean
}

const LIVE_STATUSES = new Set(['IN_PROGRESS', 'PAUSED'])
const DONE_OR_LIVE = new Set(['IN_PROGRESS', 'PAUSED', 'FINAL'])

function isPreassignedDeskMatch(match: DeskMatchItem): boolean {
  const mode = (match.court_assignment_mode || '').toUpperCase()
  if (mode === 'PREASSIGNED') return true
  if (mode === 'DYNAMIC_CHECKIN') return false
  // Fallback when mode is missing from older payloads.
  return Boolean(match.court_name)
}

function normalizeStatusLabel(label: string, waitingForCourt: boolean): PreassignedReadyStatusLabel {
  if (waitingForCourt || label === 'Waiting for Court') return 'Waiting for Court'
  if (label === 'Waiting for Release') return 'Waiting for Release'
  if (label === 'Waiting for Scheduled Time') return 'Waiting for Scheduled Time'
  return 'Ready — Assigned Court'
}

/** Prefer backend ready_assigned_queue; fall back to local check-in projection. */
export function buildPreassignedReadyEntries(args: {
  checkinMatches: CheckInMatchItem[]
  matches: DeskMatchItem[]
  readyQueue: ReadyQueueItem[]
  readyAssignedQueue?: ReadyAssignedItem[]
  nowPlayingByCourt: Record<string, DeskMatchItem | undefined>
}): PreassignedReadyEntry[] {
  const matchById = new Map((args.matches || []).map((m) => [m.match_id, m]))
  const checkinById = new Map((args.checkinMatches || []).map((cm) => [cm.match_id, cm]))

  if ((args.readyAssignedQueue || []).length > 0) {
    const entries: PreassignedReadyEntry[] = []
    for (const row of args.readyAssignedQueue || []) {
      const desk = matchById.get(row.match_id)
      if (!desk) continue
      if (DONE_OR_LIVE.has((desk.status || '').toUpperCase())) continue
      const courtName = row.court_name || desk.court_name
      if (!courtName) continue
      const occupying = args.nowPlayingByCourt[courtName]
      const courtOccupied = Boolean(
        row.waiting_for_court ||
          (occupying &&
            occupying.match_id !== desk.match_id &&
            LIVE_STATUSES.has((occupying.status || '').toUpperCase())),
      )
      entries.push({
        matchId: desk.match_id,
        matchNumber: desk.match_number,
        matchCode: desk.match_code || row.match_code || '',
        eventName: desk.event_name || row.event_name || 'Match',
        courtName,
        dayLabel: desk.day_label || row.day_label || '',
        scheduledTime: row.scheduled_time || desk.scheduled_time || null,
        sortTime: desk.sort_time || null,
        dayDate: desk.day_date || null,
        courtNumber: desk.court_number ?? null,
        team1Display: desk.team1_display || row.team1_display || 'TBD',
        team2Display: desk.team2_display || row.team2_display || 'TBD',
        statusLabel: normalizeStatusLabel(row.status_label, courtOccupied),
        courtOccupied,
        deskMatch: desk,
        checkinMatch: checkinById.get(row.match_id) || null,
        slotKey: row.slot_key,
        isOpening: row.is_opening,
      })
    }
    entries.sort((a, b) => {
      const dayCmp = (a.dayDate || '').localeCompare(b.dayDate || '')
      if (dayCmp !== 0) return dayCmp
      const timeCmp = (a.sortTime || '').localeCompare(b.sortTime || '')
      if (timeCmp !== 0) return timeCmp
      const courtCmp = (a.courtNumber ?? 0) - (b.courtNumber ?? 0)
      if (courtCmp !== 0) return courtCmp
      return a.matchNumber - b.matchNumber
    })
    return entries
  }

  const readyQueueIds = new Set((args.readyQueue || []).map((rq) => rq.match_id))
  const entries: PreassignedReadyEntry[] = []
  for (const cm of args.checkinMatches || []) {
    if (!cm.match_ready) continue
    if (readyQueueIds.has(cm.match_id)) continue

    const desk = matchById.get(cm.match_id)
    if (!desk) continue
    if (DONE_OR_LIVE.has((desk.status || '').toUpperCase())) continue
    if (!isPreassignedDeskMatch(desk)) continue

    const courtName = desk.court_name
    if (!courtName) continue

    const occupying = args.nowPlayingByCourt[courtName]
    const courtOccupied = Boolean(
      occupying &&
        occupying.match_id !== desk.match_id &&
        LIVE_STATUSES.has((occupying.status || '').toUpperCase()),
    )

    entries.push({
      matchId: desk.match_id,
      matchNumber: desk.match_number,
      matchCode: desk.match_code || cm.match_code || '',
      eventName: desk.event_name || cm.event_name || 'Match',
      courtName,
      dayLabel: desk.day_label || cm.day_label || '',
      scheduledTime: desk.scheduled_time || cm.scheduled_time || null,
      sortTime: desk.sort_time || cm.sort_time || null,
      dayDate: desk.day_date || null,
      courtNumber: desk.court_number ?? null,
      team1Display: desk.team1_display || cm.side_a.team_display || 'TBD',
      team2Display: desk.team2_display || cm.side_b.team_display || 'TBD',
      statusLabel: courtOccupied ? 'Waiting for Court' : 'Ready — Assigned Court',
      courtOccupied,
      deskMatch: desk,
      checkinMatch: cm,
      slotKey: null,
      isOpening: false,
    })
  }

  entries.sort((a, b) => {
    const dayCmp = (a.dayDate || '').localeCompare(b.dayDate || '')
    if (dayCmp !== 0) return dayCmp
    const timeCmp = (a.sortTime || '').localeCompare(b.sortTime || '')
    if (timeCmp !== 0) return timeCmp
    const courtCmp = (a.courtNumber ?? 0) - (b.courtNumber ?? 0)
    if (courtCmp !== 0) return courtCmp
    const courtNameCmp = a.courtName.localeCompare(b.courtName)
    if (courtNameCmp !== 0) return courtNameCmp
    return a.matchNumber - b.matchNumber
  })

  return entries
}

export function preassignedEntryToReadyQueueItem(entry: PreassignedReadyEntry): ReadyQueueItem {
  return {
    match_id: entry.matchId,
    match_number: entry.matchNumber,
    match_code: entry.matchCode,
    event_name: entry.eventName,
    day_label: entry.dayLabel,
    scheduled_time: entry.scheduledTime,
    ready_at: entry.checkinMatch?.ready_at || null,
    team1_display: entry.team1Display,
    team2_display: entry.team2Display,
  }
}

/** Dynamic ready queue only — preassigned lives in Ready To Go — Assigned Court. */
export function mergeReadyQueueWithPreassigned(
  readyQueue: ReadyQueueItem[],
  _preassignedEntries: PreassignedReadyEntry[],
): ReadyQueueItem[] {
  return [...readyQueue]
}

function scheduleRank(entry: PreassignedReadyEntry): string {
  const court = String(entry.courtNumber ?? 0).padStart(4, '0')
  const number = String(entry.matchNumber).padStart(8, '0')
  return `${entry.dayDate || ''}|${entry.sortTime || ''}|${court}|${number}|${entry.matchId}`
}

function hasEarlierReservation(entry: PreassignedReadyEntry, matches: DeskMatchItem[]): boolean {
  return matches.some((match) => {
    if (match.match_id === entry.matchId) return false
    if ((match.court_name || '') !== entry.courtName) return false
    if ((match.day_date || '') !== (entry.dayDate || '')) return false
    const status = (match.status || '').toUpperCase()
    if (status === 'FINAL') return false
    if (status === 'IN_PROGRESS' || status === 'PAUSED') return true
    const timeCmp = (match.sort_time || '').localeCompare(entry.sortTime || '')
    if (timeCmp < 0) return true
    if (timeCmp === 0 && (match.match_number || 0) < entry.matchNumber) return true
    return false
  })
}

function canStageOnOpenCourt(entry: PreassignedReadyEntry): boolean {
  if (entry.courtOccupied) return false
  if (entry.statusLabel === 'Waiting for Court') return false
  if (entry.statusLabel === 'Waiting for Scheduled Time') return false
  return entry.statusLabel === 'Waiting for Release' || entry.statusLabel === 'Ready — Assigned Court'
}

/**
 * One primary location per preassigned match.
 * Free court awaiting opening release → assigned court card.
 * Occupied court, earlier reservation, or scheduled-time wait → Ready To Go only.
 */
export function placePreassignedMatches(
  entries: PreassignedReadyEntry[],
  matches: DeskMatchItem[] = [],
): { courtCards: PreassignedReadyEntry[]; readyQueue: PreassignedReadyEntry[] } {
  const sorted = [...entries].sort((a, b) => scheduleRank(a).localeCompare(scheduleRank(b)))
  const stagedCourts = new Set<string>()
  const courtCards: PreassignedReadyEntry[] = []
  const readyQueue: PreassignedReadyEntry[] = []

  for (const entry of sorted) {
    const courtKey = `${entry.dayDate || ''}|${entry.courtName}`
    const reserved = hasEarlierReservation(entry, matches)
    const courtTaken = entry.courtOccupied || reserved || stagedCourts.has(courtKey)
    if (!courtTaken && canStageOnOpenCourt(entry)) {
      stagedCourts.add(courtKey)
      courtCards.push({
        ...entry,
        courtOccupied: false,
        statusLabel:
          entry.statusLabel === 'Waiting for Release'
            ? AWAITING_OPENING_RELEASE_LABEL
            : entry.statusLabel,
      })
      continue
    }
    const waitingForTimeOnly =
      entry.statusLabel === 'Waiting for Scheduled Time' && !courtTaken
    readyQueue.push({
      ...entry,
      courtOccupied: !waitingForTimeOnly,
      statusLabel: waitingForTimeOnly ? 'Waiting for Scheduled Time' : 'Waiting for Court',
    })
  }

  return { courtCards, readyQueue }
}

/** Opening check-in stays. Later preassigned rounds and already-placed matches do not. */
export function belongsInWaitingForCheckIn(
  match: Pick<
    DeskMatchItem,
    'match_id' | 'court_assignment_mode' | 'source_match_a_id' | 'source_match_b_id' | 'status'
  > | null | undefined,
  operationalMatchIds: ReadonlySet<number>,
): boolean {
  if (!match) return false
  const status = (match.status || '').toUpperCase()
  if (status === 'IN_PROGRESS' || status === 'PAUSED' || status === 'FINAL') return false
  if (operationalMatchIds.has(match.match_id)) return false
  const mode = (match.court_assignment_mode || '').toUpperCase()
  if (mode === 'PREASSIGNED' && (match.source_match_a_id || match.source_match_b_id)) return false
  return true
}

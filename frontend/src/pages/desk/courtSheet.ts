import type { DeskMatchItem, SnapshotSlot } from '../../api/client'

const LIVE = new Set(['IN_PROGRESS', 'PAUSED'])

export type CourtColumn = {
  courtName: string
  courtNumber: number | null
  closed: boolean
  blackedOut: boolean
  current: DeskMatchItem | null
  stack: DeskMatchItem[]
  startableMatchId: number | null
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

function courtNumberFromName(name: string): number {
  const digits = name.match(/(\d+)/)
  return digits ? Number(digits[1]) : 9999
}

function canStart(match: DeskMatchItem, checkinReady: boolean): boolean {
  if (!match.team1_id || !match.team2_id) return false
  if (match.checkin_reset_pending && !checkinReady) return false
  if (isOpeningMatch(match) && !checkinReady) return false
  return true
}

export function buildCourtColumns(args: {
  matches: DeskMatchItem[]
  courts: string[]
  closedCourtLabels: string[]
  slots: SnapshotSlot[]
  checkinReadyByMatchId: ReadonlyMap<number, boolean>
}): CourtColumn[] {
  const closedKeys = new Set(args.closedCourtLabels.map((label) => courtLabelKey(label)))
  const designated = (args.matches || []).filter((match) => {
    if (!isDesignatedMatch(match) || !match.court_name) return false
    return (match.status || '').toUpperCase() !== 'FINAL'
  })
  const names = new Set<string>([
    ...(args.courts || []),
    ...designated.map((match) => match.court_name as string),
  ])

  const columns = Array.from(names).map((courtName) => {
    const onCourt = designated
      .filter((match) => match.court_name === courtName)
      .sort((a, b) => (a.sort_time || '').localeCompare(b.sort_time || '') || a.match_number - b.match_number)
    const live = onCourt.find((match) => LIVE.has((match.status || '').toUpperCase())) || null
    const rest = onCourt.filter((match) => match.match_id !== live?.match_id)
    const current = live || rest[0] || null
    const stack = live ? rest : rest.slice(1)
    const key = courtLabelKey(courtName)
    const closed = closedKeys.has(key) || closedKeys.has(courtName.trim().toLowerCase())
    const blackedOut = closed || Boolean(live)
    const ready = current ? Boolean(args.checkinReadyByMatchId.get(current.match_id)) : false
    const startableMatchId = !blackedOut && current && canStart(current, ready) ? current.match_id : null
    const fromMatch = onCourt.find((match) => match.court_number != null)?.court_number ?? null
    const fromSlot = (args.slots || []).find((slot) => courtLabelKey(slot.court_label || '') === key)?.court_number ?? null
    return {
      courtName,
      courtNumber: fromMatch ?? fromSlot,
      closed,
      blackedOut,
      current,
      stack,
      startableMatchId,
    }
  })

  columns.sort((a, b) => {
    const an = a.courtNumber ?? courtNumberFromName(a.courtName)
    const bn = b.courtNumber ?? courtNumberFromName(b.courtName)
    return an - bn || a.courtName.localeCompare(b.courtName)
  })
  return columns
}

/** Earliest empty slot on the destination court for the match's day. */
export function nextOpenSlotId(
  slots: SnapshotSlot[],
  targetCourtNumber: number | null,
  targetCourtName: string,
  dayDate: string | null,
): number | null {
  const label = courtLabelKey(targetCourtName)
  const open = (slots || []).filter((slot) => {
    if (slot.assigned_match_id != null) return false
    if (slot.is_active === false) return false
    if (dayDate && slot.day_date !== dayDate) return false
    if (targetCourtNumber != null && slot.court_number === targetCourtNumber) return true
    return courtLabelKey(slot.court_label || '') === label
  })
  open.sort((a, b) => a.start_time.localeCompare(b.start_time) || a.slot_id - b.slot_id)
  return open[0]?.slot_id ?? null
}

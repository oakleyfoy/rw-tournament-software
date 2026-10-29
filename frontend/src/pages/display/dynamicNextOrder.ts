import { DisplayMatch, DisplayTimeGroup } from '../../api/client'
import { groupDisplayMatchesByTime } from './displayTimeGroups'

function bothChecked(match: DisplayMatch): boolean {
  return Boolean(match.team_a_checked_in && match.team_b_checked_in)
}

function checkinRank(match: DisplayMatch): number {
  if (bothChecked(match)) return 0
  if (match.team_a_checked_in || match.team_b_checked_in) return 1
  return 2
}

/** Both-checked first (FIFO by ready_at), then partial check-in, then the rest. */
export function sortDynamicNextMatches(matches: DisplayMatch[]): DisplayMatch[] {
  return matches.slice().sort((a, b) => {
    const rank = checkinRank(a) - checkinRank(b)
    if (rank !== 0) return rank
    if (bothChecked(a) && bothChecked(b)) {
      const ready = (a.ready_at || '9999').localeCompare(b.ready_at || '9999')
      if (ready !== 0) return ready
    }
    const court = (a.court || '').localeCompare(b.court || '')
    if (court !== 0) return court
    return a.match_id - b.match_id
  })
}

/** Time-slot groups for Next Matches with put-on order inside each slot. */
export function dynamicNextTimeGroups(matches: DisplayMatch[]): DisplayTimeGroup[] {
  return groupDisplayMatchesByTime(matches).map((group) => ({
    ...group,
    matches: sortDynamicNextMatches(group.matches),
  }))
}

/** Label time slots that are lining up to go out. */
export function dynamicTimeSlotLabel(scheduledTime: string | null | undefined): string {
  const label = (scheduledTime || '').trim()
  if (!label) return 'OUT'
  if (/\bOUT\b/i.test(label)) return label
  return `${label} OUT`
}

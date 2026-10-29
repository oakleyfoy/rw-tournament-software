import { DisplayMatch, DisplayTimeGroup } from '../../api/client'
import { groupDisplayMatchesByTime } from './displayTimeGroups'

/** Prefer showing every court-assigned slot; layout targets at least two. */
export const COURT_ASSIGNED_MIN_TIME_SLOTS = 2

/** Keep only matches that already have a court, preserving time-group order. */
export function courtAssignedTimeGroups(groups: DisplayTimeGroup[]): DisplayTimeGroup[] {
  return groups
    .map((group) => ({
      scheduled_time: group.scheduled_time,
      sort_time: group.sort_time,
      matches: group.matches.filter((match): match is DisplayMatch => Boolean(match.court)),
    }))
    .filter((group) => group.matches.length > 0)
}

/**
 * Build time groups from the full upcoming list (not the forward-only 12h window),
 * so earlier still-queued court-assigned matches still appear.
 */
export function courtAssignedGroupsFromUpcoming(matches: DisplayMatch[]): DisplayTimeGroup[] {
  return groupDisplayMatchesByTime(matches.filter((match) => Boolean(match.court)))
}

import { DisplayMatch, DisplayTimeGroup } from '../../api/client'

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

/** Prefer showing every court-assigned slot; layout targets at least two. */
export const COURT_ASSIGNED_MIN_TIME_SLOTS = 2

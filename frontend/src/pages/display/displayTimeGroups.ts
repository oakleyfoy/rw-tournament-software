import { DisplayMatch, DisplayTimeGroup } from '../../api/client'

/** Group matches into schedule time slots, sorted by day then clock time. */
export function groupDisplayMatchesByTime(matches: DisplayMatch[]): DisplayTimeGroup[] {
  const ordered = matches.slice().sort((a, b) => {
    const day = (a.day_date || '').localeCompare(b.day_date || '')
    if (day !== 0) return day
    const time = (a.sort_time || '').localeCompare(b.sort_time || '')
    if (time !== 0) return time
    return a.match_id - b.match_id
  })

  const groups: DisplayTimeGroup[] = []
  const groupMap = new Map<string, DisplayTimeGroup>()
  for (const match of ordered) {
    const label = match.scheduled_time || ''
    const sortTime = match.sort_time || ''
    const key = `${match.day_date || ''}|${sortTime}|${label}`
    let group = groupMap.get(key)
    if (!group) {
      group = { scheduled_time: label, sort_time: sortTime, matches: [] }
      groupMap.set(key, group)
      groups.push(group)
    }
    group.matches.push(match)
  }
  return groups
}

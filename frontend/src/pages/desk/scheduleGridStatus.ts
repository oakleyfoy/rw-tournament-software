export type GridStatusMatch = {
  status?: string | null
  day_date?: string | null
  sort_time?: string | null
}

/** Wall-clock stamp YYYY-MM-DDTHH:MM in the tournament timezone. */
export function wallClockStamp(now: Date, timeZone?: string | null): string {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: timeZone || undefined,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
  const parts = Object.fromEntries(fmt.formatToParts(now).map((part) => [part.type, part.value]))
  const hour = String(parts.hour ?? '00').padStart(2, '0')
  const minute = String(parts.minute ?? '00').padStart(2, '0')
  return `${parts.year}-${parts.month}-${parts.day}T${hour}:${minute}`
}

/**
 * The schedule grid is the plan for the day. A result must not paint a later
 * slot Completed before that slot has started.
 */
export function scheduleGridStatus(match: GridStatusMatch, now: Date, timeZone?: string | null): string {
  const status = (match.status || 'SCHEDULED').toUpperCase()
  if (status !== 'FINAL') return status
  if (!match.day_date || !match.sort_time) return status
  const slot = `${match.day_date}T${match.sort_time.slice(0, 5)}`
  if (slot > wallClockStamp(now, timeZone)) return 'SCHEDULED'
  return status
}

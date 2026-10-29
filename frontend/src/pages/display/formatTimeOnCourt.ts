/** Parse API timestamps the same way the desk does: naive ISO is UTC. */
export function parseDisplayTimestampMs(iso: string | null | undefined): number | null {
  if (!iso) return null
  const hasOffset = /(?:Z|[+-]\d{2}:\d{2})$/i.test(iso)
  const normalized = hasOffset ? iso : `${iso}Z`
  const ms = Date.parse(normalized)
  return Number.isFinite(ms) ? ms : null
}

/** Format elapsed on-court time from a match started_at ISO timestamp. */
export function formatTimeOnCourt(
  startedAt: string | null | undefined,
  nowMs: number = Date.now()
): string | null {
  const start = parseDisplayTimestampMs(startedAt)
  if (start === null) return null
  const elapsedMs = Math.max(0, nowMs - start)
  const totalSeconds = Math.floor(elapsedMs / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

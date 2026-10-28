/** Format elapsed on-court time from a match started_at ISO timestamp. */
export function formatTimeOnCourt(
  startedAt: string | null | undefined,
  nowMs: number = Date.now()
): string | null {
  if (!startedAt) return null
  const start = Date.parse(startedAt)
  if (!Number.isFinite(start)) return null
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

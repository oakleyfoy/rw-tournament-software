import { useCallback, useEffect, useRef, useState } from 'react'
import { listOfficialTeamPhotos, type OfficialPhotoSummary } from '../api/photography'

export const TEAM_PHOTO_POLL_MS = 5000

export type OfficialPhotoLister = (tournamentId: number) => Promise<OfficialPhotoSummary[]>

export function photoVersionsFromSummaries(
  rows: Array<Pick<OfficialPhotoSummary, 'team_id'> & { version?: string; updated_at?: string }>,
): Record<number, string> {
  const next: Record<number, string> = {}
  for (const row of rows) {
    const version = row.version || row.updated_at
    if (version) next[row.team_id] = version
  }
  return next
}

export function samePhotoVersions(left: Record<number, string>, right: Record<number, string>): boolean {
  const leftKeys = Object.keys(left)
  const rightKeys = Object.keys(right)
  if (leftKeys.length !== rightKeys.length) return false
  return leftKeys.every((key) => left[Number(key)] === right[Number(key)])
}

export function withPhotoVersion(
  current: Record<number, string>,
  teamId: number,
  version: string,
): Record<number, string> {
  if (!version || current[teamId] === version) return current
  return { ...current, [teamId]: version }
}

export function useOfficialTeamPhotoPolling(
  tournamentId: number | null,
  options?: {
    listPhotos?: OfficialPhotoLister
    intervalMs?: number
  },
) {
  const intervalMs = options?.intervalMs ?? TEAM_PHOTO_POLL_MS
  const listPhotosRef = useRef<OfficialPhotoLister>(options?.listPhotos ?? listOfficialTeamPhotos)
  listPhotosRef.current = options?.listPhotos ?? listOfficialTeamPhotos
  const [versions, setVersions] = useState<Record<number, string>>({})
  const inFlightRef = useRef(false)
  const epochRef = useRef(0)

  const showSaved = useCallback((teamId: number, version: string) => {
    epochRef.current += 1
    setVersions((current) => withPhotoVersion(current, teamId, version))
  }, [])

  const refresh = useCallback(async () => {
    if (tournamentId == null || inFlightRef.current) return
    const started = epochRef.current
    inFlightRef.current = true
    try {
      const rows = await listPhotosRef.current(tournamentId)
      if (started !== epochRef.current) return
      const next = photoVersionsFromSummaries(rows)
      setVersions((current) => (samePhotoVersions(current, next) ? current : next))
    } catch {
      // A missed poll keeps the photographs already on screen.
    } finally {
      inFlightRef.current = false
    }
  }, [tournamentId])

  useEffect(() => {
    if (tournamentId == null) return
    void refresh()
    const timer = window.setInterval(() => {
      void refresh()
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs, refresh, tournamentId])

  return { versions, refresh, showSaved }
}

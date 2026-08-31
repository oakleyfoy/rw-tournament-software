import { useCallback, useEffect, useRef, useState } from 'react'
import { DisplayBoardResponse, getDisplayBoard } from '../../api/client'

export const DISPLAY_BOARD_POLL_MS = 20_000

export type DisplayBoardFetcher = (tournamentId: number) => Promise<DisplayBoardResponse>

export function useDisplayBoard(
  tournamentId: number,
  options?: {
    fetcher?: DisplayBoardFetcher
    intervalMs?: number
    isHidden?: () => boolean
  }
) {
  const fetcher = options?.fetcher ?? getDisplayBoard
  const intervalMs = options?.intervalMs ?? DISPLAY_BOARD_POLL_MS
  const isHiddenFn = options?.isHidden
  const [data, setData] = useState<DisplayBoardResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const inFlightRef = useRef(false)
  const mountedRef = useRef(true)

  const load = useCallback(async (background: boolean) => {
    if (!tournamentId || inFlightRef.current) return
    inFlightRef.current = true
    if (background) setRefreshing(true)
    try {
      const next = await fetcher(tournamentId)
      if (!mountedRef.current) return
      setData(next)
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(err instanceof Error ? err.message : 'Failed to load tournament display')
    } finally {
      inFlightRef.current = false
      if (!mountedRef.current) return
      setInitialLoading(false)
      setRefreshing(false)
    }
  }, [fetcher, tournamentId])

  useEffect(() => {
    mountedRef.current = true
    void load(false)
    const timer = window.setInterval(() => {
      const hidden = isHiddenFn
        ? isHiddenFn()
        : typeof document !== 'undefined' && document.visibilityState === 'hidden'
      if (hidden) return
      void load(true)
    }, intervalMs)

    const onVisible = () => {
      const hidden = isHiddenFn
        ? isHiddenFn()
        : typeof document !== 'undefined' && document.visibilityState === 'hidden'
      if (!hidden) void load(true)
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      mountedRef.current = false
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [intervalMs, isHiddenFn, load])

  const refresh = useCallback(() => {
    void load(Boolean(data))
  }, [data, load])

  return {
    data,
    error,
    initialLoading,
    refreshing,
    refresh,
  }
}

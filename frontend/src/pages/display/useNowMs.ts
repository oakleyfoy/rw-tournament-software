import { useEffect, useState } from 'react'

/** Ticking clock for live elapsed labels. Disabled when `enabled` is false. */
export function useNowMs(enabled: boolean, intervalMs = 1000): number {
  const [nowMs, setNowMs] = useState(() => Date.now())

  useEffect(() => {
    if (!enabled) return
    setNowMs(Date.now())
    const timer = window.setInterval(() => setNowMs(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [enabled, intervalMs])

  return nowMs
}

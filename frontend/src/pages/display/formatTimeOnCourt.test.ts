import { describe, expect, it } from 'vitest'
import { formatTimeOnCourt, parseDisplayTimestampMs } from './formatTimeOnCourt'

describe('formatTimeOnCourt', () => {
  it('treats naive API timestamps as UTC like the desk clock', () => {
    // 14:00 UTC = 10:00 AM Eastern daylight; without Z, Date.parse would treat as local.
    const started = '2026-06-05T14:00:00'
    const now = Date.parse('2026-06-05T14:12:34Z')
    expect(formatTimeOnCourt(started, now)).toBe('12:34')
  })

  it('formats minutes and seconds under one hour', () => {
    const started = '2026-06-05T14:00:00.000Z'
    const now = Date.parse(started) + (12 * 60 + 34) * 1000
    expect(formatTimeOnCourt(started, now)).toBe('12:34')
  })

  it('formats hours when over an hour', () => {
    const started = '2026-06-05T14:00:00.000Z'
    const now = Date.parse(started) + (1 * 3600 + 5 * 60 + 2) * 1000
    expect(formatTimeOnCourt(started, now)).toBe('1:05:02')
  })

  it('returns null without a start time', () => {
    expect(formatTimeOnCourt(null)).toBeNull()
    expect(formatTimeOnCourt(undefined)).toBeNull()
  })
})

describe('parseDisplayTimestampMs', () => {
  it('appends Z for naive timestamps', () => {
    expect(parseDisplayTimestampMs('2026-06-05T14:00:00')).toBe(Date.parse('2026-06-05T14:00:00Z'))
  })
})

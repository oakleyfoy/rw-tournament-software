import { describe, expect, it } from 'vitest'
import { formatTimeOnCourt } from './formatTimeOnCourt'

describe('formatTimeOnCourt', () => {
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

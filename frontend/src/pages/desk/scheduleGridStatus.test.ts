import { describe, expect, it } from 'vitest'
import { scheduleGridStatus } from './scheduleGridStatus'

const nineAm = new Date('2026-11-07T14:00:00.000Z')

describe('scheduleGridStatus', () => {
  it('keeps a later slot Scheduled when a result was saved early', () => {
    expect(scheduleGridStatus({
      status: 'FINAL',
      day_date: '2026-11-07',
      sort_time: '10:30',
    }, nineAm, 'America/New_York')).toBe('SCHEDULED')
  })

  it('still shows Completed once that slot has started', () => {
    expect(scheduleGridStatus({
      status: 'FINAL',
      day_date: '2026-11-07',
      sort_time: '08:45',
    }, nineAm, 'America/New_York')).toBe('FINAL')
  })

  it('leaves a scheduled or live match on its own status', () => {
    expect(scheduleGridStatus({
      status: 'SCHEDULED',
      day_date: '2026-11-07',
      sort_time: '12:15',
    }, nineAm, 'America/New_York')).toBe('SCHEDULED')
    expect(scheduleGridStatus({
      status: 'IN_PROGRESS',
      day_date: '2026-11-07',
      sort_time: '07:00',
    }, nineAm, 'America/New_York')).toBe('IN_PROGRESS')
  })
})

import { describe, expect, it } from 'vitest'
import { makeMatch } from './displayBoardFixture'
import {
  dynamicNextTimeGroups,
  dynamicTimeSlotLabel,
  sortDynamicNextMatches,
} from './dynamicNextOrder'

describe('sortDynamicNextMatches', () => {
  it('puts both-checked matches on the left in ready_at order', () => {
    const ordered = sortDynamicNextMatches([
      makeMatch({
        match_id: 1,
        court: 'Court 8',
        team_a_names: 'Julie / Paige',
        team_b_names: 'Pam / Rebecca',
        team_a_checked_in: true,
        team_b_checked_in: true,
        ready_at: '2026-11-06T15:10:00',
      }),
      makeMatch({
        match_id: 2,
        court: 'Court 2',
        team_a_checked_in: false,
        team_b_checked_in: false,
      }),
      makeMatch({
        match_id: 3,
        court: 'Court 1',
        team_a_names: 'Danielle / Johnna',
        team_b_names: 'Riley / Ashley',
        team_a_checked_in: true,
        team_b_checked_in: true,
        ready_at: '2026-11-06T15:05:00',
      }),
      makeMatch({
        match_id: 4,
        court: 'Court 7',
        team_a_checked_in: true,
        team_b_checked_in: false,
      }),
    ])

    expect(ordered.map((m) => m.match_id)).toEqual([3, 1, 4, 2])
  })
})

describe('dynamicNextTimeGroups', () => {
  it('keeps time slots separate and sorts put-on order inside each', () => {
    const groups = dynamicNextTimeGroups([
      makeMatch({
        match_id: 10,
        scheduled_time: '8:00 AM',
        sort_time: '08:00',
        court: 'Court 8',
        team_a_checked_in: true,
        team_b_checked_in: true,
        ready_at: '2026-11-06T15:10:00',
      }),
      makeMatch({
        match_id: 11,
        scheduled_time: '8:00 AM',
        sort_time: '08:00',
        court: 'Court 1',
        team_a_checked_in: true,
        team_b_checked_in: true,
        ready_at: '2026-11-06T15:05:00',
      }),
      makeMatch({
        match_id: 12,
        scheduled_time: '9:00 AM',
        sort_time: '09:00',
        court: 'Court 1',
      }),
    ])

    expect(groups.map((g) => g.scheduled_time)).toEqual(['8:00 AM', '9:00 AM'])
    expect(groups[0].matches.map((m) => m.match_id)).toEqual([11, 10])
  })
})

describe('dynamicTimeSlotLabel', () => {
  it('appends OUT beside the time', () => {
    expect(dynamicTimeSlotLabel('8:00 AM')).toBe('8:00 AM OUT')
    expect(dynamicTimeSlotLabel('8:00 AM OUT')).toBe('8:00 AM OUT')
  })
})

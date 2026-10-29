import { describe, expect, it } from 'vitest'
import {
  COURT_ASSIGNED_MIN_TIME_SLOTS,
  courtAssignedGroupsFromUpcoming,
  courtAssignedTimeGroups,
} from './courtAssignedGroups'
import { makeMatch } from './displayBoardFixture'

describe('courtAssignedTimeGroups', () => {
  it('keeps only matches with a court and drops empty time slots', () => {
    const groups = courtAssignedTimeGroups([
      {
        scheduled_time: '2:30 PM',
        sort_time: '14:30',
        matches: [
          makeMatch({ match_id: 1, court: null }),
          makeMatch({ match_id: 2, court: 'Court 4' }),
        ],
      },
      {
        scheduled_time: '3:00 PM',
        sort_time: '15:00',
        matches: [makeMatch({ match_id: 3 })],
      },
      {
        scheduled_time: '3:30 PM',
        sort_time: '15:30',
        matches: [makeMatch({ match_id: 4, court: 'Court 9' })],
      },
    ])

    expect(groups).toHaveLength(2)
    expect(groups[0].sort_time).toBe('14:30')
    expect(groups[0].matches.map((m) => m.match_id)).toEqual([2])
    expect(groups[1].sort_time).toBe('15:30')
    expect(groups[1].matches.map((m) => m.match_id)).toEqual([4])
  })

  it('targets at least two time slots on the TV layout', () => {
    expect(COURT_ASSIGNED_MIN_TIME_SLOTS).toBeGreaterThanOrEqual(2)
  })
})

describe('courtAssignedGroupsFromUpcoming', () => {
  it('includes past-scheduled court-assigned matches still in upcoming', () => {
    const groups = courtAssignedGroupsFromUpcoming([
      makeMatch({
        match_id: 8,
        scheduled_time: '8:00 AM',
        sort_time: '08:00',
        day_date: '2026-11-06',
        court: 'Court 1',
        team_a_names: 'Ready / One',
      }),
      makeMatch({
        match_id: 9,
        scheduled_time: '9:00 AM',
        sort_time: '09:00',
        day_date: '2026-11-06',
        team_a_names: 'No Court Yet',
      }),
      makeMatch({
        match_id: 10,
        scheduled_time: '9:00 AM',
        sort_time: '09:00',
        day_date: '2026-11-06',
        court: 'Court 3',
        team_a_names: 'Next / Slot',
      }),
    ])

    expect(groups.map((g) => g.sort_time)).toEqual(['08:00', '09:00'])
    expect(groups[0].matches.map((m) => m.match_id)).toEqual([8])
    expect(groups[1].matches.map((m) => m.match_id)).toEqual([10])
  })
})

import { describe, expect, it } from 'vitest'
import { groupDisplayMatchesByTime } from './displayTimeGroups'
import { makeMatch } from './displayBoardFixture'

describe('groupDisplayMatchesByTime', () => {
  it('separates matches into distinct time-slot sections', () => {
    const groups = groupDisplayMatchesByTime([
      makeMatch({
        match_id: 2,
        scheduled_time: '9:00 AM',
        sort_time: '09:00',
        day_date: '2026-11-06',
        court: 'Court 10',
      }),
      makeMatch({
        match_id: 1,
        scheduled_time: '8:00 AM',
        sort_time: '08:00',
        day_date: '2026-11-06',
        court: 'Court 1',
      }),
      makeMatch({
        match_id: 3,
        scheduled_time: '9:00 AM',
        sort_time: '09:00',
        day_date: '2026-11-06',
        court: 'Court 11',
      }),
      makeMatch({
        match_id: 4,
        scheduled_time: '10:00 AM',
        sort_time: '10:00',
        day_date: '2026-11-06',
      }),
    ])

    expect(groups.map((group) => group.scheduled_time)).toEqual([
      '8:00 AM',
      '9:00 AM',
      '10:00 AM',
    ])
    expect(groups[0].matches.map((m) => m.match_id)).toEqual([1])
    expect(groups[1].matches.map((m) => m.match_id)).toEqual([2, 3])
    expect(groups[2].matches.map((m) => m.match_id)).toEqual([4])
  })
})

import { describe, expect, it } from 'vitest'
import type { DeskMatchItem, SnapshotSlot } from '../../api/client'
import { buildCourtColumns, nextOpenSlotId } from './courtSheet'

function match(overrides: Partial<DeskMatchItem> & { match_id: number }): DeskMatchItem {
  return {
    match_id: overrides.match_id,
    match_number: overrides.match_number ?? overrides.match_id,
    match_code: `WF_${overrides.match_id}`,
    event_id: 1,
    event_name: "Women's",
    stage: 'WF',
    status: overrides.status || 'SCHEDULED',
    team1_display: overrides.team1_display || 'Alpha',
    team2_display: overrides.team2_display || 'Bravo',
    team1_id: overrides.team1_id === undefined ? 1 : overrides.team1_id,
    team2_id: overrides.team2_id === undefined ? 2 : overrides.team2_id,
    court_name: overrides.court_name || 'Court 20',
    court_number: overrides.court_number ?? 20,
    day_label: 'Friday',
    day_date: overrides.day_date || '2026-11-06',
    day_index: 0,
    scheduled_time: overrides.scheduled_time || '2:00 PM',
    sort_time: overrides.sort_time || '14:00',
    court_assignment_mode: overrides.court_assignment_mode || 'PREASSIGNED',
    score_display: null,
    winner_team_id: null,
    started_at: null,
    completed_at: null,
    duration_minutes: 60,
    source_match_a_id: overrides.source_match_a_id ?? null,
    source_match_b_id: overrides.source_match_b_id ?? null,
    created_at: null,
    winner_display: null,
    slot_id: overrides.slot_id ?? overrides.match_id,
    assignment_id: 1,
    is_opening: overrides.is_opening,
    checkin_reset_pending: overrides.checkin_reset_pending,
  }
}

function slot(overrides: Partial<SnapshotSlot> & { slot_id: number }): SnapshotSlot {
  return {
    slot_id: overrides.slot_id,
    day_date: overrides.day_date || '2026-11-06',
    start_time: overrides.start_time || '15:00:00',
    end_time: '16:00:00',
    court_number: overrides.court_number ?? 21,
    court_label: overrides.court_label || '21',
    block_minutes: 60,
    is_active: overrides.is_active ?? true,
    assigned_match_id: overrides.assigned_match_id ?? null,
  }
}

describe('court sheet', () => {
  it('stacks later matches under the match that is on the court and blacks the court out', () => {
    const columns = buildCourtColumns({
      matches: [
        match({ match_id: 1, status: 'IN_PROGRESS', sort_time: '14:00', scheduled_time: '2:00 PM', is_opening: true }),
        match({
          match_id: 2,
          sort_time: '15:00',
          scheduled_time: '3:00 PM',
          source_match_a_id: 1,
          source_match_b_id: 9,
          is_opening: false,
        }),
        match({ match_id: 3, status: 'FINAL', sort_time: '13:00' }),
      ],
      courts: ['Court 20'],
      closedCourtLabels: [],
      slots: [],
      checkinReadyByMatchId: new Map([[1, true]]),
    })
    expect(columns).toHaveLength(1)
    expect(columns[0].blackedOut).toBe(true)
    expect(columns[0].current?.match_id).toBe(1)
    expect(columns[0].stack.map((row) => row.match_id)).toEqual([2])
    expect(columns[0].startableMatchId).toBeNull()
  })

  it('keeps a closed court blacked out until it is opened', () => {
    const columns = buildCourtColumns({
      matches: [match({ match_id: 4, is_opening: false, source_match_a_id: 1, source_match_b_id: 2 })],
      courts: ['Court 20'],
      closedCourtLabels: ['20'],
      slots: [],
      checkinReadyByMatchId: new Map(),
    })
    expect(columns[0].closed).toBe(true)
    expect(columns[0].blackedOut).toBe(true)
    expect(columns[0].startableMatchId).toBeNull()
    expect(columns[0].current?.match_id).toBe(4)
  })

  it('lets staff start the next match only when the court is free and the first match is checked in', () => {
    const waiting = buildCourtColumns({
      matches: [match({ match_id: 5, is_opening: true })],
      courts: ['Court 20'],
      closedCourtLabels: [],
      slots: [],
      checkinReadyByMatchId: new Map([[5, false]]),
    })
    expect(waiting[0].blackedOut).toBe(false)
    expect(waiting[0].startableMatchId).toBeNull()

    const ready = buildCourtColumns({
      matches: [
        match({ match_id: 5, is_opening: true, sort_time: '14:00' }),
        match({ match_id: 6, is_opening: false, sort_time: '15:00', source_match_a_id: 5, source_match_b_id: 8 }),
      ],
      courts: ['Court 20'],
      closedCourtLabels: [],
      slots: [],
      checkinReadyByMatchId: new Map([[5, true]]),
    })
    expect(ready[0].current?.match_id).toBe(5)
    expect(ready[0].stack.map((row) => row.match_id)).toEqual([6])
    expect(ready[0].startableMatchId).toBe(5)
  })

  it('moves a stacked match onto the next open time on another court', () => {
    const slotId = nextOpenSlotId(
      [
        slot({ slot_id: 1, court_number: 21, start_time: '16:00:00', assigned_match_id: 9 }),
        slot({ slot_id: 2, court_number: 21, start_time: '15:00:00' }),
        slot({ slot_id: 3, court_number: 20, start_time: '15:00:00' }),
      ],
      21,
      'Court 21',
      '2026-11-06',
    )
    expect(slotId).toBe(2)
  })
})

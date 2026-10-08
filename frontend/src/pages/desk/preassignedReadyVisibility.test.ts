import { describe, expect, it } from 'vitest'
import type { CheckInMatchItem, DeskMatchItem, ReadyQueueItem } from '../../api/client'
import {
  buildPreassignedReadyEntries,
  mergeReadyQueueWithPreassigned,
} from './preassignedReadyVisibility'

function side(ready: boolean, label: string): CheckInMatchItem['side_a'] {
  return {
    side: 'A',
    team_id: 1,
    team_display: label,
    team_checked_in: ready,
    team_checked_in_at: ready ? '2026-11-06T12:00:00' : null,
    show_towels: true,
    players: [],
    players_checked_in: ready ? 2 : 0,
    players_total: 2,
    side_ready: ready,
    ready_at: ready ? '2026-11-06T12:00:00' : null,
  }
}

function checkin(overrides: Partial<CheckInMatchItem> & { match_id: number; match_ready: boolean }): CheckInMatchItem {
  return {
    match_number: overrides.match_id,
    match_code: `WF-${overrides.match_id}`,
    event_id: 1,
    event_name: "Women's A",
    day_label: 'Friday, November 6',
    scheduled_time: '9:00 AM',
    sort_time: '09:00',
    slot_id: overrides.match_id,
    side_a: side(overrides.match_ready, 'Alpha'),
    side_b: { ...side(overrides.match_ready, 'Bravo'), side: 'B' },
    ready_at: overrides.match_ready ? '2026-11-06T12:00:00' : null,
    checkin_enabled: true,
    ...overrides,
  }
}

function desk(overrides: Partial<DeskMatchItem> & { match_id: number }): DeskMatchItem {
  return {
    match_number: overrides.match_id,
    match_code: `WF-${overrides.match_id}`,
    stage: 'WF',
    event_id: 1,
    event_name: "Women's A",
    division_name: null,
    day_index: 1,
    day_label: 'Friday, November 6',
    scheduled_time: '9:00 AM',
    sort_time: '09:00',
    court_name: 'Court 14',
    court_assignment_mode: 'PREASSIGNED',
    status: 'SCHEDULED',
    team1_id: 1,
    team1_display: 'Alpha',
    team2_id: 2,
    team2_display: 'Bravo',
    score_display: null,
    source_match_a_id: null,
    source_match_b_id: null,
    created_at: null,
    started_at: null,
    completed_at: null,
    winner_display: null,
    slot_id: overrides.match_id,
    assignment_id: overrides.match_id,
    court_number: 14,
    day_date: '2026-11-06',
    ...overrides,
  }
}

describe('buildPreassignedReadyEntries', () => {
  it('shows already fully checked-in preassigned matches without re-check-in', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 })],
      readyQueue: [],
      nowPlayingByCourt: {},
    })
    expect(entries).toHaveLength(1)
    expect(entries[0].matchId).toBe(101)
    expect(entries[0].courtName).toBe('Court 14')
    expect(entries[0].scheduledTime).toBe('9:00 AM')
    expect(entries[0].statusLabel).toBe('Ready — Assigned Court')
  })

  it('hides matches that are not fully checked in', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 102, match_ready: false })],
      matches: [desk({ match_id: 102 })],
      readyQueue: [],
      nowPlayingByCourt: {},
    })
    expect(entries).toHaveLength(0)
  })

  it('keeps dynamic ready-queue matches out of the preassigned lane', () => {
    const readyQueue: ReadyQueueItem[] = [{
      match_id: 201,
      match_number: 201,
      match_code: 'RR-1',
      event_name: 'Mixed',
      day_label: 'Friday, November 6',
      scheduled_time: '10:00 AM',
      ready_at: '2026-11-06T12:00:00',
      team1_display: 'C',
      team2_display: 'D',
    }]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [
        checkin({ match_id: 101, match_ready: true }),
        checkin({ match_id: 201, match_ready: true, event_name: 'Mixed' }),
      ],
      matches: [
        desk({ match_id: 101 }),
        desk({
          match_id: 201,
          court_name: null,
          court_assignment_mode: 'DYNAMIC_CHECKIN',
          court_number: null,
        }),
      ],
      readyQueue,
      nowPlayingByCourt: {},
    })
    expect(entries.map((e) => e.matchId)).toEqual([101])
  })

  it('shows multiple ready matches on the same court in scheduled order', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [
        checkin({ match_id: 2, match_ready: true, sort_time: '10:00', scheduled_time: '10:00 AM' }),
        checkin({ match_id: 1, match_ready: true, sort_time: '09:00', scheduled_time: '9:00 AM' }),
      ],
      matches: [
        desk({ match_id: 2, sort_time: '10:00', scheduled_time: '10:00 AM', court_number: 14 }),
        desk({ match_id: 1, sort_time: '09:00', scheduled_time: '9:00 AM', court_number: 14 }),
      ],
      readyQueue: [],
      nowPlayingByCourt: {},
    })
    expect(entries.map((e) => e.matchId)).toEqual([1, 2])
    expect(entries.every((e) => e.courtName === 'Court 14')).toBe(true)
  })

  it('labels ready matches Waiting for Court when the court is occupied', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 })],
      readyQueue: [],
      nowPlayingByCourt: {
        'Court 14': desk({
          match_id: 999,
          status: 'IN_PROGRESS',
          court_name: 'Court 14',
        }),
      },
    })
    expect(entries).toHaveLength(1)
    expect(entries[0].statusLabel).toBe('Waiting for Court')
    expect(entries[0].courtOccupied).toBe(true)
  })

  it('drops matches once they are on court / final', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [
        checkin({ match_id: 1, match_ready: true }),
        checkin({ match_id: 2, match_ready: true }),
      ],
      matches: [
        desk({ match_id: 1, status: 'IN_PROGRESS' }),
        desk({ match_id: 2, status: 'FINAL' }),
      ],
      readyQueue: [],
      nowPlayingByCourt: {},
    })
    expect(entries).toHaveLength(0)
  })

  it('merges preassigned ready matches into Ready To Go after dynamic queue items', () => {
    const readyQueue: ReadyQueueItem[] = [{
      match_id: 201,
      match_number: 201,
      match_code: 'RR-1',
      event_name: 'Mixed',
      day_label: 'Friday, November 6',
      scheduled_time: '10:00 AM',
      ready_at: '2026-11-06T12:00:00',
      team1_display: 'C',
      team2_display: 'D',
    }]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 })],
      readyQueue,
      nowPlayingByCourt: {},
    })
    const merged = mergeReadyQueueWithPreassigned(readyQueue, entries)
    expect(merged.map((rq) => rq.match_id)).toEqual([201, 101])
  })
})

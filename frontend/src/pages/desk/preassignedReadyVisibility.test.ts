import { describe, expect, it } from 'vitest'
import type { CheckInMatchItem, DeskMatchItem, ReadyAssignedItem, ReadyQueueItem } from '../../api/client'
import {
  AWAITING_OPENING_RELEASE_LABEL,
  belongsInWaitingForCheckIn,
  buildPreassignedReadyEntries,
  mergeReadyQueueWithPreassigned,
  placePreassignedMatches,
} from './preassignedReadyVisibility'

function side(ready: boolean, name: string) {
  return {
    side: 'A' as const,
    team_id: 1,
    team_display: name,
    team_checked_in: ready,
    team_checked_in_at: ready ? '2026-11-06T12:00:00' : null,
    show_towels: true,
    players: [],
    players_checked_in: 0,
    players_total: 0,
    side_ready: ready,
    ready_at: ready ? '2026-11-06T12:00:00' : null,
  }
}

function checkin(overrides: Partial<CheckInMatchItem> & { match_id: number; match_ready: boolean }): CheckInMatchItem {
  return {
    match_id: overrides.match_id,
    match_number: overrides.match_id,
    match_code: overrides.match_code || `WF_${overrides.match_id}`,
    event_id: 1,
    event_name: overrides.event_name || "Women's",
    day_label: 'Friday, November 6',
    scheduled_time: overrides.scheduled_time || '9:00 AM',
    sort_time: overrides.sort_time || '09:00',
    slot_id: overrides.slot_id ?? 10,
    side_a: side(overrides.match_ready, 'Alpha'),
    side_b: { ...side(overrides.match_ready, 'Bravo'), side: 'B' },
    match_ready: overrides.match_ready,
    ready_at: overrides.match_ready ? '2026-11-06T12:00:00' : null,
    checkin_enabled: true,
  }
}

function desk(overrides: Partial<DeskMatchItem> & { match_id: number }): DeskMatchItem {
  return {
    match_id: overrides.match_id,
    match_number: overrides.match_id,
    match_code: `WF_${overrides.match_id}`,
    event_id: 1,
    event_name: "Women's",
    stage: 'WF',
    status: overrides.status || 'SCHEDULED',
    team1_display: 'Alpha',
    team2_display: 'Bravo',
    team1_id: 1,
    team2_id: 2,
    court_name: overrides.court_name || 'Court 14',
    court_number: overrides.court_number ?? 14,
    day_label: 'Friday, November 6',
    day_date: '2026-11-06',
    day_index: 0,
    scheduled_time: '9:00 AM',
    sort_time: '09:00',
    court_assignment_mode: overrides.court_assignment_mode || 'PREASSIGNED',
    score_display: null,
    winner_team_id: null,
    started_at: null,
    completed_at: null,
    duration_minutes: 60,
    ...overrides,
  } as DeskMatchItem
}

describe('preassignedReadyVisibility', () => {
  it('uses backend ready_assigned_queue including waiting-for-court', () => {
    const assigned: ReadyAssignedItem[] = [
      {
        match_id: 101,
        match_number: 101,
        match_code: 'WF_101',
        event_name: "Women's",
        day_label: 'Friday, November 6',
        scheduled_time: '9:00 AM',
        court_name: 'Court 14',
        team1_display: 'Alpha',
        team2_display: 'Bravo',
        status_label: 'Waiting for Court',
        waiting_for_court: true,
        slot_key: '2026-11-06|09:00',
        is_opening: true,
        dispatch_outcome: 'waiting_court',
      },
    ]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 })],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {
        'Court 14': desk({ match_id: 999, status: 'IN_PROGRESS', court_name: 'Court 14' }),
      },
    })
    expect(entries).toHaveLength(1)
    expect(entries[0].statusLabel).toBe('Waiting for Court')
    expect(entries[0].courtOccupied).toBe(true)
  })

  it('falls back to check-in projection when ready_assigned_queue is empty', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 })],
      readyQueue: [],
      readyAssignedQueue: [],
      nowPlayingByCourt: {},
    })
    expect(entries.map((e) => e.matchId)).toEqual([101])
    expect(entries[0].statusLabel).toBe('Ready — Assigned Court')
  })

  it('keeps dynamic ready-queue matches out of the preassigned lane', () => {
    const dynamic: ReadyQueueItem = {
      match_id: 201,
      match_number: 201,
      match_code: 'MIX_1',
      event_name: 'Mixed',
      day_label: 'Friday, November 6',
      scheduled_time: '9:00 AM',
      ready_at: '2026-11-06T12:00:00',
      team1_display: 'Cara',
      team2_display: 'Dee',
    }
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [
        checkin({ match_id: 101, match_ready: true }),
        checkin({ match_id: 201, match_ready: true, event_name: 'Mixed' }),
      ],
      matches: [
        desk({ match_id: 101 }),
        desk({
          match_id: 201,
          court_assignment_mode: 'DYNAMIC_CHECKIN',
          court_name: null,
        } as Partial<DeskMatchItem> & { match_id: number }),
      ],
      readyQueue: [dynamic],
      readyAssignedQueue: [],
      nowPlayingByCourt: {},
    })
    expect(entries.map((e) => e.matchId)).toEqual([101])
  })

  it('keeps waiting-for-release and waiting-for-time visible', () => {
    const assigned: ReadyAssignedItem[] = [
      {
        match_id: 101,
        match_number: 101,
        match_code: 'WF_101',
        event_name: "Women's",
        day_label: 'Friday, November 6',
        scheduled_time: '9:00 AM',
        court_name: 'Court 14',
        team1_display: 'Alpha',
        team2_display: 'Bravo',
        status_label: 'Waiting for Release',
        waiting_for_court: false,
        slot_key: '2026-11-06|09:00',
        is_opening: true,
        dispatch_outcome: 'waiting_release',
      },
      {
        match_id: 202,
        match_number: 202,
        match_code: 'WF_202',
        event_name: "Women's",
        day_label: 'Friday, November 6',
        scheduled_time: '11:00 AM',
        court_name: 'Court 14',
        team1_display: 'Cara',
        team2_display: 'Dee',
        status_label: 'Waiting for Scheduled Time',
        waiting_for_court: false,
        slot_key: '2026-11-06|11:00',
        is_opening: false,
        dispatch_outcome: 'waiting_time',
      },
    ]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [
        desk({ match_id: 101 }),
        desk({ match_id: 202, status: 'SCHEDULED' }),
      ],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {},
    })
    expect(entries.map((e) => e.matchId).sort()).toEqual([101, 202])
    expect(entries.find((e) => e.matchId === 101)?.statusLabel).toBe('Waiting for Release')
    expect(entries.find((e) => e.matchId === 202)?.statusLabel).toBe('Waiting for Scheduled Time')
  })

  it('excludes IN_PROGRESS matches from ready-assigned lane', () => {
    const assigned: ReadyAssignedItem[] = [
      {
        match_id: 101,
        match_number: 101,
        match_code: 'WF_101',
        event_name: "Women's",
        day_label: 'Friday, November 6',
        scheduled_time: '9:00 AM',
        court_name: 'Court 14',
        team1_display: 'Alpha',
        team2_display: 'Bravo',
        status_label: 'Ready — Assigned Court',
        waiting_for_court: false,
        slot_key: '2026-11-06|09:00',
        is_opening: true,
        dispatch_outcome: 'ready_to_start',
      },
    ]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101, status: 'IN_PROGRESS' })],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {},
    })
    expect(entries).toHaveLength(0)
  })

  it('places a free-court opening match on the court card only', () => {
    const assigned: ReadyAssignedItem[] = [{
      match_id: 101, match_number: 101, match_code: 'WF_101', event_name: "Women's",
      day_label: 'Friday, November 6', scheduled_time: '9:00 AM', court_name: 'Court 14',
      team1_display: 'Alpha', team2_display: 'Bravo', status_label: 'Waiting for Release',
      waiting_for_court: false, slot_key: '2026-11-06|09:00', is_opening: true, dispatch_outcome: 'waiting_release',
    }]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 })],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {},
    })
    const placed = placePreassignedMatches(entries, [desk({ match_id: 101 })])
    expect(placed.courtCards.map((entry) => entry.matchId)).toEqual([101])
    expect(placed.courtCards[0].statusLabel).toBe(AWAITING_OPENING_RELEASE_LABEL)
    expect(placed.readyQueue).toHaveLength(0)
    expect(belongsInWaitingForCheckIn(desk({ match_id: 101 }), new Set([101]))).toBe(false)
  })

  it('places an occupied-court opening match in Ready To Go only', () => {
    const assigned: ReadyAssignedItem[] = [{
      match_id: 101, match_number: 101, match_code: 'WF_101', event_name: "Women's",
      day_label: 'Friday, November 6', scheduled_time: '9:00 AM', court_name: 'Court 14',
      team1_display: 'Alpha', team2_display: 'Bravo', status_label: 'Waiting for Release',
      waiting_for_court: false, slot_key: '2026-11-06|09:00', is_opening: true, dispatch_outcome: 'waiting_release',
    }]
    const occupant = desk({ match_id: 999, status: 'IN_PROGRESS', court_name: 'Court 14' })
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [desk({ match_id: 101 }), occupant],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: { 'Court 14': occupant },
    })
    const placed = placePreassignedMatches(entries, [desk({ match_id: 101 }), occupant])
    expect(placed.courtCards).toHaveLength(0)
    expect(placed.readyQueue.map((entry) => entry.matchId)).toEqual([101])
    expect(placed.readyQueue[0].statusLabel).toBe('Waiting for Court')
    expect(placed.readyQueue[0].courtName).toBe('Court 14')
    expect(placed.readyQueue[0].scheduledTime).toBe('9:00 AM')
  })

  it('does not show the same preassigned match in two operational areas', () => {
    const assigned: ReadyAssignedItem[] = [
      {
        match_id: 101, match_number: 101, match_code: 'WF_101', event_name: "Women's",
        day_label: 'Friday, November 6', scheduled_time: '9:00 AM', court_name: 'Court 14',
        team1_display: 'Alpha', team2_display: 'Bravo', status_label: 'Waiting for Release',
        waiting_for_court: false, slot_key: '2026-11-06|09:00', is_opening: true, dispatch_outcome: 'waiting_release',
      },
      {
        match_id: 202, match_number: 202, match_code: 'WF_202', event_name: "Women's",
        day_label: 'Friday, November 6', scheduled_time: '10:00 AM', court_name: 'Court 14',
        team1_display: 'Cara', team2_display: 'Dee', status_label: 'Waiting for Court',
        waiting_for_court: true, slot_key: '2026-11-06|10:00', is_opening: true, dispatch_outcome: 'waiting_court',
      },
    ]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [
        checkin({ match_id: 101, match_ready: true }),
        checkin({ match_id: 202, match_ready: true, scheduled_time: '10:00 AM', sort_time: '10:00' }),
      ],
      matches: [
        desk({ match_id: 101 }),
        desk({ match_id: 202, sort_time: '10:00', scheduled_time: '10:00 AM' }),
      ],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {},
    })
    const placed = placePreassignedMatches(entries, [
      desk({ match_id: 101 }),
      desk({ match_id: 202, sort_time: '10:00', scheduled_time: '10:00 AM' }),
    ])
    const courtIds = placed.courtCards.map((entry) => entry.matchId)
    const queueIds = placed.readyQueue.map((entry) => entry.matchId)
    expect(courtIds).toEqual([101])
    expect(queueIds).toEqual([202])
    expect(new Set([...courtIds, ...queueIds]).size).toBe(courtIds.length + queueIds.length)
  })

  it('keeps a missing check-in in Waiting and out of the court card', () => {
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: false })],
      matches: [desk({ match_id: 101 })],
      readyQueue: [],
      readyAssignedQueue: [],
      nowPlayingByCourt: {},
    })
    const placed = placePreassignedMatches(entries, [desk({ match_id: 101 })])
    expect(placed.courtCards).toHaveLength(0)
    expect(placed.readyQueue).toHaveLength(0)
    expect(belongsInWaitingForCheckIn(desk({ match_id: 101 }), new Set())).toBe(true)
  })

  it('keeps round 2 off Waiting For Check-In and off the court card while the court is occupied', () => {
    const round2 = desk({
      match_id: 202, sort_time: '11:00', scheduled_time: '11:00 AM',
      source_match_a_id: 101, source_match_b_id: 102,
    })
    const assigned: ReadyAssignedItem[] = [{
      match_id: 202, match_number: 202, match_code: 'WF_202', event_name: "Women's",
      day_label: 'Friday, November 6', scheduled_time: '11:00 AM', court_name: 'Court 14',
      team1_display: 'Cara', team2_display: 'Dee', status_label: 'Waiting for Court',
      waiting_for_court: true, slot_key: '2026-11-06|11:00', is_opening: false, dispatch_outcome: 'waiting_court',
    }]
    const occupant = desk({ match_id: 101, status: 'IN_PROGRESS' })
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [],
      matches: [round2, occupant],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: { 'Court 14': occupant },
    })
    const placed = placePreassignedMatches(entries, [round2, occupant])
    expect(placed.courtCards).toHaveLength(0)
    expect(placed.readyQueue.map((entry) => entry.matchId)).toEqual([202])
    expect(placed.readyQueue[0].statusLabel).toBe('Waiting for Court')
    expect(belongsInWaitingForCheckIn(round2, new Set())).toBe(false)
  })

  it('keeps a round 2 match that is waiting for its scheduled time in Ready To Go only', () => {
    const round2 = desk({
      match_id: 202, sort_time: '11:00', scheduled_time: '11:00 AM',
      source_match_a_id: 101, source_match_b_id: 102,
    })
    const assigned: ReadyAssignedItem[] = [{
      match_id: 202, match_number: 202, match_code: 'WF_202', event_name: "Women's",
      day_label: 'Friday, November 6', scheduled_time: '11:00 AM', court_name: 'Court 14',
      team1_display: 'Cara', team2_display: 'Dee', status_label: 'Waiting for Scheduled Time',
      waiting_for_court: false, slot_key: '2026-11-06|11:00', is_opening: false, dispatch_outcome: 'waiting_time',
    }]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [],
      matches: [round2],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {},
    })
    const placed = placePreassignedMatches(entries, [round2])
    expect(placed.courtCards).toHaveLength(0)
    expect(placed.readyQueue.map((entry) => entry.matchId)).toEqual([202])
    expect(placed.readyQueue[0].statusLabel).toBe('Waiting for Scheduled Time')
  })

  it('does not stage a later match ahead of an earlier reservation', () => {
    const earlier = desk({ match_id: 50, sort_time: '08:00', scheduled_time: '8:00 AM' })
    const later = desk({ match_id: 101, sort_time: '09:00' })
    const assigned: ReadyAssignedItem[] = [{
      match_id: 101, match_number: 101, match_code: 'WF_101', event_name: "Women's",
      day_label: 'Friday, November 6', scheduled_time: '9:00 AM', court_name: 'Court 14',
      team1_display: 'Alpha', team2_display: 'Bravo', status_label: 'Waiting for Release',
      waiting_for_court: false, slot_key: '2026-11-06|09:00', is_opening: true, dispatch_outcome: 'waiting_release',
    }]
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [checkin({ match_id: 101, match_ready: true })],
      matches: [earlier, later],
      readyQueue: [],
      readyAssignedQueue: assigned,
      nowPlayingByCourt: {},
    })
    const placed = placePreassignedMatches(entries, [earlier, later])
    expect(placed.courtCards).toHaveLength(0)
    expect(placed.readyQueue.map((entry) => entry.matchId)).toEqual([101])
    expect(placed.readyQueue[0].statusLabel).toBe('Waiting for Court')
  })

  it('leaves dynamic check-in matches out of preassigned placement', () => {
    const dynamic: ReadyQueueItem = {
      match_id: 201, match_number: 201, match_code: 'MIX_1', event_name: 'Mixed',
      day_label: 'Friday, November 6', scheduled_time: '9:00 AM', ready_at: '2026-11-06T12:00:00',
      team1_display: 'Cara', team2_display: 'Dee',
    }
    const opening = desk({ match_id: 101 })
    const dynamicMatch = desk({
      match_id: 201, court_assignment_mode: 'DYNAMIC_CHECKIN', court_name: null, source_match_a_id: 1,
    })
    const entries = buildPreassignedReadyEntries({
      checkinMatches: [
        checkin({ match_id: 101, match_ready: true }),
        checkin({ match_id: 201, match_ready: true, event_name: 'Mixed' }),
      ],
      matches: [opening, dynamicMatch],
      readyQueue: [dynamic],
      readyAssignedQueue: [],
      nowPlayingByCourt: {},
    })
    const placed = placePreassignedMatches(entries, [opening, dynamicMatch])
    expect(placed.courtCards.map((entry) => entry.matchId)).toEqual([101])
    expect(placed.readyQueue).toHaveLength(0)
    const merged = mergeReadyQueueWithPreassigned([dynamic], entries)
    expect(merged.map((r) => r.match_id)).toEqual([201])
    expect(belongsInWaitingForCheckIn(dynamicMatch, new Set())).toBe(true)
  })
})

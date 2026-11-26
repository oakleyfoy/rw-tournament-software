import { describe, expect, it } from 'vitest'
import type { DeskMatchItem, SnapshotSlot } from '../../api/client'
import { activeTimeTint, autoStartDecision, buildDaySchedule, buildLiveCourts, cellTone, compactScheduledTime, courtHeaderTone, courtOpenAt, divisionAbbreviation, drawAbbreviation, earliestUnfinished, elapsedMinutes, formatElapsed, listScheduleDays, liveBoardLayout, matchNeedsReassignment, readableSide, scheduleColumnLayout, settleClock, simulatedClockMs, slotAcceptsMove, summarizeDay } from './courtSheet'

function match(overrides: Partial<DeskMatchItem> & { match_id: number }): DeskMatchItem {
  return {
    match_id: overrides.match_id,
    match_number: overrides.match_number ?? overrides.match_id,
    match_code: overrides.match_code || `WOM_WF_${overrides.match_id}`,
    event_id: 1,
    event_name: "Women's",
    stage: overrides.stage || 'WF',
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
    court_assignment_mode: 'PREASSIGNED',
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
  }
}

function slot(overrides: Partial<SnapshotSlot> & { slot_id: number }): SnapshotSlot {
  return {
    slot_id: overrides.slot_id,
    day_date: overrides.day_date || '2026-11-06',
    start_time: overrides.start_time || '14:00:00',
    end_time: '15:00:00',
    court_number: overrides.court_number ?? 20,
    court_label: overrides.court_label || String(overrides.court_number ?? 20),
    block_minutes: 60,
    is_active: overrides.is_active ?? true,
    assigned_match_id: overrides.assigned_match_id ?? null,
  }
}

describe('court sheet schedule', () => {
  it('shows Friday matches only on Friday and keeps each match in its grid slot', () => {
    const slots = [
      slot({ slot_id: 1, day_date: '2026-11-06', start_time: '14:00:00', court_number: 20, assigned_match_id: 1 }),
      slot({ slot_id: 2, day_date: '2026-11-06', start_time: '15:00:00', court_number: 20, assigned_match_id: 2 }),
      slot({ slot_id: 3, day_date: '2026-11-07', start_time: '14:00:00', court_number: 20, assigned_match_id: 3 }),
    ]
    const matches = [
      match({ match_id: 1, slot_id: 1, status: 'FINAL', sort_time: '14:00' }),
      match({ match_id: 2, slot_id: 2, status: 'SCHEDULED', sort_time: '15:00', scheduled_time: '3:00 PM' }),
      match({ match_id: 3, slot_id: 3, day_date: '2026-11-07' }),
    ]
    const friday = buildDaySchedule({ day: '2026-11-06', slots, matches, closedCourtLabels: [] })
    expect(listScheduleDays(slots)).toEqual(['2026-11-06', '2026-11-07'])
    expect(friday.rows.map((row) => row.cells[0]?.match?.match_id)).toEqual([1, 2])
    expect(friday.rows[0].cells[0]?.match?.status).toBe('FINAL')
    const saturday = buildDaySchedule({ day: '2026-11-07', slots, matches, closedCourtLabels: [] })
    expect(saturday.rows.map((row) => row.cells[0]?.match?.match_id)).toEqual([3])
  })

  it('orders courts by court number and keeps a closed court match visible', () => {
    const schedule = buildDaySchedule({
      day: '2026-11-06',
      slots: [
        slot({ slot_id: 12, court_number: 12, court_label: '12', assigned_match_id: 12 }),
        slot({ slot_id: 2, court_number: 2, court_label: '2', assigned_match_id: 2 }),
      ],
      matches: [
        match({ match_id: 12, slot_id: 12, court_number: 12 }),
        match({ match_id: 2, slot_id: 2, court_number: 2 }),
      ],
      closedCourtLabels: ['2'],
    })
    expect(schedule.courts.map((court) => court.courtNumber)).toEqual([2, 12])
    expect(schedule.courts[0].closed).toBe(true)
    expect(schedule.rows[0].cells[0]?.match?.match_id).toBe(2)
  })

  it('builds one column per court for a 24-court day', () => {
    const slots = Array.from({ length: 24 }, (_, index) => slot({
      slot_id: index + 1,
      court_number: index + 1,
      court_label: String(index + 1),
      assigned_match_id: index + 1,
    }))
    const matches = slots.map((row) => match({ match_id: row.slot_id, slot_id: row.slot_id, court_number: row.court_number }))
    const schedule = buildDaySchedule({ day: '2026-11-06', slots, matches, closedCourtLabels: [] })
    expect(schedule.courts).toHaveLength(24)
    expect(schedule.courts[0].courtNumber).toBe(1)
    expect(schedule.courts[23].courtNumber).toBe(24)
    expect(summarizeDay(schedule, new Map(), null).totalCourts).toBe(24)
  })

  it('replaces raw bracket identifiers with match descriptions', () => {
    const source = match({ match_id: 7106, match_number: 7106, court_name: 'Court 20', scheduled_time: '2:00 PM', status: 'IN_PROGRESS' })
    const later = match({
      match_id: 80,
      team1_id: null,
      team1_display: 'WINNER:MIX_MIX_E32_BWW_M1',
      team2_id: null,
      team2_display: 'WFSEED:19',
      source_match_a_id: 7106,
    })
    expect(readableSide(later, 'A', [source, later]).label).toBe('Winner of Match #7106')
    expect(readableSide(later, 'B', [source, later]).label).toBe('Seed 19')
  })

  it('keeps a completed match in its slot and promotes the next unfinished match without starting it', () => {
    const slots = [
      slot({ slot_id: 1, start_time: '09:00:00', assigned_match_id: 1 }),
      slot({ slot_id: 2, start_time: '10:00:00', assigned_match_id: 2 }),
    ]
    const matches = [
      match({ match_id: 1, slot_id: 1, status: 'FINAL', sort_time: '09:00', scheduled_time: '9:00 AM' }),
      match({ match_id: 2, slot_id: 2, status: 'SCHEDULED', sort_time: '10:00', scheduled_time: '10:00 AM' }),
    ]
    const schedule = buildDaySchedule({ day: '2026-11-06', slots, matches, closedCourtLabels: [] })
    expect(schedule.rows.map((row) => row.cells[0]?.match?.match_id)).toEqual([1, 2])
    const live = buildLiveCourts(schedule)
    expect(live[0].playing).toBeNull()
    expect(live[0].upcoming.map((row) => row.match_id)).toEqual([2])
    expect(live[0].upcoming[0].status).toBe('SCHEDULED')
    expect(live[0].upcoming[0].scheduled_time).toBe('10:00 AM')
  })

  it('colors open, in-use, closed, and unavailable courts separately', () => {
    const schedule = buildDaySchedule({
      day: '2026-11-06',
      slots: [
        slot({ slot_id: 1, court_number: 1, assigned_match_id: 1 }),
        slot({ slot_id: 2, court_number: 1, start_time: '15:00:00', is_active: false, assigned_match_id: 2 }),
        slot({ slot_id: 3, court_number: 2, assigned_match_id: 3 }),
        slot({ slot_id: 4, court_number: 3, is_active: false, assigned_match_id: 4 }),
      ],
      matches: [
        match({ match_id: 1, slot_id: 1, court_number: 1, status: 'IN_PROGRESS' }),
        match({ match_id: 2, slot_id: 2, court_number: 1, status: 'SCHEDULED' }),
        match({ match_id: 3, slot_id: 3, court_number: 2, status: 'SCHEDULED' }),
        match({ match_id: 4, slot_id: 4, court_number: 3, status: 'SCHEDULED' }),
      ],
      closedCourtLabels: ['2'],
    })
    const playing = schedule.courts[0]
    const closed = schedule.courts[1]
    const unavailable = schedule.courts[2]
    expect(courtHeaderTone(playing, true)).toBe('inUse')
    expect(courtHeaderTone(closed, false)).toBe('closed')
    expect(courtHeaderTone(unavailable, false)).toBe('unavailable')
    expect(cellTone(schedule.rows[0].cells[0], playing)).toBe('inUse')
    expect(cellTone(schedule.rows[1].cells[0], playing)).toBe('unavailable')
    expect(matchNeedsReassignment(schedule.rows[1].cells[0], playing)).toBe(true)
    expect(matchNeedsReassignment(schedule.rows[0].cells[1], closed)).toBe(true)
    expect(slotAcceptsMove(schedule.rows[1].cells[0]?.slot, false)).toBe(false)
    expect(slotAcceptsMove(schedule.rows[0].cells[1]?.slot, true)).toBe(false)
    expect(slotAcceptsMove(schedule.rows[0].cells[0]?.slot, false)).toBe(true)
  })

  it('fits 24 live courts on desktop and reports a full schedule that is too narrow', () => {
    for (const [width, height] of [[1366, 768], [1920, 1080], [2560, 1440]] as const) {
      const live = liveBoardLayout(width - 48, height - 220, 24)
      expect(live.fits, `live ${width}x${height}`).toBe(true)
      expect(live.columns).toBeGreaterThan(0)
    }
    expect(scheduleColumnLayout(1366 - 48, 24).fits).toBe(false)
    expect(scheduleColumnLayout(1920 - 48, 24).fits).toBe(true)
    expect(scheduleColumnLayout(2560 - 48, 24).fits).toBe(true)
    const tight = liveBoardLayout(700, 180, 24)
    expect(tight.fits).toBe(false)
    expect(tight.neededHeight).toBeGreaterThan(180)
  })

  it('keeps a noon match in the grid until 15 minutes before its start', () => {
    const noon = match({ match_id: 12, sort_time: '12:00', scheduled_time: '12:00 PM', status: 'SCHEDULED' })
    const tenThirty = match({ match_id: 10, sort_time: '10:30', scheduled_time: '10:30 AM', status: 'SCHEDULED' })
    expect(earliestUnfinished([noon, tenThirty])?.match_id).toBe(10)
    const blocked = autoStartDecision({
      dayStarted: true,
      paused: false,
      courtClosed: false,
      slotActive: true,
      status: 'SCHEDULED',
      teamsKnown: false,
      feedersFinal: false,
      participantBusy: false,
      scheduledMinutes: 10 * 60 + 30,
      nowMinutes: 10 * 60 + 45,
    })
    expect(blocked.start).toBe(false)
    expect(blocked.reason).toBe('Awaiting result')
    const tooEarly = autoStartDecision({
      dayStarted: true,
      paused: false,
      courtClosed: false,
      slotActive: true,
      status: 'SCHEDULED',
      teamsKnown: true,
      feedersFinal: true,
      participantBusy: false,
      scheduledMinutes: 12 * 60,
      nowMinutes: 10 * 60 + 45,
    })
    expect(tooEarly.start).toBe(false)
    expect(tooEarly.reason).toBe('Not yet in the release window')
    const released = autoStartDecision({ ...{
      dayStarted: true, paused: false, courtClosed: false, slotActive: true, status: 'SCHEDULED',
      teamsKnown: true, feedersFinal: true, participantBusy: false,
      scheduledMinutes: 12 * 60, nowMinutes: 11 * 60 + 45,
    } })
    expect(released.start).toBe(true)
  })

  it('keeps a court unavailable until its covering slot is active', () => {
    const slots = [
      { minutes: 9 * 60, active: false },
      { minutes: 10 * 60, active: false },
      { minutes: 11 * 60, active: false },
      { minutes: 12 * 60, active: true },
    ]
    expect(courtOpenAt(slots, 9 * 60)).toEqual({ open: false, untilMinutes: 12 * 60 })
    expect(courtOpenAt(slots, 11 * 60 + 45)).toEqual({ open: false, untilMinutes: 12 * 60 })
    expect(courtOpenAt(slots, 12 * 60)).toEqual({ open: true, untilMinutes: null })
  })

  it('gives each scheduled time its own active color', () => {
    const times = ['09:00', '10:00', '11:00', '12:00']
    const colors = times.map((time) => activeTimeTint(time, times).bg)
    expect(new Set(colors).size).toBe(4)
    expect(activeTimeTint('09:00', times)).toEqual(activeTimeTint('09:00', times))
    expect(activeTimeTint('10:00', times).bg).not.toBe(activeTimeTint('09:00', times).bg)
  })

  it('reads the draw from the event name and keeps the division separate from the stage', () => {
    expect(drawAbbreviation("Women's B", 'WB_WF_R1')).toBe('WB')
    expect(drawAbbreviation('Mixed A', 'MXA_WF_R1')).toBe('MXA')
    expect(divisionAbbreviation('Division II')).toBe('DII')
    expect(divisionAbbreviation(null)).toBe('')
  })

  it('shows elapsed time as total minutes on one operational timeline', () => {
    expect(formatElapsed(0)).toBe('0m')
    expect(formatElapsed(19)).toBe('19m')
    expect(formatElapsed(60)).toBe('60m')
    expect(formatElapsed(84)).toBe('84m')
    expect(formatElapsed(125)).toBe('125m')
    expect(compactScheduledTime('09:00')).toBe('9:00 AM')
    const started = Date.parse('2026-12-04T09:00:00Z')
    const later = started + 15 * 60000
    expect(elapsedMinutes('2026-12-04T09:00:00', later, '2026-12-04', true)).toBe(15)
    expect(elapsedMinutes('2026-11-26T17:36:00', later, '2026-12-04', true)).toBeNull()
    expect(elapsedMinutes('2026-11-26T17:36:00Z', later, '2026-12-04', false)).toBeGreaterThan(60)
  })

  it('keeps the simulated clock from snapping backward when a refresh is stale', () => {
    const tick = Date.parse('2026-11-26T19:00:00Z')
    const sample = simulatedClockMs('2026-12-04T09:10:00', '2026-11-26T19:00:00Z', false, tick)
    const held = settleClock(null, sample, tick, false)
    const stale = simulatedClockMs('2026-12-04T09:00:00', '2026-11-26T19:00:05Z', false, tick + 5000)
    const next = settleClock(held, stale, tick + 5000, false)
    expect(next?.operationalMs).toBe((held?.operationalMs || 0) + 5000)
    const ahead = simulatedClockMs('2026-12-04T09:25:00', '2026-11-26T19:00:06Z', false, tick + 6000)
    expect(settleClock(next, ahead, tick + 6000, false)?.operationalMs).toBe(ahead)
    const frozen = simulatedClockMs('2026-12-04T09:25:00', '2026-11-26T19:00:05Z', true, tick + 65000)
    expect(settleClock(next, frozen, tick + 65000, true)?.operationalMs).toBe(frozen)
  })
})

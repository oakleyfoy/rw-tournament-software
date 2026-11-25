import { describe, expect, it } from 'vitest'
import type { CheckInMatchItem, DeskMatchItem, MatchCheckInSideState } from '../../api/client'
import { buildArrivalBoard, matrixLayout, pickArrivalSlot, searchTiles } from './firstMatchCheckIn'

function side(players: Array<[number, string, string | null, boolean]>): MatchCheckInSideState {
  return {
    side: 'A',
    team_id: 1,
    team_display: 'Team',
    team_checked_in: false,
    team_checked_in_at: null,
    show_towels: true,
    players: players.map(([player_id, player_display, towel_color, checked_in]) => ({
      player_id,
      player_display,
      towel_color,
      checked_in,
      checked_in_at: checked_in ? '2026-12-04T14:00:00Z' : null,
      report_url: null,
    })),
    players_checked_in: players.filter((player) => player[3]).length,
    players_total: players.length,
    side_ready: false,
    ready_at: null,
  }
}

function match(id: number, day: string, sort: string, court: number, code: string): DeskMatchItem {
  return {
    match_id: id,
    match_number: id,
    match_code: code,
    stage: 'WF',
    event_id: 1,
    event_name: 'Women',
    division_name: null,
    day_index: 0,
    day_label: day,
    scheduled_time: sort,
    sort_time: sort,
    court_name: `Court ${court}`,
    court_assignment_mode: 'PREASSIGNED',
    status: 'SCHEDULED',
    team1_id: 1,
    team1_display: 'A',
    team2_id: 2,
    team2_display: 'B',
    score_display: null,
    source_match_a_id: null,
    source_match_b_id: null,
    created_at: null,
    started_at: null,
    completed_at: null,
    winner_display: null,
    slot_id: id,
    assignment_id: id,
    court_number: court,
    day_date: day,
  }
}

function checkin(
  id: number,
  sort: string,
  sideA: MatchCheckInSideState,
  sideB: MatchCheckInSideState,
): CheckInMatchItem {
  return {
    match_id: id,
    match_number: id,
    match_code: 'WA_WF_R1',
    event_name: 'Women',
    day_label: 'Fri',
    scheduled_time: sort,
    sort_time: sort,
    slot_id: id,
    side_a: { ...sideA, side: 'A' },
    side_b: { ...sideB, side: 'B' },
    match_ready: false,
    ready_at: null,
    checkin_enabled: true,
  }
}

describe('first-match check-in board', () => {
  it('groups a player by the earliest match and keeps one tournament attendance', () => {
    const soniaEarly = side([[11, 'Sonia Ruiz', 'Blue', false], [12, 'Maria Lopez', 'Pink', true]])
    const soniaLater = side([[11, 'Sonia Ruiz', 'Blue', false], [19, 'Ana Diaz', 'Yellow', false]])
    const board = buildArrivalBoard(
      [
        checkin(1, '09:00', soniaEarly, side([[21, 'Kim Park', 'Green', false], [22, 'Lee Park', 'White', false]])),
        checkin(2, '11:00', soniaLater, side([[31, 'Jo Kim', null, false], [32, 'Pat Kim', 'Red', false]])),
      ],
      [match(1, '2026-12-04', '09:00', 6, 'WA_WF_R1'), match(2, '2026-12-04', '11:00', 2, 'WA_WF_R2')],
    )
    expect(board.playerIds.filter((id) => id === 11)).toHaveLength(1)
    const nine = board.slots.find((slot) => slot.sortTime === '09:00')
    const eleven = board.slots.find((slot) => slot.sortTime === '11:00')
    expect(nine?.expectedPlayerIds).toContain(11)
    expect(eleven?.expectedPlayerIds).not.toContain(11)
    expect(eleven?.expectedPlayerIds).toContain(19)
    const sonia = nine?.tiles.flatMap((tile) => tile.players).find((player) => player.playerId === 11)
    const maria = nine?.tiles.flatMap((tile) => tile.players).find((player) => player.playerId === 12)
    expect(sonia?.towelColor).toBe('Blue')
    expect(maria?.towelColor).toBe('Pink')
    expect(maria?.checkedIn).toBe(true)
    expect(board.checkedPlayerIds).toEqual([12])
  })

  it('keeps partners with different first matches on their own arrival tiles', () => {
    const board = buildArrivalBoard(
      [checkin(7, '09:00', side([[1, 'Amy Stone', 'Blue', false], [2, 'Bea Stone', 'Pink', false]]), side([[3, 'Cara', 'Red', false], [4, 'Dina', 'Navy', false]]))],
      [match(7, '2026-12-05', '09:00', 1, 'MX_WF_R1')],
    )
    const tile = board.slots[0].tiles.find((item) => item.side === 'A')
    expect(tile?.players.map((player) => player.towelColor)).toEqual(['Blue', 'Pink'])
    expect(tile?.courtLabel).toBe('1')
  })

  it('searches the whole tournament and keeps unscheduled players reachable', () => {
    const board = buildArrivalBoard(
      [checkin(3, '', side([[8, 'Early Ann', 'Orange', false], [9, 'Late Ann', 'Lime', false]]), side([[10, 'Other', 'Black', false], [13, 'More', 'Gray', false]]))],
      [{ ...match(3, '', '', 0, 'WA_WF_R1'), day_date: null, sort_time: null, court_number: null }],
    )
    expect(board.days).toContain('unscheduled')
    expect(searchTiles(board, 'ann').flatMap((tile) => tile.players.map((player) => player.playerId)).sort()).toEqual([8, 9])
  })

  it('does not replace a manually selected time slot', () => {
    const board = buildArrivalBoard(
      [
        checkin(1, '09:00', side([[1, 'A One', 'Blue', false], [2, 'A Two', 'Pink', false]]), side([[3, 'B One', 'Red', false], [4, 'B Two', 'Navy', false]])),
        checkin(2, '11:00', side([[5, 'C One', 'Blue', false], [6, 'C Two', 'Pink', false]]), side([[7, 'D One', 'Red', false], [14, 'D Two', 'Navy', false]])),
      ],
      [match(1, '2026-12-04', '09:00', 1, 'WA_WF_R1'), match(2, '2026-12-04', '11:00', 2, 'WA_WF_R1')],
    )
    expect(pickArrivalSlot(board.slots, 10 * 60, '2026-12-04|11:00')).toBe('2026-12-04|11:00')
    expect(pickArrivalSlot(board.slots, 9 * 60 + 10, null)).toBe('2026-12-04|09:00')
  })

  it('fits standard desktop time slots and reports a display that is too small', () => {
    const chrome = 220
    const cases = [
      [1366, 768],
      [1440, 900],
      [1920, 1080],
      [2560, 1440],
    ] as const
    for (const [width, height] of cases) {
      for (const teams of [12, 24, 36, 48, 60]) {
        const layout = matrixLayout(width - 48, height - chrome, teams)
        expect(layout.fits, `${teams} teams at ${width}x${height}`).toBe(true)
        expect(layout.tileHeight).toBeGreaterThanOrEqual(36)
        expect(layout.tileHeight).toBeLessThanOrEqual(52)
      }
    }
    const tight = matrixLayout(900, 180, 60)
    expect(tight.fits).toBe(false)
    expect(tight.neededHeight).toBeGreaterThan(180)
  })
})

import { describe, expect, it } from 'vitest'
import type { CheckInMatchItem, DeskMatchItem, MatchCheckInSideState } from '../../api/client'
import { buildArrivalBoard, matrixLayout, pickArrivalSlot, searchTiles } from './firstMatchCheckIn'

function side(players: Array<[number, string, string | null, boolean]>, teamId = 1): MatchCheckInSideState {
  return {
    side: 'A',
    team_id: teamId,
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
    const soniaEarly = side([[11, 'Sonia Ruiz', 'Blue', false], [12, 'Maria Lopez', 'Pink', true]], 101)
    const soniaLater = side([[11, 'Sonia Ruiz', 'Blue', false], [19, 'Ana Diaz', 'Yellow', false]], 103)
    const board = buildArrivalBoard(
      [
        checkin(1, '09:00', soniaEarly, side([[21, 'Kim Park', 'Green', false], [22, 'Lee Park', 'White', false]], 102)),
        checkin(2, '11:00', soniaLater, side([[31, 'Jo Kim', null, false], [32, 'Pat Kim', 'Red', false]], 104)),
      ],
      [match(1, '2026-12-04', '09:00', 6, 'WA_WF_R1'), match(2, '2026-12-04', '11:00', 2, 'WA_WF_R2')],
    )
    expect(board.playerIds.filter((id) => id === 11)).toHaveLength(1)
    const nine = board.slots.find((slot) => slot.sortTime === '09:00')
    const eleven = board.slots.find((slot) => slot.sortTime === '11:00')
    expect(nine?.expectedPlayerIds).toContain(11)
    expect(eleven?.expectedPlayerIds).not.toContain(11)
    expect(eleven?.expectedPlayerIds).toContain(19)
    expect(eleven?.tiles.flatMap((tile) => tile.players).some((player) => player.playerId === 11)).toBe(true)
    const sonia = nine?.tiles.flatMap((tile) => tile.players).find((player) => player.playerId === 11)
    const maria = nine?.tiles.flatMap((tile) => tile.players).find((player) => player.playerId === 12)
    expect(sonia?.towelColor).toBe('Blue')
    expect(maria?.towelColor).toBe('Pink')
    expect(maria?.checkedIn).toBe(true)
    expect(board.checkedPlayerIds).toEqual([12])
  })

  it('keeps partners with different first matches on their own arrival tiles', () => {
    const board = buildArrivalBoard(
      [checkin(7, '09:00', side([[1, 'Amy Stone', 'Blue', false], [2, 'Bea Stone', 'Pink', false]], 201), side([[3, 'Cara', 'Red', false], [4, 'Dina', 'Navy', false]], 202))],
      [match(7, '2026-12-05', '09:00', 1, 'MX_WF_R1')],
    )
    const tile = board.slots[0].tiles.find((item) => item.side === 'A')
    expect(tile?.players.map((player) => player.towelColor)).toEqual(['Blue', 'Pink'])
    expect(tile?.courtLabel).toBe('1')
  })

  it('searches the whole tournament and keeps unscheduled players reachable', () => {
    const board = buildArrivalBoard(
      [checkin(3, '', side([[8, 'Early Ann', 'Orange', false], [9, 'Late Ann', 'Lime', false]], 301), side([[10, 'Other', 'Black', false], [13, 'More', 'Gray', false]], 302))],
      [{ ...match(3, '', '', 0, 'WA_WF_R1'), day_date: null, sort_time: null, court_number: null }],
    )
    expect(board.days).toContain('unscheduled')
    expect(searchTiles(board, 'ann').flatMap((tile) => tile.players.map((player) => player.playerId)).sort()).toEqual([8, 9])
  })

  it('does not replace a manually selected time slot', () => {
    const board = buildArrivalBoard(
      [
        checkin(1, '09:00', side([[1, 'A One', 'Blue', false], [2, 'A Two', 'Pink', false]], 401), side([[3, 'B One', 'Red', false], [4, 'B Two', 'Navy', false]], 402)),
        checkin(2, '11:00', side([[5, 'C One', 'Blue', false], [6, 'C Two', 'Pink', false]], 403), side([[7, 'D One', 'Red', false], [14, 'D Two', 'Navy', false]], 404)),
      ],
      [match(1, '2026-12-04', '09:00', 1, 'WA_WF_R1'), match(2, '2026-12-04', '11:00', 2, 'WA_WF_R1')],
    )
    expect(pickArrivalSlot(board.slots, 10 * 60, '2026-12-04|11:00')).toBe('2026-12-04|11:00')
    expect(pickArrivalSlot(board.slots, 9 * 60 + 10, null)).toBe('2026-12-04|09:00')
  })

  it('keeps a named partner who has no player id and still counts a completed match', () => {
    const paired = side([[41, 'Jeff Horn', 'Black', false], [42, 'Karen Horn', 'Blue', false]], 501)
    paired.players[1] = { ...paired.players[1], player_id: null }
    const board = buildArrivalBoard(
      [checkin(9, '11:00', paired, side([[43, 'Frank Devera', 'Red', true], [44, 'Vicky Vogel', 'Pink', false]], 502))],
      [{ ...match(9, '2026-12-04', '11:00', 21, 'MX_WF_R1'), status: 'FINAL', court_assignment_mode: 'DYNAMIC_CHECKIN' }],
    )
    const names = board.slots.flatMap((slot) => slot.tiles.flatMap((tile) => tile.players.map((player) => player.firstName))).sort()
    expect(names).toEqual(['Frank', 'Jeff', 'Vicky'])
    expect(board.playerIds.slice().sort()).toEqual([41, 43, 44])
    expect(board.slots[0].expectedPlayerIds.slice().sort()).toEqual([41, 43, 44])
    expect(board.days).toEqual(['2026-12-04'])
  })

  it('ignores later-round matches and keeps a completed opening match', () => {
    const opening = checkin(1, '12:00', side([[1, 'Ann Cole', 'Blue', true], [2, 'Bea Cole', 'Pink', true]], 11), side([[3, 'Cara', 'Red', false], [4, 'Dina', 'Navy', false]], 12))
    opening.is_opening_entry = true
    const later = checkin(2, '15:00', side([[5, 'Winner One', null, false], [6, 'Winner Two', null, false]], 13), side([[7, 'Loser One', null, false], [8, 'Loser Two', null, false]], 14))
    later.is_opening_entry = false
    later.match_code = 'MIX_MIX_E32_WF_R2_1'
    const board = buildArrivalBoard(
      [opening, later],
      [match(1, '2026-12-04', '12:00', 4, 'MIX_MIX_E32_WF_R1_1'), { ...match(2, '2026-12-05', '15:00', 4, 'MIX_MIX_E32_WF_R2_1'), status: 'SCHEDULED' }],
    )
    expect(board.playerIds).toEqual([1, 2, 3, 4])
    expect(board.days).toEqual(['2026-12-04'])
    expect(board.slots.map((slot) => slot.sortTime)).toEqual(['12:00'])
    expect(board.checkedPlayerIds).toEqual([1, 2])
  })

  it('sorts teams by the top first name and keeps a photo on that player only', () => {
    const early = side([[1, 'Olivia Jones', 'Lime', true], [2, 'Carol Smith', 'Orange', false]], 20)
    early.players[0].photo_taken = true
    const laterCourt = side([[3, 'Amy Clark', 'Red', false], [4, 'Holly Moore', 'Blue', false]], 21)
    const board = buildArrivalBoard(
      [checkin(1, '09:00', early, laterCourt)],
      [match(1, '2026-12-04', '09:00', 12, 'WA_WF_R1')],
    )
    const names = board.slots[0].tiles.map((tile) => tile.players.map((player) => player.firstName))
    expect(names).toEqual([['Amy', 'Holly'], ['Olivia', 'Carol']])
    const olivia = board.slots[0].tiles[1].players[0]
    const carol = board.slots[0].tiles[1].players[1]
    expect(olivia.photoTaken).toBe(true)
    expect(carol.photoTaken).toBe(false)
    expect(olivia.checkedIn).toBe(true)
    expect(carol.checkedIn).toBe(false)
  })

  it('fits standard desktop time slots and reports a display that is too small', () => {
    const chrome = 220
    const morning = matrixLayout(1440 - 48, 900 - chrome, 26)
    expect(morning.fits).toBe(true)
    expect(morning.columns).toBeGreaterThanOrEqual(7)
    expect(morning.columns).toBeLessThanOrEqual(8)
    expect(morning.tileHeight).toBeGreaterThanOrEqual(108)
    expect(morning.tileHeight).toBeLessThanOrEqual(136)
    expect(morning.fontSize).toBeGreaterThanOrEqual(15)
    const laptop = matrixLayout(1366 - 48, 768 - chrome, 26)
    expect(laptop.fits).toBe(true)
    expect(laptop.fontSize).toBeGreaterThanOrEqual(15)
    const few = matrixLayout(1400, 700, 2)
    expect(few.columns).toBe(2)
    expect(few.tileWidth).toBeLessThanOrEqual(230)
    expect(few.tileWidth).toBeGreaterThanOrEqual(156)
    const tight = matrixLayout(900, 180, 60)
    expect(tight.fits).toBe(false)
    expect(tight.neededHeight).toBeGreaterThan(180)
  })
})

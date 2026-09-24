import { describe, expect, it } from 'vitest'
import type { CheckInMatchItem } from '../api/client'
import { summarizeTowelCountsFromLookup, summarizeTowelCountsFromMatches } from './towelCounts'

function matchWithPlayers(
  matchId: number,
  players: Array<{ id: number | null; name: string; color: string | null }>,
): CheckInMatchItem {
  const [a0, a1, b0, b1] = players
  const toState = (player?: { id: number | null; name: string; color: string | null }) =>
    player
      ? {
          player_id: player.id,
          player_display: player.name,
          checked_in: false,
          checked_in_at: null,
          towel_color: player.color,
          report_url: null,
        }
      : {
          player_id: null,
          player_display: 'TBD',
          checked_in: false,
          checked_in_at: null,
          towel_color: null,
          report_url: null,
        }
  return {
    match_id: matchId,
    match_number: matchId,
    match_code: `M${matchId}`,
    event_name: 'Mixed A',
    day_label: 'Fri',
    scheduled_time: null,
    sort_time: null,
    slot_id: 1,
    side_a: {
      side: 'A',
      team_id: 1,
      team_display: 'A / B',
      team_checked_in: false,
      team_checked_in_at: null,
      show_towels: true,
      players: [toState(a0), toState(a1)],
      players_checked_in: 0,
      players_total: 2,
      side_ready: false,
      ready_at: null,
    },
    side_b: {
      side: 'B',
      team_id: 2,
      team_display: 'C / D',
      team_checked_in: false,
      team_checked_in_at: null,
      show_towels: true,
      players: [toState(b0), toState(b1)],
      players_checked_in: 0,
      players_total: 2,
      side_ready: false,
      ready_at: null,
    },
    match_ready: false,
    ready_at: null,
  }
}

describe('summarizeTowelCountsFromMatches', () => {
  it('counts each unique player once even if they appear in two matches', () => {
    const ada = { id: 1, name: 'Ada', color: 'Lime' }
    const bea = { id: 2, name: 'Bea', color: 'Royal' }
    const cara = { id: 3, name: 'Cara', color: 'Lime' }
    const dee = { id: 4, name: 'Dee', color: 'Orange' }
    const matches = [
      matchWithPlayers(10, [ada, bea, cara, dee]),
      matchWithPlayers(11, [ada, bea, cara, dee]),
    ]
    const counts = summarizeTowelCountsFromMatches(matches)
    expect(counts).toEqual([
      { colorName: 'Lime', count: 2 },
      { colorName: 'Orange', count: 1 },
      { colorName: 'Royal', count: 1 },
    ])
    expect(counts.reduce((sum, row) => sum + row.count, 0)).toBe(4)
  })
})

describe('summarizeTowelCountsFromLookup', () => {
  it('counts imported towel rows once each', () => {
    const counts = summarizeTowelCountsFromLookup([
      { id: 1, player_id: 1, matched: true, source_name: 'Ada', source_phone: null, source_email: null, towel_color: 'Lime', report_url: null },
      { id: 2, player_id: 2, matched: true, source_name: 'Bea', source_phone: null, source_email: null, towel_color: 'Lime', report_url: null },
      { id: 3, player_id: 3, matched: true, source_name: 'Cara', source_phone: null, source_email: null, towel_color: 'Royal', report_url: null },
    ])
    expect(counts).toEqual([
      { colorName: 'Lime', count: 2 },
      { colorName: 'Royal', count: 1 },
    ])
  })
})

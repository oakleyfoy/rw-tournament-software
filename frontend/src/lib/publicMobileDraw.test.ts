import { describe, expect, it } from 'vitest'
import {
  buildTeamJourney,
  courtText,
  displaySideLabel,
  groupMatchesByRound,
  publicMatchStatus,
  publicSideLabel,
  rosterNames,
  roundLabel,
  searchPublicTeams,
  winnerName,
  type MobileMatch,
  type MobileTeam,
} from './publicMobileDraw'

function match(partial: Partial<MobileMatch> & Pick<MobileMatch, 'match_id'>): MobileMatch {
  return {
    match_number: partial.match_id,
    match_code: 'EVT_WF_R1_01',
    stage: 'WF',
    event_id: 1,
    event_name: "Women's A",
    division_name: null,
    day_index: 1,
    day_label: 'Friday, June 5',
    scheduled_time: '9:00 AM',
    sort_time: '09:00',
    court_name: 'Court 1',
    status: 'SCHEDULED',
    team1_display: 'Ada / Bea',
    team2_display: 'Cara / Dee',
    team1_full_name: 'Ada Smith / Bea Jones',
    team2_full_name: 'Cara Lee / Dee Chen',
    score_display: null,
    winner_team_id: null,
    team_a_id: 10,
    team_b_id: 20,
    ...partial,
  }
}

const teams: MobileTeam[] = [
  {
    team_id: 10,
    event_id: 1,
    event_name: "Women's A",
    seed: 1,
    full_name: 'Ada Smith / Bea Jones',
    players: ['Ada Smith', 'Bea Jones'],
    photo_version: null,
  },
  {
    team_id: 11,
    event_id: 2,
    event_name: 'Mixed B',
    seed: null,
    full_name: 'Ada Smith / Kim Park',
    players: ['Ada Smith', 'Kim Park'],
    photo_version: '2026-10-22T00:00:00',
  },
]

describe('public mobile draw', () => {
  it('searches by either partner name and keeps the division', () => {
    expect(searchPublicTeams(teams, 'bea').map((team) => team.team_id)).toEqual([10])
    expect(searchPublicTeams(teams, 'ada').map((team) => team.event_name)).toEqual(["Women's A", 'Mixed B'])
    expect(searchPublicTeams(teams, 'park')[0].event_name).toBe('Mixed B')
  })

  it('does not infer a winner from a partial score', () => {
    const live = match({ match_id: 1, status: 'IN_PROGRESS', score_display: '4-2', winner_team_id: null })
    expect(publicMatchStatus(live).label).toBe('In progress')
    expect(winnerName(live, new Map())).toBeNull()
    const done = match({ match_id: 2, status: 'FINAL', score_display: '8-4', winner_team_id: 10 })
    expect(winnerName(done, new Map(teams.map((team) => [team.team_id, team])))).toBe('Ada Smith / Bea Jones')
  })

  it('labels missing court and time without hiding a real assignment', () => {
    expect(courtText(match({ match_id: 1, court_name: null }), true)).toBe('Court TBD')
    expect(courtText(match({ match_id: 1, court_name: 'Court 4' }), true)).toBe('Court 4')
    expect(courtText(match({ match_id: 1, court_name: 'Court 4' }), false)).toBeNull()
    expect(publicMatchStatus(match({ match_id: 1, scheduled_time: null, court_name: null, status: 'SCHEDULED' })).label).toBe('Waiting')
  })

  it('follows a waterfall loss into the next published match without duplicating it', () => {
    const first = match({
      match_id: 1,
      status: 'FINAL',
      score_display: '8-6',
      winner_team_id: 20,
      team_a_id: 10,
      team_b_id: 20,
    })
    const loserPath = match({
      match_id: 3,
      match_code: 'EVT_WF_R2_L01',
      team_a_id: null,
      team_b_id: null,
      team1_full_name: 'Loser of Match #1',
      team2_full_name: 'Loser of Match #2',
      scheduled_time: null,
      court_name: null,
      status: 'UNSCHEDULED',
    })
    const sameLater = match({
      match_id: 3,
      match_code: 'EVT_WF_R2_L01',
      team_a_id: 10,
      team_b_id: 30,
      team1_full_name: 'Ada Smith / Bea Jones',
      team2_full_name: 'Eve Ray / Fay Sun',
      status: 'SCHEDULED',
    })
    const journey = buildTeamJourney(10, [first, loserPath, sameLater])
    expect(journey.matches.map((item) => item.match_id)).toEqual([1, 3])
    expect(journey.statusLabel).toBe('Next match')
    expect(journey.next?.match_id).toBe(3)
  })

  it('keeps a consolation path instead of treating a loss as the end of the draw', () => {
    const main = match({
      match_id: 4,
      match_code: 'EVT_BWW_R1_01',
      stage: 'BRACKET',
      status: 'FINAL',
      winner_team_id: 20,
      score_display: '6-3 6-4',
    })
    const consolation = match({
      match_id: 8,
      match_code: 'EVT_BWW_CONS_R1_01',
      stage: 'CONS',
      division_name: 'Division I',
      team_a_id: null,
      team_b_id: 12,
      team1_full_name: 'Loser of Match #4',
      team2_full_name: 'Cara Lee / Dee Chen',
      status: 'SCHEDULED',
    })
    const journey = buildTeamJourney(10, [main, consolation])
    expect(journey.matches.map((item) => item.match_id)).toEqual([4, 8])
    expect(journey.statusLabel).not.toMatch(/eliminated/i)
    expect(roundLabel(consolation)).toBe('Consolation · Division I')
  })

  it('groups round robin matches by the published pool', () => {
    const groups = groupMatchesByRound([
      match({ match_id: 1, match_code: 'EVT_POOLA_RR_01', stage: 'RR', division_name: 'Pool A' }),
      match({ match_id: 2, match_code: 'EVT_POOLB_RR_01', stage: 'RR', division_name: 'Pool B' }),
    ])
    expect(groups.map((group) => group.label)).toEqual(['Pool A', 'Pool B'])
  })

  it('turns feeder codes and seed placeholders into player-facing labels', () => {
    expect(publicSideLabel('SEED_4')).toBe('Seed 4')
    expect(publicSideLabel('SEED_4', { hideSeeds: true })).toBe('Opponent TBD')
    expect(publicSideLabel('W(R1_9)')).toBe('Opponent TBD')
    expect(publicSideLabel('L(R1_2)')).toBe('Opponent TBD')
    expect(publicSideLabel('Winner of Match #5612')).toBe('Winner of Match #5612')
    expect(publicSideLabel('Loser of Match #5621')).toBe('Loser of Match #5621')
    expect(publicSideLabel('WINNER:WOM_WOM_E11_BWW_M1')).toBe('Opponent TBD')
    expect(publicSideLabel('LOSER:WOM_WOM_E11_BWL_M3')).toBe('Opponent TBD')
    expect(publicSideLabel('WOM_WOM_E11_WF_R2_W07')).toBe('Opponent TBD')
    expect(publicSideLabel('Heather Robinson, Cumming, GA / Shea Butler, Johns Island, SC')).toContain('Heather Robinson')
    expect(displaySideLabel('Heather Robinson, Cumming, GA / Shea Butler, Johns Island, SC')).toBe('Heather Robinson / Shea Butler')
    expect(displaySideLabel('SEED_4')).toBe('Opponent TBD')
    expect(displaySideLabel('SEED_4', { keepPoolSeeds: true })).toBe('Seed 4')
    expect(displaySideLabel('Cons Seed 1', { keepPoolSeeds: true })).toBe('Cons Seed 1')
    expect(rosterNames({
      full_name: 'Heather Robinson, Cumming, GA / Shea Butler, Johns Island, SC',
      players: ['Heather Robinson', 'Shea Butler', 'HR'],
    })).toEqual(['Heather Robinson', 'Shea Butler'])
  })
})

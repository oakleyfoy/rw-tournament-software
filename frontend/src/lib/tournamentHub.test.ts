import { describe, expect, it } from 'vitest'
import type { PublicEventItem, PublicTeamDirectoryItem, ScheduleMatchItem } from '../api/client'
import { searchPublicTeams } from './publicMobileDraw'
import {
  drawPathWithTeamHighlight,
  drawTargetsForTeam,
  hometownSummary,
  opponentPlayerLines,
  playerHometown,
  publicTournamentHubPath,
  teamHubStatus,
} from './tournamentHub'

function match(partial: Partial<ScheduleMatchItem> & Pick<ScheduleMatchItem, 'match_id'>): ScheduleMatchItem {
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

const team: PublicTeamDirectoryItem = {
  team_id: 10,
  event_id: 1,
  event_name: "Women's A",
  seed: 1,
  full_name: 'Ada Smith / Bea Jones',
  players: ['Ada Smith', 'Bea Jones'],
  photo_version: null,
}

const events: PublicEventItem[] = [
  {
    event_id: 1,
    name: "Women's A",
    category: 'womens',
    team_count: 16,
    has_waterfall: true,
    has_round_robin: true,
    divisions: [
      { code: 'BWW', label: 'Division I' },
      { code: 'BWL', label: 'Division II' },
    ],
  },
]

describe('tournament hub helpers', () => {
  it('keeps a stable tournament-scoped hub path', () => {
    expect(publicTournamentHubPath(42)).toBe('/t/42/hub')
  })

  it('labels court assignment without treating it as in progress', () => {
    expect(teamHubStatus(10, [match({ match_id: 1, court_name: 'Court 3', status: 'SCHEDULED' })]).label).toBe(
      'Court assigned',
    )
    expect(teamHubStatus(10, [match({ match_id: 2, status: 'IN_PROGRESS', court_name: 'Court 3' })]).label).toBe(
      'Match in progress',
    )
  })

  it('shows waiting for opponent when the next side is TBD', () => {
    const status = teamHubStatus(10, [
      match({
        match_id: 3,
        team_b_id: null,
        team2_full_name: 'Winner of Match #99',
        court_name: null,
        status: 'UNSCHEDULED',
      }),
    ])
    expect(status.label).toBe('Waiting for opponent')
  })

  it('marks eliminated only when there is no further published path', () => {
    const status = teamHubStatus(10, [
      match({
        match_id: 4,
        status: 'FINAL',
        winner_team_id: 20,
        score_display: '8-3',
      }),
    ])
    expect(status.label).toBe('Eliminated')
  })

  it('only lists draws the team is in now or already played', () => {
    const waterfallOnly = drawTargetsForTeam(
      9,
      team,
      [match({ match_id: 5, match_code: 'EVT_WF_R1_01', stage: 'WF', event_id: 1 })],
      events,
    )
    expect(waterfallOnly.map((item) => item.drawType)).toEqual(['waterfall'])

    const bracketOnly = drawTargetsForTeam(
      9,
      team,
      [match({ match_id: 6, match_code: 'EVT_BWL_SF_01', stage: 'BRACKET', event_id: 1 })],
      events,
    )
    expect(bracketOnly.map((item) => item.path)).toEqual(['/t/9/draws/1/bracket/BWL'])
    expect(drawPathWithTeamHighlight(bracketOnly[0].path, 10)).toContain('team=10')
    expect(drawPathWithTeamHighlight(bracketOnly[0].path, 10)).toContain('view=draw')
  })

  it('includes earned projected bracket path after a completed feeder match', () => {
    const targets = drawTargetsForTeam(
      9,
      team,
      [
        match({
          match_id: 1,
          match_code: 'EVT_WF_R2_01',
          stage: 'WF',
          event_id: 1,
          status: 'FINAL',
          winner_team_id: 10,
          score_display: '8-4',
        }),
        match({
          match_id: 9,
          match_code: 'EVT_BWW_QF_01',
          stage: 'BRACKET',
          event_id: 1,
          team_a_id: null,
          team_b_id: null,
          team1_full_name: 'Winner of Match #1',
          team2_full_name: 'Winner of Match #2',
          status: 'UNSCHEDULED',
          scheduled_time: null,
          court_name: null,
        }),
      ],
      events,
    )
    expect(targets.map((item) => item.drawType).sort()).toEqual(['bracket', 'waterfall'])
    expect(targets[0].divisionCode).toBe('BWW')
    expect(targets.some((item) => item.divisionCode === 'BWL')).toBe(false)
  })

  it('pulls hometowns from registration full names', () => {
    expect(playerHometown('Heather Robinson, Cumming, GA')).toBe('Cumming, GA')
    expect(playerHometown('Alex Quiros, PA')).toBe('PA')
    expect(hometownSummary('Ada Smith, Cumming, GA / Bea Jones, Johns Island, SC')).toBe(
      'Cumming, GA / Johns Island, SC',
    )
    expect(opponentPlayerLines('Cara Lee, Destin, FL / Dee Chen, Atlanta, GA')).toEqual([
      { name: 'Cara Lee', hometown: 'Destin, FL' },
      { name: 'Dee Chen', hometown: 'Atlanta, GA' },
    ])
  })

  it('searches remain usable for roughly 120 teams', () => {
    const many: PublicTeamDirectoryItem[] = Array.from({ length: 120 }, (_, index) => ({
      team_id: index + 1,
      event_id: (index % 4) + 1,
      event_name: `Division ${String.fromCharCode(65 + (index % 4))}`,
      seed: index + 1,
      full_name: `Player${index} One / Player${index} Two`,
      players: [`Player${index} One`, `Player${index} Two`],
      photo_version: null,
    }))
    many[77].players = ['Alex Common', 'Pat Common']
    many[77].full_name = 'Alex Common / Pat Common'
    many[90].players = ['Alex Common', 'Sam Other']
    many[90].full_name = 'Alex Common / Sam Other'

    const started = performance.now()
    const hits = searchPublicTeams(many, 'common')
    const elapsed = performance.now() - started
    expect(hits.map((item) => item.team_id)).toEqual([78, 91])
    expect(elapsed).toBeLessThan(50)
  })
})

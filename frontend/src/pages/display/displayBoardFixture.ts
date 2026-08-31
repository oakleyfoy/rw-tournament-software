import { DisplayBoardResponse, DisplayMatch } from '../../api/client'

export function makeMatch(overrides: Partial<DisplayMatch> = {}): DisplayMatch {
  return {
    match_id: 1,
    scheduled_at: '2026-06-05T15:30:00-04:00',
    scheduled_time: '3:30 PM',
    sort_time: '15:30',
    day_date: '2026-06-05',
    event_name: "Women's B",
    division_name: null,
    event_label: "Women's B",
    round_label: 'WF R1',
    stage: 'WF',
    team_a_names: 'Helen / Simone',
    team_b_names: 'Amy / Terry',
    team_a_checked_in: false,
    team_b_checked_in: false,
    team_a_has_tbd: false,
    team_b_has_tbd: false,
    board_section: 'upcoming',
    in_next_12_hours: true,
    ...overrides,
  }
}

export const sampleBoard: DisplayBoardResponse = {
  tournament_id: 9,
  tournament_name: 'Display Board Open',
  tournament_timezone: 'America/New_York',
  now_local: '2:00 PM',
  currently_playing: [
    makeMatch({
      match_id: 11,
      scheduled_time: '1:30 PM',
      sort_time: '13:30',
      board_section: 'currently_playing',
      in_next_12_hours: false,
      court: 'Court 7',
    }),
  ],
  waiting_for_court: [
    makeMatch({
      match_id: 12,
      scheduled_time: '2:30 PM',
      sort_time: '14:30',
      team_a_names: 'Jane / Lily',
      team_b_names: 'Pam / Tess',
      team_a_checked_in: true,
      team_b_checked_in: true,
      board_section: 'waiting_for_court',
      court: 'Court 3',
    }),
  ],
  upcoming: [
    makeMatch({
      match_id: 13,
      team_a_checked_in: true,
      team_b_checked_in: false,
      court: 'Court 4',
    }),
  ],
  upcoming_12h: [
    makeMatch({
      match_id: 12,
      scheduled_time: '2:30 PM',
      sort_time: '14:30',
      team_a_names: 'Jane / Lily',
      team_b_names: 'Pam / Tess',
      board_section: 'waiting_for_court',
    }),
    makeMatch({
      match_id: 14,
      scheduled_time: '3:30 PM',
      sort_time: '15:30',
      team_a_names: 'John / TBD',
      team_b_names: 'Mike / David',
      team_a_has_tbd: true,
      court: 'Court 99',
    }),
  ],
  upcoming_12h_groups: [
    {
      scheduled_time: '2:30 PM',
      sort_time: '14:30',
      matches: [
        makeMatch({
          match_id: 12,
          scheduled_time: '2:30 PM',
          sort_time: '14:30',
          team_a_names: 'Jane / Lily',
          team_b_names: 'Pam / Tess',
          board_section: 'waiting_for_court',
        }),
      ],
    },
    {
      scheduled_time: '3:30 PM',
      sort_time: '15:30',
      matches: [
        makeMatch({
          match_id: 14,
          scheduled_time: '3:30 PM',
          sort_time: '15:30',
          team_a_names: 'John / TBD',
          team_b_names: 'Mike / David',
          team_a_has_tbd: true,
          court: 'Court 99',
        }),
      ],
    },
  ],
}

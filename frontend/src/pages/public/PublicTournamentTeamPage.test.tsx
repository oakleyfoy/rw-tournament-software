import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PublicTournamentTeamPage from './PublicTournamentTeamPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getPublicTeamDirectory: vi.fn(),
    getPublicDrawsList: vi.fn(),
    getPublicSchedule: vi.fn(),
  }
})

import { getPublicDrawsList, getPublicSchedule, getPublicTeamDirectory } from '../../api/client'

function DrawLocationProbe() {
  const location = useLocation()
  return <div data-testid="draw-location">{`${location.pathname}${location.search}`}</div>
}

describe('PublicTournamentTeamPage', () => {
  it('shows hometowns, opponent past matches, and draw position deep-link', async () => {
    vi.mocked(getPublicTeamDirectory).mockResolvedValue({
      status: 'OK',
      tournament_name: 'Amelia Island',
      teams: [
        {
          team_id: 10,
          event_id: 7,
          event_name: "Women's A",
          seed: 1,
          full_name: 'Ada Smith, Cumming, GA / Bea Jones, Johns Island, SC',
          players: ['Ada Smith', 'Bea Jones'],
          photo_version: 'photo-10',
        },
        {
          team_id: 20,
          event_id: 7,
          event_name: "Women's A",
          seed: 2,
          full_name: 'Cara Lee, Destin, FL / Dee Chen, Atlanta, GA',
          players: ['Cara Lee', 'Dee Chen'],
          photo_version: 'photo-20',
        },
        {
          team_id: 30,
          event_id: 7,
          event_name: "Women's A",
          seed: 3,
          full_name: 'Eve Ray, Orlando, FL / Fay Sun, Tampa, FL',
          players: ['Eve Ray', 'Fay Sun'],
          photo_version: null,
        },
      ],
    })
    vi.mocked(getPublicSchedule).mockResolvedValue({
      status: 'OK',
      tournament_name: 'Amelia Island',
      published_version_id: 1,
      show_court_info: true,
      events: [],
      divisions: [],
      days: [],
      matches: [
        {
          match_id: 40,
          match_number: 40,
          match_code: 'EVT_WF_R1_02',
          stage: 'WF',
          event_id: 7,
          event_name: "Women's A",
          division_name: null,
          day_index: 1,
          day_label: 'Friday, June 5',
          scheduled_time: '8:00 AM',
          sort_time: '08:00',
          court_name: 'Court 1',
          status: 'FINAL',
          team1_display: 'Cara / Dee',
          team2_display: 'Eve / Fay',
          team1_full_name: 'Cara Lee, Destin, FL / Dee Chen, Atlanta, GA',
          team2_full_name: 'Eve Ray, Orlando, FL / Fay Sun, Tampa, FL',
          score_display: '8-3',
          winner_team_id: 20,
          team_a_id: 20,
          team_b_id: 30,
        },
        {
          match_id: 41,
          match_number: 41,
          match_code: 'EVT_WF_R1_01',
          stage: 'WF',
          event_id: 7,
          event_name: "Women's A",
          division_name: null,
          day_index: 1,
          day_label: 'Friday, June 5',
          scheduled_time: '9:00 AM',
          sort_time: '09:00',
          court_name: 'Court 2',
          status: 'SCHEDULED',
          team1_display: 'Ada / Bea',
          team2_display: 'Cara / Dee',
          team1_full_name: 'Ada Smith, Cumming, GA / Bea Jones, Johns Island, SC',
          team2_full_name: 'Cara Lee, Destin, FL / Dee Chen, Atlanta, GA',
          score_display: null,
          winner_team_id: null,
          team_a_id: 10,
          team_b_id: 20,
        },
      ],
    })
    vi.mocked(getPublicDrawsList).mockResolvedValue({
      tournament_name: 'Amelia Island',
      events: [
        {
          event_id: 7,
          name: "Women's A",
          category: 'womens',
          team_count: 16,
          has_waterfall: true,
          has_round_robin: false,
          divisions: [],
        },
      ],
    })

    render(
      <MemoryRouter initialEntries={['/t/3/hub/teams/10']}>
        <Routes>
          <Route path="/t/:tournamentId/hub/teams/:teamId" element={<PublicTournamentTeamPage />} />
          <Route path="/t/:tournamentId/draws/:eventId/waterfall" element={<DrawLocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Ada Smith / Bea Jones')).toBeTruthy()
    expect(screen.getByTestId('hub-own-hometown')).toHaveTextContent('Cumming, GA / Johns Island, SC')
    expect(screen.getByTestId('hub-photo-10')).toBeTruthy()
    expect(screen.getByTestId('hub-photo-20')).toBeTruthy()
    expect(screen.getByTestId('hub-team-status')).toHaveTextContent('Court assigned')
    expect(screen.getByText('Destin, FL')).toBeTruthy()
    expect(screen.getByText('Atlanta, GA')).toBeTruthy()
    expect(screen.getByTestId('hub-opponent-past-matches')).toHaveTextContent('Opponent\'s past matches')
    expect(screen.getByTestId('hub-opponent-past-matches')).toHaveTextContent('Eve Ray')
    expect(screen.getByTestId('hub-opponent-past-matches')).toHaveTextContent('Orlando, FL')
    expect(screen.getByTestId('hub-opponent-past-matches')).toHaveTextContent('8-3')
    expect(screen.getByTestId('hub-opponent-past-matches')).toHaveTextContent('Win')

    fireEvent.click(screen.getByTestId('hub-view-draw-position'))
    expect(await screen.findByTestId('draw-location')).toHaveTextContent('/t/3/draws/7/waterfall?team=10&view=draw')
  })
})

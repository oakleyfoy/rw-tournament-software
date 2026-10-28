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
  it('shows status, next match, and draw position deep-link', async () => {
    vi.mocked(getPublicTeamDirectory).mockResolvedValue({
      status: 'OK',
      tournament_name: 'Amelia Island',
      teams: [
        {
          team_id: 10,
          event_id: 7,
          event_name: "Women's A",
          seed: 1,
          full_name: 'Ada Smith / Bea Jones',
          players: ['Ada Smith', 'Bea Jones'],
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
          team1_full_name: 'Ada Smith / Bea Jones',
          team2_full_name: 'Cara Lee / Dee Chen',
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
    expect(screen.getByTestId('hub-team-status')).toHaveTextContent('Court assigned')
    expect(screen.getByText('Cara Lee / Dee Chen')).toBeTruthy()

    fireEvent.click(screen.getByTestId('hub-view-draw-position'))
    expect(await screen.findByTestId('draw-location')).toHaveTextContent('/t/3/draws/7/waterfall?team=10&view=draw')
  })
})

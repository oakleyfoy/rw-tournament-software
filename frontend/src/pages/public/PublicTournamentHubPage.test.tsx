import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PublicTournamentHubPage from './PublicTournamentHubPage'

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

describe('PublicTournamentHubPage', () => {
  it('searches either partner and opens the team page', async () => {
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
        {
          team_id: 11,
          event_id: 8,
          event_name: 'Mixed B',
          seed: null,
          full_name: 'Ada Smith / Kim Park',
          players: ['Ada Smith', 'Kim Park'],
          photo_version: null,
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
    vi.mocked(getPublicSchedule).mockResolvedValue({
      status: 'OK',
      tournament_name: 'Amelia Island',
      published_version_id: 1,
      show_court_info: true,
      events: [],
      divisions: [],
      days: [],
      matches: [],
    })

    render(
      <MemoryRouter initialEntries={['/t/3/hub']}>
        <Routes>
          <Route path="/t/:tournamentId/hub" element={<PublicTournamentHubPage />} />
          <Route path="/t/:tournamentId/hub/teams/:teamId" element={<div>Team page 10</div>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Racquet War')).toBeTruthy()
    expect(screen.getByText('Amelia Island')).toBeTruthy()

    fireEvent.change(screen.getByTestId('hub-team-search'), { target: { value: 'bea' } })
    expect(await screen.findByText('Ada Smith / Bea Jones')).toBeTruthy()
    expect(screen.queryByText('Ada Smith / Kim Park')).toBeNull()

    fireEvent.change(screen.getByTestId('hub-team-search'), { target: { value: 'ada' } })
    await waitFor(() => {
      expect(screen.getByTestId('hub-result-10')).toBeTruthy()
      expect(screen.getByTestId('hub-result-11')).toBeTruthy()
    })

    fireEvent.click(screen.getByTestId('hub-result-10'))
    expect(await screen.findByText('Team page 10')).toBeTruthy()
  })
})

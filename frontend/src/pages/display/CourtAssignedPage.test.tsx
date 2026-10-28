import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeMatch, sampleBoard } from './displayBoardFixture'

const hookState = {
  data: sampleBoard,
  error: null as string | null,
  initialLoading: false,
  refreshing: false,
  refresh: vi.fn(),
}

vi.mock('./useDisplayBoard', () => ({
  useDisplayBoard: () => hookState,
}))

import CourtAssignedPage from './CourtAssignedPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/desk/t/9/display/court-assigned']}>
      <Routes>
        <Route path="/desk/t/:tournamentId/display/court-assigned" element={<CourtAssignedPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('CourtAssignedPage', () => {
  beforeEach(() => {
    hookState.data = {
      ...sampleBoard,
      upcoming_12h_groups: [
        {
          scheduled_time: '2:30 PM',
          sort_time: '14:30',
          matches: [
            makeMatch({
              match_id: 21,
              scheduled_time: '2:30 PM',
              sort_time: '14:30',
              team_a_names: 'Jane / Lily',
              team_b_names: 'Pam / Tess',
              court: 'Court 3',
            }),
          ],
        },
        {
          scheduled_time: '3:00 PM',
          sort_time: '15:00',
          matches: [
            makeMatch({
              match_id: 22,
              scheduled_time: '3:00 PM',
              sort_time: '15:00',
              team_a_names: 'No Court A',
              team_b_names: 'No Court B',
            }),
          ],
        },
        {
          scheduled_time: '3:30 PM',
          sort_time: '15:30',
          matches: [
            makeMatch({
              match_id: 23,
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
    hookState.error = null
    hookState.initialLoading = false
  })

  it('shows currently playing names and court numbers', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Court Assigned' })).toBeInTheDocument()
    const playing = screen.getByTestId('court-assigned-playing')
    expect(playing).toHaveTextContent('Helen / Simone')
    expect(playing).toHaveTextContent('Court 7')
    expect(playing).toHaveTextContent('Amy / Terry')
  })

  it('shows upcoming court-assigned matches by time and hides slots without courts', () => {
    renderPage()
    expect(screen.getByTestId('court-assigned-group-14:30')).toHaveTextContent('2:30 PM')
    expect(screen.getByTestId('court-assigned-group-14:30')).toHaveTextContent('Jane / Lily')
    expect(screen.getByTestId('display-court-21')).toHaveTextContent('Court 3')
    expect(screen.getByTestId('court-assigned-group-15:30')).toHaveTextContent('John / TBD')
    expect(screen.getByTestId('display-court-23')).toHaveTextContent('Court 99')
    expect(screen.queryByTestId('court-assigned-group-15:00')).not.toBeInTheDocument()
    expect(screen.queryByText('No Court A')).not.toBeInTheDocument()
    expect(screen.getByTestId('court-assigned-upcoming')).toHaveAttribute('data-slot-count', '2')
  })

  it('reserves layout space for at least two upcoming time slots', () => {
    renderPage()
    expect(screen.getByTestId('court-assigned-board')).toHaveAttribute('data-min-slots', '2')
    expect(screen.getByTestId('court-assigned-upcoming')).toHaveClass('display-court-assigned-upcoming')
  })

  it('does not show waiting queue or event/round labels', () => {
    renderPage()
    expect(screen.queryByText('Waiting for Court')).not.toBeInTheDocument()
    expect(screen.queryByText("Women's B")).not.toBeInTheDocument()
    expect(screen.queryByText('WF R1')).not.toBeInTheDocument()
  })

  it('shows empty upcoming state when no courts are assigned ahead', () => {
    hookState.data = {
      ...sampleBoard,
      upcoming_12h_groups: [
        {
          scheduled_time: '4:00 PM',
          sort_time: '16:00',
          matches: [makeMatch({ match_id: 40, scheduled_time: '4:00 PM', sort_time: '16:00' })],
        },
      ],
    }
    renderPage()
    expect(screen.getByText('No upcoming matches with a court assigned')).toBeInTheDocument()
  })

  it('has no edit controls', () => {
    renderPage()
    expect(screen.getByTestId('display-refresh')).toBeInTheDocument()
    expect(screen.getByTestId('display-fullscreen')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})

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

vi.mock('./useNowMs', () => ({
  useNowMs: () => Date.parse('2026-06-05T15:15:00.000Z'),
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
      currently_playing: [
        makeMatch({
          match_id: 11,
          scheduled_time: '7:00 AM',
          sort_time: '07:00',
          board_section: 'currently_playing',
          in_next_12_hours: false,
          court: 'Court 7',
          started_at: '2026-06-05T14:00:00',
          team_a_names: 'Helen / Simone',
          team_b_names: 'Amy / Terry',
        }),
      ],
      upcoming: [
        makeMatch({
          match_id: 21,
          scheduled_time: '8:00 AM',
          sort_time: '08:00',
          day_date: '2026-06-05',
          team_a_names: 'Jane / Lily',
          team_b_names: 'Pam / Tess',
          court: 'Court 3',
          in_next_12_hours: false,
        }),
        makeMatch({
          match_id: 22,
          scheduled_time: '9:00 AM',
          sort_time: '09:00',
          day_date: '2026-06-05',
          team_a_names: 'No Court A',
          team_b_names: 'No Court B',
          in_next_12_hours: false,
        }),
        makeMatch({
          match_id: 23,
          scheduled_time: '9:00 AM',
          sort_time: '09:00',
          day_date: '2026-06-05',
          team_a_names: 'John / TBD',
          team_b_names: 'Mike / David',
          team_a_has_tbd: true,
          court: 'Court 99',
          in_next_12_hours: false,
        }),
      ],
      upcoming_12h: [],
      upcoming_12h_groups: [],
    }
    hookState.error = null
    hookState.initialLoading = false
  })

  it('shows currently playing names, court, and live time on court', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Court Assigned' })).toBeInTheDocument()
    const playing = screen.getByTestId('court-assigned-playing')
    expect(playing).toHaveTextContent('Helen / Simone')
    expect(playing).toHaveTextContent('Court 7')
    expect(playing).toHaveTextContent('Amy / Terry')
    expect(screen.getByTestId('display-time-on-court-11')).toHaveTextContent('1:15:00')
    expect(playing).not.toHaveTextContent('7:00 AM')
  })

  it('shows past-scheduled court-assigned upcoming matches and hides slots without courts', () => {
    renderPage()
    expect(screen.getByTestId('court-assigned-group-08:00')).toHaveTextContent('8:00 AM')
    expect(screen.getByTestId('court-assigned-group-08:00')).toHaveTextContent('Jane / Lily')
    expect(screen.getByTestId('display-court-21')).toHaveTextContent('Court 3')
    expect(screen.getByTestId('court-assigned-group-09:00')).toHaveTextContent('John / TBD')
    expect(screen.getByTestId('display-court-23')).toHaveTextContent('Court 99')
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
      upcoming: [makeMatch({ match_id: 40, scheduled_time: '4:00 PM', sort_time: '16:00' })],
      upcoming_12h_groups: [],
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

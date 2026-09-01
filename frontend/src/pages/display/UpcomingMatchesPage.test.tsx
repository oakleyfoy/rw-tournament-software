import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sampleBoard } from './displayBoardFixture'

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

import UpcomingMatchesPage from './UpcomingMatchesPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/desk/t/9/display/upcoming']}>
      <Routes>
        <Route path="/desk/t/:tournamentId/display/upcoming" element={<UpcomingMatchesPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('UpcomingMatchesPage', () => {
  beforeEach(() => {
    hookState.data = sampleBoard
    hookState.error = null
    hookState.initialLoading = false
  })

  it('groups matches by scheduled time and shows names plus event', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Upcoming Matches' })).toBeInTheDocument()
    expect(screen.getByText('Next 12 Hours')).toBeInTheDocument()
    expect(screen.getByText('Display Board Open')).toBeInTheDocument()
    expect(screen.getByTestId('upcoming-group-14:30')).toHaveTextContent('2:30 PM')
    expect(screen.getByTestId('upcoming-group-14:30')).toHaveTextContent('Jane / Lily')
    expect(screen.getByTestId('upcoming-group-15:30')).toHaveTextContent('John / TBD')
    expect(screen.getByTestId('upcoming-group-15:30')).toHaveTextContent('Mike / David')
    expect(screen.getByTestId('upcoming-board')).toHaveTextContent("Women's B")
  })

  it('never renders court, including assigned court leaked from the payload', () => {
    renderPage()
    expect(screen.queryByText('Court 7')).not.toBeInTheDocument()
    expect(screen.queryByText('Court 99')).not.toBeInTheDocument()
    expect(screen.queryByText(/Court TBD/i)).not.toBeInTheDocument()
    expect(screen.queryByTestId(/display-court-/)).not.toBeInTheDocument()
  })

  it('uses the high-density upcoming grid under each time group', () => {
    renderPage()
    expect(screen.getByTestId('display-upcoming-grid-14:30')).toHaveClass('display-match-grid')
    expect(screen.getByTestId('display-upcoming-grid-15:30')).toHaveClass('display-match-grid')
  })

  it('shows the empty 12-hour state', () => {
    hookState.data = { ...sampleBoard, upcoming_12h: [], upcoming_12h_groups: [] }
    renderPage()
    expect(screen.getByText('No matches scheduled in the next 12 hours')).toBeInTheDocument()
  })

  it('has no edit controls', () => {
    renderPage()
    expect(screen.getByTestId('display-refresh')).toBeInTheDocument()
    expect(screen.getByTestId('display-fullscreen')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})

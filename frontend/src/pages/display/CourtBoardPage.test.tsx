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

import CourtBoardPage from './CourtBoardPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/desk/t/9/display/courts']}>
      <Routes>
        <Route path="/desk/t/:tournamentId/display/courts" element={<CourtBoardPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('CourtBoardPage', () => {
  beforeEach(() => {
    hookState.data = sampleBoard
    hookState.error = null
    hookState.initialLoading = false
    hookState.refreshing = false
  })

  it('renders currently playing with court and scheduled time', () => {
    renderPage()
    expect(screen.getByTestId('currently-playing')).toHaveTextContent('Helen / Simone')
    expect(screen.getByTestId('currently-playing')).toHaveTextContent('Court 7')
    expect(screen.getByTestId('currently-playing')).toHaveTextContent('1:30 PM')
    expect(screen.queryByText('Helen Robinson')).not.toBeInTheDocument()
  })

  it('moves both-checked matches into waiting without court', () => {
    renderPage()
    const waiting = screen.getByTestId('waiting-for-court')
    expect(waiting).toHaveTextContent('Jane / Lily')
    expect(waiting).toHaveTextContent('Pam / Tess')
    expect(waiting).not.toHaveTextContent('Court 3')
  })

  it('shows one-team check-in in upcoming without court', () => {
    renderPage()
    const upcoming = screen.getByTestId('court-board-upcoming')
    expect(upcoming).toHaveTextContent('Helen / Simone')
    expect(upcoming).not.toHaveTextContent('Court 4')
  })

  it('shows quiet empty states', () => {
    hookState.data = {
      ...sampleBoard,
      currently_playing: [],
      waiting_for_court: [],
      upcoming: [],
    }
    renderPage()
    expect(screen.getByText('No matches currently on court')).toBeInTheDocument()
    expect(screen.getByText('No matches waiting for court')).toBeInTheDocument()
  })

  it('has no edit controls', () => {
    renderPage()
    expect(screen.getByTestId('display-refresh')).toBeInTheDocument()
    expect(screen.getByTestId('display-fullscreen')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('renders the loading state', () => {
    hookState.data = null
    hookState.initialLoading = true
    renderPage()
    expect(screen.getByTestId('display-loading')).toHaveTextContent('Loading tournament display')
  })
})

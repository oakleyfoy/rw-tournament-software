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

  it('collapses empty currently playing and waiting into a compact single line', () => {
    hookState.data = {
      ...sampleBoard,
      currently_playing: [],
      waiting_for_court: [],
      upcoming: [],
    }
    renderPage()
    const playing = screen.getByTestId('currently-playing')
    const waiting = screen.getByTestId('waiting-for-court')
    expect(playing).toHaveAttribute('data-empty', 'true')
    expect(waiting).toHaveAttribute('data-empty', 'true')
    expect(playing).toHaveClass('display-section-compact')
    expect(waiting).toHaveClass('display-section-compact')
    expect(playing).toHaveTextContent('Currently Playing')
    expect(playing).toHaveTextContent('No matches currently on court')
    expect(waiting).toHaveTextContent('Waiting for Court')
    expect(waiting).toHaveTextContent('No matches waiting for court')
    expect(screen.queryByTestId('display-playing-grid')).not.toBeInTheDocument()
    expect(screen.queryByTestId('display-waiting-grid')).not.toBeInTheDocument()
  })

  it('keeps full card grids when currently playing and waiting have matches', () => {
    renderPage()
    expect(screen.getByTestId('currently-playing')).toHaveAttribute('data-empty', 'false')
    expect(screen.getByTestId('waiting-for-court')).toHaveAttribute('data-empty', 'false')
    expect(screen.getByTestId('currently-playing')).not.toHaveClass('display-section-compact')
    expect(screen.getByTestId('display-playing-grid')).toHaveClass('display-playing-grid')
    expect(screen.getByTestId('display-waiting-grid')).toHaveClass('display-waiting-grid')
    expect(screen.getByTestId('display-upcoming-grid')).toHaveClass('display-match-grid')
    expect(screen.getByTestId('display-match-11')).toBeInTheDocument()
    expect(screen.getByTestId('display-match-12')).toBeInTheDocument()
  })

  it('shows court only on currently playing cards', () => {
    renderPage()
    expect(screen.getByTestId('display-court-11')).toHaveTextContent('Court 7')
    expect(screen.queryByTestId('display-court-12')).not.toBeInTheDocument()
    expect(screen.queryByTestId('display-court-13')).not.toBeInTheDocument()
  })

  it('does not render event, division, or round on any court-board section', () => {
    renderPage()
    expect(screen.queryByText("Women's B")).not.toBeInTheDocument()
    expect(screen.queryByText('WF R1')).not.toBeInTheDocument()
    expect(screen.queryByText(/ · /)).not.toBeInTheDocument()
    expect(document.querySelector('.display-meta')).toBeNull()
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

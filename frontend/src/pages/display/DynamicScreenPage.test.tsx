import { render, screen, within } from '@testing-library/react'
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
  useNowMs: () => Date.parse('2026-06-05T14:15:00.000Z'),
}))

import DynamicScreenPage from './DynamicScreenPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/desk/t/9/display/dynamic']}>
      <Routes>
        <Route path="/desk/t/:tournamentId/display/dynamic" element={<DynamicScreenPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('DynamicScreenPage', () => {
  beforeEach(() => {
    hookState.data = {
      ...sampleBoard,
      currently_playing: [
        makeMatch({
          match_id: 11,
          scheduled_time: '1:30 PM',
          sort_time: '13:30',
          board_section: 'currently_playing',
          in_next_12_hours: false,
          court: 'Court 7',
          started_at: '2026-06-05T14:00:00.000Z',
        }),
      ],
      waiting_for_court: [
        makeMatch({
          match_id: 31,
          scheduled_time: '2:30 PM',
          sort_time: '14:30',
          team_a_names: 'First Ready / A',
          team_b_names: 'First Ready / B',
          team_a_checked_in: true,
          team_b_checked_in: true,
          board_section: 'waiting_for_court',
          ready_at: '2026-06-05T13:50:00.000Z',
        }),
        makeMatch({
          match_id: 32,
          scheduled_time: '2:00 PM',
          sort_time: '14:00',
          team_a_names: 'Second Ready / A',
          team_b_names: 'Second Ready / B',
          team_a_checked_in: true,
          team_b_checked_in: true,
          board_section: 'waiting_for_court',
          ready_at: '2026-06-05T13:55:00.000Z',
        }),
      ],
      upcoming: [
        makeMatch({
          match_id: 41,
          scheduled_time: '8:00 AM',
          sort_time: '08:00',
          day_date: '2026-11-06',
          team_a_names: 'Checked / One',
          team_b_names: 'Waiting / Two',
          team_a_checked_in: true,
          team_b_checked_in: false,
        }),
        makeMatch({
          match_id: 42,
          scheduled_time: '9:00 AM',
          sort_time: '09:00',
          day_date: '2026-11-06',
          team_a_names: 'Later / A',
          team_b_names: 'Later / B',
        }),
        makeMatch({
          match_id: 43,
          scheduled_time: '8:00 AM',
          sort_time: '08:00',
          day_date: '2026-11-06',
          team_a_names: 'Same Slot / A',
          team_b_names: 'Same Slot / B',
        }),
      ],
    }
    hookState.error = null
    hookState.initialLoading = false
  })

  it('shows currently playing with names, court, and time on court', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Dynamic Screen' })).toBeInTheDocument()
    const playing = screen.getByTestId('dynamic-currently-playing')
    expect(playing).toHaveTextContent('Helen / Simone')
    expect(playing).toHaveTextContent('Court 7')
    expect(screen.getByTestId('display-time-on-court-11')).toHaveTextContent('15:00')
  })

  it('shows next matches with checkmarks as teams check in', () => {
    renderPage()
    const next = screen.getByTestId('dynamic-next-matches')
    expect(next).toHaveTextContent('Checked / One')
    expect(next).toHaveTextContent('Waiting / Two')
    expect(within(next).getByText('Checked / One').closest('[data-checked]')).toHaveAttribute(
      'data-checked',
      'true'
    )
    expect(within(next).getByText('Waiting / Two').closest('[data-checked]')).toHaveAttribute(
      'data-checked',
      'false'
    )
    expect(screen.queryByTestId('display-court-41')).not.toBeInTheDocument()
  })

  it('separates next matches into time-slot sections', () => {
    renderPage()
    expect(screen.getByTestId('dynamic-next-group-08:00')).toHaveTextContent('8:00 AM')
    expect(screen.getByTestId('dynamic-next-group-08:00')).toHaveTextContent('Checked / One')
    expect(screen.getByTestId('dynamic-next-group-08:00')).toHaveTextContent('Same Slot / A')
    expect(screen.getByTestId('dynamic-next-group-09:00')).toHaveTextContent('9:00 AM')
    expect(screen.getByTestId('dynamic-next-group-09:00')).toHaveTextContent('Later / A')
    expect(screen.getByTestId('dynamic-next-group-08:00')).not.toHaveTextContent('Later / A')
  })

  it('moves both-checked matches into waiting and keeps ready order', () => {
    renderPage()
    const waiting = screen.getByTestId('dynamic-waiting-for-court')
    expect(waiting).toHaveTextContent('First Ready / A')
    expect(waiting).toHaveTextContent('Second Ready / A')
    expect(screen.queryByTestId('display-court-31')).not.toBeInTheDocument()
    expect(screen.queryByTestId('display-court-32')).not.toBeInTheDocument()
    const cards = within(waiting).getAllByTestId(/display-match-/)
    expect(cards[0]).toHaveAttribute('data-testid', 'display-match-31')
    expect(cards[1]).toHaveAttribute('data-testid', 'display-match-32')
  })

  it('renders sections in playing → next → waiting order', () => {
    renderPage()
    const board = screen.getByTestId('dynamic-screen-board')
    const sections = within(board).getAllByRole('heading', { level: 2 })
    expect(sections.map((node) => node.textContent)).toEqual([
      'Currently Playing',
      'Next Matches',
      'Waiting for Court',
    ])
  })

  it('has no edit controls', () => {
    renderPage()
    expect(screen.getByTestId('display-refresh')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})

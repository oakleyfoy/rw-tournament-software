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
          scheduled_time: '7:00 AM',
          sort_time: '07:00',
          day_date: '2026-11-06',
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
          court: 'Court 8',
          team_a_names: 'Julie / Paige',
          team_b_names: 'Pam / Rebecca',
          team_a_checked_in: true,
          team_b_checked_in: true,
          ready_at: '2026-11-06T15:10:00',
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
          court: 'Court 2',
          team_a_names: 'Not Ready / A',
          team_b_names: 'Not Ready / B',
        }),
        makeMatch({
          match_id: 44,
          scheduled_time: '8:00 AM',
          sort_time: '08:00',
          day_date: '2026-11-06',
          court: 'Court 1',
          team_a_names: 'Danielle / Johnna',
          team_b_names: 'Riley / Ashley',
          team_a_checked_in: true,
          team_b_checked_in: true,
          ready_at: '2026-11-06T15:05:00',
        }),
      ],
    }
    hookState.error = null
    hookState.initialLoading = false
  })

  it('shows currently playing under its time slot after the slot moves up', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Dynamic Screen' })).toBeInTheDocument()
    const playing = screen.getByTestId('dynamic-currently-playing')
    expect(playing).toHaveTextContent('Helen / Simone')
    expect(playing).toHaveTextContent('Court 7')
    expect(screen.getByTestId('dynamic-playing-group-07:00')).toHaveTextContent('7:00 AM')
    expect(screen.getByTestId('display-time-on-court-11')).toHaveTextContent('15:00')
  })

  it('labels next time slots with OUT and sorts both-checked left by ready_at', () => {
    renderPage()
    const eight = screen.getByTestId('dynamic-next-group-08:00')
    expect(eight).toHaveTextContent('8:00 AM OUT')
    const cards = within(eight).getAllByTestId(/display-match-/)
    expect(cards[0]).toHaveAttribute('data-testid', 'display-match-44')
    expect(cards[1]).toHaveAttribute('data-testid', 'display-match-41')
    expect(cards[2]).toHaveAttribute('data-testid', 'display-match-43')
    expect(within(eight).getByText('Danielle / Johnna').closest('[data-checked]')).toHaveAttribute(
      'data-checked',
      'true'
    )
    expect(within(eight).getByText('Julie / Paige').closest('[data-checked]')).toHaveAttribute(
      'data-checked',
      'true'
    )
  })

  it('separates next matches into time-slot sections', () => {
    renderPage()
    expect(screen.getByTestId('dynamic-next-group-08:00')).toHaveTextContent('Julie / Paige')
    expect(screen.getByTestId('dynamic-next-group-09:00')).toHaveTextContent('9:00 AM OUT')
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

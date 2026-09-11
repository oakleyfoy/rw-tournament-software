import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PublicWaterfallPage, {
  PHONE_WATERFALL_MAX_WIDTH,
  buildPhoneWaterfallLayout,
  buildWaterfallLayout,
} from './PublicWaterfallPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getPublicWaterfall: vi.fn(),
  }
})

import { getPublicWaterfall, PublicWaterfallResponse } from '../../api/client'

const sample: PublicWaterfallResponse = {
  tournament_name: 'Amelia Island',
  event_name: "Women's A",
  division_type: 'bracket',
  show_court_info: false,
  rows: [
    {
      center_box: {
        match_id: 1,
        match_number: 1,
        court_label: null,
        start_time_local: null,
        status: 'SCHEDULED',
        score_display: null,
        top_line: 'Match 1',
        line1: 'Heather Herman / Barry Herman',
        line2: 'Lisa Jones / Mary Smith',
        notes: null,
        winner_team_id: null,
        team_a_id: 1,
        team_b_id: 2,
      },
      loser_box: {
        match_id: 3,
        match_number: 3,
        court_label: null,
        start_time_local: null,
        status: 'UNSCHEDULED',
        score_display: null,
        top_line: 'Match 3',
        line1: 'Loser of Match 1',
        line2: 'Loser of Match 2',
        notes: null,
        winner_team_id: null,
        team_a_id: null,
        team_b_id: null,
      },
      winner_box: {
        match_id: 4,
        match_number: 4,
        court_label: null,
        start_time_local: null,
        status: 'UNSCHEDULED',
        score_display: null,
        top_line: 'Match 4',
        line1: 'Winner of Match 1',
        line2: 'Winner of Match 2',
        notes: null,
        winner_team_id: null,
        team_a_id: null,
        team_b_id: null,
      },
      winner_dest: 'Winner to Division I\nLoser to Division II',
      loser_dest: 'Winner to Division III\nLoser to Division IV',
      r2_winner_team_name: null,
      r2_loser_team_name: null,
    },
    {
      center_box: {
        match_id: 2,
        match_number: 2,
        court_label: null,
        start_time_local: null,
        status: 'SCHEDULED',
        score_display: null,
        top_line: 'Match 2',
        line1: 'Ann Partner / Patty Shepard',
        line2: 'Darlene Oldenberg / Brannan',
        notes: null,
        winner_team_id: null,
        team_a_id: 3,
        team_b_id: 4,
      },
      loser_box: null,
      winner_box: null,
      winner_dest: null,
      loser_dest: null,
      r2_winner_team_name: null,
      r2_loser_team_name: null,
    },
  ],
}

describe('waterfall phone layout', () => {
  it('keeps phone team names at a readable size', () => {
    const phone = buildPhoneWaterfallLayout()
    expect(phone.teamFontSize).toBeGreaterThanOrEqual(14)
    expect(phone.matchFontSize).toBeGreaterThanOrEqual(12)
    expect(phone.destFontSize).toBeGreaterThanOrEqual(12)
  })

  it('does not shrink desktop scale below a readable floor', () => {
    const scaled = buildWaterfallLayout(390 / 1688, 390)
    expect(scaled.teamFontSize).toBeGreaterThanOrEqual(6.8)
    expect(PHONE_WATERFALL_MAX_WIDTH).toBeGreaterThanOrEqual(768)
  })

  it('renders stacked match names on a phone-width canvas', async () => {
    vi.mocked(getPublicWaterfall).mockResolvedValue(sample)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })

    render(
      <MemoryRouter initialEntries={['/t/9/draws/19/waterfall']}>
        <Routes>
          <Route path="/t/:tournamentId/draws/:eventId/waterfall" element={<PublicWaterfallPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Heather Herman / Barry Herman')).toBeInTheDocument()
    })
    expect(screen.getByText('↓ Loser Path')).toBeInTheDocument()
    expect(screen.getByText('↓ Winner Path')).toBeInTheDocument()
    expect(screen.getAllByText(/Winner to Division I/).length).toBeGreaterThan(0)
  })
})

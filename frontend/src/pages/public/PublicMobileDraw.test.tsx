import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PublicMobileDraw from './PublicMobileDraw'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getPublicSchedule: vi.fn(),
    getPublicTeamDirectory: vi.fn(),
  }
})

import { getPublicSchedule, getPublicTeamDirectory } from '../../api/client'

const schedule = {
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
}

const directory = {
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
      team_id: 20,
      event_id: 7,
      event_name: "Women's A",
      seed: 2,
      full_name: 'Cara Lee / Dee Chen',
      players: ['Cara Lee', 'Dee Chen'],
      photo_version: 'photo-1',
    },
  ],
}

describe('PublicMobileDraw', () => {
  it('shows the division, a photo when one exists, and keeps the selected team after refresh', async () => {
    vi.mocked(getPublicSchedule).mockResolvedValue(schedule)
    vi.mocked(getPublicTeamDirectory).mockResolvedValue(directory)
    const onShowFullDraw = vi.fn()

    render(
      <MemoryRouter>
        <PublicMobileDraw
          tournamentId={3}
          eventId={7}
          tournamentName="Amelia Island"
          eventName="Women's A"
          formatLabel="Waterfall"
          backHref="/t/3/draws"
          onShowFullDraw={onShowFullDraw}
          refreshMs={20}
        />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Ada Smith / Bea Jones')).toBeTruthy()
    expect(screen.queryByText('Seed 1')).toBeNull()
    expect(screen.queryByText('Seed 2')).toBeNull()
    expect(document.querySelector('img')?.getAttribute('src')).toContain('/teams/20/photo?v=photo-1')
    expect(screen.getByText('AB')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Find your team'), { target: { value: 'bea' } })
    fireEvent.click(document.querySelector('.public-search-result') as HTMLButtonElement)
    expect(screen.getByRole('tab', { name: 'My Matches' })).toHaveAttribute('aria-selected', 'true')

    vi.mocked(getPublicSchedule).mockResolvedValue({
      ...schedule,
      matches: [{ ...schedule.matches[0], court_name: 'Court 8', scheduled_time: '10:30 AM' }],
    })
    await waitFor(() => {
      expect(screen.getAllByText('Court 8').length).toBeGreaterThan(0)
    })
    expect(screen.getByRole('tab', { name: 'My Matches' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByText('10:30 AM').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Full Draw' }))
    expect(onShowFullDraw).toHaveBeenCalled()
  })

  it('shows a short team header and does not repeat the next match', async () => {
    vi.mocked(getPublicSchedule).mockResolvedValue({
      ...schedule,
      matches: [
        {
          ...schedule.matches[0],
          status: 'FINAL',
          score_display: '8-5',
          winner_team_id: 10,
          team1_full_name: 'Heather Robinson, Cumming, GA / Shea Butler, Johns Island, SC',
          team2_full_name: 'Cara Lee, Southlake, TX / Dee Chen, Plano, TX',
        },
        {
          ...schedule.matches[0],
          match_id: 42,
          match_number: 42,
          match_code: 'EVT_WF_R2_W01',
          day_label: 'Saturday, June 6',
          scheduled_time: '11:00 AM',
          court_name: 'Court 4',
          status: 'SCHEDULED',
          team_a_id: 10,
          team_b_id: 20,
          team1_full_name: 'Heather Robinson, Cumming, GA / Shea Butler, Johns Island, SC',
          team2_full_name: 'Cara Lee, Southlake, TX / Dee Chen, Plano, TX',
          score_display: null,
          winner_team_id: null,
        },
      ],
    })
    vi.mocked(getPublicTeamDirectory).mockResolvedValue({
      ...directory,
      teams: [
        {
          ...directory.teams[0],
          seed: 4,
          full_name: 'Heather Robinson, Cumming, GA / Shea Butler, Johns Island, SC',
          players: ['Heather Robinson', 'Shea Butler', 'HR'],
          photo_version: null,
        },
        {
          ...directory.teams[1],
          full_name: 'Cara Lee, Southlake, TX / Dee Chen, Plano, TX',
          players: ['Cara Lee', 'Dee Chen'],
          photo_version: null,
        },
      ],
    })

    render(
      <MemoryRouter>
        <PublicMobileDraw
          tournamentId={3}
          eventId={7}
          tournamentName="Amelia Island"
          eventName="Women's A"
          formatLabel="Waterfall"
          backHref="/t/3/draws"
          onShowFullDraw={vi.fn()}
        />
      </MemoryRouter>,
    )

    fireEvent.change(await screen.findByLabelText('Find your team'), { target: { value: 'heather' } })
    fireEvent.click(document.querySelector('.public-search-result') as HTMLButtonElement)
    expect(screen.getByRole('tab', { name: 'My Matches' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Heather Robinson')).toBeTruthy()
    expect(screen.getByText('Shea Butler')).toBeTruthy()
    expect(screen.queryByText(/Cumming/)).toBeNull()
    expect(screen.queryByText('HR')).toBeNull()
    expect(screen.queryByText(/Seed 4/)).toBeNull()
    expect(screen.getByText('Cara Lee')).toBeTruthy()
    expect(screen.getByText('Dee Chen')).toBeTruthy()
    expect(screen.getByText('11:00 AM')).toBeTruthy()
    expect(screen.getByText('Court 4')).toBeTruthy()
    expect(screen.getAllByText('Match #42')).toHaveLength(1)
    expect(screen.getByText('Score 8-5')).toBeTruthy()
    expect(document.querySelector('.public-photo-fallback.large')).toBeTruthy()
    expect(document.querySelector('.public-photo.large')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Score 8-5/ }))
    expect(screen.getByText('Full registration names')).toBeTruthy()
  })
})

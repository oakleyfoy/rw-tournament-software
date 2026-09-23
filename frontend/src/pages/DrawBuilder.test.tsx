import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Event, Phase1Status, Tournament } from '../api/client'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    getTournament: vi.fn(),
    getEvents: vi.fn(),
    getPhase1Status: vi.fn(),
    getScheduleVersions: vi.fn(),
    getPlanReport: vi.fn(),
    getTournamentDays: vi.fn(),
    getScheduleBuilder: vi.fn(),
    refreshRwOsImport: vi.fn(),
    getEventTeams: vi.fn(),
    importCombinedTeams: vi.fn(),
    updateTournament: vi.fn(),
  }
})

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

import DrawBuilder from './DrawBuilder'
import { getEvents, getPhase1Status, getPlanReport, getScheduleBuilder, getScheduleVersions, getTournament, getTournamentDays } from '../api/client'

const tournamentBase: Tournament = {
  id: 5,
  name: 'Scottsdale',
  location: 'AZ',
  timezone: 'America/Phoenix',
  start_date: '2026-08-23',
  end_date: '2026-08-23',
  is_archived: false,
  use_time_windows: true,
  public_schedule_version_id: null,
  rw_os_import_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const finalizedEvent: Event = {
  id: 19,
  tournament_id: 5,
  category: 'womens',
  name: "Women's A",
  team_count: 8,
  draw_status: 'final',
  guarantee_selected: 5,
}

const phase1: Phase1Status = {
  is_ready: true,
  errors: [],
  summary: { active_days: 1, total_court_minutes: 7200, events_count: 1 },
}

function mockDrawBuilderApis(tournament: Tournament) {
  vi.mocked(getTournament).mockResolvedValue(tournament)
  vi.mocked(getEvents).mockResolvedValue([finalizedEvent])
  vi.mocked(getPhase1Status).mockResolvedValue(phase1)
  vi.mocked(getScheduleVersions).mockResolvedValue([])
  vi.mocked(getPlanReport).mockResolvedValue(null)
  vi.mocked(getTournamentDays).mockResolvedValue([
    { id: 1, tournament_id: 5, date: '2026-08-23', is_active: true, courts_available: 8 },
  ])
  vi.mocked(getScheduleBuilder).mockResolvedValue({ tournament_id: 5, events: [] })
}

function renderDrawBuilder() {
  return render(
    <MemoryRouter initialEntries={['/tournaments/5/draw-builder']}>
      <Routes>
        <Route path="/tournaments/:id/draw-builder" element={<DrawBuilder />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DrawBuilder RW-OS roster refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.scrollTo = vi.fn()
  })

  it('shows Refresh roster from RW-OS and hides Combined paste when rw_os_import_id is set', async () => {
    mockDrawBuilderApis({ ...tournamentBase, rw_os_import_id: 12 })
    renderDrawBuilder()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Refresh roster from RW-OS' })).toBeInTheDocument()
    })
    expect(screen.getByText(/This replaces Combined paste/)).toBeInTheDocument()
    expect(screen.queryByText('Combined Team + Towel Import')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Import Teams \+ Towels/i })).not.toBeInTheDocument()
  })

  it('keeps Combined paste for manual tournaments', async () => {
    mockDrawBuilderApis(tournamentBase)
    renderDrawBuilder()

    await waitFor(() => {
      expect(screen.getByText('Combined Team + Towel Import')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Refresh roster from RW-OS' })).not.toBeInTheDocument()
  })
})

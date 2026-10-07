import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Event, Match, Phase1Status, TeamListItem, Tournament } from '../api/client'

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
    getTournamentRwOsImport: vi.fn(),
    ensureTournamentRwOsImport: vi.fn(),
    getEventTeams: vi.fn(),
    getEventAvoidEdges: vi.fn(),
    getEventWhoKnowsWhoSummary: vi.fn(),
    getTournamentWhoKnowsWhoSummary: vi.fn(),
    getMatches: vi.fn(),
    importCombinedTeams: vi.fn(),
    updateTournament: vi.fn(),
    swapPostDrawTeams: vi.fn(),
  }
})

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

import DrawBuilder from './DrawBuilder'
import {
  getEventAvoidEdges,
  getEventTeams,
  getEventWhoKnowsWhoSummary,
  getEvents,
  getMatches,
  getPhase1Status,
  getPlanReport,
  getScheduleBuilder,
  getScheduleVersions,
  getTournament,
  getTournamentDays,
  getTournamentRwOsImport,
  getTournamentWhoKnowsWhoSummary,
  swapPostDrawTeams,
} from '../api/client'

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

const eventA: Event = {
  id: 19,
  tournament_id: 5,
  category: 'womens',
  name: "Women's A",
  team_count: 8,
  draw_status: 'final',
  guarantee_selected: 5,
  draw_plan_json: JSON.stringify({
    template_type: 'WF_TO_POOLS_DYNAMIC',
    wf_rounds: 1,
    timing: { standard_block_minutes: 120, wf_block_minutes: 60 },
  }),
}

const eventB: Event = {
  id: 20,
  tournament_id: 5,
  category: 'womens',
  name: "Women's B",
  team_count: 8,
  draw_status: 'final',
  guarantee_selected: 5,
  draw_plan_json: JSON.stringify({
    template_type: 'WF_TO_POOLS_DYNAMIC',
    wf_rounds: 1,
    timing: { standard_block_minutes: 120, wf_block_minutes: 60 },
  }),
}

const phase1: Phase1Status = {
  is_ready: true,
  errors: [],
  summary: { active_days: 1, total_court_minutes: 7200, events_count: 2 },
}

function team(
  id: number,
  eventId: number,
  name: string,
  neighbors: string[] = [],
): TeamListItem {
  return {
    id,
    event_id: eventId,
    name,
    display_name: name,
    seed: id,
    rating: 8.5,
    avoid_group: null,
    avoid_neighbors: neighbors,
    avoid_neighbor_count: neighbors.length,
    created_at: '2026-01-01T00:00:00Z',
    wf_group_index: null,
    p1_cell: null,
    p1_email: null,
    p2_cell: null,
    p2_email: null,
  }
}

/** A–B and A–C edges only (no B–C). */
const teamsEventA: TeamListItem[] = [
  team(1, 19, 'Alpha', ['Bravo', 'Charlie']),
  team(2, 19, 'Bravo', ['Alpha']),
  team(3, 19, 'Charlie', ['Alpha']),
  team(4, 19, 'Delta', []),
]

const teamsEventB: TeamListItem[] = [
  team(101, 20, 'Echo', ['Foxtrot']),
  team(102, 20, 'Foxtrot', ['Echo']),
]

const matchesEventA: Match[] = [
  {
    id: 501,
    tournament_id: 5,
    event_id: 19,
    schedule_version_id: 9,
    match_code: 'WF-R1-1',
    match_type: 'WF',
    round_number: 1,
    round_index: 1,
    sequence_in_round: 1,
    duration_minutes: 60,
    placeholder_side_a: 'Alpha',
    placeholder_side_b: 'Bravo',
    status: 'unscheduled',
    created_at: '2026-01-01T00:00:00Z',
    team_a_id: 1,
    team_b_id: 2,
  },
  {
    id: 502,
    tournament_id: 5,
    event_id: 19,
    schedule_version_id: 9,
    match_code: 'WF-R1-2',
    match_type: 'WF',
    round_number: 1,
    round_index: 1,
    sequence_in_round: 2,
    duration_minutes: 60,
    placeholder_side_a: 'Charlie',
    placeholder_side_b: 'Delta',
    status: 'unscheduled',
    created_at: '2026-01-01T00:00:00Z',
    team_a_id: 3,
    team_b_id: 4,
  },
]

const matchesEventB: Match[] = [
  {
    id: 601,
    tournament_id: 5,
    event_id: 20,
    schedule_version_id: 9,
    match_code: 'WF-R1-B1',
    match_type: 'WF',
    round_number: 1,
    round_index: 1,
    sequence_in_round: 1,
    duration_minutes: 60,
    placeholder_side_a: 'Echo',
    placeholder_side_b: 'Foxtrot',
    status: 'unscheduled',
    created_at: '2026-01-01T00:00:00Z',
    team_a_id: 101,
    team_b_id: 102,
  },
]

function mockApis() {
  vi.mocked(getTournament).mockResolvedValue(tournamentBase)
  vi.mocked(getEvents).mockResolvedValue([eventA, eventB])
  vi.mocked(getPhase1Status).mockResolvedValue(phase1)
  vi.mocked(getScheduleVersions).mockResolvedValue([
    {
      id: 9,
      tournament_id: 5,
      version_number: 1,
      status: 'draft',
      created_at: '2026-01-01T00:00:00Z',
    },
  ])
  vi.mocked(getPlanReport).mockResolvedValue(null)
  vi.mocked(getTournamentDays).mockResolvedValue([
    { id: 1, tournament_id: 5, date: '2026-08-23', is_active: true, courts_available: 8 },
  ])
  vi.mocked(getScheduleBuilder).mockResolvedValue({ tournament_id: 5, events: [] })
  vi.mocked(getEventTeams).mockImplementation(async (eventId: number) => {
    if (eventId === 19) return teamsEventA
    if (eventId === 20) return teamsEventB
    return []
  })
  vi.mocked(getEventAvoidEdges).mockImplementation(async (eventId: number) => {
    if (eventId === 19) {
      return [
        { id: 1, event_id: 19, team_id_a: 1, team_id_b: 2, reason: 'rw_os_wkw', created_at: '2026-01-01T00:00:00Z' },
        { id: 2, event_id: 19, team_id_a: 1, team_id_b: 3, reason: 'rw_os_wkw', created_at: '2026-01-01T00:00:00Z' },
        { id: 3, event_id: 19, team_id_a: 2, team_id_b: 4, reason: 'group:B', created_at: '2026-01-01T00:00:00Z' },
      ]
    }
    if (eventId === 20) {
      return [
        { id: 10, event_id: 20, team_id_a: 101, team_id_b: 102, reason: 'rw_os_wkw', created_at: '2026-01-01T00:00:00Z' },
      ]
    }
    return []
  })
  vi.mocked(getEventWhoKnowsWhoSummary).mockResolvedValue({
    eventId: 19,
    connections: 2,
    rwOsConnections: 2,
    pairwiseConnections: 2,
  })
  vi.mocked(getTournamentWhoKnowsWhoSummary).mockResolvedValue({
    tournamentId: 5,
    pairwise: true,
    snapshotConnections: 3,
    byDrawKind: {},
  })
  vi.mocked(getTournamentRwOsImport).mockResolvedValue(null)
  vi.mocked(getMatches).mockImplementation(async (_tid, _vid, eventId?: number) => {
    if (eventId === 19) return matchesEventA
    if (eventId === 20) return matchesEventB
    return []
  })
}

async function renderAndLoadRows() {
  render(
    <MemoryRouter initialEntries={['/tournaments/5/draw-builder']}>
      <Routes>
        <Route path="/tournaments/:id/draw-builder" element={<DrawBuilder />} />
      </Routes>
    </MemoryRouter>,
  )

  await waitFor(() => {
    expect(screen.getAllByRole('button', { name: 'Load WF R1 rows' }).length).toBeGreaterThan(0)
  })

  const loadButtons = screen.getAllByRole('button', { name: 'Load WF R1 rows' })
  for (const btn of loadButtons) {
    fireEvent.click(btn)
  }

  await waitFor(() => {
    expect(screen.getByTestId('wf-r1-table-19')).toBeInTheDocument()
    expect(screen.getByTestId('wf-r1-table-20')).toBeInTheDocument()
  })
}

function teamCard(teamId: number, eventId: number) {
  return document.querySelector(`[data-team-id="${teamId}"][data-event-id="${eventId}"]`) as HTMLElement | null
}

describe('DrawBuilder WKW highlight inspection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.scrollTo = vi.fn()
    mockApis()
  })

  it('highlights selected and connected teams by ID, leaves others unchanged, and shows legend', async () => {
    await renderAndLoadRows()

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Alpha' }))

    await waitFor(() => {
      expect(screen.getByTestId('wkw-legend-19')).toBeInTheDocument()
    })
    expect(within(screen.getByTestId('avoid-cell-1')).getByText('Bravo')).toBeInTheDocument()
    expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBe('selected')
    expect(teamCard(2, 19)?.getAttribute('data-wkw-role')).toBe('connected')
    expect(teamCard(3, 19)?.getAttribute('data-wkw-role')).toBe('connected')
    expect(teamCard(4, 19)?.getAttribute('data-wkw-role')).toBeNull()
    expect(teamCard(1, 19)).toHaveTextContent('Selected')
    expect(teamCard(2, 19)).toHaveTextContent('Connected')
  })

  it('does not highlight C when inspecting B unless B–C is a real edge', async () => {
    await renderAndLoadRows()

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Bravo' }))

    await waitFor(() => {
      expect(teamCard(2, 19)?.getAttribute('data-wkw-role')).toBe('selected')
    })
    expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBe('connected')
    expect(teamCard(3, 19)?.getAttribute('data-wkw-role')).toBeNull()
    expect(teamCard(4, 19)?.getAttribute('data-wkw-role')).toBeNull()
  })

  it('clears highlights on Hide and restores normal cards', async () => {
    await renderAndLoadRows()

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Alpha' }))
    await waitFor(() => {
      expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBe('selected')
    })

    fireEvent.click(screen.getByRole('button', { name: 'Hide Who Knows Who for Alpha' }))
    await waitFor(() => {
      expect(screen.queryByTestId('wkw-legend-19')).not.toBeInTheDocument()
    })
    expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBeNull()
    expect(teamCard(2, 19)?.getAttribute('data-wkw-role')).toBeNull()
    expect(teamCard(3, 19)?.getAttribute('data-wkw-role')).toBeNull()
  })

  it('replaces previous highlights when View is clicked on another team', async () => {
    await renderAndLoadRows()

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Alpha' }))
    await waitFor(() => {
      expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBe('selected')
    })

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Bravo' }))
    await waitFor(() => {
      expect(teamCard(2, 19)?.getAttribute('data-wkw-role')).toBe('selected')
    })
    expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBe('connected')
    expect(teamCard(3, 19)?.getAttribute('data-wkw-role')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Hide Who Knows Who for Alpha' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide Who Knows Who for Bravo' })).toBeInTheDocument()
  })

  it('does not highlight teams in other event cards', async () => {
    await renderAndLoadRows()

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Alpha' }))
    await waitFor(() => {
      expect(teamCard(1, 19)?.getAttribute('data-wkw-role')).toBe('selected')
    })
    expect(screen.queryByTestId('wkw-legend-20')).not.toBeInTheDocument()
    expect(teamCard(101, 20)?.getAttribute('data-wkw-role')).toBeNull()
    expect(teamCard(102, 20)?.getAttribute('data-wkw-role')).toBeNull()
  })

  it('performs no backend writes while inspecting WKW', async () => {
    await renderAndLoadRows()
    const avoidCallsBefore = vi.mocked(getEventAvoidEdges).mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Alpha' }))
    fireEvent.click(screen.getByRole('button', { name: 'Hide Who Knows Who for Alpha' }))
    fireEvent.click(screen.getByRole('button', { name: 'View Who Knows Who for Bravo' }))

    expect(vi.mocked(swapPostDrawTeams)).not.toHaveBeenCalled()
    // Inspection only uses already-loaded GET data; no extra avoid-edge fetches on View/Hide.
    expect(vi.mocked(getEventAvoidEdges).mock.calls.length).toBe(avoidCallsBefore)
  })
})

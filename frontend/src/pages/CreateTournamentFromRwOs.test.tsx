import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreateTournamentFromRwOs from './CreateTournamentFromRwOs'
import type { RwOsDrawPlan, RwOsImportResponse, RwOsSplitOption } from '../api/client'
import { TOWEL_WARNING_CODE, WKW_WARNING_CODE } from './rwOsImportReadiness'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    getTournamentRwOsImport: vi.fn(),
    approveRwOsPlan: vi.fn(),
    selectRwOsStructure: vi.fn(),
    submitRwOsCustomStructure: vi.fn(),
    refreshRwOsImport: vi.fn(),
    resetRwOsForecasts: vi.fn(),
    updateRwOsForecasts: vi.fn(),
    listRwOsEvents: vi.fn(),
    createRwOsImport: vi.fn(),
    deleteTournament: vi.fn(),
    startOverTournament: vi.fn(),
  }
})

vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

import {
  approveRwOsPlan,
  deleteTournament,
  getTournamentRwOsImport,
  selectRwOsStructure,
  startOverTournament,
  submitRwOsCustomStructure,
} from '../api/client'

function makeOption(optionKey: string, sizes: number[], recommended: boolean, labels: string[]): RwOsSplitOption {
  let start = 1
  return {
    optionKey,
    sizes,
    recommended,
    cuts: [],
    reasons: [{ code: 'cut', message: 'Clean rating cut' }],
    warnings: [],
    score: {
      cutQuality: 1,
      sizeQuality: 1,
      tinyBracketPenalty: 0,
      unratedTeamPenalty: 0,
      total: 1,
      reasons: ['Clean rating cut'],
    },
    brackets: sizes.map((size, index) => {
      const rankStart = start
      const rankEnd = start + size - 1
      start = rankEnd + 1
      return {
        label: labels[index],
        letter: String.fromCharCode(65 + index),
        size,
        rankStart,
        rankEnd,
        highestRating: 7.5,
        lowestRating: 6.0,
        averageRating: 6.85,
        medianRating: 7.0,
        ratingSpread: 1.5,
        knownTeamCount: 1,
        unknownTeamCount: 0,
        teams: [
          {
            rank: rankStart,
            teamKey: `${optionKey}-${rankStart}`,
            name: `Known ${labels[index]}`,
            teamRating: 7.5,
            ratingStatus: 'complete',
          },
        ],
      }
    }),
  }
}

function makeDraw(drawKind: string, drawLabel: string, options: RwOsSplitOption[]): RwOsDrawPlan {
  return {
    drawKind,
    drawLabel,
    teamCount: 10,
    currentCount: 10,
    forecastCount: 10,
    unratedCount: 0,
    partialCount: 0,
    ratingReviewNeeded: 0,
    options,
    teams: [
      {
        rank: 1,
        teamKey: `${drawKind}-1`,
        name: `Known ${drawLabel} A`,
        teamRating: 7.5,
        ratingStatus: 'complete',
      },
    ],
  }
}

function makeImport(overrides: Partial<RwOsImportResponse> = {}, importOverrides: Partial<RwOsImportResponse['import']> = {}): RwOsImportResponse {
  const mixedOptions = [
    makeOption('10', [10], true, ['Mixed A']),
    makeOption('6-4', [6, 4], false, ['Mixed A', 'Mixed B']),
  ]
  const womensOptions = [
    makeOption('w10', [10], true, ["Women's A"]),
    makeOption('w8-2', [8, 2], false, ["Women's A", "Women's B"]),
  ]
  const base: RwOsImportResponse = {
    import: {
      id: 44,
      tournamentId: 5,
      organizationSlug: 'rw',
      sourceTournamentId: 244,
      eventName: 'Amelia Island',
      eventDate: '2026-09-21',
      importedAt: null,
      sourceUpdatedAt: null,
      sourceVersion: null,
      sourceTeamCount: 20,
      sourceHash: 'abc123def456',
      validationStatus: 'needs_attention',
      validationIssues: [
        { code: TOWEL_WARNING_CODE, message: 'One or both players are missing a towel color.', team_key: '1/2' },
        { code: TOWEL_WARNING_CODE, message: 'One or both players are missing a towel color.', team_key: '3/4' },
        { code: WKW_WARNING_CODE, message: 'Who knows who / avoid group is missing.', team_key: '1/2' },
        { code: WKW_WARNING_CODE, message: 'Who knows who / avoid group is missing.', team_key: '3/4' },
      ],
      refreshDiff: null,
      planStatus: 'imported',
      approvedAt: null,
      teams: [
        {
          teamKey: '1/2',
          drawKind: 'mixed',
          drawLabel: 'Mixed',
          displayName: 'Ada / Bea',
          player1: { rw_id: '1', name: 'Ada', rating: 4, towelColor: null },
          player2: { rw_id: '2', name: 'Bea', rating: 3.5, towelColor: 'Blue' },
          teamRating: 7.5,
          ratingStatus: 'complete',
          status: 'confirmed',
          bucket: 'active',
        },
        {
          teamKey: '3/4',
          drawKind: 'womens',
          drawLabel: "Women's",
          displayName: 'Cara / Dee',
          player1: { rw_id: '3', name: 'Cara', rating: 4, towelColor: null },
          player2: { rw_id: '4', name: 'Dee', rating: 3.5, towelColor: null },
          teamRating: 7.5,
          ratingStatus: 'complete',
          status: 'confirmed',
          bucket: 'active',
        },
      ],
      waitlistTeams: [],
      ...importOverrides,
    },
    planner: {
      draws: [
        makeDraw('mixed', 'Mixed', mixedOptions),
        makeDraw('womens', "Women's", womensOptions),
      ],
      maxBracketSize: 32,
      minBracketSize: 8,
      preferredBracketSizes: [8, 10, 12],
      byeLogicApplicable: false,
      teamRatingFormula: 'ntrp_combined',
    },
    drawCounts: { mixed: 10, womens: 10 },
    waitlistCount: 0,
    approvedPlans: [],
    selectedPlans: [],
    bracketsCreated: false,
    ...overrides,
  }
  return base
}

function renderImport(data: RwOsImportResponse) {
  vi.mocked(getTournamentRwOsImport).mockResolvedValue(data)
  vi.mocked(selectRwOsStructure).mockImplementation(async (_importId, drawKind, optionKey) => ({
    ...data,
    selectedPlans: [{ drawKind, optionKey, approved: false, isRecommended: false }],
  }))
  vi.mocked(approveRwOsPlan).mockResolvedValue({
    ...data,
    import: { ...data.import, planStatus: 'approved' },
    approvedPlans: data.planner.draws.map((draw) => ({
      drawKind: draw.drawKind,
      optionKey: draw.options[0].optionKey,
      approved: true,
      isRecommended: true,
      brackets: draw.options[0].brackets.map((bracket) => ({
        label: bracket.label,
        size: bracket.size,
        rankStart: bracket.rankStart,
        rankEnd: bracket.rankEnd,
      })),
    })),
    tournamentEvents: [
      {
        id: 1,
        tournamentId: 5,
        category: 'mixed',
        name: 'Mixed A',
        teamCount: 10,
        teamRowCount: 10,
      },
    ],
  })
  return render(
    <MemoryRouter initialEntries={['/tournaments/5/import']}>
      <Routes>
        <Route path="/tournaments/:id/import" element={<CreateTournamentFromRwOs />} />
        <Route path="/tournaments/:id/setup" element={<div>Tournament setup screen</div>} />
        <Route path="/tournaments" element={<div>Tournament list screen</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

async function loadPage(data: RwOsImportResponse = makeImport()) {
  renderImport(data)
  await screen.findByText('Step 3 — Bracket Plan')
  return data
}

describe('CreateTournamentFromRwOs Step 3 workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('aggregates repeated RW-OS warnings and identifies affected records', async () => {
    await loadPage()
    expect(screen.getByText('3 players missing towel color')).toBeInTheDocument()
    expect(screen.getByText('2 teams missing Who Knows Who / Avoid Group')).toBeInTheDocument()
    expect(screen.queryByText(/One or both players are missing a towel color/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'View Details' }))
    expect(screen.getByTestId('import-readiness-details')).toHaveTextContent('Ada / Bea')
    expect(screen.getByTestId('import-readiness-details')).toHaveTextContent('Missing towel color')
  })

  it('shows only one recommendation per category and replaces it when browsing', async () => {
    await loadPage()
    const mixed = screen.getByTestId('draw-planner-mixed')
    expect(within(mixed).getAllByTestId(/option-card-/)).toHaveLength(1)
    expect(within(mixed).getByTestId('option-card-10')).toBeInTheDocument()
    expect(within(mixed).queryByTestId('option-card-6-4')).not.toBeInTheDocument()

    fireEvent.click(within(mixed).getByRole('button', { name: 'Show Another Recommendation' }))
    expect(within(mixed).getAllByTestId(/option-card-/)).toHaveLength(1)
    expect(within(mixed).getByTestId('option-card-6-4')).toBeInTheDocument()
    expect(within(mixed).queryByTestId('option-card-10')).not.toBeInTheDocument()
    expect(selectRwOsStructure).not.toHaveBeenCalled()
    expect(within(mixed).getByRole('button', { name: 'Select This Structure' })).toBeInTheDocument()
  })

  it('keeps custom split controls hidden until Create My Own Split', async () => {
    await loadPage()
    const mixed = screen.getByTestId('draw-planner-mixed')
    expect(within(mixed).queryByTestId('custom-structure-form')).not.toBeInTheDocument()
    expect(within(mixed).queryByRole('button', { name: 'Analyze Custom Structure' })).not.toBeInTheDocument()
    fireEvent.click(within(mixed).getByRole('button', { name: 'Create My Own Split' }))
    expect(within(mixed).getByTestId('custom-structure-form')).toBeInTheDocument()
    expect(within(mixed).getByRole('button', { name: 'Analyze Custom Structure' })).toBeInTheDocument()
  })

  it('uses a blue Select This Structure control and a red Selected Structure control without greening the card', async () => {
    await loadPage()
    const mixed = screen.getByTestId('draw-planner-mixed')
    const selectButton = within(mixed).getByRole('button', { name: 'Select This Structure' })
    expect(selectButton).toHaveClass('btn-select-structure')
    expect(selectButton).not.toHaveClass('btn-selected-structure')
    expect(within(mixed).getByTestId('option-card-10')).toHaveAttribute('data-card-tone', 'neutral')

    fireEvent.click(selectButton)
    await waitFor(() => {
      expect(within(mixed).getByRole('button', { name: 'Selected Structure' })).toHaveClass('btn-selected-structure')
    })
    const selectedCard = within(mixed).getByTestId('option-card-10')
    expect(selectedCard).toHaveAttribute('data-card-tone', 'neutral')
    expect(selectedCard.className).not.toMatch(/success|green/)
    expect(selectRwOsStructure).toHaveBeenCalledWith(44, 'mixed', '10')
  })

  it('keeps Proceed unavailable until every required category is selected', async () => {
    await loadPage()
    const proceed = screen.getByTestId('proceed-plan')
    expect(proceed).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Approve Selected Structure' })).not.toBeInTheDocument()

    fireEvent.click(within(screen.getByTestId('draw-planner-mixed')).getByRole('button', { name: 'Select This Structure' }))
    await waitFor(() => {
      expect(within(screen.getByTestId('draw-planner-mixed')).getByRole('button', { name: 'Selected Structure' })).toBeInTheDocument()
    })
    expect(proceed).toBeDisabled()

    fireEvent.click(within(screen.getByTestId('draw-planner-womens')).getByRole('button', { name: 'Select This Structure' }))
    await waitFor(() => {
      expect(screen.getByTestId('proceed-plan')).toBeEnabled()
    })
  })

  it('invokes existing approve persistence on Proceed and continues to tournament setup', async () => {
    await loadPage()
    fireEvent.click(within(screen.getByTestId('draw-planner-mixed')).getByRole('button', { name: 'Select This Structure' }))
    await waitFor(() => {
      expect(within(screen.getByTestId('draw-planner-mixed')).getByRole('button', { name: 'Selected Structure' })).toBeInTheDocument()
    })
    fireEvent.click(within(screen.getByTestId('draw-planner-womens')).getByRole('button', { name: 'Select This Structure' }))
    await waitFor(() => expect(screen.getByTestId('proceed-plan')).toBeEnabled())

    fireEvent.click(screen.getByTestId('proceed-plan'))
    await waitFor(() => {
      expect(approveRwOsPlan).toHaveBeenCalledWith(44, { mixed: '10', womens: 'w10' })
    })
    expect(await screen.findByText('Tournament setup screen')).toBeInTheDocument()
  })

  it('navigates Cancel back to the tournament list without modifying data', async () => {
    await loadPage()
    fireEvent.click(screen.getByTestId('cancel-to-list'))
    expect(await screen.findByText('Tournament list screen')).toBeInTheDocument()
    expect(deleteTournament).not.toHaveBeenCalled()
    expect(startOverTournament).not.toHaveBeenCalled()
    expect(approveRwOsPlan).not.toHaveBeenCalled()
    expect(selectRwOsStructure).not.toHaveBeenCalled()
    expect(submitRwOsCustomStructure).not.toHaveBeenCalled()
  })

  it('still shows conflict protection and Known Teams', async () => {
    await loadPage(
      makeImport(
        {
          structureEventConflicts: [
            {
              eventId: 9,
              category: 'mixed',
              name: 'Mixed A',
              reason: 'Event already has matches',
              currentTeamCount: 10,
              requestedTeamCount: 8,
            },
          ],
        },
        { planStatus: 'approved' },
      ),
    )
    expect(screen.getByTestId('structure-event-conflicts')).toHaveTextContent('Event already has matches')
    expect(screen.queryByText(/Selecting another structure keeps existing events/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve Selected Structure' })).not.toBeInTheDocument()

    const mixed = screen.getByTestId('draw-planner-mixed')
    fireEvent.click(within(mixed).getByRole('button', { name: /View Known Teams/ }))
    expect(within(mixed).getByText(/Known Mixed A/)).toBeInTheDocument()
  })
})

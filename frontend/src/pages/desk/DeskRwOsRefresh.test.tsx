import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/client', () => ({
  refreshRwOsImport: vi.fn(),
  rebuildRwOsDraws: vi.fn(),
}))

import { rebuildRwOsDraws, refreshRwOsImport } from '../../api/client'
import { DeskRwOsRefresh } from './DeskRwOsRefresh'

const refresh = vi.mocked(refreshRwOsImport)
const rebuild = vi.mocked(rebuildRwOsDraws)

function projection(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    created: { events: 0, teams: 0, towelRows: 0, wkwEdges: 0 },
    updated: { teams: 0, contactFields: 0, towelRows: 0 },
    reconciled: { withdrawnTeams: 0, drawSlotsReplaced: 0 },
    warnings: [],
    conflicts: [],
    ...overrides,
  }
}

describe('DeskRwOsRefresh', () => {
  beforeEach(() => {
    refresh.mockReset()
    rebuild.mockReset()
  })

  it('hides the button when the tournament has no RW-OS import', () => {
    render(<DeskRwOsRefresh importId={null} onApplied={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Check RW-OS for Changes' })).not.toBeInTheDocument()
  })

  it('shows a reconciliation result when the download matches but the local roster was stale', async () => {
    const onApplied = vi.fn()
    refresh.mockResolvedValue({
      diff: {
        changed: true,
        addedTeams: [],
        withdrawnTeams: [],
        operationalDrift: { reconciliationNeeded: true, missingFromDraw: ['1/2', '3/4', '5/6', '7/8'] },
      },
      applied: true,
      rosterProjection: projection({
        reconciled: { withdrawnTeams: 0, drawSlotsReplaced: 4 },
      }),
    } as never)
    render(<DeskRwOsRefresh importId={12} onApplied={onApplied} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    expect(await screen.findByRole('heading', { name: 'RW-OS Roster Reconciled' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'RW-OS Roster Is Current' })).not.toBeInTheDocument()
    expect(screen.queryByText('No player or team changes were found.')).not.toBeInTheDocument()
    expect(screen.getByText(/event and draw membership was reconciled/)).toBeInTheDocument()
    expect(screen.getByText('4 draw positions updated')).toBeInTheDocument()
    expect(screen.queryByText(/seed\/rank update/)).not.toBeInTheDocument()
    expect(onApplied).toHaveBeenCalledTimes(1)
    expect(refresh).toHaveBeenCalledWith(12, false)
  })

  it('reports seed/rank metadata repairs on their own line', async () => {
    refresh.mockResolvedValue({
      diff: {
        changed: true,
        addedTeams: [],
        withdrawnTeams: [],
        operationalDrift: { reconciliationNeeded: true, seedMismatches: [{ teamKey: '13511/14084' }] },
      },
      applied: true,
      rosterProjection: projection({
        updated: { teams: 0, contactFields: 0, towelRows: 0, seeds: 5 },
      }),
    } as never)
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    expect(await screen.findByText('5 seed/rank updates')).toBeInTheDocument()
    expect(screen.queryByText(/player\/contact change/)).toBeInTheDocument()
    expect(screen.getByText('0 player/contact changes')).toBeInTheDocument()
  })

  it('does not call a failed roster repair reconciled', async () => {
    refresh.mockResolvedValue({
      diff: {
        changed: true,
        addedTeams: [],
        withdrawnTeams: [],
        operationalDrift: { reconciliationNeeded: true, missingFromEvent: ['a', 'b', 'c', 'd'] },
      },
      applied: true,
      rosterProjection: projection({
        conflicts: [{
          code: 'roster_reconciliation_incomplete',
          stage: 'event',
          message: 'Mixed — Event roster could not be reconciled\nRW-OS: 24\nTournament teams: 19\nMissing:\nLauri / Marc (12884/15825)',
        }],
      }),
    } as never)
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    expect(await screen.findByRole('heading', { name: 'RW-OS Roster Was Not Reconciled' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'RW-OS Roster Reconciled' })).not.toBeInTheDocument()
    expect(screen.queryByText('No player or team changes were found.')).not.toBeInTheDocument()
    expect(screen.getByText(/Event roster could not be reconciled/)).toBeInTheDocument()
    expect(screen.getByText(/Lauri \/ Marc \(12884\/15825\)/)).toBeInTheDocument()
  })

  it('says the roster is current without applying', async () => {
    refresh.mockResolvedValue({
      diff: { changed: false, addedTeams: [], withdrawnTeams: [] },
      applied: false,
    } as never)
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    expect(await screen.findByRole('heading', { name: 'RW-OS Roster Is Current' })).toBeInTheDocument()
    expect(screen.getByText('No player or team changes were found.')).toBeInTheDocument()
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(refresh).toHaveBeenCalledWith(12, false)
  })

  it('previews a new team and a withdrawal from the canonical diff', async () => {
    refresh.mockResolvedValue({
      diff: {
        changed: true,
        addedTeams: [{
          teamKey: '8801/8802',
          displayName: 'Torrie Smith / Nancy Jones',
          drawLabel: "Women's A",
          player1: { towelColor: 'Purple' },
          player2: { towelColor: 'Gold' },
        }],
        withdrawnTeams: [{
          teamKey: '100/101',
          displayName: 'Jane Smith / Susan Brown',
          drawLabel: "Women's A",
        }],
        contactChanges: [{
          teamKey: '500/501',
          drawLabel: 'Mixed B',
          playerName: 'John Smith',
          field: 'cellphone',
          before: '901-555-1111',
          after: '901-555-2222',
        }],
        towelChanges: [{
          teamKey: '200/201',
          drawLabel: "Women's B",
          playerName: 'Mary Jones',
          before: 'Blue',
          after: 'Pink',
        }],
        avoidGroupChanges: [{
          teamKey: '300/301',
          drawLabel: "Women's C",
          teamLabel: 'Pat Lee / Ann Cole',
          before: 'B',
          after: 'C',
        }],
      },
      applied: false,
    } as never)
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    expect(await screen.findByRole('heading', { name: 'RW-OS Changes Found' })).toBeInTheDocument()
    expect(screen.getByText('NEW TEAM')).toBeInTheDocument()
    expect(screen.getByText('Torrie Smith / Nancy Jones')).toBeInTheDocument()
    expect(screen.getByText('Towels: Purple / Gold')).toBeInTheDocument()
    expect(screen.getByText('WITHDRAWN / REMOVED')).toBeInTheDocument()
    expect(screen.getByText('Jane Smith / Susan Brown')).toBeInTheDocument()
    expect(screen.getByText('cellphone: 901-555-1111 → 901-555-2222')).toBeInTheDocument()
    expect(screen.getByText('Blue → Pink')).toBeInTheDocument()
    expect(screen.getByText('Avoid Group B → C')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply RW-OS Changes' })).toBeInTheDocument()
    expect(refresh).toHaveBeenCalledWith(12, false)
  })

  it('applies through the existing refresh API, then asks the desk to refetch', async () => {
    refresh.mockImplementation(async (_importId, apply) => {
      if (!apply) {
        return {
          diff: {
            changed: true,
            addedTeams: [{ teamKey: '8801/8802', displayName: 'Torrie / Nancy', drawLabel: "Women's" }],
            withdrawnTeams: [{ teamKey: '100/101', displayName: 'W1', drawLabel: "Women's" }],
          },
          applied: false,
        } as never
      }
      return {
        diff: { changed: true },
        applied: true,
        rosterProjection: projection({
          created: { events: 0, teams: 1, towelRows: 2, wkwEdges: 2 },
          updated: { teams: 0, contactFields: 0, towelRows: 0 },
          reconciled: { withdrawnTeams: 1, drawSlotsReplaced: 1 },
        }),
      } as never
    })
    const onApplied = vi.fn()
    render(<DeskRwOsRefresh importId={12} onApplied={onApplied} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply RW-OS Changes' }))
    expect(await screen.findByRole('heading', { name: 'RW-OS Changes Applied' })).toBeInTheDocument()
    expect(screen.getByText('1 team added')).toBeInTheDocument()
    expect(screen.getByText('1 team withdrawn')).toBeInTheDocument()
    expect(screen.getByText('2 towel updates')).toBeInTheDocument()
    expect(screen.getByText('2 Who-Knows-Who updates')).toBeInTheDocument()
    expect(screen.getByText('1 draw position updated')).toBeInTheDocument()
    expect(screen.getByText('Tournament Desk has been refreshed.')).toBeInTheDocument()
    expect(refresh).toHaveBeenLastCalledWith(12, true)
    expect(onApplied).toHaveBeenCalledTimes(1)
  })

  it('shows protected, open-slot, unresolved, and move conflicts after apply', async () => {
    refresh.mockImplementation(async (_importId, apply) => {
      if (!apply) {
        return { diff: { changed: true, addedTeams: [{ teamKey: 'new', displayName: 'New' }], withdrawnTeams: [] }, applied: false } as never
      }
      return {
        diff: { changed: true },
        applied: true,
        rosterProjection: projection({
          ok: false,
          conflicts: [
            {
              code: 'roster_reconciliation_blocked',
              message: "Women's A: Jane Smith / Susan Brown is withdrawn in RW-OS, but automatic draw reconciliation was blocked because the match has already started. Torrie Smith / Nancy Jones is active in RW-OS but was not placed into that match.",
            },
            {
              code: 'roster_draw_placement_unresolved',
              message: "Mixed A: New Team added from RW-OS, but no safe unplayed draw slot was open.",
            },
            {
              code: 'team_would_move',
              message: "Women's B would move between events and the draw is protected.",
            },
          ],
          warnings: [
            {
              code: 'draw_slot_left_open',
              message: "Women's B: Team withdrawn. Draw slot left TBD.",
            },
          ],
        }),
      } as never
    })
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply RW-OS Changes' }))
    expect(await screen.findByText('4 items need staff attention')).toBeInTheDocument()
    expect(screen.getByText('Needs Staff Attention')).toBeInTheDocument()
    expect(screen.getByText(/automatic draw reconciliation was blocked/)).toBeInTheDocument()
    expect(screen.getByText(/Draw slot left TBD/)).toBeInTheDocument()
    expect(screen.getByText(/no safe unplayed draw slot/)).toBeInTheDocument()
    expect(screen.getByText(/draw is protected/)).toBeInTheDocument()
  })

  it('sends one apply when Apply is clicked twice', async () => {
    let release: (value: unknown) => void = () => {}
    refresh.mockImplementation(async (_importId, apply) => {
      if (!apply) {
        return {
          diff: { changed: true, addedTeams: [{ teamKey: 'new', displayName: 'New Team' }], withdrawnTeams: [] },
          applied: false,
        } as never
      }
      return new Promise((resolve) => {
        release = resolve
      })
    })
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check RW-OS for Changes' }))
    const apply = await screen.findByRole('button', { name: 'Apply RW-OS Changes' })
    fireEvent.click(apply)
    fireEvent.click(apply)
    expect(screen.getAllByText('Applying RW-OS Changes…').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Applying RW-OS Changes…' })).toBeDisabled()
    expect(refresh.mock.calls.filter((call) => call[1] === true)).toHaveLength(1)
    release({
      diff: { changed: true },
      applied: true,
      rosterProjection: projection({ created: { events: 0, teams: 1, towelRows: 0, wkwEdges: 0 } }),
    })
    expect(await screen.findByRole('heading', { name: 'RW-OS Changes Applied' })).toBeInTheDocument()
    expect(refresh.mock.calls.filter((call) => call[1] === true)).toHaveLength(1)
  })

  it('disables another check while the first check is running', async () => {
    let release: (value: unknown) => void = () => {}
    refresh.mockImplementation(() => new Promise((resolve) => {
      release = resolve
    }))
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    const button = screen.getByRole('button', { name: 'Check RW-OS for Changes' })
    fireEvent.click(button)
    fireEvent.click(button)
    expect(screen.getByRole('button', { name: 'Checking RW-OS…' })).toBeDisabled()
    expect(refresh).toHaveBeenCalledTimes(1)
    release({ diff: { changed: false }, applied: false })
    await waitFor(() => expect(screen.getByRole('heading', { name: 'RW-OS Roster Is Current' })).toBeInTheDocument())
  })

  it('keeps rebuild behind a confirmation modal and does not call refresh', async () => {
    const onApplied = vi.fn()
    rebuild.mockResolvedValue({
      ok: true,
      heading: 'RW-OS Refreshed + Draws Rebuilt',
      events: [
        {
          eventId: 4,
          name: 'Mixed',
          teamCount: 24,
          structure: '24-team waterfall',
          detail: 'Draw rebuilt using current ratings, seeds, and Who-Knows-Who',
          schedulePreserved: true,
        },
      ],
      scheduleNote: 'Match numbers, dates, times, courts, and grid assignments were preserved.',
    })
    render(<DeskRwOsRefresh importId={12} onApplied={onApplied} />)
    expect(screen.getByText('Updates teams and information without rebuilding draws.')).toBeInTheDocument()
    expect(screen.getByText(/Existing match numbers, dates, times, courts, and grid positions stay in place/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Refresh RW-OS + Rebuild Draws' }))
    expect(screen.getByRole('heading', { name: 'REBUILD ALL DRAWS?' })).toBeInTheDocument()
    expect(rebuild).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('heading', { name: 'REBUILD ALL DRAWS?' })).not.toBeInTheDocument()
    expect(rebuild).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Refresh RW-OS + Rebuild Draws' }))
    const confirm = screen.getByRole('button', { name: 'Refresh & Rebuild Draws' })
    expect(confirm).toHaveStyle({ background: '#c62828' })
    fireEvent.click(confirm)
    expect(await screen.findByRole('heading', { name: 'RW-OS Refreshed + Draws Rebuilt' })).toBeInTheDocument()
    expect(screen.getByText('Mixed')).toBeInTheDocument()
    expect(screen.getByText('24-team waterfall')).toBeInTheDocument()
    expect(screen.getByText('Match numbers, dates, times, courts, and grid assignments were preserved.')).toBeInTheDocument()
    expect(rebuild).toHaveBeenCalledTimes(1)
    expect(rebuild).toHaveBeenCalledWith(12)
    expect(refresh).not.toHaveBeenCalled()
    expect(onApplied).toHaveBeenCalledTimes(1)
  })

  it('shows the rebuild failure reason under the blocked heading', async () => {
    rebuild.mockRejectedValue(
      new Error(
        'Mixed draw structure does not match its stored guarantee.\n\nStored guarantee: 5\nExisting draw topology: guarantee 4\n\nBracket structure requires review before draws can be rebuilt.',
      ),
    )
    render(<DeskRwOsRefresh importId={12} onApplied={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh RW-OS + Rebuild Draws' }))
    fireEvent.click(screen.getByRole('button', { name: 'Refresh & Rebuild Draws' }))
    expect(await screen.findByRole('heading', { name: 'Draws were not rebuilt' })).toBeInTheDocument()
    expect(screen.getByText(/Mixed draw structure does not match its stored guarantee/)).toBeInTheDocument()
    expect(screen.getByText(/Stored guarantee: 5/)).toBeInTheDocument()
    expect(screen.getByText(/Existing draw topology: guarantee 4/)).toBeInTheDocument()
    expect(screen.queryByText('NOT_A_CANONICAL_CODE')).not.toBeInTheDocument()
  })
})

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  formatRwOsRosterRefreshSummary,
  isRwOsBackedTournament,
  summarizeRwOsRefreshNotices,
  RwOsRosterRefreshCard,
} from './RwOsRosterRefreshCard'

describe('RwOsRosterRefreshCard', () => {
  it('treats rw_os_import_id as the RW-OS roster path', () => {
    expect(isRwOsBackedTournament({ rw_os_import_id: 12 })).toBe(true)
    expect(isRwOsBackedTournament({ source_rw_os_tournament_id: 151 })).toBe(true)
    expect(isRwOsBackedTournament({ rw_os_import_id: null })).toBe(false)
    expect(isRwOsBackedTournament(null)).toBe(false)
  })

  it('summarizes teams, contacts, and towels', () => {
    expect(formatRwOsRosterRefreshSummary({ teams: 1, contactFields: 2, towelRows: 3 })).toBe(
      '1 team updated · 2 contact fields · 3 towels',
    )
  })

  it('renders the Draw Builder refresh action', () => {
    const onRefresh = vi.fn()
    render(
      <RwOsRosterRefreshCard
        loading={false}
        summary="2 teams updated · 4 contact fields · 2 towels"
        notices={[{ code: 'structural_snapshot_changed_after_approval', message: 'Snapshot changed after approval' }]}
        onRefresh={onRefresh}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Refresh roster from RW-OS' }))
    expect(onRefresh).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/Pull the latest names, ratings, contacts, and towels/)).toBeInTheDocument()
    expect(screen.getByTestId('rw-os-roster-refresh-summary')).toHaveTextContent('2 teams updated')
    expect(screen.getByTestId('rw-os-roster-refresh-notices')).toHaveTextContent('Snapshot changed after approval')
    expect(screen.queryByText('Combined Team + Towel Import')).not.toBeInTheDocument()
  })

  it('lists before and after values for applied field changes', () => {
    render(
      <RwOsRosterRefreshCard
        loading={false}
        summary="1 team updated · 2 contact fields · 1 towel"
        fieldChanges={[
          {
            teamKey: '100/101',
            teamLabel: 'Short / Names',
            field: 'displayName',
            label: 'Short name',
            before: 'W1',
            after: 'Short / Names',
          },
          {
            teamKey: '100/101',
            teamLabel: 'Short / Names',
            field: 'rating',
            label: 'Rating',
            before: 9,
            after: 7.75,
          },
        ]}
        snapshotDiff={{ addedTeams: [{ teamKey: '900/901', displayName: 'New Team' }], addedCount: 1 }}
        onRefresh={vi.fn()}
      />,
    )
    expect(screen.getByTestId('rw-os-roster-refresh-changes')).toHaveTextContent('Short name: W1 → Short / Names')
    expect(screen.getByTestId('rw-os-roster-refresh-changes')).toHaveTextContent('Rating: 9 → 7.75')
    expect(screen.getByTestId('rw-os-roster-refresh-snapshot')).toHaveTextContent('Added: New Team')
  })

  it('collapses repeated towel, Who Knows Who, and generated-draw notices', () => {
    expect(
      summarizeRwOsRefreshNotices([
        { code: 'structural_snapshot_changed_after_approval', message: 'The structural snapshot changed after approval.' },
        { code: 'missing_towel_color', message: 'Team 15430/15431 player 1 is missing a towel color.', teamKey: '15430/15431' },
        { code: 'missing_towel_color', message: 'Team 15430/15431 player 2 is missing a towel color.', teamKey: '15430/15431' },
        { code: 'missing_who_knows_who', message: 'Team 15430/15431 is missing Who-knows-who.', teamKey: '15430/15431' },
        { code: 'missing_towel_color', message: 'Team 750/751 player 1 is missing a towel color.', teamKey: '750/751' },
        { code: 'missing_who_knows_who', message: 'Team 750/751 is missing Who-knows-who.', teamKey: '750/751' },
        { code: 'live_draw_protection_blocks_structural_change', message: "Mixed A: event has generated draw." },
        { code: 'live_draw_protection_blocks_structural_change', message: "Women's A: event has generated draw." },
      ]).map((notice) => notice.message),
    ).toEqual([
      'The structural snapshot changed after approval.',
      '2 teams still missing a towel color in RW-OS',
      '2 teams still missing Who Knows Who in RW-OS',
      'Live draws were left in place. Withdrawals and new teams were not added or removed from the bracket.',
    ])
  })
})

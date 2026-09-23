import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  formatRwOsRosterRefreshSummary,
  isRwOsBackedTournament,
  RwOsRosterRefreshCard,
} from './RwOsRosterRefreshCard'

describe('RwOsRosterRefreshCard', () => {
  it('treats rw_os_import_id as the RW-OS roster path', () => {
    expect(isRwOsBackedTournament({ rw_os_import_id: 12 })).toBe(true)
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
})

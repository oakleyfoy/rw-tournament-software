import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ImportReadinessPanel } from './ImportReadinessPanel'
import { TOWEL_WARNING_CODE, WKW_WARNING_CODE } from './rwOsImportReadiness'

describe('ImportReadinessPanel', () => {
  const issues = [
    { code: TOWEL_WARNING_CODE, message: 'One or both players are missing a towel color.', team_key: '1/2' },
    { code: TOWEL_WARNING_CODE, message: 'One or both players are missing a towel color.', team_key: '3/4' },
    { code: WKW_WARNING_CODE, message: 'Who knows who / avoid group is missing.', team_key: '1/2' },
    { code: WKW_WARNING_CODE, message: 'Who knows who / avoid group is missing.', team_key: '3/4' },
  ]
  const teams = [
    {
      teamKey: '1/2',
      displayName: 'Ada / Bea',
      player1: { name: 'Ada', towelColor: null },
      player2: { name: 'Bea', towelColor: 'Blue' },
    },
    {
      teamKey: '3/4',
      displayName: 'Cara / Dee',
      player1: { name: 'Cara', towelColor: null },
      player2: { name: 'Dee', towelColor: null },
    },
  ]

  it('shows aggregated counts instead of repeated warning sentences', () => {
    render(<ImportReadinessPanel issues={issues} teams={teams} />)
    expect(screen.getByText('3 players missing towel color')).toBeInTheDocument()
    expect(screen.getByText('2 teams missing Who Knows Who / Avoid Group')).toBeInTheDocument()
    expect(screen.queryByText(/One or both players are missing a towel color/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Who knows who \/ avoid group is missing/)).not.toBeInTheDocument()
    expect(screen.getByText(/Import can proceed/)).toBeInTheDocument()
  })

  it('exposes affected records in View Details', () => {
    render(<ImportReadinessPanel issues={issues} teams={teams} />)
    fireEvent.click(screen.getByRole('button', { name: 'View Details' }))
    const details = screen.getByTestId('import-readiness-details')
    expect(details).toHaveTextContent('Ada / Bea')
    expect(details).toHaveTextContent('Ada')
    expect(details).toHaveTextContent('Missing towel color')
    expect(details).toHaveTextContent('Cara / Dee')
    expect(details).toHaveTextContent('Dee')
    expect(details).toHaveTextContent('Missing Who Knows Who / Avoid Group')
  })
})

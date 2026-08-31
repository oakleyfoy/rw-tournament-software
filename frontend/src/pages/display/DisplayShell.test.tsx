import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DisplayShell } from './DisplayShell'

describe('DisplayShell', () => {
  it('keeps last-good content visible with a connection warning', () => {
    render(
      <DisplayShell
        tournamentName="Display Board Open"
        title="Court Board"
        nowLocal="2:00 PM"
        refreshing={false}
        error="network down"
        hasData
        onRefresh={vi.fn()}
      >
        <div>Board content</div>
      </DisplayShell>
    )
    expect(screen.getByText('Board content')).toBeInTheDocument()
    expect(screen.getByTestId('display-connection-issue')).toHaveTextContent('Connection issue — retrying')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})

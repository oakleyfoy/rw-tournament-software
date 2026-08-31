import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DisplayMatchCard } from './DisplayMatchCard'
import { makeMatch } from './displayBoardFixture'

describe('DisplayMatchCard', () => {
  it('shows first names, scheduled time, and court only while playing', () => {
    render(
      <DisplayMatchCard
        match={makeMatch({
          team_a_names: 'Helen / Simone',
          team_b_names: 'Amy / Terry',
          scheduled_time: '1:30 PM',
          court: 'Court 7',
        })}
        variant="playing"
      />
    )
    expect(screen.getByText('Helen / Simone')).toBeInTheDocument()
    expect(screen.getByText('Amy / Terry')).toBeInTheDocument()
    expect(screen.getByText('1:30 PM')).toBeInTheDocument()
    expect(screen.getByText('Court 7')).toBeInTheDocument()
    expect(screen.queryByText('Helen Robinson')).not.toBeInTheDocument()
  })

  it('does not show court on waiting or upcoming cards even if court is present', () => {
    const waiting = makeMatch({ match_id: 2, court: 'Court 3', team_a_checked_in: true, team_b_checked_in: true })
    const { rerender } = render(<DisplayMatchCard match={waiting} variant="waiting" />)
    expect(screen.queryByText('Court 3')).not.toBeInTheDocument()
    rerender(<DisplayMatchCard match={waiting} variant="upcoming" />)
    expect(screen.queryByText('Court 3')).not.toBeInTheDocument()
    rerender(<DisplayMatchCard match={waiting} variant="upcoming12" />)
    expect(screen.queryByText('Court 3')).not.toBeInTheDocument()
  })

  it('highlights a checked-in team on upcoming cards', () => {
    render(
      <DisplayMatchCard
        match={makeMatch({ team_a_checked_in: true, team_b_checked_in: false })}
        variant="upcoming"
      />
    )
    expect(screen.getByText('Helen / Simone').closest('[data-checked]')).toHaveAttribute('data-checked', 'true')
    expect(screen.getByText('Amy / Terry').closest('[data-checked]')).toHaveAttribute('data-checked', 'false')
  })

  it('renders TBD partner names', () => {
    render(
      <DisplayMatchCard
        match={makeMatch({ team_a_names: 'John / TBD', team_b_names: 'Mike / David', team_a_has_tbd: true })}
        variant="upcoming12"
      />
    )
    expect(screen.getByText('John / TBD')).toBeInTheDocument()
    expect(screen.getByText('Mike / David')).toBeInTheDocument()
  })
})

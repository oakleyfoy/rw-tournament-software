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

  it('wraps long first names instead of expanding the column', () => {
    render(
      <DisplayMatchCard
        match={makeMatch({
          team_a_names: 'Christopherson / Hilary',
          team_b_names: 'Amber / Megan',
        })}
        variant="upcoming"
      />
    )
    expect(screen.getByText('Christopherson / Hilary')).toHaveClass('display-team-names')
  })

  it('never renders event, division, round, or stage on any card variant', () => {
    const match = makeMatch({
      event_name: "Women's C",
      event_label: "Women's C",
      division_name: 'Division 2',
      round_label: 'WF R1',
      stage: 'WF',
      court: 'Court 7',
    })
    const { rerender } = render(<DisplayMatchCard match={match} variant="upcoming" />)
    for (const variant of ['upcoming', 'waiting', 'playing', 'upcoming12'] as const) {
      rerender(<DisplayMatchCard match={match} variant={variant} />)
      const card = screen.getByTestId('display-match-1')
      expect(card.querySelector('.display-meta')).toBeNull()
      expect(card).not.toHaveTextContent("Women's C")
      expect(card).not.toHaveTextContent("Women's B")
      expect(card).not.toHaveTextContent('Division 2')
      expect(card).not.toHaveTextContent('WF R1')
      expect(card).not.toHaveTextContent('WF R2')
      expect(card.textContent).not.toMatch(/\bWF\b/)
      expect(card.textContent).not.toMatch(/\bSF\b/)
      expect(card).not.toHaveTextContent(' · ')
    }
  })

  it('shows only time, names, and vs on upcoming cards', () => {
    render(<DisplayMatchCard match={makeMatch({ court: 'Court 4' })} variant="upcoming" />)
    const card = screen.getByTestId('display-match-1')
    expect(card).toHaveTextContent('3:30 PM')
    expect(card).toHaveTextContent('Helen / Simone')
    expect(card).toHaveTextContent('vs')
    expect(card).toHaveTextContent('Amy / Terry')
    expect(card).not.toHaveTextContent('Court 4')
    expect(card).not.toHaveTextContent("Women's B")
    expect(card).not.toHaveTextContent('WF R1')
  })

  it('shows time, names, vs, and check-in state on waiting cards without court or event', () => {
    render(
      <DisplayMatchCard
        match={makeMatch({
          court: 'Court 3',
          team_a_checked_in: true,
          team_b_checked_in: true,
        })}
        variant="waiting"
      />
    )
    const card = screen.getByTestId('display-match-1')
    expect(card).toHaveTextContent('3:30 PM')
    expect(card).toHaveTextContent('Helen / Simone')
    expect(card).toHaveTextContent('vs')
    expect(card).toHaveTextContent('Amy / Terry')
    expect(screen.getByText('Helen / Simone').closest('[data-checked]')).toHaveAttribute('data-checked', 'true')
    expect(screen.getByText('Amy / Terry').closest('[data-checked]')).toHaveAttribute('data-checked', 'true')
    expect(card).not.toHaveTextContent('Court 3')
    expect(card).not.toHaveTextContent("Women's B")
    expect(card).not.toHaveTextContent('WF R1')
  })

  it('shows time, names, vs, and court on currently playing cards without event or round', () => {
    render(
      <DisplayMatchCard
        match={makeMatch({ scheduled_time: '9:30 AM', court: 'Court 7' })}
        variant="playing"
      />
    )
    const card = screen.getByTestId('display-match-1')
    expect(card).toHaveTextContent('9:30 AM')
    expect(card).toHaveTextContent('Helen / Simone')
    expect(card).toHaveTextContent('vs')
    expect(card).toHaveTextContent('Amy / Terry')
    expect(screen.getByTestId('display-court-1')).toHaveTextContent('Court 7')
    expect(card).not.toHaveTextContent("Women's B")
    expect(card).not.toHaveTextContent('WF R1')
  })
})

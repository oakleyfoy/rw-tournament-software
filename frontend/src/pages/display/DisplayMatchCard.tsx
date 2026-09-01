import { DisplayMatch } from '../../api/client'

type CardVariant = 'playing' | 'waiting' | 'upcoming' | 'upcoming12'

export function DisplayMatchCard({
  match,
  variant,
}: {
  match: DisplayMatch
  variant: CardVariant
}) {
  const showCourt = variant === 'playing'
  const showCheckin = variant === 'upcoming' || variant === 'waiting'
  const cardClass =
    variant === 'playing'
      ? 'display-card display-card-playing'
      : variant === 'waiting'
        ? 'display-card display-card-waiting'
        : 'display-card'

  return (
    <article className={cardClass} data-testid={`display-match-${match.match_id}`}>
      {match.scheduled_time ? (
        <div className="display-card-time">{match.scheduled_time}</div>
      ) : null}
      <TeamLine
        names={match.team_a_names}
        checkedIn={match.team_a_checked_in}
        showCheckin={showCheckin}
      />
      <div className="display-vs">vs</div>
      <TeamLine
        names={match.team_b_names}
        checkedIn={match.team_b_checked_in}
        showCheckin={showCheckin}
      />
      <div className="display-meta">
        {match.event_label}
        {match.round_label ? ` · ${match.round_label}` : ''}
      </div>
      {showCourt && match.court ? (
        <div className="display-court" data-testid={`display-court-${match.match_id}`}>
          {match.court}
        </div>
      ) : null}
    </article>
  )
}

function TeamLine({
  names,
  checkedIn,
  showCheckin,
}: {
  names: string
  checkedIn: boolean
  showCheckin: boolean
}) {
  const highlight = showCheckin && checkedIn
  return (
    <div
      className={highlight ? 'display-team display-team-checked' : 'display-team'}
      data-checked={highlight ? 'true' : 'false'}
    >
      {highlight ? <span className="display-team-badge" aria-hidden>✓</span> : null}
      <span className="display-team-names">{names || 'TBD'}</span>
    </div>
  )
}

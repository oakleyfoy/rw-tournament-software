import { DisplayMatch } from '../../api/client'
import { formatTimeOnCourt } from './formatTimeOnCourt'

type CardVariant = 'playing' | 'waiting' | 'upcoming' | 'upcoming12'

export function DisplayMatchCard({
  match,
  variant,
  nowMs,
  preferTimeOnCourt = false,
}: {
  match: DisplayMatch
  variant: CardVariant
  nowMs?: number
  /** When true on playing cards, show elapsed on-court time instead of scheduled time. */
  preferTimeOnCourt?: boolean
}) {
  const showCourt = variant === 'playing' || ((variant === 'upcoming' || variant === 'upcoming12') && Boolean(match.court))
  const showCheckin = variant === 'upcoming' || variant === 'waiting'
  const timeOnCourt =
    variant === 'playing' ? formatTimeOnCourt(match.started_at, nowMs ?? Date.now()) : null
  const cardClass =
    variant === 'playing'
      ? 'display-card display-card-playing'
      : variant === 'waiting'
        ? 'display-card display-card-waiting'
        : 'display-card'

  const primaryTime =
    preferTimeOnCourt && timeOnCourt
      ? timeOnCourt
      : match.scheduled_time

  return (
    <article className={cardClass} data-testid={`display-match-${match.match_id}`}>
      {primaryTime ? (
        <div
          className={preferTimeOnCourt && timeOnCourt ? 'display-card-time display-time-on-court' : 'display-card-time'}
          data-testid={preferTimeOnCourt && timeOnCourt ? `display-time-on-court-${match.match_id}` : undefined}
        >
          {primaryTime}
        </div>
      ) : null}
      {!preferTimeOnCourt && timeOnCourt ? (
        <div className="display-time-on-court" data-testid={`display-time-on-court-${match.match_id}`}>
          {timeOnCourt}
        </div>
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

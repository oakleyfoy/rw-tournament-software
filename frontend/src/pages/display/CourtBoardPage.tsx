import { useParams } from 'react-router-dom'
import { DisplayMatchCard } from './DisplayMatchCard'
import { DisplayLoadingState, DisplayShell } from './DisplayShell'
import { useDisplayBoard } from './useDisplayBoard'

export default function CourtBoardPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = Number(tournamentId)
  const { data, error, initialLoading, refreshing, refresh } = useDisplayBoard(tid)

  if (initialLoading && !data) {
    return <DisplayLoadingState />
  }

  if (!data) {
    return (
      <div className="display-loading">
        <div className="display-loading-copy">{error || 'Unable to load tournament display'}</div>
      </div>
    )
  }

  return (
    <DisplayShell
      tournamentName={data.tournament_name}
      title="Court Board"
      nowLocal={data.now_local}
      refreshing={refreshing}
      error={error}
      hasData
      onRefresh={refresh}
    >
      <section className="display-section" data-testid="currently-playing">
        <h2 className="display-section-title">Currently Playing</h2>
        {data.currently_playing.length === 0 ? (
          <div className="display-empty">No matches currently on court</div>
        ) : (
          <div className="display-playing-grid">
            {data.currently_playing.map((match) => (
              <DisplayMatchCard key={match.match_id} match={match} variant="playing" />
            ))}
          </div>
        )}
      </section>

      <section className="display-section" data-testid="waiting-for-court">
        <h2 className="display-section-title">Waiting for Court</h2>
        {data.waiting_for_court.length === 0 ? (
          <div className="display-empty">No matches waiting for court</div>
        ) : (
          <div className="display-match-grid">
            {data.waiting_for_court.map((match) => (
              <DisplayMatchCard key={match.match_id} match={match} variant="waiting" />
            ))}
          </div>
        )}
      </section>

      <section className="display-section" data-testid="court-board-upcoming">
        <h2 className="display-section-title">Upcoming / Next Matches</h2>
        {data.upcoming.length === 0 ? (
          <div className="display-empty">No upcoming matches</div>
        ) : (
          <div className="display-match-grid">
            {data.upcoming.map((match) => (
              <DisplayMatchCard key={match.match_id} match={match} variant="upcoming" />
            ))}
          </div>
        )}
      </section>
    </DisplayShell>
  )
}

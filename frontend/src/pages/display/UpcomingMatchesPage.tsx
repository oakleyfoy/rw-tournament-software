import { useParams } from 'react-router-dom'
import { DisplayMatchCard } from './DisplayMatchCard'
import { DisplayLoadingState, DisplayShell } from './DisplayShell'
import { useDisplayBoard } from './useDisplayBoard'

export default function UpcomingMatchesPage() {
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
      title="Upcoming Matches"
      subtitle="Next 12 Hours"
      nowLocal={data.now_local}
      refreshing={refreshing}
      error={error}
      hasData
      onRefresh={refresh}
    >
      <div data-testid="upcoming-board">
        {data.upcoming_12h_groups.length === 0 ? (
          <div className="display-empty">No matches scheduled in the next 12 hours</div>
        ) : (
          data.upcoming_12h_groups.map((group) => (
            <section
              key={`${group.sort_time}-${group.scheduled_time}`}
              className="display-time-group"
              data-testid={`upcoming-group-${group.sort_time}`}
            >
              <h2 className="display-time-header">{group.scheduled_time}</h2>
              <div className="display-match-grid">
                {group.matches.map((match) => (
                  <DisplayMatchCard key={match.match_id} match={match} variant="upcoming12" />
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </DisplayShell>
  )
}

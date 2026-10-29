import { useParams } from 'react-router-dom'
import { DisplayBoardSection } from './DisplayBoardSection'
import { DisplayMatchCard } from './DisplayMatchCard'
import { DisplayLoadingState, DisplayShell } from './DisplayShell'
import { groupDisplayMatchesByTime } from './displayTimeGroups'
import { useDisplayBoard } from './useDisplayBoard'
import { useNowMs } from './useNowMs'

export default function DynamicScreenPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = Number(tournamentId)
  const { data, error, initialLoading, refreshing, refresh } = useDisplayBoard(tid)
  const hasLivePlaying = Boolean(data?.currently_playing.some((match) => match.started_at))
  const nowMs = useNowMs(hasLivePlaying)

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

  const nextGroups = groupDisplayMatchesByTime(data.upcoming)
  const nextEmpty = nextGroups.length === 0

  return (
    <DisplayShell
      tournamentName={data.tournament_name}
      title="Dynamic Screen"
      subtitle="Check-in courts"
      nowLocal={data.now_local}
      refreshing={refreshing}
      error={error}
      hasData
      onRefresh={refresh}
    >
      <div className="display-dynamic-screen" data-testid="dynamic-screen-board">
        <DisplayBoardSection
          testId="dynamic-currently-playing"
          title="Currently Playing"
          emptyLabel="No matches currently on court"
          isEmpty={data.currently_playing.length === 0}
          gridClass="display-match-grid"
          gridTestId="dynamic-playing-grid"
        >
          {data.currently_playing.map((match) => (
            <DisplayMatchCard
              key={match.match_id}
              match={match}
              variant="playing"
              nowMs={nowMs}
              preferTimeOnCourt
            />
          ))}
        </DisplayBoardSection>

        <section
          className={
            nextEmpty
              ? 'display-section display-section-compact'
              : 'display-section'
          }
          data-testid="dynamic-next-matches"
          data-empty={nextEmpty ? 'true' : 'false'}
        >
          <h2 className="display-section-title">Next Matches</h2>
          {nextEmpty ? (
            <p className="display-empty">No upcoming matches</p>
          ) : (
            nextGroups.map((group) => (
              <section
                key={`${group.sort_time}-${group.scheduled_time}`}
                className="display-time-group"
                data-testid={`dynamic-next-group-${group.sort_time}`}
              >
                <h3 className="display-time-header">{group.scheduled_time}</h3>
                <div
                  className="display-match-grid"
                  data-testid={`dynamic-next-grid-${group.sort_time}`}
                >
                  {group.matches.map((match) => (
                    <DisplayMatchCard key={match.match_id} match={match} variant="upcoming" />
                  ))}
                </div>
              </section>
            ))
          )}
        </section>

        <DisplayBoardSection
          testId="dynamic-waiting-for-court"
          title="Waiting for Court"
          emptyLabel="No matches waiting for court"
          isEmpty={data.waiting_for_court.length === 0}
          gridClass="display-waiting-grid"
          gridTestId="dynamic-waiting-grid"
        >
          {data.waiting_for_court.map((match) => (
            <DisplayMatchCard key={match.match_id} match={match} variant="waiting" />
          ))}
        </DisplayBoardSection>
      </div>
    </DisplayShell>
  )
}

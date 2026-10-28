import { useParams } from 'react-router-dom'
import { DisplayBoardSection } from './DisplayBoardSection'
import { DisplayMatchCard } from './DisplayMatchCard'
import { DisplayLoadingState, DisplayShell } from './DisplayShell'
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
          gridClass="display-playing-grid"
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

        <DisplayBoardSection
          testId="dynamic-next-matches"
          title="Next Matches"
          emptyLabel="No upcoming matches"
          isEmpty={data.upcoming.length === 0}
          gridClass="display-match-grid"
          gridTestId="dynamic-next-grid"
        >
          {data.upcoming.map((match) => (
            <DisplayMatchCard key={match.match_id} match={match} variant="upcoming" />
          ))}
        </DisplayBoardSection>

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

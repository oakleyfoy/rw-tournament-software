import { useParams } from 'react-router-dom'
import { DisplayBoardSection } from './DisplayBoardSection'
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
      <DisplayBoardSection
        testId="currently-playing"
        title="Currently Playing"
        emptyLabel="No matches currently on court"
        isEmpty={data.currently_playing.length === 0}
        gridClass="display-playing-grid"
        gridTestId="display-playing-grid"
      >
        {data.currently_playing.map((match) => (
          <DisplayMatchCard key={match.match_id} match={match} variant="playing" />
        ))}
      </DisplayBoardSection>

      <DisplayBoardSection
        testId="waiting-for-court"
        title="Waiting for Court"
        emptyLabel="No matches waiting for court"
        isEmpty={data.waiting_for_court.length === 0}
        gridClass="display-waiting-grid"
        gridTestId="display-waiting-grid"
      >
        {data.waiting_for_court.map((match) => (
          <DisplayMatchCard key={match.match_id} match={match} variant="waiting" />
        ))}
      </DisplayBoardSection>

      <DisplayBoardSection
        testId="court-board-upcoming"
        title="Upcoming / Next Matches"
        emptyLabel="No upcoming matches"
        isEmpty={data.upcoming.length === 0}
        gridClass="display-match-grid"
        gridTestId="display-upcoming-grid"
      >
        {data.upcoming.map((match) => (
          <DisplayMatchCard key={match.match_id} match={match} variant="upcoming" />
        ))}
      </DisplayBoardSection>
    </DisplayShell>
  )
}

import { useParams } from 'react-router-dom'
import { DisplayBoardSection } from './DisplayBoardSection'
import { DisplayMatchCard } from './DisplayMatchCard'
import { DisplayLoadingState, DisplayShell } from './DisplayShell'
import { COURT_ASSIGNED_MIN_TIME_SLOTS, courtAssignedGroupsFromUpcoming } from './courtAssignedGroups'
import { useDisplayBoard } from './useDisplayBoard'
import { useNowMs } from './useNowMs'

export default function CourtAssignedPage() {
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

  const assignedGroups = courtAssignedGroupsFromUpcoming(data.upcoming)
  const upcomingEmpty = assignedGroups.length === 0

  return (
    <DisplayShell
      tournamentName={data.tournament_name}
      title="Court Assigned"
      subtitle="Playing now + upcoming courts"
      nowLocal={data.now_local}
      refreshing={refreshing}
      error={error}
      hasData
      onRefresh={refresh}
    >
      <div
        className="display-court-assigned"
        data-testid="court-assigned-board"
        data-min-slots={COURT_ASSIGNED_MIN_TIME_SLOTS}
      >
        <DisplayBoardSection
          testId="court-assigned-playing"
          title="Currently Playing"
          emptyLabel="No matches currently on court"
          isEmpty={data.currently_playing.length === 0}
          gridClass="display-match-grid"
          gridTestId="court-assigned-playing-grid"
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
            upcomingEmpty
              ? 'display-section display-section-compact display-court-assigned-upcoming'
              : 'display-section display-court-assigned-upcoming'
          }
          data-testid="court-assigned-upcoming"
          data-empty={upcomingEmpty ? 'true' : 'false'}
          data-slot-count={assignedGroups.length}
        >
          <h2 className="display-section-title">Upcoming — Court Assigned</h2>
          {upcomingEmpty ? (
            <p className="display-empty">No upcoming matches with a court assigned</p>
          ) : (
            assignedGroups.map((group) => (
              <section
                key={`${group.sort_time}-${group.scheduled_time}`}
                className="display-time-group"
                data-testid={`court-assigned-group-${group.sort_time}`}
              >
                <h3 className="display-time-header">{group.scheduled_time}</h3>
                <div
                  className="display-match-grid"
                  data-testid={`court-assigned-grid-${group.sort_time}`}
                >
                  {group.matches.map((match) => (
                    <DisplayMatchCard key={match.match_id} match={match} variant="upcoming12" />
                  ))}
                </div>
              </section>
            ))
          )}
        </section>
      </div>
    </DisplayShell>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  getPublicDrawsList,
  getPublicSchedule,
  getPublicTeamDirectory,
  type PublicEventItem,
  type PublicTeamDirectoryItem,
  type ScheduleMatchItem,
} from '../../api/client'
import {
  buildTeamJourney,
  courtText,
  rosterNames,
  roundLabel,
  timeText,
} from '../../lib/publicMobileDraw'
import {
  drawPathWithTeamHighlight,
  drawTargetsForTeam,
  hubOpponentLabel,
  matchResultLabel,
  publicTournamentHubPath,
  teamHubStatus,
} from '../../lib/tournamentHub'
import { HubPhotoDialog, HubTeamPhoto } from './HubTeamPhoto'
import './publicTournamentHub.css'

const REFRESH_MS = 15000

function opponentTeamId(match: ScheduleMatchItem, teamId: number): number | null {
  if (match.team_a_id === teamId) return match.team_b_id
  if (match.team_b_id === teamId) return match.team_a_id
  return null
}

export default function PublicTournamentTeamPage() {
  const { tournamentId, teamId } = useParams<{ tournamentId: string; teamId: string }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : NaN
  const selectedTeamId = teamId ? parseInt(teamId, 10) : NaN
  const navigate = useNavigate()

  const [tournamentName, setTournamentName] = useState('')
  const [teams, setTeams] = useState<PublicTeamDirectoryItem[]>([])
  const [matches, setMatches] = useState<ScheduleMatchItem[]>([])
  const [events, setEvents] = useState<PublicEventItem[]>([])
  const [showCourtInfo, setShowCourtInfo] = useState(true)
  const [loading, setLoading] = useState(true)
  const [notPublished, setNotPublished] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [choosingDraw, setChoosingDraw] = useState(false)
  const [enlargedTeamId, setEnlargedTeamId] = useState<number | null>(null)

  useEffect(() => {
    if (!Number.isFinite(tid) || tid <= 0) return
    let cancelled = false

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true)
      try {
        const [directory, schedule, draws] = await Promise.all([
          getPublicTeamDirectory(tid),
          getPublicSchedule(tid),
          getPublicDrawsList(tid).catch(() => null),
        ])
        if (cancelled) return
        if (directory.status === 'NOT_PUBLISHED' || schedule.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
          return
        }
        setNotPublished(false)
        setTournamentName(directory.tournament_name || schedule.tournament_name)
        setTeams(directory.teams)
        setMatches(schedule.matches)
        setShowCourtInfo(schedule.show_court_info)
        if (draws && (draws as { status?: string }).status !== 'NOT_PUBLISHED') {
          setEvents(draws.events || [])
        } else {
          setEvents([])
        }
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load team information')
      } finally {
        if (!cancelled && showSpinner) setLoading(false)
      }
    }

    void load(true)
    const timer = window.setInterval(() => { void load(false) }, REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [tid])

  const teamMap = useMemo(() => new Map(teams.map((item) => [item.team_id, item])), [teams])
  const team = useMemo(
    () => teams.find((item) => item.team_id === selectedTeamId) || null,
    [teams, selectedTeamId],
  )
  const journey = useMemo(
    () => (Number.isFinite(selectedTeamId) ? buildTeamJourney(selectedTeamId, matches) : null),
    [selectedTeamId, matches],
  )
  const status = useMemo(
    () => (Number.isFinite(selectedTeamId) ? teamHubStatus(selectedTeamId, matches) : null),
    [selectedTeamId, matches],
  )
  const drawTargets = useMemo(
    () => (team ? drawTargetsForTeam(tid, team, matches, events) : []),
    [tid, team, matches, events],
  )
  const enlargedTeam = enlargedTeamId == null ? null : teamMap.get(enlargedTeamId) || null

  if (!Number.isFinite(tid) || tid <= 0 || !Number.isFinite(selectedTeamId)) {
    return <div className="hub-page"><p className="hub-error" role="alert">Team not found.</p></div>
  }

  if (loading) {
    return <div className="hub-page"><p className="hub-loading">Loading your tournament info…</p></div>
  }

  if (notPublished) {
    return (
      <div className="hub-page">
        <Link className="hub-back" to={publicTournamentHubPath(tid)}>Back to search</Link>
        <p className="hub-empty">The tournament schedule has not been published yet.</p>
      </div>
    )
  }

  if (error) {
    return <div className="hub-page"><p className="hub-error" role="alert">{error}</p></div>
  }

  if (!team || !journey || !status) {
    return (
      <div className="hub-page">
        <Link className="hub-back" to={publicTournamentHubPath(tid)}>Back to search</Link>
        <p className="hub-empty">That team is not in the published tournament directory.</p>
      </div>
    )
  }

  const openDraw = (path: string) => {
    navigate(drawPathWithTeamHighlight(path, team.team_id, true))
  }

  const onViewDraw = () => {
    if (drawTargets.length === 0) return
    if (drawTargets.length === 1) {
      openDraw(drawTargets[0].path)
      return
    }
    setChoosingDraw(true)
  }

  const previous = journey.completed.slice().reverse()
  const next = journey.next
  const nextOpponentId = next ? opponentTeamId(next, team.team_id) : null
  const nextOpponent = nextOpponentId == null ? null : teamMap.get(nextOpponentId) || null

  return (
    <div className="hub-page" data-testid="tournament-hub-team">
      <Link className="hub-back" to={publicTournamentHubPath(tid)}>Back to search</Link>
      <p className="hub-kicker">{tournamentName}</p>

      <p className="hub-kicker" style={{ marginTop: 18 }}>Team</p>
      <div className="hub-team-header">
        <HubTeamPhoto
          tournamentId={tid}
          team={team}
          large
          onEnlarge={team.photo_version ? () => setEnlargedTeamId(team.team_id) : undefined}
        />
        <h1 className="hub-team-names">{rosterNames(team).join(' / ')}</h1>
      </div>

      <p className="hub-kicker" style={{ marginTop: 18 }}>Division</p>
      <p className="hub-division">{team.event_name}</p>

      <p className="hub-kicker" style={{ marginTop: 18 }}>Current Status</p>
      <span className="hub-status" data-testid="hub-team-status">{status.label}</span>

      <section className="hub-card" aria-label="Next match">
        <h2>Next Match</h2>
        {next ? (
          <>
            <div className="hub-opponent-row">
              <HubTeamPhoto
                tournamentId={tid}
                team={nextOpponent}
                onEnlarge={nextOpponent?.photo_version ? () => setEnlargedTeamId(nextOpponent.team_id) : undefined}
              />
              <div className="hub-opponent">{hubOpponentLabel(next, team.team_id)}</div>
            </div>
            <div className="hub-meta">
              <span>{roundLabel(next)}</span>
              <span>{timeText(next)}</span>
              {courtText(next, showCourtInfo) && <span>{courtText(next, showCourtInfo)}</span>}
              <span>{(next.status || 'WAITING').replace(/_/g, ' ')}</span>
            </div>
            {hubOpponentLabel(next, team.team_id) === 'Opponent TBD' && (
              <p className="hub-hint" style={{ textAlign: 'left', marginTop: 10 }}>
                Opponent is not determined yet.
              </p>
            )}
          </>
        ) : (
          <p className="hub-hint" style={{ textAlign: 'left', margin: 0 }}>
            No upcoming match is published for this team.
          </p>
        )}
      </section>

      <section className="hub-card" aria-label="Previous matches">
        <h2>Previous Matches</h2>
        {previous.length === 0 && (
          <p className="hub-hint" style={{ textAlign: 'left', margin: 0 }}>No completed matches yet.</p>
        )}
        {previous.map((match) => {
          const result = matchResultLabel(match, team.team_id)
          const oppId = opponentTeamId(match, team.team_id)
          const opponent = oppId == null ? null : teamMap.get(oppId) || null
          return (
            <div key={match.match_id} className="hub-history-item">
              <div className="hub-history-main">
                <HubTeamPhoto tournamentId={tid} team={opponent} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="hub-history-top">
                    <span>{hubOpponentLabel(match, team.team_id)}</span>
                    {result && <span className={result === 'Win' ? 'hub-win' : 'hub-loss'}>{result}</span>}
                  </div>
                  <div className="hub-meta">
                    <span>{roundLabel(match)}</span>
                    {match.score_display && <span>{match.score_display}</span>}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </section>

      {drawTargets.length > 0 && (
        <section className="hub-card" aria-label="Draw position">
          <h2>Draw Position</h2>
          {!choosingDraw ? (
            <button
              type="button"
              className="hub-draw-btn"
              data-testid="hub-view-draw-position"
              onClick={onViewDraw}
            >
              View My Position In The Draw
            </button>
          ) : (
            <div className="hub-draw-choices">
              <p className="hub-hint" style={{ textAlign: 'left', margin: 0 }}>
                This team appears in more than one draw. Choose where to look:
              </p>
              {drawTargets.map((target) => (
                <button
                  key={target.path}
                  type="button"
                  className="hub-draw-btn secondary"
                  onClick={() => openDraw(target.path)}
                >
                  {target.label}
                </button>
              ))}
              <button type="button" className="hub-draw-btn secondary" onClick={() => setChoosingDraw(false)}>
                Cancel
              </button>
            </div>
          )}
        </section>
      )}

      {enlargedTeam?.photo_version && (
        <HubPhotoDialog
          tournamentId={tid}
          team={enlargedTeam}
          onClose={() => setEnlargedTeamId(null)}
        />
      )}
    </div>
  )
}

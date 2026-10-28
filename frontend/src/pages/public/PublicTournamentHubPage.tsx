import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  getPublicDrawsList,
  getPublicSchedule,
  getPublicTeamDirectory,
  type PublicEventItem,
  type PublicTeamDirectoryItem,
} from '../../api/client'
import { rosterNames, searchPublicTeams } from '../../lib/publicMobileDraw'
import { publicTournamentTeamPath } from '../../lib/tournamentHub'
import './publicTournamentHub.css'

const REFRESH_MS = 15000

export default function PublicTournamentHubPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : NaN
  const navigate = useNavigate()

  const [tournamentName, setTournamentName] = useState('')
  const [teams, setTeams] = useState<PublicTeamDirectoryItem[]>([])
  const [events, setEvents] = useState<PublicEventItem[]>([])
  const [hasSchedule, setHasSchedule] = useState(false)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [notPublished, setNotPublished] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!Number.isFinite(tid) || tid <= 0) return
    let cancelled = false

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true)
      try {
        const [directory, draws, schedule] = await Promise.all([
          getPublicTeamDirectory(tid),
          getPublicDrawsList(tid).catch(() => null),
          getPublicSchedule(tid).catch(() => null),
        ])
        if (cancelled) return
        if (directory.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
          setTeams([])
          setTournamentName('')
          setError(null)
          return
        }
        setNotPublished(false)
        setTournamentName(directory.tournament_name)
        setTeams(directory.teams)
        if (draws && (draws as { status?: string }).status !== 'NOT_PUBLISHED') {
          setEvents(draws.events || [])
        } else {
          setEvents([])
        }
        if (schedule && schedule.status !== 'NOT_PUBLISHED') {
          setHasSchedule(true)
        } else {
          setHasSchedule(false)
        }
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the tournament hub')
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

  if (!Number.isFinite(tid) || tid <= 0) {
    return <div className="hub-page"><p className="hub-error" role="alert">Tournament not found.</p></div>
  }

  if (loading) {
    return <div className="hub-page"><p className="hub-loading">Loading tournament hub…</p></div>
  }

  if (notPublished) {
    return (
      <div className="hub-page">
        <p className="hub-brand">Racquet War</p>
        <p className="hub-empty">The tournament schedule has not been published yet. Check back later.</p>
      </div>
    )
  }

  if (error) {
    return <div className="hub-page"><p className="hub-error" role="alert">{error}</p></div>
  }

  const results = searchPublicTeams(teams, query)
  const showResults = query.trim().length >= 2
  const hasDraws = events.some((event) => event.has_waterfall || event.has_round_robin || (event.divisions?.length ?? 0) > 0)

  return (
    <div className="hub-page" data-testid="tournament-hub">
      <p className="hub-brand">Racquet War</p>
      <p className="hub-tournament">{tournamentName}</p>

      <h1 className="hub-section-title">Find Your Team</h1>
      <form className="hub-search" role="search" onSubmit={(event) => event.preventDefault()}>
        <label htmlFor="hub-team-search">Search by player or team name</label>
        <input
          id="hub-team-search"
          data-testid="hub-team-search"
          value={query}
          placeholder="First name, last name, or team"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          onChange={(event) => setQuery(event.target.value)}
        />
      </form>

      {showResults && (
        <div className="hub-results" aria-live="polite" data-testid="hub-search-results">
          {results.length === 0 && (
            <p className="hub-empty">No matching team found. Try another name spelling.</p>
          )}
          {results.map((team) => (
            <button
              key={team.team_id}
              type="button"
              className="hub-result"
              data-testid={`hub-result-${team.team_id}`}
              onClick={() => navigate(publicTournamentTeamPath(tid, team.team_id))}
            >
              <span>
                <strong>{rosterNames(team).join(' / ')}</strong>
                <small>{team.event_name}</small>
              </span>
            </button>
          ))}
        </div>
      )}

      {!showResults && (
        <p className="hub-hint">Type at least 2 letters to search either doubles partner.</p>
      )}

      <nav className="hub-nav" aria-label="Tournament links">
        {hasDraws && (
          <Link className="hub-nav-link" to={`/t/${tid}/draws`} data-testid="hub-view-draws">
            View All Draws
          </Link>
        )}
        {hasSchedule && (
          <Link className="hub-nav-link" to={`/t/${tid}/schedule`} data-testid="hub-view-schedule">
            Tournament Schedule
          </Link>
        )}
        {hasSchedule && (
          <Link className="hub-nav-link" to={`/t/${tid}/schedule`} data-testid="hub-view-results">
            Match Results
          </Link>
        )}
      </nav>
    </div>
  )
}

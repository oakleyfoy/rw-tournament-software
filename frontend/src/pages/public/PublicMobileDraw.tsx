import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  getPublicSchedule,
  getPublicTeamDirectory,
  publicTeamPhotoUrl,
  type PublicTeamDirectoryItem,
  type ScheduleMatchItem,
} from '../../api/client'
import {
  buildTeamJourney,
  courtText,
  displaySideLabel,
  groupMatchesByRound,
  matchesForView,
  opponentName,
  publicMatchStatus,
  rosterNames,
  roundLabel,
  searchPublicTeams,
  teamInitials,
  timeText,
  winnerName,
  type MobileTeam,
} from '../../lib/publicMobileDraw'
import './publicMobileDraw.css'

const REFRESH_MS = 15000

interface PublicMobileDrawProps {
  tournamentId: number
  eventId: number
  tournamentName: string
  eventName: string
  formatLabel: string
  divisionCode?: string | null
  divisionLabel?: string | null
  onlyStage?: string | null
  backHref: string
  onShowFullDraw: () => void
  refreshMs?: number
  /** Prefill from hub deep-link (?team=). */
  initialTeamId?: number | null
}

function TeamPhoto({
  tournamentId,
  team,
  large = false,
  onEnlarge,
}: {
  tournamentId: number
  team: MobileTeam | null
  large?: boolean
  onEnlarge?: () => void
}) {
  const [broken, setBroken] = useState(false)
  const name = team?.full_name || 'Team'
  const version = team?.photo_version
  if (!team || !version || broken) {
    return <span className={large ? 'public-photo-fallback large' : 'public-photo-fallback'} aria-hidden="true">{teamInitials(name)}</span>
  }
  const image = (
    <img
      className={large ? 'public-photo large' : 'public-photo'}
      src={publicTeamPhotoUrl(tournamentId, team.team_id, version)}
      alt=""
      width={large ? 80 : 44}
      height={large ? 80 : 44}
      loading="lazy"
      onError={() => setBroken(true)}
    />
  )
  if (!large || !onEnlarge) return image
  return (
    <button type="button" className="public-photo-enlarge" onClick={onEnlarge} aria-label={`Enlarge photo of ${name}`}>
      {image}
    </button>
  )
}

function teamForSide(teams: Map<number, MobileTeam>, teamId: number | null): MobileTeam | null {
  if (teamId == null) return null
  return teams.get(teamId) || null
}

export default function PublicMobileDraw({
  tournamentId,
  eventId,
  tournamentName,
  eventName,
  formatLabel,
  divisionCode,
  divisionLabel,
  onlyStage,
  backHref,
  onShowFullDraw,
  refreshMs = REFRESH_MS,
  initialTeamId = null,
}: PublicMobileDrawProps) {
  const [searchParams] = useSearchParams()
  const teamFromQuery = Number(searchParams.get('team') || '')
  const resolvedInitialTeamId = initialTeamId
    ?? (Number.isFinite(teamFromQuery) && teamFromQuery > 0 ? teamFromQuery : null)
  const [matches, setMatches] = useState<ScheduleMatchItem[]>([])
  const [teams, setTeams] = useState<PublicTeamDirectoryItem[]>([])
  const [showCourtInfo, setShowCourtInfo] = useState(true)
  const [query, setQuery] = useState('')
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(resolvedInitialTeamId)
  const [view, setView] = useState<'matches' | 'journey'>(resolvedInitialTeamId != null ? 'journey' : 'matches')
  const [round, setRound] = useState('All')
  const [detailId, setDetailId] = useState<number | null>(null)
  const [enlargedTeamId, setEnlargedTeamId] = useState<number | null>(null)
  const [notPublished, setNotPublished] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (resolvedInitialTeamId == null) return
    setSelectedTeamId(resolvedInitialTeamId)
    setView('journey')
  }, [resolvedInitialTeamId])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [schedule, directory] = await Promise.all([
          getPublicSchedule(tournamentId),
          getPublicTeamDirectory(tournamentId),
        ])
        if (cancelled) return
        if (schedule.status === 'NOT_PUBLISHED' || directory.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
          return
        }
        setNotPublished(false)
        setMatches(schedule.matches)
        setTeams(directory.teams)
        setShowCourtInfo(schedule.show_court_info)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the draw')
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, refreshMs)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [tournamentId, refreshMs])

  const teamMap = useMemo(() => new Map(teams.map((team) => [team.team_id, team])), [teams])
  const selectedTeam = selectedTeamId == null ? null : teamMap.get(selectedTeamId) || null
  const results = searchPublicTeams(teams, query)
  const divisionMatches = useMemo(() => {
    const rows = matchesForView(matches, eventId, divisionCode, divisionLabel)
    if (!onlyStage) return rows
    const stage = onlyStage.toUpperCase()
    return rows.filter((match) => (
      (match.stage || '').toUpperCase() === stage
      || (match.match_code || '').toUpperCase().includes(`_${stage}_`)
    ))
  }, [matches, eventId, divisionCode, divisionLabel, onlyStage])
  const groups = useMemo(() => groupMatchesByRound(divisionMatches), [divisionMatches])
  const visibleMatches = round === 'All'
    ? divisionMatches
    : divisionMatches.filter((match) => roundLabel(match) === round)
  const journey = useMemo(
    () => selectedTeamId == null ? null : buildTeamJourney(selectedTeamId, matches),
    [selectedTeamId, matches],
  )
  const detail = matches.find((match) => match.match_id === detailId) || null
  const headerTeam = selectedTeam
  const keepPoolSeeds = formatLabel === 'Round robin' || (onlyStage || '').toUpperCase() === 'RR'
  const sideLabel = (name: string | null | undefined) => displaySideLabel(name, { keepPoolSeeds })
  const drawStatus = divisionMatches.some((match) => match.status === 'IN_PROGRESS')
    ? 'In progress'
    : divisionMatches.length && divisionMatches.every((match) => match.status === 'FINAL')
      ? 'Complete'
      : null

  if (notPublished) {
    return <div className="public-mobile"><p>The tournament schedule has not been published yet.</p></div>
  }
  if (error) {
    return <div className="public-mobile"><p role="alert">{error}</p></div>
  }

  const chooseTeam = (teamId: number) => {
    setSelectedTeamId(teamId)
    setView('journey')
    setDetailId(null)
    setQuery('')
  }
  const headingStatus = headerTeam && journey ? journey.statusLabel : drawStatus

  return (
    <div className="public-mobile">
      <Link className="public-mobile-back" to={backHref}>Back to draws</Link>
      <p className="public-mobile-kicker">{tournamentName}</p>
      <h1>{eventName}</h1>
      <p className="public-mobile-meta">
        {headerTeam ? headerTeam.event_name : eventName}
        {' · '}
        {divisionLabel || formatLabel}
      </p>
      {headingStatus ? <span className="public-mobile-status">{headingStatus}</span> : null}

      <form className="public-search" role="search" onSubmit={(event) => event.preventDefault()}>
        <label htmlFor="public-team-search">Find your team</label>
        <input
          id="public-team-search"
          value={query}
          placeholder="First name, last name, partner, or team"
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
        />
        {query.trim().length >= 2 && (
          <div className="public-search-results" aria-live="polite">
            {results.length === 0 && <p>No matching team in this tournament.</p>}
            {results.map((team) => (
              <button key={team.team_id} type="button" className="public-search-result" onClick={() => chooseTeam(team.team_id)}>
                <TeamPhoto tournamentId={tournamentId} team={team} />
                <span>
                  <strong>{rosterNames(team).join(' / ')}</strong>
                  <small>{team.event_name}</small>
                </span>
              </button>
            ))}
          </div>
        )}
      </form>

      <div className="public-mobile-tabs" role="tablist" aria-label="Draw views">
        <button type="button" role="tab" aria-selected={view === 'journey'} onClick={() => setView('journey')}>My Matches</button>
        <button type="button" role="tab" aria-selected={view === 'matches'} onClick={() => { setView('matches'); setDetailId(null) }}>All Matches</button>
        <button type="button" onClick={onShowFullDraw}>Full Draw</button>
      </div>

      {view === 'journey' && !journey && (
        <div className="public-journey">
          <p>Search for a team to see its matches. This division is shown under All Matches until then.</p>
          <button type="button" className="public-mobile-full" onClick={() => setView('matches')}>View {eventName}</button>
        </div>
      )}

      {view === 'journey' && journey && selectedTeam && !detail && (
        <div className="public-journey">
          <article className="public-team-header">
            <TeamPhoto tournamentId={tournamentId} team={selectedTeam} large onEnlarge={() => setEnlargedTeamId(selectedTeam.team_id)} />
            <div className="public-team-copy">
              {rosterNames(selectedTeam).map((name) => (
                <strong key={name} className="public-player-name">{name}</strong>
              ))}
              <div className="public-team-division">{selectedTeam.event_name}{divisionLabel ? ` · ${divisionLabel}` : ` · ${formatLabel}`}</div>
            </div>
          </article>
          {journey.next && (
            <article className="public-next-match" aria-label={`Next match ${journey.next.match_number}`}>
              <div className="public-next-kicker">Next match</div>
              <div className="public-opponent">
                {opponentName(journey.next, selectedTeam.team_id, { keepPoolSeeds }).split(/\s*\/\s*/).map((name) => (
                  <span key={name}>{name}</span>
                ))}
              </div>
              <div className="public-when">{timeText(journey.next)}</div>
              {courtText(journey.next, showCourtInfo) && <div className="public-court">{courtText(journey.next, showCourtInfo)}</div>}
              <div className="public-next-meta">
                <span>{journey.next.day_label}</span>
                <span>Match #{journey.next.match_number}</span>
                <span>{roundLabel(journey.next)}</span>
              </div>
            </article>
          )}
          {journey.matches.filter((match) => match.match_id !== journey.next?.match_id).map((match) => (
            <MatchCard
              key={match.match_id}
              match={match}
              teams={teamMap}
              tournamentId={tournamentId}
              showCourtInfo={showCourtInfo}
              keepPoolSeeds={keepPoolSeeds}
              highlightTeamId={selectedTeam.team_id}
              onOpen={() => setDetailId(match.match_id)}
            />
          ))}
        </div>
      )}

      {view === 'matches' && !detail && (
        <>
          <div className="public-round-nav" aria-label="Rounds">
            <button type="button" aria-pressed={round === 'All'} onClick={() => setRound('All')}>All</button>
            {groups.map((group) => (
              <button key={group.label} type="button" aria-pressed={round === group.label} onClick={() => setRound(group.label)}>
                {group.label}
              </button>
            ))}
          </div>
          <div className="public-match-list">
            {visibleMatches.map((match) => (
              <MatchCard
                key={match.match_id}
                match={match}
                teams={teamMap}
                tournamentId={tournamentId}
                showCourtInfo={showCourtInfo}
                keepPoolSeeds={keepPoolSeeds}
                onOpen={() => setDetailId(match.match_id)}
              />
            ))}
            {visibleMatches.length === 0 && <p>No matches in this round yet.</p>}
          </div>
        </>
      )}

      {detail && (
        <article className="public-match-card" aria-label={`Match ${detail.match_number}`}>
          <button type="button" onClick={() => setDetailId(null)}>Back to matches</button>
          <div className="public-match-top">
            <strong>Match #{detail.match_number}</strong>
            <span className={`public-status ${publicMatchStatus(detail).key}`}>{publicMatchStatus(detail).label}</span>
          </div>
          <div>{roundLabel(detail)}</div>
          <div className="public-detail-teams">
            <DetailSide
              tournamentId={tournamentId}
              name={sideLabel(detail.team1_full_name)}
              team={teamForSide(teamMap, detail.team_a_id)}
              winner={detail.winner_team_id != null && detail.winner_team_id === detail.team_a_id}
              onEnlarge={() => detail.team_a_id != null && setEnlargedTeamId(detail.team_a_id)}
            />
            <DetailSide
              tournamentId={tournamentId}
              name={sideLabel(detail.team2_full_name)}
              team={teamForSide(teamMap, detail.team_b_id)}
              winner={detail.winner_team_id != null && detail.winner_team_id === detail.team_b_id}
              onEnlarge={() => detail.team_b_id != null && setEnlargedTeamId(detail.team_b_id)}
            />
          </div>
          {detail.score_display && <div>Score {detail.score_display}</div>}
          {winnerName(detail, teamMap) && <div>Winner: {sideLabel(winnerName(detail, teamMap))}</div>}
          {(detail.team1_full_name !== sideLabel(detail.team1_full_name) || detail.team2_full_name !== sideLabel(detail.team2_full_name)) && (
            <details className="public-full-names">
              <summary>Full registration names</summary>
              <p>{detail.team1_full_name}</p>
              <p>{detail.team2_full_name}</p>
            </details>
          )}
          <div className="public-when">{timeText(detail)}</div>
          <div>{detail.day_label}</div>
          {courtText(detail, showCourtInfo) && <div>{courtText(detail, showCourtInfo)}</div>}
        </article>
      )}

      {enlargedTeamId != null && teamMap.get(enlargedTeamId)?.photo_version && (
        <div className="public-dialog" role="dialog" aria-modal="true" aria-label="Team photograph">
          <button type="button" onClick={() => setEnlargedTeamId(null)}>Close</button>
          <img
            src={publicTeamPhotoUrl(tournamentId, enlargedTeamId, teamMap.get(enlargedTeamId)!.photo_version!)}
            alt={teamMap.get(enlargedTeamId)!.full_name}
          />
        </div>
      )}
    </div>
  )
}

function DetailSide({
  tournamentId,
  name,
  team,
  winner,
  onEnlarge,
}: {
  tournamentId: number
  name: string
  team: MobileTeam | null
  winner: boolean
  onEnlarge: () => void
}) {
  return (
    <div className="public-detail-team">
      <TeamPhoto tournamentId={tournamentId} team={team || { team_id: 0, event_id: 0, event_name: '', seed: null, full_name: name, players: [], photo_version: null }} large onEnlarge={team?.photo_version ? onEnlarge : undefined} />
      <div className="public-team-copy">
        <span className={winner ? 'public-team-name winner' : 'public-team-name'} title={name}>{name}</span>
        {winner && <div>Winner</div>}
      </div>
    </div>
  )
}

function MatchCard({
  match,
  teams,
  tournamentId,
  showCourtInfo,
  keepPoolSeeds,
  highlightTeamId,
  onOpen,
}: {
  match: ScheduleMatchItem
  teams: Map<number, MobileTeam>
  tournamentId: number
  showCourtInfo: boolean
  keepPoolSeeds: boolean
  highlightTeamId?: number
  onOpen: () => void
}) {
  const status = publicMatchStatus(match)
  const winnerId = (match.status || '').toUpperCase() === 'FINAL' ? match.winner_team_id : null
  const upcoming = status.key === 'scheduled' || status.key === 'waiting' || status.key === 'in_progress'
  return (
    <button type="button" className="public-match-card" onClick={onOpen}>
      <div className="public-match-top">
        <span>Match #{match.match_number} · {roundLabel(match)}</span>
        <span className={`public-status ${status.key}`}>{status.label}</span>
      </div>
      <TeamLine
        tournamentId={tournamentId}
        name={displaySideLabel(match.team1_full_name, { keepPoolSeeds })}
        team={teamForSide(teams, match.team_a_id)}
        winner={winnerId != null && winnerId === match.team_a_id}
        highlight={highlightTeamId != null && highlightTeamId === match.team_a_id}
      />
      <TeamLine
        tournamentId={tournamentId}
        name={displaySideLabel(match.team2_full_name, { keepPoolSeeds })}
        team={teamForSide(teams, match.team_b_id)}
        winner={winnerId != null && winnerId === match.team_b_id}
        highlight={highlightTeamId != null && highlightTeamId === match.team_b_id}
      />
      {match.score_display && <div>Score {match.score_display}</div>}
      {upcoming && <div className="public-when">{timeText(match)}</div>}
      <div className="public-match-facts">
        <span>{match.day_label}</span>
        {courtText(match, showCourtInfo) && <span>{courtText(match, showCourtInfo)}</span>}
      </div>
    </button>
  )
}

function TeamLine({
  tournamentId,
  name,
  team,
  winner,
  highlight,
}: {
  tournamentId: number
  name: string
  team: MobileTeam | null
  winner: boolean
  highlight: boolean
}) {
  return (
    <div className="public-team-row">
      <TeamPhoto
        tournamentId={tournamentId}
        team={team || { team_id: 0, event_id: 0, event_name: '', seed: null, full_name: name, players: [], photo_version: null }}
      />
      <div className="public-team-copy">
        <span className={winner || highlight ? 'public-team-name winner' : 'public-team-name'} title={name}>{name}</span>
      </div>
    </div>
  )
}

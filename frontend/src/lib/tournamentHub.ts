import type { PublicEventItem, PublicTeamDirectoryItem, ScheduleMatchItem } from '../api/client'
import {
  buildTeamJourney,
  displaySideLabel,
  opponentName,
  type MobileMatch,
  type TeamJourney,
} from './publicMobileDraw'

export type TeamHubStatusKey =
  | 'awaiting_first_match'
  | 'waiting_for_opponent'
  | 'ready_to_play'
  | 'court_assigned'
  | 'match_in_progress'
  | 'advanced_to_next_round'
  | 'eliminated'
  | 'division_completed'

export interface TeamHubStatus {
  key: TeamHubStatusKey
  label: string
}

export interface DrawTarget {
  label: string
  path: string
  drawType: 'waterfall' | 'round_robin' | 'bracket'
  divisionCode?: string | null
  divisionLabel?: string | null
}

const BRACKET_DIV_ORDER = ['BWW', 'BWL', 'BLW', 'BLL', 'B1', 'B2', 'B3'] as const
const BRACKET_DIV_LABELS: Record<string, string> = {
  BWW: 'Division I',
  BWL: 'Division II',
  BLW: 'Division III',
  BLL: 'Division IV',
  B1: 'Bracket 1',
  B2: 'Bracket 2',
  B3: 'Bracket 3',
}

const STATUS_LABEL: Record<TeamHubStatusKey, string> = {
  awaiting_first_match: 'Awaiting first match',
  waiting_for_opponent: 'Waiting for opponent',
  ready_to_play: 'Ready to play',
  court_assigned: 'Court assigned',
  match_in_progress: 'Match in progress',
  advanced_to_next_round: 'Advanced to next round',
  eliminated: 'Eliminated',
  division_completed: 'Division completed',
}

export function publicTournamentHubPath(tournamentId: number): string {
  return `/t/${tournamentId}/hub`
}

export function publicTournamentTeamPath(tournamentId: number, teamId: number): string {
  return `/t/${tournamentId}/hub/teams/${teamId}`
}

function asMobileMatches(matches: ScheduleMatchItem[]): MobileMatch[] {
  return matches as MobileMatch[]
}

function opponentIsTbd(match: MobileMatch, teamId: number): boolean {
  const name = opponentName(match, teamId)
  return !name || name === 'Opponent TBD' || /^(Winner|Loser) of Match/i.test(name)
}

function sideKnown(match: MobileMatch, teamId: number): boolean {
  if (match.team_a_id === teamId || match.team_b_id === teamId) return true
  return false
}

function lastCompletedResult(teamId: number, journey: TeamJourney): 'win' | 'loss' | null {
  const last = [...journey.completed].reverse()[0]
  if (!last || last.winner_team_id == null) return null
  return last.winner_team_id === teamId ? 'win' : 'loss'
}

/** Player-facing status from published match/schedule records only. */
export function teamHubStatus(teamId: number, matches: ScheduleMatchItem[]): TeamHubStatus {
  const journey = buildTeamJourney(teamId, asMobileMatches(matches))
  const next = journey.next
  const completed = journey.completed
  const lastResult = lastCompletedResult(teamId, journey)

  if (next) {
    const runtime = (next.status || '').toUpperCase()
    if (runtime === 'IN_PROGRESS') {
      return { key: 'match_in_progress', label: STATUS_LABEL.match_in_progress }
    }
    if (opponentIsTbd(next, teamId)) {
      return { key: 'waiting_for_opponent', label: STATUS_LABEL.waiting_for_opponent }
    }
    if (runtime === 'SCHEDULED' && next.court_name) {
      return { key: 'court_assigned', label: STATUS_LABEL.court_assigned }
    }
    if (sideKnown(next, teamId) && !opponentIsTbd(next, teamId)) {
      if (lastResult === 'win' && completed.length > 0) {
        return { key: 'advanced_to_next_round', label: STATUS_LABEL.advanced_to_next_round }
      }
      return { key: 'ready_to_play', label: STATUS_LABEL.ready_to_play }
    }
    if (completed.length === 0) {
      return { key: 'awaiting_first_match', label: STATUS_LABEL.awaiting_first_match }
    }
    return { key: 'waiting_for_opponent', label: STATUS_LABEL.waiting_for_opponent }
  }

  if (completed.length === 0 && journey.matches.length === 0) {
    return { key: 'awaiting_first_match', label: STATUS_LABEL.awaiting_first_match }
  }
  if (completed.length === 0) {
    return { key: 'awaiting_first_match', label: STATUS_LABEL.awaiting_first_match }
  }
  if (lastResult === 'loss') {
    return { key: 'eliminated', label: STATUS_LABEL.eliminated }
  }
  return { key: 'division_completed', label: STATUS_LABEL.division_completed }
}

function divisionCodeFromMatch(match: MobileMatch | null): string | null {
  if (!match) return null
  const code = (match.match_code || '').toUpperCase()
  for (const div of BRACKET_DIV_ORDER) {
    if (code.includes(`_${div}_`)) return div
  }
  return null
}

export function drawTargetsForTeam(
  tournamentId: number,
  team: Pick<PublicTeamDirectoryItem, 'team_id' | 'event_id' | 'event_name'>,
  matches: ScheduleMatchItem[],
  events: PublicEventItem[],
): DrawTarget[] {
  const event = events.find((item) => item.event_id === team.event_id)
  if (!event) return []

  const journey = buildTeamJourney(team.team_id, asMobileMatches(matches))
  const focusMatch = journey.next || [...journey.completed].reverse()[0] || null
  const focusDiv = divisionCodeFromMatch(focusMatch)
  const targets: DrawTarget[] = []

  if (event.has_waterfall) {
    targets.push({
      label: `${event.name} · Waterfall`,
      path: `/t/${tournamentId}/draws/${event.event_id}/waterfall`,
      drawType: 'waterfall',
    })
  }
  if (event.has_round_robin) {
    targets.push({
      label: `${event.name} · Round Robin`,
      path: `/t/${tournamentId}/draws/${event.event_id}/roundrobin`,
      drawType: 'round_robin',
    })
  }
  for (const div of event.divisions || []) {
    targets.push({
      label: `${event.name} · ${div.label || BRACKET_DIV_LABELS[div.code] || div.code}`,
      path: `/t/${tournamentId}/draws/${event.event_id}/bracket/${div.code}`,
      drawType: 'bracket',
      divisionCode: div.code,
      divisionLabel: div.label,
    })
  }

  if (targets.length <= 1) return targets
  if (!focusDiv) return targets

  const preferred = targets.filter(
    (target) => target.drawType === 'bracket' && target.divisionCode === focusDiv,
  )
  if (preferred.length) {
    const rest = targets.filter((target) => !preferred.includes(target))
    return [...preferred, ...rest]
  }
  return targets
}

export function drawPathWithTeamHighlight(path: string, teamId: number, openFullDraw = true): string {
  const params = new URLSearchParams()
  params.set('team', String(teamId))
  if (openFullDraw) params.set('view', 'draw')
  return `${path}?${params.toString()}`
}

export function matchResultLabel(match: ScheduleMatchItem, teamId: number): 'Win' | 'Loss' | null {
  if ((match.status || '').toUpperCase() !== 'FINAL' || match.winner_team_id == null) return null
  return match.winner_team_id === teamId ? 'Win' : 'Loss'
}

export function hubOpponentLabel(match: ScheduleMatchItem, teamId: number): string {
  return displaySideLabel(opponentName(match as MobileMatch, teamId))
}

export interface MobileMatch {
  match_id: number
  match_number: number
  match_code: string
  stage: string
  event_id: number
  event_name: string
  division_name: string | null
  day_index: number
  day_label: string
  scheduled_time: string | null
  sort_time: string | null
  court_name: string | null
  status: string
  team1_display: string
  team2_display: string
  team1_full_name: string
  team2_full_name: string
  score_display: string | null
  winner_team_id: number | null
  team_a_id: number | null
  team_b_id: number | null
}

export interface MobileTeam {
  team_id: number
  event_id: number
  event_name: string
  seed: number | null
  full_name: string
  players: string[]
  photo_version: string | null
}

export type PublicMatchStatus =
  | 'waiting'
  | 'scheduled'
  | 'in_progress'
  | 'completed'
  | 'retired'
  | 'walkover'

const STATUS_LABEL: Record<PublicMatchStatus, string> = {
  waiting: 'Waiting',
  scheduled: 'Scheduled',
  in_progress: 'In progress',
  completed: 'Completed',
  retired: 'Retired',
  walkover: 'Walkover',
}

export function publicMatchStatus(match: MobileMatch): { key: PublicMatchStatus; label: string } {
  const score = (match.score_display || '').toUpperCase()
  const status = (match.status || '').toUpperCase()
  if (status === 'FINAL' && score.includes('RET')) return { key: 'retired', label: STATUS_LABEL.retired }
  if (status === 'FINAL' && (score.includes('W/O') || score.includes('WALKOVER') || /\bWO\b/.test(score))) {
    return { key: 'walkover', label: STATUS_LABEL.walkover }
  }
  if (status === 'FINAL') return { key: 'completed', label: STATUS_LABEL.completed }
  if (status === 'IN_PROGRESS') return { key: 'in_progress', label: STATUS_LABEL.in_progress }
  if (status === 'SCHEDULED' && (match.scheduled_time || match.court_name)) {
    return { key: 'scheduled', label: STATUS_LABEL.scheduled }
  }
  return { key: 'waiting', label: STATUS_LABEL.waiting }
}

export function roundLabel(match: MobileMatch): string {
  const code = (match.match_code || '').toUpperCase()
  const waterfall = code.match(/WF_R(\d+)/)
  if (waterfall) return `Waterfall Round ${waterfall[1]}`
  if (match.stage === 'RR' || code.includes('_RR_')) return match.division_name || 'Round Robin'
  if (match.stage === 'CONS' || code.includes('_CONS_')) {
    return match.division_name ? `Consolation · ${match.division_name}` : 'Consolation'
  }
  if (match.stage === 'PLACEMENT') return match.division_name || 'Placement'
  if (code.includes('_QF_')) return 'Quarterfinals'
  if (code.includes('_SF_')) return 'Semifinals'
  if (/_F(?:_|\d|$)/.test(code)) return 'Final'
  const round = code.match(/_R(\d+)_/)
  if (round) return `Round ${round[1]}`
  if (match.stage === 'WF') return 'Waterfall'
  return match.division_name || match.stage || 'Matches'
}

export function matchesForView(
  matches: MobileMatch[],
  eventId: number,
  divisionCode?: string | null,
  divisionLabel?: string | null,
): MobileMatch[] {
  return matches.filter((match) => {
    if (match.event_id !== eventId) return false
    if (!divisionCode && !divisionLabel) return true
    const code = (divisionCode || '').toUpperCase()
    if (code && match.match_code.toUpperCase().includes(`_${code}_`)) return true
    if (divisionLabel && match.division_name && match.division_name.toLowerCase() === divisionLabel.toLowerCase()) {
      return true
    }
    return false
  })
}

export function groupMatchesByRound(matches: MobileMatch[]): { label: string; matches: MobileMatch[] }[] {
  const order: string[] = []
  const groups = new Map<string, MobileMatch[]>()
  const sorted = matches.slice().sort(compareMatches)
  for (const match of sorted) {
    const label = roundLabel(match)
    if (!groups.has(label)) {
      groups.set(label, [])
      order.push(label)
    }
    groups.get(label)!.push(match)
  }
  return order.map((label) => ({ label, matches: groups.get(label)! }))
}

export function searchPublicTeams(teams: MobileTeam[], query: string): MobileTeam[] {
  const q = query.trim().toLowerCase()
  if (q.length < 2) return []
  return teams.filter((team) => {
    const haystack = [team.full_name, team.event_name, ...team.players].join(' ').toLowerCase()
    if (haystack.includes(q)) return true
    return team.players.some((player) => player.toLowerCase().split(/\s+/).some((part) => part.startsWith(q)))
  })
}

export function compareMatches(a: MobileMatch, b: MobileMatch): number {
  if (a.day_index !== b.day_index) return a.day_index - b.day_index
  const time = (a.sort_time || '').localeCompare(b.sort_time || '')
  if (time !== 0) return time
  return a.match_id - b.match_id
}

function mentionsRole(match: MobileMatch, role: 'Winner' | 'Loser', sourceMatchId: number): boolean {
  const pattern = new RegExp(`${role} of Match #?${sourceMatchId}\\b`, 'i')
  return pattern.test(`${match.team1_full_name} ${match.team2_full_name} ${match.team1_display} ${match.team2_display}`)
}

export interface TeamJourney {
  matches: MobileMatch[]
  completed: MobileMatch[]
  upcoming: MobileMatch[]
  next: MobileMatch | null
  statusLabel: string
}

export function buildTeamJourney(teamId: number, matches: MobileMatch[]): TeamJourney {
  const direct = matches.filter((match) => match.team_a_id === teamId || match.team_b_id === teamId)
  const seen = new Set(direct.map((match) => match.match_id))
  const projected: MobileMatch[] = []
  for (const match of direct) {
    if ((match.status || '').toUpperCase() !== 'FINAL' || match.winner_team_id == null) continue
    const role = match.winner_team_id === teamId ? 'Winner' : 'Loser'
    for (const candidate of matches) {
      if (seen.has(candidate.match_id)) continue
      if (!mentionsRole(candidate, role, match.match_id)) continue
      seen.add(candidate.match_id)
      projected.push(candidate)
    }
  }
  const ordered = [...direct, ...projected].sort(compareMatches)
  const completed = ordered.filter((match) => (match.status || '').toUpperCase() === 'FINAL')
  const upcoming = ordered.filter((match) => (match.status || '').toUpperCase() !== 'FINAL')
  const next = upcoming[0] || null
  return {
    matches: ordered,
    completed,
    upcoming,
    next,
    statusLabel: next ? 'Next match' : ordered.length ? 'Draw complete' : 'No matches yet',
  }
}

export function opponentName(match: MobileMatch, teamId: number | null, options?: { keepPoolSeeds?: boolean }): string {
  if (teamId != null && match.team_a_id === teamId) return displaySideLabel(match.team2_full_name, options)
  if (teamId != null && match.team_b_id === teamId) return displaySideLabel(match.team1_full_name, options)
  const known = [match.team1_full_name, match.team2_full_name]
    .map((name) => displaySideLabel(name, options))
    .filter((name) => name !== 'Opponent TBD')
  return known[0] || 'Opponent TBD'
}

export function shortPlayerName(value: string): string {
  return value
    .trim()
    .replace(/,\s*[^,]+,\s*[A-Z]{2}\s*$/i, '')
    .replace(/\s+-\s+[A-Z]{2}\s*$/i, '')
    .trim()
}

export function rosterNames(team: Pick<MobileTeam, 'full_name' | 'players'>): string[] {
  const named = (team.players || []).map(shortPlayerName).filter(Boolean).slice(0, 2)
  if (named.length) return named
  return shortPlayerName(team.full_name).split(/\s*\/\s*|\s+&\s+/).map((part) => part.trim()).filter(Boolean).slice(0, 2)
}

export function displaySideLabel(name: string | null | undefined, options?: { keepPoolSeeds?: boolean }): string {
  const labeled = publicSideLabel(name, { hideSeeds: !options?.keepPoolSeeds })
  if (!/[/,]/.test(labeled) || /^(Winner|Loser|Opponent|Pool|Seed|Cons)\b/i.test(labeled)) return labeled
  return labeled.split(/\s*\/\s*/).map((part) => shortPlayerName(part)).filter(Boolean).join(' / ')
}

export function publicSideLabel(name: string | null | undefined, options?: { hideSeeds?: boolean }): string {
  const value = (name || '').trim()
  if (!value || /^tbd$/i.test(value)) return 'Opponent TBD'
  const seed = value.match(/^(?:cons\s+)?seed[_\s-]*(\d+)$/i)
  if (seed) {
    if (options?.hideSeeds) return 'Opponent TBD'
    return /^cons\b/i.test(value) ? `Cons Seed ${seed[1]}` : `Seed ${seed[1]}`
  }
  const short = value.match(/^([WL])\(R(\d+)_\d+\)$/i)
  if (short) return `${short[1].toUpperCase() === 'W' ? 'Winner' : 'Loser'} of Round ${short[2]}`
  const waterfall = value.match(/WF_R(\d+)_([WL])\d+/i)
  if (waterfall) {
    const role = waterfall[2].toUpperCase() === 'W' ? 'Winner' : 'Loser'
    return `${role} of Waterfall Round ${waterfall[1]}`
  }
  const division = value.match(/_(BWW|BWL|BLW|BLL)_/i)
  const divisionName = division
    ? { BWW: 'Division I', BWL: 'Division II', BLW: 'Division III', BLL: 'Division IV' }[division[1].toUpperCase()]
    : null
  if (/^winner:/i.test(value)) return divisionName ? `Winner of ${divisionName}` : 'Winner of an earlier match'
  if (/^loser:/i.test(value)) return divisionName ? `Loser of ${divisionName}` : 'Loser of an earlier match'
  if (!/\s/.test(value) && (value.match(/_/g) || []).length >= 2) return 'Opponent TBD'
  return value
}

export function winnerName(match: MobileMatch, teams: Map<number, MobileTeam>): string | null {
  if ((match.status || '').toUpperCase() !== 'FINAL' || match.winner_team_id == null) return null
  const team = teams.get(match.winner_team_id)
  if (team) return team.full_name
  if (match.winner_team_id === match.team_a_id) return match.team1_full_name
  if (match.winner_team_id === match.team_b_id) return match.team2_full_name
  return null
}

export function courtText(match: MobileMatch, showCourtInfo: boolean): string | null {
  if (!showCourtInfo) return null
  return match.court_name || 'Court TBD'
}

export function timeText(match: MobileMatch): string {
  return match.scheduled_time || 'Time TBD'
}

export function teamInitials(name: string): string {
  const players = name.split(/\s*\/\s*|\s*&\s*/).map((part) => shortPlayerName(part)).filter(Boolean).slice(0, 2)
  const letters = players.map((player) => player.charAt(0).toUpperCase()).join('')
  return letters || '•'
}

export const TOWEL_WARNING_CODE = 'missing_towel_color'
export const WKW_WARNING_CODE = 'missing_who_knows_who'

export const WARNING_CODES = new Set([TOWEL_WARNING_CODE, WKW_WARNING_CODE])

/** Current RW-OS import never blocks on validation issues. Reserved for genuine blockers. */
export const BLOCKING_CODES = new Set<string>()

const EMPTY_PLACEHOLDERS = new Set(['', '—', '-', '–', 'n/a', 'na', 'none', 'unassigned'])

export type RwOsValidationIssue = {
  code: string
  message: string
  team_key?: string | null
  teamKey?: string | null
  draw_kind?: string | null
}

export type RwOsReadinessPlayer = {
  name?: string | null
  towelColor?: string | null
  towel_color?: string | null
}

export type RwOsReadinessTeam = {
  teamKey?: string | null
  team_key?: string | null
  displayName?: string | null
  display_name?: string | null
  fullName?: string | null
  full_name?: string | null
  player1?: RwOsReadinessPlayer | null
  player2?: RwOsReadinessPlayer | null
}

export type ImportReadinessDetail = {
  teamKey: string | null
  teamName: string
  player: string | null
  issue: string
  code: string
}

export type ImportReadinessGroup = {
  code: string
  summary: string
  count: number
  unit: 'player' | 'team' | 'issue'
  severity: 'warning' | 'problem' | 'blocking'
  details: ImportReadinessDetail[]
}

export type ImportReadiness = {
  warnings: ImportReadinessGroup[]
  problems: ImportReadinessGroup[]
  blocking: ImportReadinessGroup[]
  canProceed: boolean
  details: ImportReadinessDetail[]
}

function presentText(raw: unknown): string | null {
  const value = String(raw ?? '').trim()
  if (!value || EMPTY_PLACEHOLDERS.has(value.toLowerCase())) return null
  return value
}

export function issueTeamKey(issue: RwOsValidationIssue): string | null {
  return presentText(issue.teamKey) || presentText(issue.team_key)
}

export function teamLookupKey(team: RwOsReadinessTeam): string | null {
  return presentText(team.teamKey) || presentText(team.team_key)
}

export function teamDisplayName(team: RwOsReadinessTeam | undefined, fallbackKey: string | null): string {
  if (!team) return fallbackKey || 'Unknown team'
  const named =
    presentText(team.displayName) ||
    presentText(team.display_name) ||
    presentText(team.fullName) ||
    presentText(team.full_name)
  if (named) return named
  const p1 = presentText(team.player1?.name)
  const p2 = presentText(team.player2?.name)
  if (p1 || p2) return [p1, p2].filter(Boolean).join(' / ')
  return fallbackKey || 'Unknown team'
}

function playerMissingTowel(player: RwOsReadinessPlayer | null | undefined): boolean {
  if (!player) return true
  return !presentText(player.towelColor) && !presentText(player.towel_color)
}

function playerName(player: RwOsReadinessPlayer | null | undefined, fallback: string): string {
  return presentText(player?.name) || fallback
}

function findTeam(teams: RwOsReadinessTeam[], key: string | null): RwOsReadinessTeam | undefined {
  if (!key) return undefined
  return teams.find((team) => teamLookupKey(team) === key)
}

function countLabel(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`
}

function towelDetails(issues: RwOsValidationIssue[], teams: RwOsReadinessTeam[]): ImportReadinessDetail[] {
  const details: ImportReadinessDetail[] = []
  for (const issue of issues) {
    const key = issueTeamKey(issue)
    const team = findTeam(teams, key)
    const teamName = teamDisplayName(team, key)
    const players: Array<{ player: RwOsReadinessPlayer | null | undefined; label: string }> = [
      { player: team?.player1, label: 'Player 1' },
      { player: team?.player2, label: 'Player 2' },
    ]
    const missing = players.filter(({ player }) => playerMissingTowel(player))
    if (!team || missing.length === 0) {
      details.push({
        teamKey: key,
        teamName,
        player: null,
        issue: 'Missing towel color',
        code: TOWEL_WARNING_CODE,
      })
      continue
    }
    for (const row of missing) {
      details.push({
        teamKey: key,
        teamName,
        player: playerName(row.player, row.label),
        issue: 'Missing towel color',
        code: TOWEL_WARNING_CODE,
      })
    }
  }
  return details
}

function teamIssueDetails(
  issues: RwOsValidationIssue[],
  teams: RwOsReadinessTeam[],
  issueLabel: string,
): ImportReadinessDetail[] {
  const seen = new Set<string>()
  const details: ImportReadinessDetail[] = []
  for (const issue of issues) {
    const key = issueTeamKey(issue)
    const unique = `${issue.code}:${key || details.length}`
    if (seen.has(unique)) continue
    seen.add(unique)
    details.push({
      teamKey: key,
      teamName: teamDisplayName(findTeam(teams, key), key),
      player: null,
      issue: issueLabel,
      code: issue.code,
    })
  }
  return details
}

function genericDetails(issues: RwOsValidationIssue[], teams: RwOsReadinessTeam[]): ImportReadinessDetail[] {
  return issues.map((issue) => {
    const key = issueTeamKey(issue)
    return {
      teamKey: key,
      teamName: teamDisplayName(findTeam(teams, key), key),
      player: null,
      issue: issue.message,
      code: issue.code,
    }
  })
}

function groupFromDetails(
  code: string,
  summary: string,
  unit: ImportReadinessGroup['unit'],
  severity: ImportReadinessGroup['severity'],
  details: ImportReadinessDetail[],
): ImportReadinessGroup {
  return { code, summary, count: details.length, unit, severity, details }
}

export function aggregateImportReadiness(
  issues: RwOsValidationIssue[] | undefined,
  teams: RwOsReadinessTeam[] | undefined = [],
): ImportReadiness {
  const allIssues = issues || []
  const roster = teams || []
  const byCode = new Map<string, RwOsValidationIssue[]>()
  for (const issue of allIssues) {
    const list = byCode.get(issue.code) || []
    list.push(issue)
    byCode.set(issue.code, list)
  }

  const warnings: ImportReadinessGroup[] = []
  const problems: ImportReadinessGroup[] = []
  const blocking: ImportReadinessGroup[] = []

  const towelIssues = byCode.get(TOWEL_WARNING_CODE) || []
  if (towelIssues.length) {
    const details = towelDetails(towelIssues, roster)
    warnings.push(
      groupFromDetails(
        TOWEL_WARNING_CODE,
        `${countLabel(details.length, 'player', 'players')} missing towel color`,
        'player',
        'warning',
        details,
      ),
    )
    byCode.delete(TOWEL_WARNING_CODE)
  }

  const wkwIssues = byCode.get(WKW_WARNING_CODE) || []
  if (wkwIssues.length) {
    const details = teamIssueDetails(wkwIssues, roster, 'Missing Who Knows Who / Avoid Group')
    warnings.push(
      groupFromDetails(
        WKW_WARNING_CODE,
        `${countLabel(details.length, 'team', 'teams')} missing Who Knows Who / Avoid Group`,
        'team',
        'warning',
        details,
      ),
    )
    byCode.delete(WKW_WARNING_CODE)
  }

  for (const [code, codeIssues] of byCode) {
    const details = genericDetails(codeIssues, roster)
    const uniqueTeams = new Set(details.map((detail) => detail.teamKey).filter(Boolean))
    const count = uniqueTeams.size || details.length
    const unit: ImportReadinessGroup['unit'] = uniqueTeams.size ? 'team' : 'issue'
    const summary = `${countLabel(count, unit, `${unit}s`)}: ${codeIssues[0]?.message || code}`
    const group = groupFromDetails(
      code,
      summary,
      unit,
      BLOCKING_CODES.has(code) ? 'blocking' : 'problem',
      details,
    )
    if (group.severity === 'blocking') blocking.push(group)
    else problems.push(group)
  }

  const details = [...blocking, ...warnings, ...problems].flatMap((group) => group.details)
  return {
    warnings,
    problems,
    blocking,
    canProceed: blocking.length === 0,
    details,
  }
}

export function repeatedWarningMessages(issues: RwOsValidationIssue[] | undefined): string[] {
  const messages = (issues || []).map((issue) => issue.message)
  return messages.filter((message, index) => messages.indexOf(message) !== index)
}

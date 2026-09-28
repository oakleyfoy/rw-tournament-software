/** Mirrors backend team_is_active: withdrawn, cancelled, and defaulted teams are not active. */
export function isActiveTeam(team: { is_defaulted?: boolean | null }): boolean {
  return !team.is_defaulted
}

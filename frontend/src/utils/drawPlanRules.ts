/**
 * Draw Plan Rules — Phase 1 Allowed Matrix (Single Source of Truth)
 * 
 * This file mirrors backend/app/services/draw_plan_rules.py
 * All Phase 1 validation rules must match between frontend and backend.
 */

// Template families
export type TemplateFamily = 'RR_ONLY' | 'WF_TO_POOLS_DYNAMIC' | 'WF_TO_BRACKETS_8';

// Allowed team counts per family
export const ALLOWED_TEAM_COUNTS: Record<TemplateFamily, readonly number[]> = {
  RR_ONLY: [4, 6],
  WF_TO_POOLS_DYNAMIC: [8, 10, 12, 16, 20, 24, 28],
  WF_TO_BRACKETS_8: [32],
} as const;

// All Phase 1 supported team counts (union of all families)
export const PHASE1_SUPPORTED_TEAM_COUNTS = [
  ...ALLOWED_TEAM_COUNTS.RR_ONLY,
  ...ALLOWED_TEAM_COUNTS.WF_TO_POOLS_DYNAMIC,
  ...ALLOWED_TEAM_COUNTS.WF_TO_BRACKETS_8,
] as const;

// Unsupported in Phase 1 (Phase 2 candidates)
export const PHASE2_TEAM_COUNTS = [14, 18, 22, 26, 30] as const;

/**
 * Return the required number of waterfall rounds for a given family and team count.
 */
export function requiredWfRounds(family: TemplateFamily, teamCount: number): number {
  switch (family) {
    case 'RR_ONLY':
      return 0;
    case 'WF_TO_POOLS_DYNAMIC':
      return teamCount === 8 || teamCount === 10 ? 1 : 2;
    case 'WF_TO_BRACKETS_8':
      return 2;
    default:
      return 0;
  }
}

/**
 * Return (poolsCount, teamsPerPool) for WF_TO_POOLS_DYNAMIC.
 */
export function poolConfig(teamCount: number): [number, number] {
  if (teamCount === 10) {
    return [2, 5]; // 2 pools of 5
  }
  return [teamCount / 4, 4]; // n/4 pools of 4
}

/**
 * Return the valid template family for a given team count, or null if unsupported.
 */
export function getValidFamilyForTeamCount(teamCount: number): TemplateFamily | null {
  if (ALLOWED_TEAM_COUNTS.WF_TO_BRACKETS_8.includes(teamCount)) {
    return 'WF_TO_BRACKETS_8';
  }
  if (ALLOWED_TEAM_COUNTS.WF_TO_POOLS_DYNAMIC.includes(teamCount)) {
    return 'WF_TO_POOLS_DYNAMIC';
  }
  if (ALLOWED_TEAM_COUNTS.RR_ONLY.includes(teamCount)) {
    return 'RR_ONLY';
  }
  return null;
}

/**
 * Check if a team count is valid for a given family.
 */
export function isTeamCountValidForFamily(family: TemplateFamily, teamCount: number): boolean {
  return ALLOWED_TEAM_COUNTS[family]?.includes(teamCount) ?? false;
}

/**
 * Validate a template configuration.
 * Returns null if valid, or an error message string if invalid.
 */
export function validateTemplateConfig(
  templateKey: string,
  teamCount: number,
  wfRounds: number
): string | null {
  const key = templateKey.trim().toUpperCase().replace(/ /g, '_');
  
  // Check if this is a known family
  if (!(key in ALLOWED_TEAM_COUNTS)) {
    // Check for legacy templates
    if (key === 'WF_TO_POOLS_4') {
      if (teamCount !== 16) {
        return `WF_TO_POOLS_4 requires exactly 16 teams, got ${teamCount}`;
      }
      if (wfRounds !== 2) {
        return `WF_TO_POOLS_4 requires 2 waterfall rounds, got ${wfRounds}`;
      }
      return null;
    }
    return `Unknown template: ${templateKey}`;
  }
  
  const family = key as TemplateFamily;
  
  // Validate team count
  if (!isTeamCountValidForFamily(family, teamCount)) {
    const allowed = ALLOWED_TEAM_COUNTS[family].join(',');
    return `${family} requires team_count in {${allowed}}, got ${teamCount}`;
  }
  
  // Validate waterfall rounds
  const expectedWf = requiredWfRounds(family, teamCount);
  if (wfRounds !== expectedWf) {
    return `${family} with ${teamCount} teams requires waterfall_rounds=${expectedWf}, got ${wfRounds}`;
  }
  
  return null;
}

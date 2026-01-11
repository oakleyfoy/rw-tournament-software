// Draw estimation utilities for Phase 2

export type TemplateType = 'RR_ONLY' | 'WF_TO_POOLS_4' | 'CANONICAL_32' | 'SPLIT_FLIGHTS';

export interface DrawPlan {
  version: string;
  template_type: TemplateType;
  wf_rounds?: number;
  post_wf?: string;
  pool_assignment?: string;
  natural_flow?: boolean;
  timing?: {
    wf_block_minutes: number;
    standard_block_minutes: number;
  };
  cadence_hint?: {
    preferred: { fri: number; sat: number; sun: number };
    fallback: { fri: number; sat: number; sun: number };
  };
  flights?: Array<{
    size: number;
    template_type: TemplateType;
    wf_rounds?: number;
  }>;
}

export interface ScheduleProfile {
  preferred: { fri: number; sat: number; sun: number };
  fallback: { fri: number; sat: number; sun: number };
}

// Match count helpers (even-only; if odd throw)
export function rrMatches(n: number): number {
  if (n % 2 !== 0) {
    throw new Error(`rrMatches: n must be even, got ${n}`);
  }
  return (n * (n - 1)) / 2;
}

export function wfRoundMatches(n: number): number {
  if (n % 2 !== 0) {
    throw new Error(`wfRoundMatches: n must be even, got ${n}`);
  }
  return n / 2;
}

// Template match count calculations
export interface MatchCounts {
  wfMatches: number;
  standardMatches: number;
  standardMatchesFor4?: number; // For CANONICAL_32 and WF_TO_POOLS_4
  standardMatchesFor5?: number; // For CANONICAL_32 and WF_TO_POOLS_4
}

export function calculateMatches(
  templateType: TemplateType,
  teamCount: number,
  wfRounds: number = 0
): MatchCounts {
  if (teamCount % 2 !== 0) {
    throw new Error(`calculateMatches: teamCount must be even, got ${teamCount}`);
  }

  switch (templateType) {
    case 'RR_ONLY':
      return {
        wfMatches: 0,
        standardMatches: rrMatches(teamCount),
      };

    case 'WF_TO_POOLS_4':
      if (teamCount % 4 !== 0) {
        throw new Error(`WF_TO_POOLS_4 requires teamCount divisible by 4, got ${teamCount}`);
      }
      const wfMatches = wfRoundMatches(teamCount) * wfRounds;
      const pools = teamCount / 4;
      const matchesPerPool = rrMatches(4); // rrMatches(4) = 6 matches per pool (full round robin)
      // Guarantee calculation:
      // - With wfRounds waterfall matches, each team has wfRounds matches
      // - Guarantee 4: Need (4 - wfRounds) more matches per team
      // - Guarantee 5: Need (5 - wfRounds) more matches per team
      // In a pool of 4, a full round robin gives 3 matches per team (6 matches total)
      // For partial round robin: 4 matches per pool gives 2 matches per team
      const matchesNeededFor4 = 4 - wfRounds; // Additional matches needed per team for guarantee 4
      const matchesNeededFor5 = 5 - wfRounds; // Additional matches needed per team for guarantee 5
      
      // Calculate matches per pool based on matches needed per team
      // If need 2 matches per team: 4 matches per pool (partial round robin)
      // If need 3 matches per team: 6 matches per pool (full round robin)
      // If need 4 matches per team: 6 matches per pool (full round robin, can't exceed pool size)
      const matchesPerPoolFor4 = matchesNeededFor4 === 2 ? 4 : (matchesNeededFor4 >= 3 ? 6 : 0);
      const matchesPerPoolFor5 = matchesNeededFor5 === 2 ? 4 : (matchesNeededFor5 >= 3 ? 6 : 0);
      
      const matchesForGuarantee4 = pools * matchesPerPoolFor4;
      const matchesForGuarantee5 = pools * matchesPerPoolFor5;
      return {
        wfMatches,
        standardMatches: matchesForGuarantee5, // Default (for backwards compatibility)
        standardMatchesFor4: matchesForGuarantee4,
        standardMatchesFor5: matchesForGuarantee5,
      };

    case 'CANONICAL_32':
      if (teamCount !== 32) {
        throw new Error(`CANONICAL_32 requires teamCount=32, got ${teamCount}`);
      }
      if (wfRounds !== 2) {
        throw new Error(`CANONICAL_32 requires wfRounds=2, got ${wfRounds}`);
      }
      return {
        wfMatches: wfRoundMatches(32) * 2, // 32 matches
        standardMatches: 36, // Default for guarantee 4
        standardMatchesFor4: 36, // 4 brackets * 9 matches
        standardMatchesFor5: 48, // 4 brackets * 12 matches
      };

    case 'SPLIT_FLIGHTS':
      // This will be handled by summing across flights
      return {
        wfMatches: 0,
        standardMatches: 0,
      };

    default:
      throw new Error(`Unknown template type: ${templateType}`);
  }
}

// Calculate minutes required
export function calculateMinutesRequired(
  matchCounts: MatchCounts,
  waterfallBlockMinutes: number,
  standardBlockMinutes: number,
  guarantee: 4 | 5
): number {
  const wfMinutes = matchCounts.wfMatches * waterfallBlockMinutes;
  let standardMatches: number;
  
  if (matchCounts.standardMatchesFor4 && matchCounts.standardMatchesFor5) {
    // CANONICAL_32 or WF_TO_POOLS_4 case (guarantee-aware)
    standardMatches = guarantee === 5 ? matchCounts.standardMatchesFor5 : matchCounts.standardMatchesFor4;
  } else {
    standardMatches = matchCounts.standardMatches;
  }
  
  const standardMinutes = standardMatches * standardBlockMinutes;
  return wfMinutes + standardMinutes;
}

// Determine guarantee (5 if fits, else 4 if fits, else null)
export function determineGuarantee(
  matchCounts: MatchCounts,
  waterfallBlockMinutes: number,
  standardBlockMinutes: number,
  totalCourtMinutes: number
): 4 | 5 | null {
  // Try guarantee 5
  const minutesFor5 = calculateMinutesRequired(matchCounts, waterfallBlockMinutes, standardBlockMinutes, 5);
  if (minutesFor5 <= totalCourtMinutes) {
    return 5;
  }
  
  // Try guarantee 4
  const minutesFor4 = calculateMinutesRequired(matchCounts, waterfallBlockMinutes, standardBlockMinutes, 4);
  if (minutesFor4 <= totalCourtMinutes) {
    return 4;
  }
  
  return null;
}


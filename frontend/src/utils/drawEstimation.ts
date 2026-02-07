// Draw estimation utilities for Phase 2

export type TemplateType = 'RR_ONLY' | 'WF_TO_POOLS_4' | 'WF_TO_POOLS_DYNAMIC' | 'WF_TO_BRACKETS_8' | 'CANONICAL_32' | 'SPLIT_FLIGHTS';

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
  estimationError?: string; // Set when template is unknown/unsupported
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

    case 'WF_TO_POOLS_DYNAMIC': {
      // WF_TO_POOLS_DYNAMIC: Phase 1 template for 8,10,12,16,20,24,28 teams
      // Pools: n==10 -> 2 pools of 5, else n/4 pools of 4
      // WF rounds: 1 for 8/10 teams, 2 for 12+ teams
      const wfMatchesDynamic = wfRoundMatches(teamCount) * wfRounds;
      
      let poolCount: number;
      let rrMatchesPerPool: number;
      
      if (teamCount === 10) {
        poolCount = 2;
        rrMatchesPerPool = (5 * 4) / 2; // 10 matches per pool of 5
      } else {
        poolCount = teamCount / 4;
        rrMatchesPerPool = (4 * 3) / 2; // 6 matches per pool of 4
      }
      
      const totalRrMatches = poolCount * rrMatchesPerPool;
      
      return {
        wfMatches: wfMatchesDynamic,
        standardMatches: totalRrMatches,
      };
    }

    case 'CANONICAL_32':
      // Safe fallback: if teamCount !== 32, use deterministic rules instead of crashing
      if (teamCount !== 32) {
        console.warn(
          `[drawEstimation] CANONICAL_32 mismatch: expected 32 teams, got ${teamCount}. Falling back to 8-team rules.`
        );

        if (teamCount < 8) {
          // Round robin: N*(N-1)/2 matches
          return {
            wfMatches: 0,
            standardMatches: (teamCount * (teamCount - 1)) / 2,
          };
        }

        // 8-team bracket baseline (product invariant: bracket size is always 8)
        // Main bracket: QF(4) + SF(2) + F(1) = 7
        // Guarantee 4: 7 + 2 consolation = 9 matches
        // Guarantee 5: 7 + 5 consolation = 12 matches
        return {
          wfMatches: 0,
          standardMatches: 9, // Default for guarantee 4
          standardMatchesFor4: 9,
          standardMatchesFor5: 12,
        };
      }

      if (wfRounds !== 2) {
        console.warn(
          `[drawEstimation] CANONICAL_32 wfRounds mismatch: expected 2, got ${wfRounds}. Using provided value.`
        );
      }

      return {
        wfMatches: wfRoundMatches(32) * wfRounds, // Use actual wfRounds instead of hardcoded 2
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

    case 'WF_TO_BRACKETS_8': {
      // WF_TO_BRACKETS_8: 8, 12, 16, or 32 teams. Brackets of 8.
      // Bracket per 8-team: G4=9, G5=12
      const bracketCount =
        teamCount === 8 ? 1 : teamCount === 12 || teamCount === 16 ? 2 : teamCount === 32 ? 4 : 1
      const bracketG4 = 9
      const bracketG5 = 12
      const standardFor4 = bracketCount * bracketG4
      const standardFor5 = bracketCount * bracketG5
      const wfMatchesBrackets = wfRoundMatches(teamCount) * (wfRounds || 0)
      return {
        wfMatches: wfMatchesBrackets,
        standardMatches: standardFor5, // Default for guarantee 5
        standardMatchesFor4: standardFor4,
        standardMatchesFor5: standardFor5,
      }
    }

    default:
      // For unknown templates, return zeros with error flag for UI to surface
      console.warn(`[drawEstimation] Unknown template type: ${templateType}`);
      return {
        wfMatches: 0,
        standardMatches: 0,
        estimationError: `Unsupported template type: ${templateType}`,
      };
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


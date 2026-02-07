import { useMemo } from 'react';
import { GridMatch, TeamInfo } from '../../../../api/client';
import { DraggableMatch } from './DraggableMatch';

// Stage precedence mapping (matches scheduler ordering)
const STAGE_PRECEDENCE: Record<string, number> = {
  WF: 1,
  MAIN: 2,
  CONSOLATION: 3,
  PLACEMENT: 4,
};

// Sort matches: event category (Women's first) → stage → round → sequence → id
// Order: Women's WF → Mixed WF → Women's MAIN → Mixed MAIN → etc.
function getMatchSortKey(match: GridMatch): [number, number, number, number, number] {
  // Determine event category from match_code prefix (WOM_WOM = womens, MIX_MIX = mixed)
  // Women's = 1, Mixed = 2 (Women's comes first)
  let eventCategoryOrder = 999;
  if (match.match_code) {
    const prefix = match.match_code.substring(0, 7).toUpperCase();
    if (prefix.startsWith('WOM_')) {
      eventCategoryOrder = 1; // Women's first
    } else if (prefix.startsWith('MIX_')) {
      eventCategoryOrder = 2; // Mixed second
    }
  }
  
  const stageOrder = STAGE_PRECEDENCE[match.stage] || 999;
  const roundIndex = match.round_index ?? 999;
  const sequenceInRound = match.sequence_in_round ?? 999;
  const matchId = match.match_id ?? 999;
  return [eventCategoryOrder, stageOrder, roundIndex, sequenceInRound, matchId];
}

interface MatchQueuePanelProps {
  unassignedMatches: GridMatch[];
  teams: TeamInfo[];
  loading: boolean;
  isFinal: boolean;
  isPatchingMatchId: number | null;
}

export function MatchQueuePanel({
  unassignedMatches,
  teams: _teams,
  loading,
  isFinal,
  isPatchingMatchId,
}: MatchQueuePanelProps) {
  // Defensive: ensure arrays are never undefined
  const safeUnassigned = unassignedMatches || [];

  // Sort unassigned matches in scheduler order (stage → round → sequence → id)
  const sortedUnassigned = useMemo(() => {
    return [...safeUnassigned].sort((a, b) => {
      const keyA = getMatchSortKey(a);
      const keyB = getMatchSortKey(b);
      for (let i = 0; i < keyA.length; i++) {
        if (keyA[i] !== keyB[i]) {
          return keyA[i] - keyB[i];
        }
      }
      return 0;
    });
  }, [safeUnassigned]);

  if (loading) {
    return (
      <div className="match-queue-panel">
        <h2>Match Queue</h2>
        <div className="loading">Loading matches...</div>
      </div>
    );
  }

  return (
    <div className="match-queue-panel">
      <h2>Unassigned Matches ({sortedUnassigned.length})</h2>
      
      {sortedUnassigned.length === 0 ? (
        <div style={{ color: '#666', fontSize: '13px', textAlign: 'center', padding: '20px' }}>
          ✅ All matches assigned
        </div>
      ) : (
        <div style={{ marginBottom: '16px' }}>
          {sortedUnassigned.map((match) => (
            <DraggableMatch
              key={match.match_id}
              matchId={match.match_id}
              match={match}
              isFinal={isFinal}
              isPatching={isPatchingMatchId === match.match_id}
            />
          ))}
        </div>
      )}

      <div style={{ borderTop: '1px solid #ddd', paddingTop: '12px', marginTop: '12px' }}>
        <div style={{ fontSize: '12px', color: '#666' }}>
          <div style={{ marginBottom: '6px' }}>
            <strong>Tip:</strong> Drag matches from here to empty slots in the grid to assign them.
          </div>
          <div>
            Drag assigned matches in the grid to move them to different slots.
          </div>
        </div>
      </div>
    </div>
  );
}


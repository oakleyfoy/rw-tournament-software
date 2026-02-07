import { ConflictReportV1 } from '../../../../api/client';

interface ConflictsPanelProps {
  conflicts: ConflictReportV1 | null;
  loading: boolean;
  onRefresh: () => void;
}

export function ConflictsPanel({ conflicts, loading, onRefresh }: ConflictsPanelProps) {
  if (loading) {
    return (
      <div className="conflicts-panel">
        <h2>Conflicts & Diagnostics</h2>
        <div className="loading">Loading conflicts...</div>
      </div>
    );
  }

  if (!conflicts) {
    return (
      <div className="conflicts-panel">
        <h2>Conflicts & Diagnostics</h2>
        <div style={{ color: '#666', fontSize: '13px' }}>No conflict data available</div>
      </div>
    );
  }

  // Defensive: ensure all expected properties exist
  const summary = conflicts.summary || {
    total_slots: 0,
    total_matches: 0,
    assigned_matches: 0,
    unassigned_matches: 0,
    assignment_rate: 0,
  };
  const unassigned_matches = conflicts.unassigned_matches || [];
  const slot_pressure = conflicts.slot_pressure || [];
  const ordering_integrity = conflicts.ordering_integrity || { 
    violations_detected: 0, 
    violations: [] 
  };
  const team_conflicts = conflicts.team_conflicts || {
    known_team_conflicts_count: 0,
    unknown_team_matches_count: 0,
    conflicts: [],
  };

  return (
    <div className="conflicts-panel">
      <h2>Conflicts & Diagnostics</h2>

      {/* Summary */}
      <div className="conflicts-summary">
        <div className="conflicts-summary-row">
          <span>Total Slots:</span>
          <strong>{summary.total_slots}</strong>
        </div>
        <div className="conflicts-summary-row">
          <span>Total Matches:</span>
          <strong>{summary.total_matches}</strong>
        </div>
        <div className="conflicts-summary-row">
          <span>Assigned:</span>
          <strong style={{ color: '#4caf50' }}>{summary.assigned_matches}</strong>
        </div>
        <div className="conflicts-summary-row">
          <span>Unassigned:</span>
          <strong style={{ color: summary.unassigned_matches > 0 ? '#ff9800' : '#4caf50' }}>
            {summary.unassigned_matches}
          </strong>
        </div>
        <div className="conflicts-summary-row">
          <span>Assignment Rate:</span>
          <strong>{(summary.assignment_rate * 100).toFixed(1)}%</strong>
        </div>
      </div>

      {/* Unassigned Matches */}
      {unassigned_matches.length > 0 && (
        <div className="conflicts-section">
          <h3>⚠️ Unassigned Matches ({unassigned_matches.length})</h3>
          <ul className="unassigned-list">
            {unassigned_matches.slice(0, 10).map((match) => (
              <li key={match.match_id}>
                <strong>{match.match_code}</strong> - {match.stage} R{match.round_index} (
                {match.duration_minutes}m)
              </li>
            ))}
            {unassigned_matches.length > 10 && (
              <li style={{ background: '#f5f5f5', color: '#666' }}>
                ...and {unassigned_matches.length - 10} more
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Team Overlap Conflicts */}
      {team_conflicts.known_team_conflicts_count > 0 && (
        <div className="conflicts-section">
          <h3 style={{ color: '#d32f2f' }}>🚨 Team Overlap Conflicts ({team_conflicts.known_team_conflicts_count})</h3>
          <div style={{ fontSize: '12px', color: '#d32f2f', marginBottom: '8px' }}>
            Same team scheduled in overlapping time slots
          </div>
          <ul className="unassigned-list">
            {team_conflicts.conflicts.slice(0, 5).map((c, idx) => (
              <li key={idx} style={{ background: '#ffebee', borderColor: '#ef5350' }}>
                <div>
                  <strong>{c.match_code}</strong> vs <strong>{c.conflicting_match_code}</strong>
                </div>
                <div style={{ fontSize: '11px', color: '#c62828' }}>
                  Team {c.team_id} overlaps
                </div>
              </li>
            ))}
            {team_conflicts.conflicts.length > 5 && (
              <li style={{ background: '#f5f5f5', color: '#666' }}>
                ...and {team_conflicts.conflicts.length - 5} more
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Unknown Team Matches Info */}
      {team_conflicts.unknown_team_matches_count > 0 && (
        <div style={{
          background: '#fff3e0',
          border: '1px solid #ffb74d',
          borderRadius: '4px',
          padding: '8px 12px',
          marginBottom: '12px',
          fontSize: '12px',
          color: '#e65100',
        }}>
          ⚠️ {team_conflicts.unknown_team_matches_count} matches pending team assignment.
          Team conflicts will be fully validated once teams are determined.
        </div>
      )}

      {/* Ordering Violations */}
      {ordering_integrity.violations_detected > 0 && (
        <div className="conflicts-section">
          <h3>🔀 Ordering Violations ({ordering_integrity.violations_detected})</h3>
          <ul className="unassigned-list">
            {ordering_integrity.violations.slice(0, 5).map((v, idx) => (
              <li key={idx} style={{ background: '#ffebee', borderColor: '#ef5350' }}>
                <div>
                  <strong>{v.earlier_match_code}</strong> @ {v.earlier_slot_time}
                </div>
                <div style={{ fontSize: '11px', color: '#c62828' }}>
                  should be before
                </div>
                <div>
                  <strong>{v.later_match_code}</strong> @ {v.later_slot_time}
                </div>
                <div style={{ fontSize: '10px', color: '#666', marginTop: '4px' }}>
                  {v.reason}
                </div>
              </li>
            ))}
            {ordering_integrity.violations.length > 5 && (
              <li style={{ background: '#f5f5f5', color: '#666' }}>
                ...and {ordering_integrity.violations.length - 5} more
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Slot Pressure */}
      {slot_pressure.length > 0 && (
        <div className="conflicts-section">
          <h3>⏰ Slot Pressure</h3>
          <div style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>
            Slots with unusual assignment counts
          </div>
          <ul className="unassigned-list">
            {slot_pressure.slice(0, 5).map((sp) => (
              <li key={sp.slot_id} style={{ background: '#fff3e0', borderColor: '#ffb74d' }}>
                <strong>
                  {sp.court_label} @ {sp.start_time}
                </strong>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  {sp.match_count} match{sp.match_count !== 1 ? 'es' : ''} assigned
                </div>
              </li>
            ))}
            {slot_pressure.length > 5 && (
              <li style={{ background: '#f5f5f5', color: '#666' }}>
                ...and {slot_pressure.length - 5} more
              </li>
            )}
          </ul>
        </div>
      )}

      {/* All Clear Message */}
      {unassigned_matches.length === 0 &&
        ordering_integrity.violations_detected === 0 &&
        slot_pressure.length === 0 &&
        team_conflicts.known_team_conflicts_count === 0 && (
          <div
            style={{
              background: '#e8f5e9',
              border: '1px solid #a5d6a7',
              borderRadius: '4px',
              padding: '16px',
              textAlign: 'center',
              color: '#2e7d32',
              fontSize: '14px',
            }}
          >
            ✅ No conflicts detected
            {team_conflicts.unknown_team_matches_count > 0 && (
              <div style={{ fontSize: '11px', color: '#666', marginTop: '4px' }}>
                ({team_conflicts.unknown_team_matches_count} matches pending team assignment)
              </div>
            )}
          </div>
        )}

      {/* Refresh Button */}
      <button onClick={onRefresh} disabled={loading} className="btn-refresh">
        {loading ? 'Refreshing...' : 'Refresh Conflicts'}
      </button>
    </div>
  );
}


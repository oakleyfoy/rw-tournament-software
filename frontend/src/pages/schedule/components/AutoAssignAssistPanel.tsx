/**
 * Phase 3F: Auto-Assign Assist — run Auto-Assign V2 on draft, show before/after delta.
 * Respects locked assignments. No backend changes.
 */
import { useState, useCallback } from 'react';
import {
  buildScheduleVersion,
  getConflicts,
  ConflictReportSummary,
} from '../../../api/client';
import { showToast } from '../../../utils/toast';

export interface AutoAssignAssistPanelProps {
  tournamentId: number | null;
  activeVersionId: number | null;
  activeVersionStatus: string | null;
  onRefresh: () => Promise<void>;
}

interface Snapshot {
  assigned_matches: number;
  unassigned_matches: number;
  assignment_rate: number;
}

function snapshotFromSummary(s: ConflictReportSummary | undefined): Snapshot | null {
  if (!s) return null;
  return {
    assigned_matches: s.assigned_matches,
    unassigned_matches: s.unassigned_matches,
    assignment_rate: s.assignment_rate,
  };
}

export function AutoAssignAssistPanel({
  tournamentId,
  activeVersionId,
  activeVersionStatus,
  onRefresh,
}: AutoAssignAssistPanelProps) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [before, setBefore] = useState<Snapshot | null>(null);
  const [after, setAfter] = useState<Snapshot | null>(null);

  const isDraft = activeVersionStatus === 'draft';
  const disabled = !tournamentId || !activeVersionId || !isDraft || running;

  const runAutoAssign = useCallback(async () => {
    if (!tournamentId || !activeVersionId || !isDraft) return;

    setError(null);
    setAfter(null);
    setRunning(true);

    try {
      // 3A) Before snapshot
      const conflictsBefore = await getConflicts(tournamentId, activeVersionId);
      const beforeSnapshot = snapshotFromSummary(conflictsBefore?.summary);
      setBefore(beforeSnapshot);

      // 3B) Run build
      await buildScheduleVersion(tournamentId, activeVersionId);

      // 3C) After snapshot + refresh UI (refresh grid even if conflicts fetch fails)
      try {
        const conflictsAfter = await getConflicts(tournamentId, activeVersionId);
        const afterSnapshot = snapshotFromSummary(conflictsAfter?.summary);
        setAfter(afterSnapshot);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Conflicts fetch failed after build');
      }
      await onRefresh();

      showToast('Auto-Assign completed', 'success');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Auto-Assign failed';
      setError(msg);
      showToast(msg, 'error');
      // Do not refresh grid/conflicts on 422/409/etc (spec)
    } finally {
      setRunning(false);
    }
  }, [tournamentId, activeVersionId, isDraft, onRefresh]);

  const assignedDelta = after && before ? after.assigned_matches - before.assigned_matches : null;
  const unassignedDelta = after && before ? before.unassigned_matches - after.unassigned_matches : null;
  const rateDelta = after && before ? after.assignment_rate - before.assignment_rate : null;

  return (
    <div className="card" style={{ padding: '16px', marginBottom: '16px' }}>
      <h3 style={{ margin: '0 0 12px 0', fontSize: '16px' }}>
        ⚡ Auto-Assign Assist
      </h3>
      <div style={{ fontSize: '13px', color: '#666', marginBottom: '12px' }}>
        Version: <strong>{activeVersionStatus === 'draft' ? 'DRAFT' : activeVersionStatus === 'final' ? 'FINAL' : activeVersionStatus ?? '—'}</strong>
        {!isDraft && activeVersionId && (
          <span style={{ marginLeft: '8px' }} title="Only draft versions can be auto-assigned">
            (Run Auto-Assign only on draft)
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={runAutoAssign}
        disabled={disabled}
        title={!activeVersionId ? 'Select a version' : !isDraft ? 'Only draft versions can be auto-assigned' : undefined}
        style={{
          padding: '10px 20px',
          background: disabled ? '#ccc' : '#2196F3',
          color: '#fff',
          border: 'none',
          borderRadius: '4px',
          cursor: disabled ? 'not-allowed' : 'pointer',
          fontSize: '14px',
          fontWeight: 600,
        }}
      >
        {running ? 'Running Auto-Assign...' : '⚡ Run Auto-Assign (fills unassigned, respects 🔒 locked)'}
      </button>

      {error && (
        <div
          style={{
            marginTop: '12px',
            padding: '12px',
            background: '#ffebee',
            border: '1px solid #f44336',
            borderRadius: '4px',
            fontSize: '13px',
            color: '#c62828',
          }}
        >
          {error}
        </div>
      )}

      {(before || after) && !error && (
        <div style={{ marginTop: '16px', fontSize: '13px' }}>
          <div style={{ fontWeight: 600, marginBottom: '8px' }}>Last run</div>
          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
            {assignedDelta !== null && (
              <span>
                Assigned: <strong>{assignedDelta >= 0 ? '+' : ''}{assignedDelta}</strong>
              </span>
            )}
            {unassignedDelta !== null && (
              <span>
                Unassigned: <strong>{unassignedDelta >= 0 ? '-' : '+'}{Math.abs(unassignedDelta)}</strong>
              </span>
            )}
            {rateDelta !== null && (
              <span>
                Assignment rate: <strong>{(rateDelta >= 0 ? '+' : '') + rateDelta.toFixed(1)}%</strong>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Phase 4: Score / Finalize modal — update match runtime status and score.
 * Runtime only; no schedule mutation.
 */
import { useState, useEffect } from 'react';
import {
  GridMatch,
  TeamInfo,
  MatchRuntimeState,
  MatchRuntimeUpdate,
  updateMatchRuntime,
} from '../../../api/client';
import { showToast } from '../../../utils/toast';

interface MatchRuntimeModalProps {
  tournamentId: number;
  match: GridMatch;
  teams: TeamInfo[];
  runtime: MatchRuntimeState | null;
  onSave: () => void;
  onClose: () => void;
}

const RUNTIME_SCHEDULED = 'SCHEDULED';
const RUNTIME_IN_PROGRESS = 'IN_PROGRESS';
const RUNTIME_FINAL = 'FINAL';

export function MatchRuntimeModal({
  tournamentId,
  match,
  teams,
  runtime,
  onSave,
  onClose,
}: MatchRuntimeModalProps) {
  const [status, setStatus] = useState(runtime?.runtime_status ?? RUNTIME_SCHEDULED);
  const [scoreText, setScoreText] = useState(
    runtime?.score_json ? JSON.stringify(runtime.score_json, null, 2) : ''
  );
  const [winnerTeamId, setWinnerTeamId] = useState<number | null>(runtime?.winner_team_id ?? null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setStatus(runtime?.runtime_status ?? RUNTIME_SCHEDULED);
    setScoreText(runtime?.score_json ? JSON.stringify(runtime.score_json, null, 2) : '');
    setWinnerTeamId(runtime?.winner_team_id ?? null);
  }, [runtime]);

  const options: { id: number | null; label: string }[] = [
    { id: null, label: '—' },
  ];
  if (match.team_a_id) {
    options.push({ id: match.team_a_id, label: teams.find(t => t.id === match.team_a_id)?.name ?? `Team ${match.team_a_id}` });
  }
  if (match.team_b_id && match.team_b_id !== match.team_a_id) {
    options.push({ id: match.team_b_id, label: teams.find(t => t.id === match.team_b_id)?.name ?? `Team ${match.team_b_id}` });
  }

  const handleSave = async () => {
    if (status === RUNTIME_FINAL && winnerTeamId == null) {
      showToast('Select a winner when setting status to Completed', 'error');
      return;
    }
    if (status === RUNTIME_FINAL && !scoreText.trim()) {
      showToast('Score is required when finalizing a match', 'error');
      return;
    }
    let score: Record<string, unknown> | undefined;
    if (scoreText.trim()) {
      try {
        score = JSON.parse(scoreText) as Record<string, unknown>;
      } catch {
        showToast('Invalid JSON in score', 'error');
        return;
      }
    }
    setSaving(true);
    try {
      const payload: MatchRuntimeUpdate = {
        status,
        score: score ?? undefined,
        winner_team_id: winnerTeamId ?? undefined,
      };
      const res = await updateMatchRuntime(tournamentId, match.match_id, payload);
      const advMsg = res.advanced_count > 0
        ? ` Advanced: ${res.advanced_count} downstream match(es).`
        : '';
      showToast(`Runtime updated.${advMsg}`, 'success');
      onSave();
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Update failed', 'error');
    } finally {
      setSaving(false);
    }
  };

  const isFinal = runtime?.runtime_status === RUNTIME_FINAL;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#fff',
          padding: '24px',
          borderRadius: '8px',
          maxWidth: '420px',
          width: '90%',
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '18px' }}>Score / Finalize — {match.match_code}</h3>

        <div style={{ marginBottom: '12px' }}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '4px', fontSize: '13px' }}>Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            disabled={isFinal}
            style={{ width: '100%', padding: '8px', fontSize: '14px' }}
          >
            <option value={RUNTIME_SCHEDULED}>Scheduled</option>
            <option value={RUNTIME_IN_PROGRESS}>Live</option>
            <option value={RUNTIME_FINAL}>Completed</option>
          </select>
          {isFinal && <div style={{ fontSize: '12px', color: '#666', marginTop: '4px' }}>Completed is terminal; cannot change.</div>}
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '4px', fontSize: '13px' }}>Score (JSON, optional)</label>
          <textarea
            value={scoreText}
            onChange={(e) => setScoreText(e.target.value)}
            rows={3}
            placeholder='{"set1_a": 21, "set1_b": 19}'
            style={{ width: '100%', padding: '8px', fontSize: '13px', fontFamily: 'monospace' }}
          />
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '4px', fontSize: '13px' }}>Winner</label>
          <select
            value={winnerTeamId ?? ''}
            onChange={(e) => setWinnerTeamId(e.target.value ? Number(e.target.value) : null)}
            style={{ width: '100%', padding: '8px', fontSize: '14px' }}
          >
            {options.map((o) => (
              <option key={o.id ?? 'none'} value={o.id ?? ''}>{o.label}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="button" onClick={handleSave} disabled={saving} className="btn-primary">
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

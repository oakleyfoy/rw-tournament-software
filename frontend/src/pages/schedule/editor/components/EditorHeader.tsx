import { Link } from 'react-router-dom';
import { ScheduleVersion } from '../../../../api/client';

interface EditorHeaderProps {
  tournamentId: number;
  versions: ScheduleVersion[];
  activeVersionId: number | null;
  versionStatus: 'draft' | 'final' | null;
  onVersionChange: (versionId: number) => void;
  onCloneToEdit: () => void;
  isCloning: boolean;
  /** Phase 3F: Run Auto-Assign V2 on draft, then refresh grid/conflicts */
  onRunAutoAssign?: () => Promise<void>;
  isRunningAutoAssign?: boolean;
}

export function EditorHeader({
  tournamentId,
  versions,
  activeVersionId,
  versionStatus,
  onVersionChange,
  onCloneToEdit,
  isCloning,
  onRunAutoAssign,
  isRunningAutoAssign,
}: EditorHeaderProps) {
  return (
    <div style={{ marginBottom: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '12px' }}>
        <Link to={`/tournaments/${tournamentId}/schedule`} style={{ textDecoration: 'none' }}>
          <button className="btn-secondary">← Back to Schedule</button>
        </Link>
        <h1 style={{ margin: 0, fontSize: '24px' }}>Manual Schedule Editor</h1>
      </div>

      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        <label htmlFor="version-select" style={{ fontWeight: 600, fontSize: '14px' }}>
          Version:
        </label>
        <select
          id="version-select"
          value={activeVersionId || ''}
          onChange={(e) => onVersionChange(parseInt(e.target.value))}
          style={{
            padding: '8px 12px',
            border: '1px solid #ddd',
            borderRadius: '4px',
            fontSize: '14px',
          }}
        >
          {versions.length === 0 && <option value="">No versions available</option>}
          {versions.map((v) => (
            <option key={v.id} value={v.id}>
              v{v.version_number} ({v.status})
              {v.notes ? ` - ${v.notes}` : ''}
            </option>
          ))}
        </select>

        {versionStatus === 'final' && (
          <button
            onClick={onCloneToEdit}
            disabled={isCloning}
            className="btn-secondary"
          >
            {isCloning ? 'Cloning...' : 'Clone to Draft'}
          </button>
        )}

        {versionStatus === 'draft' && onRunAutoAssign && (
          <button
            type="button"
            onClick={onRunAutoAssign}
            disabled={isRunningAutoAssign}
            className="btn-secondary"
            style={{ marginLeft: '8px' }}
            title="Run Auto-Assign V2 (fills unassigned, respects locked)"
          >
            {isRunningAutoAssign ? 'Running Auto-Assign...' : '⚡ Run Auto-Assign'}
          </button>
        )}

        {versionStatus && (
          <span
            style={{
              marginLeft: 'auto',
              padding: '6px 12px',
              background: versionStatus === 'draft' ? '#e3f2fd' : '#f5f5f5',
              color: versionStatus === 'draft' ? '#1565c0' : '#666',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
            }}
          >
            {versionStatus === 'draft' ? '✏️ Draft' : '📄 Final'}
          </span>
        )}
      </div>
    </div>
  );
}


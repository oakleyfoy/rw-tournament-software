import React from 'react'
import { useNavigate } from 'react-router-dom'
import { ScheduleVersion } from '../../../api/client'

interface ScheduleHeaderProps {
  tournamentName: string
  tournamentId: number | null
  versions: ScheduleVersion[]
  activeVersion: ScheduleVersion | null
  onVersionChange: (version: ScheduleVersion | null) => void
  onCreateDraft: () => void
  onCloneFinal: () => void
  onFinalize: () => void
}

export const ScheduleHeader: React.FC<ScheduleHeaderProps> = ({
  tournamentName,
  tournamentId,
  versions,
  activeVersion,
  onVersionChange,
  onCreateDraft,
  onCloneFinal,
  onFinalize,
}) => {
  const navigate = useNavigate()
  const isReadOnly = activeVersion?.status === 'final'
  const hasDraft = versions.some(v => v.status === 'draft')
  const hasFinal = versions.some(v => v.status === 'final')

  return (
    <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <h1 style={{ margin: 0 }}>Schedule – {tournamentName}</h1>
        {isReadOnly && (
          <span style={{
            padding: '4px 12px',
            backgroundColor: '#f0f0f0',
            color: '#666',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: 'bold',
          }}>
            READ-ONLY
          </span>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Version Selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <label style={{ fontSize: '14px' }}>Version:</label>
          <select
            value={activeVersion?.id || ''}
            onChange={(e) => {
              const version = versions.find(v => v.id === parseInt(e.target.value))
              onVersionChange(version || null)
            }}
            style={{ padding: '6px 12px', fontSize: '14px', minWidth: '150px' }}
          >
            {versions.length === 0 && <option value="">No versions</option>}
            {versions.map(v => (
              <option key={v.id} value={v.id}>
                {v.status === 'draft' ? `Draft v${v.version_number}` : `Final v${v.version_number}`}
              </option>
            ))}
          </select>
        </div>

        {/* Action Buttons */}
        {!hasDraft && !hasFinal && (
          <button className="btn btn-primary" onClick={onCreateDraft}>
            Create Draft
          </button>
        )}

        {!hasDraft && hasFinal && activeVersion?.status === 'final' && (
          <button className="btn btn-primary" onClick={onCloneFinal}>
            Clone Final → Draft
          </button>
        )}

        {activeVersion?.status === 'draft' && (
          <button className="btn btn-success" onClick={onFinalize}>
            Finalize Draft
          </button>
        )}

        <button className="btn btn-secondary" onClick={() => tournamentId && navigate(`/tournaments/${tournamentId}/setup`)}>
          ← Back to Setup
        </button>
      </div>
    </div>
  )
}


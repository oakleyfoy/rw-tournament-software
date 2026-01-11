import React, { useState } from 'react'
import { ScheduleVersion } from '../../../api/client'

interface ScheduleBuildPanelProps {
  activeVersion: ScheduleVersion | null
  building: boolean
  onBuild: () => void
  onCreateDraft: () => void
}

export const ScheduleBuildPanel: React.FC<ScheduleBuildPanelProps> = ({
  activeVersion,
  building,
  onBuild,
  onCreateDraft,
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const isReadOnly = activeVersion?.status === 'final'
  const hasDraft = activeVersion?.status === 'draft'

  if (isReadOnly) {
    return (
      <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
        <div style={{ textAlign: 'center', color: '#666' }}>
          <p>This schedule is finalized and read-only.</p>
          <p style={{ fontSize: '14px', marginTop: '8px' }}>
            Build Schedule generates the schedule automatically from your Setup (time windows + finalized events). Manual changes are only needed for exceptions.
          </p>
        </div>
      </div>
    )
  }

  if (!activeVersion) {
    return (
      <div className="card" style={{ padding: '24px', marginBottom: '24px', textAlign: 'center' }}>
        <p style={{ marginBottom: '16px', color: '#666' }}>
          Build Schedule generates the schedule automatically from your Setup (time windows + finalized events). Manual changes are only needed for exceptions.
        </p>
        <button
          className="btn btn-primary"
          onClick={onCreateDraft}
          style={{ fontSize: '16px', padding: '12px 24px' }}
        >
          Create Draft
        </button>
      </div>
    )
  }

  return (
    <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ marginBottom: '16px', color: '#666' }}>
          Build Schedule generates the schedule automatically from your Setup (time windows + finalized events). Manual changes are only needed for exceptions.
        </p>
        <button
          className="btn btn-primary"
          onClick={onBuild}
          disabled={building || !hasDraft}
          style={{ fontSize: '18px', padding: '14px 32px', fontWeight: 'bold' }}
        >
          {building ? 'Building Schedule...' : 'Build Schedule'}
        </button>
        <p style={{ marginTop: '8px', fontSize: '12px', color: '#999' }}>
          Generates slots, generates matches, auto-places matches.
        </p>
      </div>

      {/* Advanced Controls (collapsed by default) */}
      <div style={{ marginTop: '24px', borderTop: '1px solid #ddd', paddingTop: '16px' }}>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          style={{
            background: 'none',
            border: 'none',
            color: '#666',
            cursor: 'pointer',
            fontSize: '12px',
            textDecoration: 'underline',
          }}
        >
          {showAdvanced ? '▼ Hide' : '▶ Show'} Advanced Controls
        </button>

        {showAdvanced && (
          <div style={{ marginTop: '12px', padding: '12px', backgroundColor: '#f9f9f9', borderRadius: '4px' }}>
            <p style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>
              These controls are useful for debugging but hidden by default.
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button className="btn btn-secondary" disabled style={{ fontSize: '12px', padding: '6px 12px' }}>
                Generate Slots only
              </button>
              <button className="btn btn-secondary" disabled style={{ fontSize: '12px', padding: '6px 12px' }}>
                Generate Matches only
              </button>
              <button className="btn btn-secondary" disabled style={{ fontSize: '12px', padding: '6px 12px' }}>
                Auto-assign only
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}


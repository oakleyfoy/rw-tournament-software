import React from 'react'
import { ScheduleVersion } from '../../../api/client'

interface ScheduleToolbarProps {
  versions: ScheduleVersion[]
  currentVersion: ScheduleVersion | null
  onCreateDraft: () => void
  onFinalize: () => void
  onDelete: () => void
  onGenerateSlots: () => void
  onGenerateMatches: () => void
  onBuildFullSchedule?: () => void
  generating: boolean
  building?: boolean
}

export const ScheduleToolbar: React.FC<ScheduleToolbarProps> = React.memo(({
  versions,
  currentVersion,
  onCreateDraft,
  onFinalize,
  onDelete,
  onGenerateSlots,
  onGenerateMatches,
  onBuildFullSchedule,
  generating,
  building = false,
}) => {
  return (
    <div className="card" style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h2 style={{ margin: 0 }}>Schedule Versions</h2>
        {!currentVersion && (
          <button className="btn btn-primary" onClick={onCreateDraft}>
            Create Draft
          </button>
        )}
      </div>

      {versions.length === 0 ? (
        <p>No schedule versions yet. Click "Create Draft" to begin.</p>
      ) : (
        <div>
          {versions.map(version => (
            <div key={version.id} style={{ padding: '12px', border: '1px solid #ddd', borderRadius: '4px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>Version {version.version_number} — {version.status}</strong>
                <div style={{ fontSize: '12px', color: '#666' }}>
                  Created: {new Date(version.created_at).toLocaleString()}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                {version.status === 'draft' && (
                  <button className="btn btn-success" onClick={onFinalize} disabled={version.id !== currentVersion?.id}>
                    Finalize
                  </button>
                )}
                <button className="btn btn-danger" onClick={onDelete} disabled={version.id !== currentVersion?.id}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {currentVersion && (
        <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #ddd' }}>
          <h3 style={{ marginBottom: '12px' }}>Actions</h3>
          
          {/* P4: One-Click Build Full Schedule Button */}
          {currentVersion.status === 'draft' && onBuildFullSchedule && (
            <div style={{ marginBottom: '16px', padding: '16px', background: '#e8f5e9', borderRadius: '6px', border: '2px solid #4caf50' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <h4 style={{ margin: '0 0 8px 0', color: '#2e7d32' }}>🚀 One-Click Build</h4>
                  <p style={{ margin: 0, fontSize: '13px', color: '#555' }}>
                    Generate slots, matches, assign WF groups, inject teams, and auto-assign in one step
                  </p>
                </div>
                <button 
                  className="btn btn-success" 
                  onClick={onBuildFullSchedule} 
                  disabled={building || generating}
                  style={{ 
                    fontSize: '16px', 
                    fontWeight: 'bold', 
                    padding: '12px 24px',
                    minWidth: '200px'
                  }}
                >
                  {building ? '⏳ Building...' : '🚀 Build Full Schedule'}
                </button>
              </div>
            </div>
          )}
          
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={onGenerateSlots} disabled={generating || building}>
              {generating ? 'Generating...' : 'Generate Slots'}
            </button>
            <button className="btn btn-primary" onClick={onGenerateMatches} disabled={generating || building}>
              {generating ? 'Generating...' : 'Generate Matches'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
})

ScheduleToolbar.displayName = 'ScheduleToolbar'


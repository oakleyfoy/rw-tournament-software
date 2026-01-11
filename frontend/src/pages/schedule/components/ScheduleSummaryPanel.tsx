import React from 'react'
import { BuildSummary } from '../types'

interface ScheduleSummaryPanelProps {
  buildSummary: BuildSummary | null
}

export const ScheduleSummaryPanel: React.FC<ScheduleSummaryPanelProps> = ({
  buildSummary,
}) => {
  if (!buildSummary) {
    return null
  }

  return (
    <div className="card" style={{ padding: '20px', marginBottom: '24px' }}>
      <h3 style={{ marginTop: 0, marginBottom: '16px' }}>Build Summary</h3>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '16px', marginBottom: '16px' }}>
        <div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#333' }}>
            {buildSummary.slots_created}
          </div>
          <div style={{ fontSize: '12px', color: '#666' }}>Slots Created</div>
        </div>
        
        <div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#333' }}>
            {buildSummary.matches_created}
          </div>
          <div style={{ fontSize: '12px', color: '#666' }}>Matches Created</div>
        </div>
        
        <div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#28a745' }}>
            {buildSummary.matches_assigned}
          </div>
          <div style={{ fontSize: '12px', color: '#666' }}>Matches Assigned</div>
        </div>
        
        <div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: buildSummary.matches_unassigned > 0 ? '#dc3545' : '#28a745' }}>
            {buildSummary.matches_unassigned}
          </div>
          <div style={{ fontSize: '12px', color: '#666' }}>Matches Unassigned</div>
        </div>
      </div>

      {buildSummary.conflicts && buildSummary.conflicts.length > 0 && (
        <div style={{ marginTop: '16px', padding: '12px', backgroundColor: '#fff3cd', borderRadius: '4px' }}>
          <div style={{ fontWeight: 'bold', marginBottom: '8px', color: '#856404' }}>Conflicts:</div>
          {buildSummary.conflicts.map((conflict, idx) => (
            <div key={idx} style={{ fontSize: '12px', color: '#856404' }}>
              {conflict.reason}: {conflict.count}
            </div>
          ))}
        </div>
      )}

      {buildSummary.warnings && buildSummary.warnings.length > 0 && (
        <div style={{ marginTop: '16px', padding: '12px', backgroundColor: '#d1ecf1', borderRadius: '4px' }}>
          <div style={{ fontWeight: 'bold', marginBottom: '8px', color: '#0c5460' }}>Warnings:</div>
          {buildSummary.warnings.map((warning, idx) => (
            <div key={idx} style={{ fontSize: '12px', color: '#0c5460' }}>
              {warning.message}: {warning.count}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


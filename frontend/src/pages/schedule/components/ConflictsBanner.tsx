import React from 'react'
import { ConflictSummary } from '../../../api/client'

interface ConflictsBannerProps {
  summary: ConflictSummary | null
  spilloverWarning?: boolean
}

export const ConflictsBanner: React.FC<ConflictsBannerProps> = ({
  summary,
  spilloverWarning = false
}) => {
  if (!summary) return null

  const hasIssues = summary.unassigned_matches > 0 || spilloverWarning

  return (
    <div style={{
      padding: '16px',
      background: hasIssues ? '#fff3e0' : '#e8f5e9',
      border: `1px solid ${hasIssues ? '#ffb74d' : '#81c784'}`,
      borderRadius: '4px',
      marginBottom: '16px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      flexWrap: 'wrap',
      gap: '16px'
    }}>
      <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '13px', color: '#666', marginBottom: '4px' }}>
            Assigned
          </div>
          <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#2196F3' }}>
            {summary.assigned_matches} / {summary.total_matches}
          </div>
        </div>
        
        <div>
          <div style={{ fontSize: '13px', color: '#666', marginBottom: '4px' }}>
            Unassigned
          </div>
          <div style={{ 
            fontSize: '20px', 
            fontWeight: 'bold', 
            color: summary.unassigned_matches > 0 ? '#ff9800' : '#4caf50'
          }}>
            {summary.unassigned_matches}
          </div>
        </div>

        <div>
          <div style={{ fontSize: '13px', color: '#666', marginBottom: '4px' }}>
            Assignment Rate
          </div>
          <div style={{ 
            fontSize: '20px', 
            fontWeight: 'bold', 
            color: summary.assignment_rate >= 90 ? '#4caf50' : summary.assignment_rate >= 70 ? '#ff9800' : '#f44336'
          }}>
            {summary.assignment_rate}%
          </div>
        </div>

        <div>
          <div style={{ fontSize: '13px', color: '#666', marginBottom: '4px' }}>
            Available Slots
          </div>
          <div style={{ fontSize: '16px', fontWeight: '500', color: '#666' }}>
            {summary.total_slots}
          </div>
        </div>
      </div>

      {spilloverWarning && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 12px',
          background: '#fff',
          borderRadius: '4px',
          border: '1px solid #ff9800'
        }}>
          <span style={{ fontSize: '18px' }}>⚠️</span>
          <span style={{ fontSize: '13px', color: '#666' }}>
            Stage spillover detected
          </span>
        </div>
      )}
    </div>
  )
}


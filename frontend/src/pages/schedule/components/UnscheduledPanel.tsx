import React, { useMemo, useState } from 'react'
import { UnscheduledMatch } from '../types'
import { Event } from '../../../api/client'
import { minutesToClock } from '../../../utils/timeFormat'

interface UnscheduledPanelProps {
  matches: UnscheduledMatch[]
  events: Event[]
  selectedMatchId: number | null
  onSelectMatch: (match: UnscheduledMatch | null) => void
}

export const UnscheduledPanel: React.FC<UnscheduledPanelProps> = ({
  matches,
  events,
  selectedMatchId,
  onSelectMatch,
}) => {
  const [filterEventId, setFilterEventId] = useState<number | null>(null)
  const [filterMatchType, setFilterMatchType] = useState<string>('all')
  const [filterDuration, setFilterDuration] = useState<number | null>(null)

  const filteredMatches = useMemo(() => {
    return matches.filter(m => {
      if (filterEventId && m.event_id !== filterEventId) return false
      if (filterMatchType !== 'all' && m.match_type !== filterMatchType) return false
      if (filterDuration && m.duration_minutes !== filterDuration) return false
      return true
    })
  }, [matches, filterEventId, filterMatchType, filterDuration])

  return (
    <div className="card" style={{ width: '300px', flexShrink: 0, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h3 style={{ marginBottom: '16px' }}>
        Unscheduled Matches ({matches.length})
      </h3>
      
      {/* Filters */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ marginBottom: '8px' }}>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px' }}>Event:</label>
          <select
            value={filterEventId || ''}
            onChange={(e) => setFilterEventId(e.target.value ? parseInt(e.target.value) : null)}
            style={{ width: '100%', padding: '4px 8px', fontSize: '14px' }}
          >
            <option value="">All</option>
            {events.map(e => (
              <option key={e.id} value={e.id}>
                {e.name} ({e.category})
              </option>
            ))}
          </select>
        </div>
        
        <div style={{ marginBottom: '8px' }}>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px' }}>Type:</label>
          <select
            value={filterMatchType}
            onChange={(e) => setFilterMatchType(e.target.value)}
            style={{ width: '100%', padding: '4px 8px', fontSize: '14px' }}
          >
            <option value="all">All</option>
            <option value="WF">Waterfall</option>
            <option value="RR">Round Robin</option>
            <option value="BRACKET">Bracket</option>
            <option value="PLACEMENT">Placement</option>
          </select>
        </div>
        
        <div>
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px' }}>Duration:</label>
          <select
            value={filterDuration || ''}
            onChange={(e) => setFilterDuration(e.target.value ? parseInt(e.target.value) : null)}
            style={{ width: '100%', padding: '4px 8px', fontSize: '14px' }}
          >
            <option value="">All</option>
            <option value="60">1:00</option>
            <option value="90">1:30</option>
            <option value="105">1:45</option>
            <option value="120">2:00</option>
          </select>
        </div>
      </div>
      
      {/* Match List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filteredMatches.length === 0 ? (
          <div style={{ padding: '16px', textAlign: 'center', color: '#666' }}>
            {matches.length === 0 ? 'No unscheduled matches' : 'No matches match filters'}
          </div>
        ) : (
          <div>
            {filteredMatches.map(match => {
              const event = events.find(e => e.id === match.event_id)
              const isSelected = selectedMatchId === match.id
              return (
                <div
                  key={match.id}
                  style={{
                    padding: '8px',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? '#e3f2fd' : 'white',
                    marginBottom: '8px',
                  }}
                  onClick={() => onSelectMatch(isSelected ? null : match)}
                >
                  <div style={{ fontWeight: 'bold', fontSize: '14px' }}>{match.match_code}</div>
                  <div style={{ fontSize: '12px', color: '#666' }}>
                    {event?.name} • {match.match_type} • {minutesToClock(match.duration_minutes)}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}


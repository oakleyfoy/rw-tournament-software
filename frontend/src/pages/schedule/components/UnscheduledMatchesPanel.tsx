import React, { useMemo, useState } from 'react'
import { Match, Event } from '../../../api/client'
import { minutesToClock } from '../../../utils/timeFormat'

interface UnscheduledMatchesPanelProps {
  matches: Match[]
  events: Event[]
  selectedMatchId: number | null
  onSelectMatch: (match: Match) => void
}

interface MatchItemProps {
  match: Match
  event: Event | undefined
  isSelected: boolean
  onSelect: () => void
}

const MatchItem: React.FC<MatchItemProps> = React.memo(({ match, event, isSelected, onSelect }) => {
  return (
    <div
      style={{
        padding: '8px',
        border: '1px solid #ddd',
        borderRadius: '4px',
        cursor: 'pointer',
        backgroundColor: isSelected ? '#e3f2fd' : 'white',
        marginBottom: '8px',
      }}
      onClick={onSelect}
    >
      <div style={{ fontWeight: 'bold', fontSize: '14px' }}>{match.match_code}</div>
      <div style={{ fontSize: '12px', color: '#666' }}>
        {event?.name} • {match.match_type} • {minutesToClock(match.duration_minutes)}
      </div>
    </div>
  )
})

MatchItem.displayName = 'MatchItem'

export const UnscheduledMatchesPanel: React.FC<UnscheduledMatchesPanelProps> = React.memo(({
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
    <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h3 style={{ marginBottom: '16px' }}>Unscheduled Matches</h3>
      
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
          <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px' }}>Match Type:</label>
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
            No unscheduled matches
          </div>
        ) : (
          <div>
            {filteredMatches.map(match => {
              const event = events.find(e => e.id === match.event_id)
              return (
                <MatchItem
                  key={match.id}
                  match={match}
                  event={event}
                  isSelected={selectedMatchId === match.id}
                  onSelect={() => onSelectMatch(match)}
                />
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
})

UnscheduledMatchesPanel.displayName = 'UnscheduledMatchesPanel'


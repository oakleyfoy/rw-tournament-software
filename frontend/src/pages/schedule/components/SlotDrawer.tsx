import React from 'react'
import { ScheduleSlot, Match, Event } from '../../../api/client'
import { UnscheduledMatch } from '../types'
import { timeTo12Hour, minutesToClock } from '../../../utils/timeFormat'

interface SlotDrawerProps {
  slot: ScheduleSlot | null
  assignedMatch: Match | null
  event: Event | undefined
  unscheduledMatches: UnscheduledMatch[]
  events: Event[]
  selectedMatch: UnscheduledMatch | null
  readOnly: boolean
  onAssign: (slotId: number, matchId: number) => void
  onUnassign: (slotId: number) => void
  onSelectMatch: (match: UnscheduledMatch | null) => void
  onClose: () => void
}

export const SlotDrawer: React.FC<SlotDrawerProps> = ({
  slot,
  assignedMatch,
  event,
  unscheduledMatches,
  events,
  selectedMatch,
  readOnly,
  onAssign,
  onUnassign,
  onSelectMatch,
  onClose,
}) => {
  if (!slot) return null

  const slotStartParts = slot.start_time.split(':')
  const slotEndParts = slot.end_time.split(':')
  const slotDuration = (Number(slotEndParts[0]) * 60 + Number(slotEndParts[1])) - 
                       (Number(slotStartParts[0]) * 60 + Number(slotStartParts[1]))

  // Filter matches that fit the slot duration
  const eligibleMatches = unscheduledMatches.filter(m => m.duration_minutes <= slotDuration)

  const handleAssignSelected = () => {
    if (selectedMatch && slot) {
      onAssign(slot.id, selectedMatch.id)
      onClose()
    }
  }

  const handleAssignFromList = (matchId: number) => {
    if (slot) {
      onAssign(slot.id, matchId)
      onClose()
    }
  }

  const handleUnassign = () => {
    if (slot) {
      onUnassign(slot.id)
      onClose()
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          width: '600px',
          maxHeight: '80vh',
          overflowY: 'auto',
          zIndex: 1001,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ marginBottom: '16px' }}>
          {assignedMatch ? 'Slot Details' : 'Assign Match to Slot'}
        </h3>
        
        {/* Slot Info */}
        <div style={{ marginBottom: '16px', padding: '12px', backgroundColor: '#f5f5f5', borderRadius: '4px' }}>
          <div><strong>Date:</strong> {new Date(slot.day_date + 'T12:00:00').toLocaleDateString()}</div>
          <div><strong>Time:</strong> {timeTo12Hour(slot.start_time)} - {timeTo12Hour(slot.end_time)}</div>
          <div><strong>Court:</strong> {slot.court_label}</div>
          <div><strong>Duration:</strong> {slotDuration} minutes</div>
        </div>
        
        {assignedMatch ? (
          <div>
            <div style={{ marginBottom: '16px' }}>
              <strong>Assigned Match:</strong>
              <div style={{ marginTop: '8px', padding: '12px', backgroundColor: '#e8f5e9', borderRadius: '4px' }}>
                <div><strong>{assignedMatch.match_code}</strong></div>
                <div style={{ fontSize: '14px', color: '#666', marginTop: '4px' }}>
                  {event?.name} • {assignedMatch.match_type} • {minutesToClock(assignedMatch.duration_minutes)}
                </div>
              </div>
            </div>
            {!readOnly && (
              <button className="btn btn-danger" onClick={handleUnassign}>
                Unassign Match
              </button>
            )}
          </div>
        ) : (
          <div>
            {selectedMatch ? (
              <div>
                <div style={{ marginBottom: '16px' }}>
                  <strong>Selected Match:</strong>
                  <div style={{ marginTop: '8px', padding: '12px', backgroundColor: '#e3f2fd', borderRadius: '4px' }}>
                    <div><strong>{selectedMatch.match_code}</strong></div>
                    <div style={{ fontSize: '14px', color: '#666', marginTop: '4px' }}>
                      {events.find(e => e.id === selectedMatch.event_id)?.name} • {selectedMatch.match_type} • {minutesToClock(selectedMatch.duration_minutes)}
                    </div>
                  </div>
                </div>
                {selectedMatch.duration_minutes <= slotDuration ? (
                  <button className="btn btn-primary" onClick={handleAssignSelected}>
                    Confirm Assignment
                  </button>
                ) : (
                  <div style={{ padding: '8px', backgroundColor: '#fff3cd', borderRadius: '4px', color: '#856404' }}>
                    Selected match duration ({minutesToClock(selectedMatch.duration_minutes)}) exceeds slot duration ({slotDuration} min)
                  </div>
                )}
              </div>
            ) : null}

            <div style={{ marginTop: '16px' }}>
              <label style={{ display: 'block', marginBottom: '8px' }}>
                <strong>Or select from eligible matches (fits {slotDuration} min slot):</strong>
              </label>
              <div style={{ maxHeight: '300px', overflowY: 'auto', border: '1px solid #ddd', borderRadius: '4px' }}>
                {eligibleMatches.length === 0 ? (
                  <div style={{ padding: '16px', textAlign: 'center', color: '#666' }}>
                    No matches available that fit this {slotDuration}-minute slot
                  </div>
                ) : (
                  eligibleMatches.map(match => {
                    const matchEvent = events.find(e => e.id === match.event_id)
                    return (
                      <div
                        key={match.id}
                        style={{
                          padding: '12px',
                          borderBottom: '1px solid #eee',
                          cursor: 'pointer',
                          backgroundColor: selectedMatch?.id === match.id ? '#e3f2fd' : 'white',
                        }}
                        onClick={() => onSelectMatch(match)}
                      >
                        <div style={{ fontWeight: 'bold' }}>{match.match_code}</div>
                        <div style={{ fontSize: '14px', color: '#666' }}>
                          {matchEvent?.name} • {match.match_type} • {minutesToClock(match.duration_minutes)}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
              {eligibleMatches.length > 0 && !selectedMatch && (
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    if (eligibleMatches.length > 0) {
                      handleAssignFromList(eligibleMatches[0].id)
                    }
                  }}
                  style={{ marginTop: '12px' }}
                >
                  Assign First Match
                </button>
              )}
            </div>
          </div>
        )}
        
        <div style={{ marginTop: '16px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}


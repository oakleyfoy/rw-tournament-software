import React, { useMemo, useState } from 'react'
import { ScheduleSlot, Match, Event, Tournament } from '../../../api/client'
import { timeTo12Hour } from '../../../utils/timeFormat'

interface ScheduleGridViewerProps {
  slots: ScheduleSlot[]
  matches: Match[]
  events: Event[]
  tournament: Tournament | null
  readOnly: boolean
  onSlotClick: (slot: ScheduleSlot) => void
}

export const ScheduleGridViewer: React.FC<ScheduleGridViewerProps> = ({
  slots,
  matches,
  events,
  tournament: _tournament,
  readOnly,
  onSlotClick,
}) => {
  const [selectedDay, setSelectedDay] = useState<string | null>(null)

  // Get unique days from slots
  const days = useMemo(() => {
    const uniqueDays = Array.from(new Set(slots.map(s => s.day_date))).sort()
    return uniqueDays
  }, [slots])

  // Set default day on mount
  React.useEffect(() => {
    if (days.length > 0 && !selectedDay) {
      setSelectedDay(days[0])
    }
  }, [days, selectedDay])

  // Derive court labels and order from slots (immutable per version)
  const courtLabels = useMemo(() => {
    if (!selectedDay) return []
    
    const daySlotsList = slots.filter(s => s.day_date === selectedDay)
    
    // Get unique court labels with their court_number for sorting
    const courtMap = new Map<string, { label: string; number: number }>()
    daySlotsList.forEach(slot => {
      if (!courtMap.has(slot.court_label)) {
        courtMap.set(slot.court_label, {
          label: slot.court_label,
          number: slot.court_number,
        })
      }
    })
    
    // Sort by court_number to maintain order
    return Array.from(courtMap.values())
      .sort((a, b) => a.number - b.number)
      .map(c => c.label)
  }, [slots, selectedDay])

  // Get slots for selected day, grouped by time and court_label
  const daySlots = useMemo(() => {
    if (!selectedDay) return []
    
    const daySlotsList = slots.filter(s => s.day_date === selectedDay)
    
    // Group by time, then by court_label
    const timeGroups = new Map<string, Map<string, ScheduleSlot>>()
    
    daySlotsList.forEach(slot => {
      const timeKey = slot.start_time
      if (!timeGroups.has(timeKey)) {
        timeGroups.set(timeKey, new Map())
      }
      timeGroups.get(timeKey)!.set(slot.court_label, slot)
    })
    
    // Convert to array and sort by time
    return Array.from(timeGroups.entries())
      .sort(([timeA], [timeB]) => timeA.localeCompare(timeB))
      .map(([time, courtMap]) => ({
        time,
        slotsByCourtLabel: courtMap,
      }))
  }, [slots, selectedDay])

  // Get match for a slot
  const getMatchForSlot = (slot: ScheduleSlot): Match | null => {
    if (!slot.match_id) return null
    return matches.find(m => m.id === slot.match_id) || null
  }

  // Get event for a match
  const getEventForMatch = (match: Match | null): Event | undefined => {
    if (!match) return undefined
    return events.find(e => e.id === match.event_id)
  }

  if (days.length === 0) {
    return (
      <div className="card" style={{ padding: '24px', textAlign: 'center', color: '#666' }}>
        No slots available. Build the schedule first.
      </div>
    )
  }

  return (
    <div className="card" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Day Selector */}
      <div style={{ padding: '16px', borderBottom: '1px solid #ddd', display: 'flex', gap: '8px', alignItems: 'center' }}>
        <label style={{ fontSize: '14px', fontWeight: 'bold' }}>Day:</label>
        <select
          value={selectedDay || ''}
          onChange={(e) => setSelectedDay(e.target.value)}
          style={{ padding: '6px 12px', fontSize: '14px', minWidth: '200px' }}
        >
          {days.map(day => (
            <option key={day} value={day}>
              {new Date(day + 'T12:00:00').toLocaleDateString('en-US', { 
                weekday: 'long', 
                month: 'long', 
                day: 'numeric' 
              })}
            </option>
          ))}
        </select>
      </div>

      {/* Grid */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ 
                padding: '8px', 
                border: '1px solid #ddd', 
                backgroundColor: '#f5f5f5',
                textAlign: 'left',
                position: 'sticky',
                left: 0,
                zIndex: 10,
              }}>
                Time
              </th>
              {courtLabels.map(courtLabel => (
                <th
                  key={courtLabel}
                  style={{
                    padding: '8px',
                    border: '1px solid #ddd',
                    backgroundColor: '#f5f5f5',
                    textAlign: 'center',
                    minWidth: '120px',
                  }}
                >
                  {courtLabel}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {daySlots.map(({ time, slotsByCourtLabel }, idx) => (
              <tr key={`${time}-${idx}`}>
                <td style={{
                  padding: '8px',
                  border: '1px solid #ddd',
                  backgroundColor: '#fafafa',
                  fontWeight: '500',
                  position: 'sticky',
                  left: 0,
                  zIndex: 5,
                }}>
                  {timeTo12Hour(time)}
                </td>
                {courtLabels.map(courtLabel => {
                  const slot = slotsByCourtLabel.get(courtLabel)
                  const match = slot ? getMatchForSlot(slot) : null
                  const event = getEventForMatch(match)
                  
                  return (
                    <td
                      key={courtLabel}
                      style={{
                        padding: '4px',
                        border: '1px solid #ddd',
                        cursor: readOnly ? 'default' : 'pointer',
                        backgroundColor: match ? '#e8f5e9' : '#fff',
                        minHeight: '40px',
                      }}
                      onClick={() => {
                        if (!readOnly && slot) {
                          onSlotClick(slot)
                        }
                      }}
                    >
                      {match ? (
                        <div style={{ fontSize: '12px' }}>
                          <div style={{ fontWeight: 'bold' }}>{match.match_code}</div>
                          <div style={{ fontSize: '11px', color: '#666' }}>
                            {event?.name} • {match.match_type}
                          </div>
                        </div>
                      ) : slot ? (
                        <div style={{ fontSize: '11px', color: '#999', fontStyle: 'italic' }}>
                          Empty
                        </div>
                      ) : null}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


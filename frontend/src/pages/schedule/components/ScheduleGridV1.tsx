import React, { useMemo, useState } from 'react'
import { ScheduleGridV1, GridSlot, GridMatch, GridAssignment, TeamInfo } from '../../../api/client'
import { timeTo12Hour } from '../../../utils/timeFormat'

interface ScheduleGridV1Props {
  gridData: ScheduleGridV1 | null
  readOnly: boolean
  onSlotClick?: (slotId: number, matchId: number | null) => void
}

interface DayGridData {
  dayDate: string
  timeRows: TimeRow[]
  courts: string[]
}

interface TimeRow {
  time: string
  slotsByCourt: Map<string, GridSlot>
}

export const ScheduleGridV1Viewer: React.FC<ScheduleGridV1Props> = ({
  gridData,
  readOnly,
  onSlotClick,
}) => {
  const [selectedDay, setSelectedDay] = useState<string | null>(null)

  // Build lookup maps
  const assignmentMap = useMemo(() => {
    if (!gridData) return new Map<number, GridAssignment>()
    const map = new Map<number, GridAssignment>()
    gridData.assignments.forEach(a => map.set(a.slot_id, a))
    return map
  }, [gridData])

  const matchMap = useMemo(() => {
    if (!gridData) return new Map<number, GridMatch>()
    const map = new Map<number, GridMatch>()
    gridData.matches.forEach(m => map.set(m.match_id, m))
    return map
  }, [gridData])

  // Build team lookup map
  const teamMap = useMemo(() => {
    if (!gridData) return new Map<number, TeamInfo>()
    const map = new Map<number, TeamInfo>()
    gridData.teams.forEach(t => map.set(t.id, t))
    return map
  }, [gridData])

  // Build day grid data
  const dayGridData = useMemo((): DayGridData[] => {
    if (!gridData) return []

    // Group slots by day
    const dayGroups = new Map<string, GridSlot[]>()
    gridData.slots.forEach(slot => {
      if (!dayGroups.has(slot.day_date)) {
        dayGroups.set(slot.day_date, [])
      }
      dayGroups.get(slot.day_date)!.push(slot)
    })

    // Build structured data for each day
    const result: DayGridData[] = []
    
    for (const [dayDate, slots] of Array.from(dayGroups.entries()).sort(([a], [b]) => a.localeCompare(b))) {
      // Get unique courts for this day (sorted by court_id)
      const courtSet = new Map<string, number>()
      slots.forEach(s => {
        if (!courtSet.has(s.court_label)) {
          courtSet.set(s.court_label, s.court_id)
        }
      })
      const courts = Array.from(courtSet.entries())
        .sort(([, idA], [, idB]) => idA - idB)
        .map(([label]) => label)

      // Group slots by time
      const timeGroups = new Map<string, GridSlot[]>()
      slots.forEach(slot => {
        if (!timeGroups.has(slot.start_time)) {
          timeGroups.set(slot.start_time, [])
        }
        timeGroups.get(slot.start_time)!.push(slot)
      })

      // Build time rows
      const timeRows: TimeRow[] = Array.from(timeGroups.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([time, timeSlots]) => {
          const slotsByCourt = new Map<string, GridSlot>()
          timeSlots.forEach(slot => {
            slotsByCourt.set(slot.court_label, slot)
          })
          return { time, slotsByCourt }
        })

      result.push({ dayDate, timeRows, courts })
    }

    return result
  }, [gridData])

  // Set default day
  React.useEffect(() => {
    if (dayGridData.length > 0 && !selectedDay) {
      setSelectedDay(dayGridData[0].dayDate)
    }
  }, [dayGridData, selectedDay])

  // Get selected day data
  const selectedDayData = useMemo(() => {
    return dayGridData.find(d => d.dayDate === selectedDay) || null
  }, [dayGridData, selectedDay])

  // Get match for a slot
  const getMatchForSlot = (slot: GridSlot): GridMatch | null => {
    const assignment = assignmentMap.get(slot.slot_id)
    if (!assignment) return null
    return matchMap.get(assignment.match_id) || null
  }

  // Format stage label
  const getStageLabel = (stage: string): string => {
    const labels: Record<string, string> = {
      'WF': 'WF',
      'MAIN': 'MAIN',
      'CONSOLATION': 'CONS',
      'PLACEMENT': 'PLCMT'
    }
    return labels[stage] || stage
  }

  // Get team label (name or fallback)
  const getTeamLabel = (teamId: number | null, placeholder: string): string => {
    if (teamId === null) {
      return placeholder
    }
    const team = teamMap.get(teamId)
    if (team) {
      return team.name
    }
    // Fallback if team not found in map
    return `Team #${teamId}`
  }

  const handleSlotClickInternal = (slot: GridSlot) => {
    if (readOnly || !onSlotClick) return
    const assignment = assignmentMap.get(slot.slot_id)
    onSlotClick(slot.slot_id, assignment?.match_id || null)
  }

  if (!gridData) {
    return (
      <div className="card" style={{ padding: '24px', textAlign: 'center', color: '#666' }}>
        No grid data available
      </div>
    )
  }

  if (dayGridData.length === 0) {
    return (
      <div className="card" style={{ padding: '24px', textAlign: 'center', color: '#666' }}>
        No slots generated yet. Click "Build Schedule" to get started.
      </div>
    )
  }

  return (
    <div className="schedule-grid-container">
      {/* Day Tabs */}
      <div className="day-tabs" style={{ 
        display: 'flex', 
        gap: '8px', 
        marginBottom: '16px', 
        borderBottom: '1px solid #e0e0e0',
        paddingBottom: '8px'
      }}>
        {dayGridData.map(day => (
          <button
            key={day.dayDate}
            onClick={() => setSelectedDay(day.dayDate)}
            className={selectedDay === day.dayDate ? 'active' : ''}
            style={{
              padding: '8px 16px',
              border: 'none',
              borderBottom: selectedDay === day.dayDate ? '2px solid #2196F3' : '2px solid transparent',
              background: 'none',
              cursor: 'pointer',
              fontWeight: selectedDay === day.dayDate ? 'bold' : 'normal',
              color: selectedDay === day.dayDate ? '#2196F3' : '#666'
            }}
          >
            {new Date(day.dayDate + 'T00:00:00').toLocaleDateString('en-US', { 
              weekday: 'short', 
              month: 'short', 
              day: 'numeric' 
            })}
          </button>
        ))}
      </div>

      {/* Grid */}
      {selectedDayData && (
        <div className="schedule-grid" style={{ overflowX: 'auto' }}>
          <table style={{ 
            width: '100%', 
            borderCollapse: 'collapse',
            fontSize: '13px'
          }}>
            <thead>
              <tr>
                <th style={{ 
                  position: 'sticky', 
                  left: 0, 
                  background: '#f5f5f5', 
                  padding: '12px 8px',
                  textAlign: 'left',
                  borderBottom: '2px solid #ddd',
                  minWidth: '80px',
                  zIndex: 2
                }}>
                  Time
                </th>
                {selectedDayData.courts.map(court => (
                  <th key={court} style={{ 
                    padding: '12px 8px',
                    textAlign: 'center',
                    borderBottom: '2px solid #ddd',
                    background: '#f5f5f5',
                    minWidth: '140px'
                  }}>
                    {court}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {selectedDayData.timeRows.map(row => (
                <tr key={row.time}>
                  <td style={{ 
                    position: 'sticky', 
                    left: 0, 
                    background: '#fff', 
                    padding: '8px',
                    borderBottom: '1px solid #eee',
                    fontWeight: '500',
                    whiteSpace: 'nowrap',
                    zIndex: 1
                  }}>
                    {timeTo12Hour(row.time)}
                  </td>
                  {selectedDayData.courts.map(court => {
                    const slot = row.slotsByCourt.get(court)
                    if (!slot) {
                      return (
                        <td key={court} style={{ 
                          padding: '8px',
                          borderBottom: '1px solid #eee',
                          textAlign: 'center',
                          color: '#999'
                        }}>
                          -
                        </td>
                      )
                    }

                    const match = getMatchForSlot(slot)
                    const isAssigned = match !== null

                    return (
                      <td
                        key={court}
                        onClick={() => handleSlotClickInternal(slot)}
                        style={{ 
                          padding: '4px',
                          borderBottom: '1px solid #eee',
                          cursor: readOnly ? 'default' : 'pointer',
                          background: isAssigned ? '#e3f2fd' : '#fff'
                        }}
                      >
                        <div style={{
                          padding: '8px',
                          borderRadius: '4px',
                          border: isAssigned ? '1px solid #90caf9' : '1px solid #e0e0e0',
                          minHeight: '50px',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '4px'
                        }}>
                          <div style={{ fontSize: '11px', color: '#666' }}>
                            {slot.duration_minutes}min
                          </div>
                          {isAssigned && match ? (
                            <>
                              <div style={{ 
                                fontWeight: 'bold',
                                color: '#1976d2',
                                fontSize: '12px'
                              }}>
                                {getStageLabel(match.stage)} R{match.round_index} #{match.sequence_in_round}
                              </div>
                              <div style={{ 
                                fontSize: '10px', 
                                color: '#999',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                marginBottom: '4px'
                              }}>
                                {match.match_code}
                              </div>
                              <div style={{ 
                                fontSize: '11px', 
                                color: '#333',
                                lineHeight: '1.3'
                              }}>
                                {getTeamLabel(match.team_a_id, match.placeholder_side_a)}
                              </div>
                              <div style={{ 
                                fontSize: '10px', 
                                color: '#999',
                                textAlign: 'center',
                                margin: '2px 0'
                              }}>
                                vs
                              </div>
                              <div style={{ 
                                fontSize: '11px', 
                                color: '#333',
                                lineHeight: '1.3'
                              }}>
                                {getTeamLabel(match.team_b_id, match.placeholder_side_b)}
                              </div>
                              <div style={{ fontSize: '10px', color: '#999', marginTop: '4px' }}>
                                {match.duration_minutes}min
                              </div>
                            </>
                          ) : (
                            <div style={{ 
                              color: '#999',
                              fontStyle: 'italic',
                              fontSize: '12px'
                            }}>
                              Open
                            </div>
                          )}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


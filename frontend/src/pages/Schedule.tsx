import { useEffect, useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getTournament,
  getEvents,
  getScheduleVersions,
  createScheduleVersion,
  finalizeScheduleVersion,
  deleteScheduleVersion,
  generateSlots,
  getSlots,
  generateMatches,
  getMatches,
  createAssignment,
  deleteAssignment,
  Tournament,
  Event,
  ScheduleVersion,
  ScheduleSlot,
  Match,
} from '../api/client'
import { showToast } from '../utils/toast'
import { confirmDialog } from '../utils/confirm'
import { timeTo12Hour, minutesToClock } from '../utils/timeFormat'
import { getCellSpan } from '../utils/gridHelper'
import './TournamentSetup.css'

function Schedule() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id) : null

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [currentVersion, setCurrentVersion] = useState<ScheduleVersion | null>(null)
  const [slots, setSlots] = useState<ScheduleSlot[]>([])
  const [matches, setMatches] = useState<Match[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [selectedCell, setSelectedCell] = useState<{ dayDate: string; timeSlot: string; courtNumber: number } | null>(null)
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null)

  // Helper function to get court display name
  const getCourtName = (courtIndex: number): string => {
    if (tournament?.court_names && tournament.court_names.length > 0) {
      return tournament.court_names[courtIndex] || `Court ${courtIndex + 1}`
    }
    return `Court ${courtIndex + 1}`
  }

  useEffect(() => {
    if (tournamentId) {
      loadData()
    }
  }, [tournamentId])

  const loadData = async () => {
    if (!tournamentId) return
    
    try {
      setLoading(true)
      const [tournamentData, eventsData] = await Promise.all([
        getTournament(tournamentId),
        getEvents(tournamentId),
      ])
      
      setTournament(tournamentData)
      setEvents(eventsData)
      
      try {
        const versionsData = await getScheduleVersions(tournamentId)
        setVersions(versionsData)
        
        const draft = versionsData.find(v => v.status === 'draft')
        if (draft) {
          setCurrentVersion(draft)
        } else if (versionsData.length > 0) {
          setCurrentVersion(versionsData[0])
        } else {
          setCurrentVersion(null)
        }
      } catch (versionsErr) {
        console.warn('Failed to load schedule versions:', versionsErr)
        setVersions([])
        setCurrentVersion(null)
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load data', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (currentVersion) {
      loadSlotsAndMatches()
    }
  }, [currentVersion, tournamentId])

  const loadSlotsAndMatches = async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      const [slotsData, matchesData] = await Promise.all([
        getSlots(tournamentId, currentVersion.id),
        getMatches(tournamentId, currentVersion.id),
      ])
      
      setSlots(slotsData)
      setMatches(matchesData)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load slots/matches', 'error')
    }
  }

  const handleCreateDraft = async () => {
    if (!tournamentId) return
    
    try {
      const version = await createScheduleVersion(tournamentId)
      setVersions(prev => [version, ...prev])
      setCurrentVersion(version)
      showToast('Draft schedule version created', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to create draft', 'error')
    }
  }

  const handleDeleteVersion = async () => {
    if (!tournamentId || !currentVersion) return
    
    const confirmed = await confirmDialog(
      `Are you sure you want to delete Version ${currentVersion.version_number}?\n\nThis will permanently delete all associated data.`
    )
    if (!confirmed) return
    
    try {
      await deleteScheduleVersion(tournamentId, currentVersion.id)
      showToast('Schedule version deleted successfully', 'success')
      setCurrentVersion(null)
      await loadData()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to delete schedule version', 'error')
    }
  }

  const handleFinalize = async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      const finalized = await finalizeScheduleVersion(tournamentId, currentVersion.id)
      setVersions(prev => prev.map(v => v.id === finalized.id ? finalized : v))
      setCurrentVersion(finalized)
      showToast('Schedule finalized', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to finalize schedule', 'error')
    }
  }

  const handleGenerateSlots = async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      setGenerating(true)
      const result = await generateSlots(tournamentId, {
        source: 'auto',
        schedule_version_id: currentVersion.id,
        wipe_existing: true,
      })
      showToast(`Generated ${result.slots_created} slots`, 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to generate slots', 'error')
    } finally {
      setGenerating(false)
    }
  }

  const handleGenerateMatches = async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      setGenerating(true)
      const result = await generateMatches(tournamentId, {
        schedule_version_id: currentVersion.id,
        wipe_existing: true,
      })
      showToast(`Generated ${result.total_matches_created} matches`, 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to generate matches', 'error')
    } finally {
      setGenerating(false)
    }
  }

  const handleAssignMatch = async (matchId: number, dayDate: string, startTime: string, courtNumber: number) => {
    if (!tournamentId || !currentVersion) return
    
    try {
      const match = matches.find(m => m.id === matchId)
      if (!match) {
        showToast('Match not found', 'error')
        return
      }

      // Find the slot that starts at this exact time
      const [cellHour, cellMin] = startTime.split(':').map(Number)
      const slot = slots.find(s => {
        if (s.day_date !== dayDate || s.court_number !== courtNumber) return false
        const sParts = s.start_time.split(':')
        return Number(sParts[0]) === cellHour && Number(sParts[1]) === cellMin
      })
      
      if (!slot) {
        showToast(`No slot found at ${startTime} on court ${courtNumber}`, 'error')
        return
      }

      // Check if enough consecutive slots exist
      const span = getCellSpan(match.duration_minutes)
      const slotStartParts = slot.start_time.split(':')
      const slotStartMinutes = Number(slotStartParts[0]) * 60 + Number(slotStartParts[1])
      
      for (let i = 0; i < span; i++) {
        const checkMinutes = slotStartMinutes + (i * 30)
        const checkHour = Math.floor(checkMinutes / 60)
        const checkMin = checkMinutes % 60
        const checkTime = `${String(checkHour).padStart(2, '0')}:${String(checkMin).padStart(2, '0')}`
        
        const checkSlot = slots.find(s => {
          if (s.day_date !== dayDate || s.court_number !== courtNumber) return false
          const sParts = s.start_time.split(':')
          return Number(sParts[0]) === checkHour && Number(sParts[1]) === checkMin
        })
        
        if (!checkSlot) {
          showToast(`Not enough consecutive slots. Need ${span} slots starting at ${startTime}`, 'error')
          return
        }
        
        if (checkSlot.match_id && checkSlot.match_id !== matchId) {
          showToast(`Slot at ${checkTime} is already assigned`, 'error')
          return
        }
      }
      
      await createAssignment(tournamentId, {
        schedule_version_id: currentVersion.id,
        match_id: matchId,
        slot_id: slot.id,
      })
      showToast('Match assigned', 'success')
      setSelectedCell(null)
      setSelectedMatch(null)
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to assign match', 'error')
    }
  }

  const handleUnassign = async (assignmentId: number) => {
    if (!tournamentId) return
    
    try {
      await deleteAssignment(tournamentId, assignmentId)
      showToast('Match unassigned', 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to unassign match', 'error')
    }
  }

  // Filter unscheduled matches
  const unscheduledMatches = useMemo(() => {
    return matches.filter(m => m.status === 'unscheduled')
  }, [matches])

  // Generate grid from slots
  const gridData = useMemo(() => {
    if (slots.length === 0) return null

    // Group slots by day
    const byDay: Record<string, ScheduleSlot[]> = {}
    for (const slot of slots) {
      if (!byDay[slot.day_date]) {
        byDay[slot.day_date] = []
      }
      byDay[slot.day_date].push(slot)
    }

    const days: Array<{
      date: string
      timeSlots: string[]
      maxCourts: number
      slotsByTime: Record<string, ScheduleSlot[]>
    }> = []

    for (const [dayDate, daySlots] of Object.entries(byDay)) {
      const timeSlots = new Set<string>()
      let maxCourts = 0
      const slotsByTime: Record<string, ScheduleSlot[]> = {}

      for (const slot of daySlots) {
        const timeParts = slot.start_time.split(':')
        const timeSlot = `${timeParts[0]}:${timeParts[1]}`
        timeSlots.add(timeSlot)
        maxCourts = Math.max(maxCourts, slot.court_number)
        
        if (!slotsByTime[timeSlot]) {
          slotsByTime[timeSlot] = []
        }
        slotsByTime[timeSlot].push(slot)
      }

      days.push({
        date: dayDate,
        timeSlots: Array.from(timeSlots).sort(),
        maxCourts,
        slotsByTime,
      })
    }

    return days.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  }, [slots])

  // Map matches to slots
  const matchAssignments = useMemo(() => {
    const assignments: Record<string, { match: Match; slot: ScheduleSlot; span: number }> = {}
    
    for (const slot of slots) {
      if (!slot.match_id) continue
      const match = matches.find(m => m.id === slot.match_id)
      if (!match) continue
      
      const span = getCellSpan(match.duration_minutes)
      const timeParts = slot.start_time.split(':')
      const timeSlot = `${timeParts[0]}:${timeParts[1]}`
      const cellKey = `${slot.day_date}-${timeSlot}-${slot.court_number}`
      
      assignments[cellKey] = { match, slot, span }
    }
    
    return assignments
  }, [slots, matches])

  if (loading) {
    return <div className="container"><div className="loading">Loading...</div></div>
  }

  if (!tournament) {
    return <div className="container"><div>Tournament not found</div></div>
  }

  return (
    <div className="container">
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Schedule - {tournament.name}</h1>
        <button className="btn btn-secondary" onClick={() => navigate('/tournaments')}>
          ← Back to Tournaments
        </button>
      </div>

      {/* Schedule Versions */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ margin: 0 }}>Schedule Versions</h2>
          {!currentVersion && (
            <button className="btn btn-primary" onClick={handleCreateDraft}>
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
                    <button className="btn btn-success" onClick={handleFinalize} disabled={version.id !== currentVersion?.id}>
                      Finalize
                    </button>
                  )}
                  <button className="btn btn-danger" onClick={handleDeleteVersion} disabled={version.id !== currentVersion?.id}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      {currentVersion && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <h3 style={{ marginBottom: '16px' }}>Actions</h3>
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={handleGenerateSlots} disabled={generating}>
              {generating ? 'Generating...' : 'Generate Slots'}
            </button>
            <button className="btn btn-primary" onClick={handleGenerateMatches} disabled={generating}>
              {generating ? 'Generating...' : 'Generate Matches'}
            </button>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div style={{ display: 'flex', gap: '24px', alignItems: 'flex-start' }}>
        {/* Left Panel: Unscheduled Matches */}
        <div style={{ width: '300px', flexShrink: 0 }}>
          <div className="card">
            <h3 style={{ marginBottom: '16px' }}>Unscheduled Matches</h3>
            <div style={{ maxHeight: '600px', overflowY: 'auto' }}>
              {unscheduledMatches.length === 0 ? (
                <div style={{ padding: '16px', textAlign: 'center', color: '#666' }}>
                  No unscheduled matches
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {unscheduledMatches.map(match => {
                    const event = events.find(e => e.id === match.event_id)
                    return (
                      <div
                        key={match.id}
                        style={{
                          padding: '8px',
                          border: '1px solid #ddd',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          backgroundColor: selectedMatch?.id === match.id ? '#e3f2fd' : 'white',
                        }}
                        onClick={() => setSelectedMatch(match)}
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
        </div>

        {/* Main Panel: Schedule Grid */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="card">
            <h3 style={{ marginBottom: '16px' }}>Schedule Grid</h3>
            
            {!gridData || gridData.length === 0 ? (
              <div style={{ padding: '32px', textAlign: 'center', color: '#666' }}>
                {slots.length === 0 
                  ? 'No slots generated. Click "Generate Slots" to create schedule slots.'
                  : 'No grid data available.'}
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                {gridData.map((day) => (
                  <div key={day.date} style={{ marginBottom: '32px' }}>
                    <h4 style={{ marginBottom: '12px', fontSize: '16px', fontWeight: 'bold' }}>
                      {new Date(day.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                    </h4>
                    
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', border: '1px solid #000' }}>
                      <thead>
                        <tr>
                          <th style={{ padding: '8px', textAlign: 'left', borderBottom: '2px solid #000', borderRight: '1px solid #000', width: '120px', backgroundColor: '#f5f5f5' }}>
                            Time
                          </th>
                          {Array.from({ length: day.maxCourts }, (_, i) => (
                            <th key={i} style={{ padding: '8px', textAlign: 'center', borderBottom: '2px solid #000', borderRight: '1px solid #000', minWidth: '100px', backgroundColor: '#f5f5f5' }}>
                              {getCourtName(i)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {day.timeSlots.map((timeSlot, timeIndex) => {
                          const displayTime = timeTo12Hour(timeSlot)
                          
                          return (
                            <tr key={timeSlot}>
                              <td style={{ padding: '8px', borderBottom: '1px solid #000', borderRight: '1px solid #000', fontWeight: '500', backgroundColor: '#f5f5f5' }}>
                                {displayTime}
                              </td>
                              {Array.from({ length: day.maxCourts }, (_, courtIndex) => {
                                const courtNumber = courtIndex + 1
                                const cellKey = `${day.date}-${timeSlot}-${courtNumber}`
                                const assignment = matchAssignments[cellKey]
                                
                                // Skip rendering if this cell is part of a multi-cell match (not the first cell)
                                if (assignment && assignment.span > 1) {
                                  const isFirstCell = timeIndex === 0 || (() => {
                                    const prevTimeSlot = day.timeSlots[timeIndex - 1]
                                    const prevCellKey = `${day.date}-${prevTimeSlot}-${courtNumber}`
                                    return !matchAssignments[prevCellKey] || matchAssignments[prevCellKey].match.id !== assignment.match.id
                                  })()
                                  
                                  if (!isFirstCell) {
                                    return null
                                  }
                                }
                                
                                return (
                                  <td
                                    key={courtIndex}
                                    style={{
                                      padding: '4px',
                                      borderBottom: '1px solid #000',
                                      borderRight: '1px solid #000',
                                      cursor: 'pointer',
                                      backgroundColor: assignment ? '#e8f5e9' : 'white',
                                      height: '40px',
                                      position: 'relative',
                                      verticalAlign: 'top',
                                    }}
                                    onClick={() => setSelectedCell({ dayDate: day.date, timeSlot, courtNumber })}
                                  >
                                    {assignment ? (
                                      <div
                                        style={{
                                          fontSize: '10px',
                                          fontWeight: 'bold',
                                          padding: '4px',
                                          backgroundColor: '#4caf50',
                                          color: 'white',
                                          borderRadius: '2px',
                                          height: assignment.span > 1 ? `${assignment.span * 40 - 8}px` : 'auto',
                                          display: 'flex',
                                          flexDirection: 'column',
                                          justifyContent: 'center',
                                        }}
                                      >
                                        <div>{assignment.match.match_code}</div>
                                        <div style={{ fontSize: '9px', marginTop: '2px', opacity: 0.9 }}>
                                          {events.find(e => e.id === assignment.match.event_id)?.name}
                                        </div>
                                        <div style={{ fontSize: '8px', marginTop: '2px', opacity: 0.8 }}>
                                          {minutesToClock(assignment.match.duration_minutes)}
                                        </div>
                                      </div>
                                    ) : (
                                      <div style={{ height: '32px' }}></div>
                                    )}
                                  </td>
                                )
                              })}
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Assignment Modal */}
      {selectedCell && (
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
          onClick={() => setSelectedCell(null)}
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
              {matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`] 
                ? 'Match Details' 
                : 'Assign Match'}
            </h3>
            
            <div style={{ marginBottom: '16px' }}>
              <strong>Cell:</strong> {new Date(selectedCell.dayDate + 'T12:00:00').toLocaleDateString()} • {timeTo12Hour(selectedCell.timeSlot)} • {getCourtName(selectedCell.courtNumber - 1)}
            </div>
            
            {matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`] ? (
              <div>
                <div style={{ marginBottom: '16px' }}>
                  <strong>Assigned Match:</strong>
                  <div style={{ marginTop: '8px', padding: '12px', backgroundColor: '#f5f5f5', borderRadius: '4px' }}>
                    <div><strong>{matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`].match.match_code}</strong></div>
                    <div style={{ fontSize: '14px', color: '#666', marginTop: '4px' }}>
                      {events.find(e => e.id === matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`].match.event_id)?.name} • {matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`].match.match_type} • {minutesToClock(matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`].match.duration_minutes)}
                    </div>
                  </div>
                </div>
                {matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`].slot.assignment_id && (
                  <button
                    className="btn btn-danger"
                    onClick={async () => {
                      await handleUnassign(matchAssignments[`${selectedCell.dayDate}-${selectedCell.timeSlot}-${selectedCell.courtNumber}`].slot.assignment_id!)
                      setSelectedCell(null)
                    }}
                  >
                    Unassign Match
                  </button>
                )}
              </div>
            ) : (
              <div>
                <label style={{ display: 'block', marginBottom: '8px' }}>
                  <strong>Select Match:</strong>
                </label>
                <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid #ddd', borderRadius: '4px' }}>
                  {unscheduledMatches.map(match => {
                    const event = events.find(e => e.id === match.event_id)
                    return (
                      <div
                        key={match.id}
                        style={{
                          padding: '12px',
                          borderBottom: '1px solid #eee',
                          cursor: 'pointer',
                          backgroundColor: selectedMatch?.id === match.id ? '#e3f2fd' : 'white',
                        }}
                        onClick={() => setSelectedMatch(match)}
                      >
                        <div style={{ fontWeight: 'bold' }}>{match.match_code}</div>
                        <div style={{ fontSize: '14px', color: '#666' }}>
                          {event?.name} • {match.match_type} • {minutesToClock(match.duration_minutes)}
                        </div>
                      </div>
                    )
                  })}
                </div>
                
                {unscheduledMatches.length === 0 && (
                  <div style={{ padding: '16px', textAlign: 'center', color: '#666' }}>
                    No unscheduled matches available
                  </div>
                )}
                
                <div style={{ marginTop: '16px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  <button className="btn btn-secondary" onClick={() => setSelectedCell(null)}>
                    Cancel
                  </button>
                  {selectedMatch && (
                    <button
                      className="btn btn-primary"
                      onClick={() => {
                        handleAssignMatch(selectedMatch.id, selectedCell.dayDate, selectedCell.timeSlot, selectedCell.courtNumber)
                      }}
                    >
                      Assign Match
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Schedule

import React, { useMemo, useCallback } from 'react'
import { List } from 'react-window'
import { ScheduleSlot, Match, Event, Tournament } from '../../../api/client'
import { timeTo12Hour } from '../../../utils/timeFormat'
import { getCellSpan } from '../../../utils/gridHelper'

interface ScheduleGridVirtualProps {
  slots: ScheduleSlot[]
  matches: Match[]
  events: Event[]
  tournament: Tournament | null
  readOnly: boolean
  onSlotClick: (slot: ScheduleSlot) => void
}

interface GridRow {
  dayDate: string
  timeSlot: string
  slotsByCourtLabel: Map<string, ScheduleSlot>
  courtLabels: string[]
}

interface RowProps {
  rows: GridRow[]
  matches: Match[]
  events: Event[]
  tournament: Tournament | null
  readOnly: boolean
  onSlotClick: (slot: ScheduleSlot) => void
  getMatchAssignment: (slot: ScheduleSlot) => { match: Match; span: number } | null
}

const GridRowComponent = ({ index, style, rows, events, readOnly, onSlotClick, getMatchAssignment }: { index: number; style: React.CSSProperties; ariaAttributes: { "aria-posinset": number; "aria-setsize": number; role: "listitem" } } & RowProps): React.ReactElement => {
  const row = rows[index]
  
  if (!row) {
    return <div style={style}></div>
  }

  const displayTime = timeTo12Hour(row.timeSlot)
  const dayLabel = new Date(row.dayDate + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })

  return (
    <div style={style}>
      <div style={{ display: 'flex', borderBottom: '1px solid #000' }}>
        {/* Time column */}
        <div className="schedule-grid-time-column" style={{ 
          width: '150px', 
          padding: '8px', 
          borderRight: '1px solid #000', 
          backgroundColor: '#f5f5f5',
          fontWeight: '500',
          flexShrink: 0,
        }}>
          {index === 0 || rows[index - 1]?.dayDate !== row.dayDate ? (
            <div>
              <div className="schedule-grid-time-label" style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '4px' }}>{dayLabel}</div>
              <div className="schedule-grid-time-label">{displayTime}</div>
            </div>
          ) : (
            <div className="schedule-grid-time-label">{displayTime}</div>
          )}
        </div>
        
        {/* Court cells */}
        <div style={{ display: 'flex', flex: 1 }}>
          {row.courtLabels.map((courtLabel) => {
            const slot = row.slotsByCourtLabel.get(courtLabel)
            
            if (!slot) {
              return (
                <div
                  key={courtLabel}
                  style={{
                    flex: 1,
                    minWidth: '100px',
                    padding: '4px',
                    borderRight: '1px solid #000',
                    height: '40px',
                  }}
                />
              )
            }

            const assignment = getMatchAssignment(slot)
            
            // Check if this is the first cell of a multi-cell match
            let isFirstCell = true
            if (assignment && assignment.span > 1 && index > 0) {
              // Check previous rows to see if this match started earlier
              for (let prevIdx = index - 1; prevIdx >= Math.max(0, index - assignment.span); prevIdx--) {
                const prevRow = rows[prevIdx]
                const prevSlot = prevRow?.slotsByCourtLabel.get(courtLabel)
                if (prevSlot) {
                  const prevAssignment = getMatchAssignment(prevSlot)
                  if (prevAssignment && prevAssignment.match.id === assignment.match.id) {
                    isFirstCell = false
                    break
                  }
                }
              }
            }

            // Skip rendering if not first cell of multi-cell match
            if (assignment && assignment.span > 1 && !isFirstCell) {
              return null
            }

            return (
              <div
                key={courtLabel}
                style={{
                  flex: 1,
                  minWidth: '100px',
                  padding: '4px',
                  borderRight: '1px solid #000',
                  cursor: readOnly ? 'default' : 'pointer',
                  backgroundColor: assignment ? '#e8f5e9' : 'white',
                  height: assignment && assignment.span > 1 ? `${assignment.span * 40}px` : '40px',
                  position: 'relative',
                }}
                onClick={() => !readOnly && onSlotClick(slot)}
              >
                {assignment ? (
                  <div
                    style={{
                      fontSize: '10px',
                      fontWeight: 'bold',
                      padding: '4px',
                      backgroundColor: '#4caf50',
                      color: '#fff',
                      borderRadius: '2px',
                      height: '100%',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'center',
                    }}
                  >
                    <div style={{ color: '#fff' }}>{assignment.match.match_code}</div>
                    <div style={{ fontSize: '9px', marginTop: '2px', color: '#fff' }}>
                      {events.find(e => e.id === assignment.match.event_id)?.name}
                    </div>
                  </div>
                ) : (
                  <div style={{ height: '32px' }}></div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export const ScheduleGridVirtual: React.FC<ScheduleGridVirtualProps> = React.memo(({
  slots,
  matches,
  events,
  tournament,
  readOnly,
  onSlotClick,
}) => {
  // Get all unique court labels from slots, sorted by court_number for consistent ordering
  const allCourtLabels = useMemo(() => {
    const courtMap = new Map<string, { label: string; number: number }>()
    slots.forEach(slot => {
      if (!courtMap.has(slot.court_label)) {
        courtMap.set(slot.court_label, {
          label: slot.court_label,
          number: slot.court_number,
        })
      }
    })
    return Array.from(courtMap.values())
      .sort((a, b) => a.number - b.number)
      .map(c => c.label)
  }, [slots])

  // Get court labels from slots (already sorted by court_number)
  const courtLabels = useMemo(() => {
    return allCourtLabels
  }, [allCourtLabels])

  const getMatchAssignment = (slot: ScheduleSlot): { match: Match; span: number } | null => {
    if (!slot.match_id) return null
    const match = matches.find(m => m.id === slot.match_id)
    if (!match) return null
    
    const span = getCellSpan(match.duration_minutes)
    return { match, span }
  }

  const rows = useMemo(() => {
    if (slots.length === 0) return []

    // Group slots by day and time
    const byDayTime: Record<string, Map<string, ScheduleSlot>> = {}

    for (const slot of slots) {
      const timeParts = slot.start_time.split(':')
      const timeSlot = `${timeParts[0]}:${timeParts[1]}`
      const key = `${slot.day_date}|${timeSlot}`
      
      if (!byDayTime[key]) {
        byDayTime[key] = new Map()
      }
      byDayTime[key].set(slot.court_label, slot)
    }

    // Convert to array of rows
    const rowArray: GridRow[] = []
    for (const [key, slotsMap] of Object.entries(byDayTime)) {
      const [dayDate, timeSlot] = key.split('|')
      rowArray.push({
        dayDate,
        timeSlot,
        slotsByCourtLabel: slotsMap,
        courtLabels: allCourtLabels,
      })
    }

    // Sort by date then time
    return rowArray.sort((a, b) => {
      const dateCompare = new Date(a.dayDate).getTime() - new Date(b.dayDate).getTime()
      if (dateCompare !== 0) return dateCompare
      return a.timeSlot.localeCompare(b.timeSlot)
    })
  }, [slots, allCourtLabels])

  // Calculate row heights (40px base, but taller if match spans multiple cells)
  const getRowHeight = useCallback((index: number): number => {
    const row = rows[index]
    if (!row) return 40
    
    // Check if any slot in this row has a multi-cell match
    let maxSpan = 1
    for (const slot of row.slotsByCourtLabel.values()) {
      const assignment = getMatchAssignment(slot)
      if (assignment && assignment.span > maxSpan) {
        maxSpan = assignment.span
      }
    }
    
    return maxSpan * 40
  }, [rows, getMatchAssignment])

  const rowProps = useMemo(() => ({
    rows,
    matches,
    events,
    tournament,
    readOnly,
    onSlotClick,
    getMatchAssignment,
  }), [rows, matches, events, tournament, readOnly, onSlotClick, getMatchAssignment])

  if (rows.length === 0) {
    return (
      <div className="card" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', color: '#000' }}>
          {slots.length === 0 
            ? 'No slots generated. Click "Generate Slots" to create schedule slots.'
            : 'No grid data available.'}
        </div>
      </div>
    )
  }

  return (
    <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h3 style={{ marginBottom: '16px', color: '#000' }}>Schedule Grid</h3>
      
      {/* Header */}
      <div className="schedule-grid-header" style={{ display: 'flex', flexShrink: 0 }}>
        <div className="schedule-grid-time-label" style={{ width: '150px', padding: '8px', borderRight: '1px solid #000', flexShrink: 0 }}>
          Time
        </div>
        <div style={{ display: 'flex', flex: 1 }}>
          {courtLabels.map((courtLabel) => (
            <div
              key={courtLabel}
              className="schedule-grid-court-label"
              style={{
                flex: 1,
                minWidth: '100px',
                padding: '8px',
                borderRight: '1px solid #000',
              }}
            >
              {courtLabel}
            </div>
          ))}
        </div>
      </div>

      {/* Virtualized list */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <List
          defaultHeight={600}
          rowCount={rows.length}
          rowHeight={getRowHeight}
          rowProps={rowProps}
          rowComponent={GridRowComponent}
        />
      </div>
    </div>
  )
})

ScheduleGridVirtual.displayName = 'ScheduleGridVirtual'


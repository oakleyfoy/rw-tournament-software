import React, { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useScheduleAutoBuild } from './hooks/useScheduleAutoBuild'
import { ScheduleHeader } from './components/ScheduleHeader'
import { ScheduleBuildPanel } from './components/ScheduleBuildPanel'
import { ScheduleSummaryPanel } from './components/ScheduleSummaryPanel'
import { UnscheduledPanel } from './components/UnscheduledPanel'
import { ScheduleGridViewer } from './components/ScheduleGridViewer'
import { SlotDrawer } from './components/SlotDrawer'
import { UnscheduledMatch } from './types'
import { Match, ScheduleSlot } from '../../api/client'
import './SchedulePage.css'

function SchedulePage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id) : null

  const {
    tournament,
    events,
    versions,
    activeVersion,
    slots,
    matches,
    unscheduledMatches,
    buildSummary,
    loading,
    building,
    createDraft,
    buildSchedule,
    finalizeDraft,
    cloneFinalToDraft,
    assign,
    unassign,
    setActiveVersion,
  } = useScheduleAutoBuild(tournamentId)

  const [selectedSlot, setSelectedSlot] = useState<ScheduleSlot | null>(null)
  const [selectedMatch, setSelectedMatch] = useState<UnscheduledMatch | null>(null)

  // Get assigned match for selected slot
  const assignedMatch = useMemo(() => {
    if (!selectedSlot || !selectedSlot.match_id) return null
    return matches.find(m => m.id === selectedSlot.match_id) || null
  }, [selectedSlot, matches])

  const assignedEvent = useMemo(() => {
    if (!assignedMatch) return undefined
    return events.find(e => e.id === assignedMatch.event_id)
  }, [assignedMatch, events])

  const getCourtName = (courtIndex: number): string => {
    if (tournament?.court_names && tournament.court_names.length > 0) {
      return tournament.court_names[courtIndex] || `Court ${courtIndex + 1}`
    }
    return `Court ${courtIndex + 1}`
  }

  const handleSlotClick = (slot: ScheduleSlot) => {
    if (activeVersion?.status === 'final') return // Read-only for final versions
    setSelectedSlot(slot)
  }

  const handleAssign = async (slotId: number, matchId: number) => {
    await assign(slotId, matchId)
    setSelectedSlot(null)
    setSelectedMatch(null)
  }

  const handleUnassign = async (slotId: number) => {
    await unassign(slotId)
    setSelectedSlot(null)
  }

  const isReadOnly = activeVersion?.status === 'final' || false

  if (loading) {
    return <div className="container"><div className="loading">Loading...</div></div>
  }

  if (!tournament) {
    return <div className="container"><div>Tournament not found</div></div>
  }

  return (
    <div className="container schedule-page">
      <ScheduleHeader
        tournamentName={tournament.name}
        versions={versions}
        activeVersion={activeVersion}
        onVersionChange={setActiveVersion}
        onCreateDraft={createDraft}
        onCloneFinal={cloneFinalToDraft}
        onFinalize={finalizeDraft}
      />

      <ScheduleBuildPanel
        activeVersion={activeVersion}
        building={building}
        onBuild={buildSchedule}
        onCreateDraft={createDraft}
      />

      {buildSummary && <ScheduleSummaryPanel buildSummary={buildSummary} />}

      {/* Main Content */}
      <div style={{ display: 'flex', gap: '24px', height: 'calc(100vh - 400px)', minHeight: '500px' }}>
        {/* Left Panel: Unscheduled Matches */}
        <UnscheduledPanel
          matches={unscheduledMatches}
          events={events}
          selectedMatchId={selectedMatch?.id || null}
          onSelectMatch={setSelectedMatch}
        />

        {/* Right Panel: Schedule Grid */}
        <ScheduleGridViewer
          slots={slots}
          matches={matches}
          events={events}
          tournament={tournament}
          readOnly={isReadOnly}
          onSlotClick={handleSlotClick}
        />
      </div>

      {/* Slot Drawer */}
      {selectedSlot && (
        <SlotDrawer
          slot={selectedSlot}
          assignedMatch={assignedMatch}
          event={assignedEvent}
          unscheduledMatches={unscheduledMatches}
          events={events}
          selectedMatch={selectedMatch}
          readOnly={isReadOnly}
          onAssign={handleAssign}
          onUnassign={handleUnassign}
          onSelectMatch={setSelectedMatch}
          onClose={() => {
            setSelectedSlot(null)
            setSelectedMatch(null)
          }}
          getCourtName={getCourtName}
        />
      )}
    </div>
  )
}

export default SchedulePage

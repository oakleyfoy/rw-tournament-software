import { useParams } from 'react-router-dom'
import { useScheduleGrid } from './hooks/useScheduleGrid'
import { ScheduleHeader } from './components/ScheduleHeader'
import { ScheduleBuildPanel } from './components/ScheduleBuildPanel'
import { ScheduleSummaryPanel } from './components/ScheduleSummaryPanel'
import { ScheduleGridV1Viewer } from './components/ScheduleGridV1'
import { ConflictsBanner } from './components/ConflictsBanner'
import './SchedulePage.css'

function SchedulePageGridV1() {
  const { id } = useParams<{ id: string }>()
  const tournamentId = id ? parseInt(id) : null

  const {
    tournament,
    versions,
    activeVersion,
    gridData,
    buildSummary,
    loading,
    building,
    createDraft,
    buildSchedule,
    finalizeDraft,
    cloneFinalToDraft,
    setActiveVersion,
  } = useScheduleGrid(tournamentId)

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
        tournamentId={tournament.id}
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

      {/* Conflicts Banner */}
      {gridData?.conflicts_summary && (
        <ConflictsBanner
          summary={gridData.conflicts_summary}
          spilloverWarning={false}
        />
      )}

      {/* Main Content - Grid V1 */}
      <div className="schedule-content">
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center',
            marginBottom: '16px'
          }}>
            <h2 style={{ margin: 0 }}>Schedule Grid</h2>
            {gridData && (
              <div style={{ fontSize: '13px', color: '#666' }}>
                {gridData.slots.length} slots · {gridData.matches.length} matches · {gridData.assignments.length} assigned
              </div>
            )}
          </div>

          <ScheduleGridV1Viewer
            gridData={gridData}
            readOnly={isReadOnly}
            onSlotClick={(slotId, matchId) => {
              // TODO: Implement slot click handler for assignment/unassignment
              console.log('Slot clicked:', slotId, matchId)
            }}
          />
        </div>
      </div>
    </div>
  )
}

export default SchedulePageGridV1


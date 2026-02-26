import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useScheduleGrid } from './hooks/useScheduleGrid'
import { ScheduleHeader } from './components/ScheduleHeader'
import { SchedulePhasedPanel } from './components/SchedulePhasedPanel'
import ScheduleInventoryPanel, { type InventoryTab } from './components/ScheduleInventoryPanel'
import { AutoAssignAssistPanel } from './components/AutoAssignAssistPanel'
import { ScheduleSummaryPanel } from './components/ScheduleSummaryPanel'
import { ScheduleGridV1Viewer } from './components/ScheduleGridV1'
import { ConflictsBanner } from './components/ConflictsBanner'
import { MatchRuntimeModal } from './components/MatchRuntimeModal'
import { featureFlags, featureFlagsRaw } from '../../config/featureFlags'
import { getVersionRuntimeMatches, getActiveScheduleVersion, MatchRuntimeState } from '../../api/client'
import type { GridMatch } from '../../api/client'
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
    createDraft,
    finalizeDraft,
    cloneFinalToDraft,
    setActiveVersion,
    refresh,
  } = useScheduleGrid(tournamentId)

  const [runtimeByMatchId, setRuntimeByMatchId] = useState<Record<number, MatchRuntimeState>>({})
  const [selectedMatchForRuntime, setSelectedMatchForRuntime] = useState<{ matchId: number; match: GridMatch } | null>(null)
  const [inventoryTab, setInventoryTab] = useState<InventoryTab>('slots')
  const [inventoryRefreshKey, setInventoryRefreshKey] = useState(0)
  const [activeVersionFromBackend, setActiveVersionFromBackend] = useState<number | null>(null)

  const loadRuntimeMatches = useCallback(async () => {
    if (!tournamentId || !activeVersion?.id) {
      setRuntimeByMatchId({})
      return
    }
    try {
      const list = await getVersionRuntimeMatches(tournamentId, activeVersion.id)
      const map: Record<number, MatchRuntimeState> = {}
      list.forEach((r) => { map[r.id] = r })
      setRuntimeByMatchId(map)
    } catch {
      setRuntimeByMatchId({})
    }
  }, [tournamentId, activeVersion?.id])

  useEffect(() => {
    loadRuntimeMatches()
  }, [loadRuntimeMatches])

  // Fetch backend active version for mismatch guard
  useEffect(() => {
    if (!tournamentId) return
    getActiveScheduleVersion(tournamentId)
      .then(r => {
        if (r && !r.none_found) setActiveVersionFromBackend(r.schedule_version_id)
      })
      .catch(() => {})
  }, [tournamentId])

  const handleInventoryAction = useCallback((tab: InventoryTab) => {
    setInventoryTab(tab)
    setInventoryRefreshKey(k => k + 1)
  }, [])

  // Build eventNamesById from grid data (best-effort from match codes)
  const eventNamesById = useMemo<Record<number, string>>(() => {
    // No direct event names in grid data, so we use event IDs as fallback
    // The inventory panel gracefully shows "Event {id}" if no name is found
    return {}
  }, [])

  const usingVersionId = activeVersion?.id ?? null
  const versionMismatch = activeVersionFromBackend != null
    && usingVersionId != null
    && activeVersionFromBackend !== usingVersionId

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

      {/* ═══════ Version Guard Banner ═══════ */}
      <div style={{
        padding: '10px 16px',
        marginBottom: 16,
        borderRadius: 6,
        backgroundColor: versionMismatch ? 'rgba(220,53,69,0.1)' : 'rgba(0,0,0,0.03)',
        border: versionMismatch ? '2px solid #dc3545' : '1px solid rgba(0,0,0,0.08)',
        fontSize: 13,
        fontFamily: 'monospace',
      }}>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
          <span>Tournament: <strong>{tournamentId}</strong></span>
          <span>Active Draft Version: <strong>{activeVersionFromBackend ?? 'none'}</strong></span>
          <span>Using Version: <strong>{usingVersionId ?? 'none'}</strong></span>
          {activeVersion && (
            <span>Status: <strong>{activeVersion.status}</strong></span>
          )}
        </div>
        {versionMismatch && (
          <div style={{
            marginTop: 8,
            padding: '8px 12px',
            backgroundColor: '#dc3545',
            color: '#fff',
            fontWeight: 700,
            borderRadius: 4,
            fontSize: 14,
            fontFamily: 'sans-serif',
          }}>
            VERSION MISMATCH: UI querying version {usingVersionId} but active draft is {activeVersionFromBackend}
          </div>
        )}
      </div>

      <SchedulePhasedPanel
        tournamentId={tournamentId}
        activeVersion={activeVersion}
        onCreateDraft={createDraft}
        onRefresh={refresh}
        slotsCount={gridData?.conflicts_summary?.total_slots ?? 0}
        matchesCount={gridData?.conflicts_summary?.total_matches ?? 0}
        assignedCount={gridData?.conflicts_summary?.assigned_matches ?? 0}
        unassignedCount={gridData?.conflicts_summary?.unassigned_matches ?? 0}
        onInventoryAction={handleInventoryAction}
        gridMatches={gridData?.matches ?? []}
        gridAssignments={gridData?.assignments ?? []}
      />

      {/* ═══════ Schedule Inventory Panel ═══════ */}
      <ScheduleInventoryPanel
        tournamentId={tournamentId!}
        versionId={usingVersionId}
        activeTab={inventoryTab}
        onTabChange={setInventoryTab}
        eventNamesById={eventNamesById}
        refreshKey={inventoryRefreshKey}
      />

      <AutoAssignAssistPanel
        tournamentId={tournamentId}
        activeVersionId={activeVersion?.id ?? null}
        activeVersionStatus={activeVersion?.status ?? null}
        onRefresh={refresh}
      />

      {/* TEMP Debug: Feature flag status (dev only) */}
      {(import.meta as any).env.DEV && (
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 8 }}>
          ManualEditor flag: raw="{featureFlagsRaw.VITE_ENABLE_MANUAL_EDITOR}" parsed={String(featureFlags.manualScheduleEditor)}
        </div>
      )}

      {/* Manual Editor Link - Gated by feature flag */}
      {featureFlags.manualScheduleEditor && activeVersion && (
        <div style={{ marginBottom: '16px' }}>
          <Link
            to={`/tournaments/${tournamentId}/schedule/editor?versionId=${activeVersion.id}`}
            style={{ textDecoration: 'none' }}
          >
            <button
              style={{
                padding: '10px 20px',
                background: '#9c27b0',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 600,
              }}
            >
              ✏️ Open Manual Schedule Editor
            </button>
          </Link>
        </div>
      )}

      {buildSummary && <ScheduleSummaryPanel buildSummary={buildSummary} />}

      {activeVersion && (
        <div style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            type="button"
            onClick={() => { loadRuntimeMatches(); refresh() }}
            className="btn-secondary"
            style={{ fontSize: '13px' }}
          >
            Refresh runtime
          </button>
        </div>
      )}

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
            runtimeByMatchId={runtimeByMatchId}
            onMatchClick={(matchId, match) => setSelectedMatchForRuntime({ matchId, match })}
            onSlotClick={() => {}}
          />
        </div>
      </div>

      {selectedMatchForRuntime && tournamentId && gridData && (
        <MatchRuntimeModal
          tournamentId={tournamentId}
          match={selectedMatchForRuntime.match}
          teams={gridData.teams}
          runtime={runtimeByMatchId[selectedMatchForRuntime.match.match_id] ?? null}
          onSave={loadRuntimeMatches}
          onClose={() => setSelectedMatchForRuntime(null)}
        />
      )}
    </div>
  )
}

export default SchedulePageGridV1


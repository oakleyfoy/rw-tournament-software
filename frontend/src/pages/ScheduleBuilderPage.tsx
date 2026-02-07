import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getScheduleBuilder,
  getScheduleVersions,
  createScheduleVersion,
  getScheduleGrid,
  ScheduleBuilderResponse,
  ScheduleVersion,
} from '../api/client'
import ScheduleBuilderTable from '../components/ScheduleBuilderTable'
import { SchedulePhasedPanel } from './schedule/components/SchedulePhasedPanel'
import { showToast } from '../utils/toast'

export default function ScheduleBuilderPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id, 10) : null

  const [data, setData] = useState<ScheduleBuilderResponse | null>(null)
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<ScheduleVersion | null>(null)
  const [gridSummary, setGridSummary] = useState<{
    slots: number
    matches: number
    assigned: number
    unassigned: number
  } | null>(null)
  const [loading, setLoading] = useState(true)

  const loadVersions = useCallback(async () => {
    if (!tournamentId) return
    try {
      const vs = await getScheduleVersions(tournamentId)
      setVersions(vs)
      const draft = vs.find((v) => v.status === 'draft')
      const defaultVersion = draft ?? vs[0] ?? null
      setSelectedVersion((prev) => {
        if (!prev) return defaultVersion
        const stillExists = vs.some((v) => v.id === prev.id)
        return stillExists ? prev : defaultVersion
      })
    } catch {
      setVersions([])
      setSelectedVersion(null)
    }
  }, [tournamentId])

  const loadGridSummary = useCallback(async () => {
    if (!tournamentId || !selectedVersion) {
      setGridSummary(null)
      return
    }
    try {
      const grid = await getScheduleGrid(tournamentId, selectedVersion.id)
      setGridSummary({
        slots: grid.conflicts_summary?.total_slots ?? 0,
        matches: grid.conflicts_summary?.total_matches ?? 0,
        assigned: grid.conflicts_summary?.assigned_matches ?? 0,
        unassigned: grid.conflicts_summary?.unassigned_matches ?? 0,
      })
    } catch {
      setGridSummary(null)
    }
  }, [tournamentId, selectedVersion])

  const refresh = useCallback(async () => {
    await loadVersions()
    await loadGridSummary()
  }, [loadVersions, loadGridSummary])

  const createDraft = useCallback(async () => {
    if (!tournamentId) return
    try {
      const v = await createScheduleVersion(tournamentId)
      setVersions((prev) => [...prev.filter((x) => x.id !== v.id), v])
      setSelectedVersion(v)
      showToast('Draft version created', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to create draft', 'error')
    }
  }, [tournamentId])

  useEffect(() => {
    if (!tournamentId) return
    let cancelled = false
    setLoading(true)
    Promise.all([
      getScheduleBuilder(tournamentId),
      getScheduleVersions(tournamentId),
    ])
      .then(([res, vs]) => {
        if (cancelled) return
        setData(res)
        setVersions(vs)
        const draft = vs.find((v) => v.status === 'draft')
        setSelectedVersion(draft ?? vs[0] ?? null)
      })
      .catch((err) => {
        if (!cancelled) showToast(err instanceof Error ? err.message : 'Failed to load schedule builder', 'error')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [tournamentId])

  useEffect(() => {
    if (tournamentId && selectedVersion) loadGridSummary()
    else setGridSummary(null)
  }, [tournamentId, selectedVersion, loadGridSummary])


  // Validation: check if inventory is valid for proceeding
  const hasErrors = data?.events?.some((e) => e.error != null) ?? false
  const hasZeroMatches = data?.events?.some((e) => (e.total_matches ?? 0) === 0) ?? false
  const canProceed = !loading && data != null && !hasErrors && !hasZeroMatches

  if (tournamentId == null) {
    return (
      <div style={{ padding: 24 }}>
        <p>Invalid tournament.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <p>Loading schedule plan…</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div style={{ padding: 24 }}>
        <p>No data.</p>
      </div>
    )
  }

  return (
    <div className="container" style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Header with title and actions */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ marginBottom: 4 }}>Schedule Builder</h1>
          <p style={{ color: '#666', margin: 0 }}>
            This is the authoritative match inventory used by the scheduler.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            onClick={() => navigate(`/tournaments/${tournamentId}/draw-builder`)}
          >
            Back to Draw Builder
          </button>
          <button
            className="btn btn-primary"
            disabled={!canProceed}
            onClick={() => navigate(`/tournaments/${tournamentId}/schedule`)}
          >
            Go to Schedule
          </button>
        </div>
      </div>

      {/* Validation helper text */}
      {(hasErrors || hasZeroMatches) && (
        <div style={{ marginBottom: 16, padding: '8px 12px', backgroundColor: 'rgba(255, 0, 0, 0.08)', borderRadius: 4, color: '#c00', fontSize: 14 }}>
          Fix draw plan errors before proceeding.
        </div>
      )}

      <div className="card" style={{ padding: 24, marginBottom: 24 }}>
        <ScheduleBuilderTable events={data.events} />
      </div>

      {selectedVersion && (
        <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ fontWeight: 600 }}>Version:</label>
          <select
            value={selectedVersion.id}
            onChange={(e) => {
              const v = versions.find((x) => x.id === Number(e.target.value))
              if (v) setSelectedVersion(v)
            }}
            style={{ padding: '6px 12px', fontSize: 14 }}
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number} ({v.status}) — id {v.id}
              </option>
            ))}
          </select>
        </div>
      )}

      <SchedulePhasedPanel
        tournamentId={tournamentId}
        activeVersion={selectedVersion}
        onCreateDraft={createDraft}
        onRefresh={refresh}
        slotsCount={gridSummary?.slots ?? 0}
        matchesCount={gridSummary?.matches ?? 0}
        assignedCount={gridSummary?.assigned ?? 0}
        unassignedCount={gridSummary?.unassigned ?? 0}
        inventoryTotalMatches={data?.events?.reduce((s, e) => s + (e.total_matches ?? 0), 0)}
      />
    </div>
  )
}

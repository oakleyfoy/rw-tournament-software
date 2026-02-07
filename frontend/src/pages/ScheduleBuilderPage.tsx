import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getScheduleBuilder,
  getScheduleVersions,
  createScheduleVersion,
  getScheduleGrid,
  getPlanReport,
  getPlanReportVersioned,
  ScheduleBuilderResponse,
  SchedulePlanReport,
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
  const [planReport, setPlanReport] = useState<SchedulePlanReport | null>(null)
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<ScheduleVersion | null>(null)
  const [gridSummary, setGridSummary] = useState<{
    slots: number
    matches: number
    assigned: number
    unassigned: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [copiedJson, setCopiedJson] = useState(false)

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

  const loadPlanReport = useCallback(async () => {
    if (!tournamentId) return
    try {
      // Use versioned report if a version is selected, otherwise draw-plan-only
      const report = selectedVersion
        ? await getPlanReportVersioned(tournamentId, selectedVersion.id)
        : await getPlanReport(tournamentId)
      setPlanReport(report)
    } catch {
      setPlanReport(null)
    }
  }, [tournamentId, selectedVersion])

  const refresh = useCallback(async () => {
    await loadVersions()
    await loadGridSummary()
    await loadPlanReport()
  }, [loadVersions, loadGridSummary, loadPlanReport])

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
      getPlanReport(tournamentId).catch(() => null),
    ])
      .then(([res, vs, pr]) => {
        if (cancelled) return
        setData(res)
        setPlanReport(pr)
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

  // Reload plan report when version changes
  useEffect(() => {
    if (tournamentId && selectedVersion) {
      loadGridSummary()
      loadPlanReport()
    } else {
      setGridSummary(null)
    }
  }, [tournamentId, selectedVersion, loadGridSummary, loadPlanReport])

  // Contract gating: use plan report as single source of truth
  const reportOk = planReport?.ok === true
  const canProceed = !loading && planReport != null && reportOk && (planReport.events?.length ?? 0) > 0

  const handleCopyDebugJson = useCallback(() => {
    if (!planReport) return
    const json = JSON.stringify(planReport, null, 2)
    navigator.clipboard.writeText(json).then(() => {
      setCopiedJson(true)
      setTimeout(() => setCopiedJson(false), 2000)
    }).catch(() => {
      showToast('Failed to copy to clipboard', 'error')
    })
  }, [planReport])

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
            Authoritative schedule plan report — single source of truth.
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
            className={canProceed ? 'btn btn-primary' : 'btn btn-secondary'}
            disabled={!canProceed}
            onClick={() => navigate(`/tournaments/${tournamentId}/schedule`)}
            title={!canProceed && planReport?.blocking_errors?.[0]
              ? `${planReport.blocking_errors[0].code}: ${planReport.blocking_errors[0].message}`
              : !canProceed ? 'Fix draw plan errors first.' : ''}
          >
            Go to Schedule
          </button>
        </div>
      </div>

      {/* Plan Report Status Banner */}
      {planReport && (
        <div style={{
          marginBottom: 20,
          padding: '14px 20px',
          borderRadius: '8px',
          backgroundColor: reportOk
            ? 'rgba(40, 167, 69, 0.08)'
            : 'rgba(220, 53, 69, 0.08)',
          border: `1px solid ${reportOk ? 'rgba(40, 167, 69, 0.25)' : 'rgba(220, 53, 69, 0.25)'}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{
              fontSize: '18px',
              fontWeight: 700,
              color: reportOk ? '#28a745' : '#dc3545',
            }}>
              {reportOk ? 'Ready to schedule' : 'Fix required'}
            </span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {planReport.version_status && (
                <span style={{
                  fontSize: '12px',
                  padding: '2px 8px',
                  borderRadius: '10px',
                  backgroundColor: 'rgba(0,0,0,0.06)',
                  color: '#666',
                }}>
                  version: {planReport.version_status}
                </span>
              )}
              <button
                onClick={handleCopyDebugJson}
                style={{
                  fontSize: '12px',
                  padding: '4px 10px',
                  border: '1px solid rgba(0,0,0,0.15)',
                  borderRadius: '4px',
                  backgroundColor: copiedJson ? '#28a745' : 'transparent',
                  color: copiedJson ? '#fff' : '#666',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
              >
                {copiedJson ? 'Copied!' : 'Copy Debug JSON'}
              </button>
            </div>
          </div>

          {/* Summary line */}
          <div style={{ fontSize: '14px', color: '#555', marginBottom: reportOk ? 0 : 12 }}>
            {planReport.totals.events} event{planReport.totals.events !== 1 ? 's' : ''} &middot; {planReport.totals.matches_total} expected matches
            {planReport.warnings.length > 0 && (
              <span style={{ marginLeft: 12, color: '#a86b00' }}>
                {planReport.warnings.length} warning{planReport.warnings.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {/* Blocking errors */}
          {!reportOk && planReport.blocking_errors.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <div style={{ fontWeight: 600, color: '#dc3545', fontSize: '13px', marginBottom: 6 }}>
                Blocking errors ({planReport.blocking_errors.length}):
              </div>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: '13px', color: '#721c24' }}>
                {planReport.blocking_errors.slice(0, 8).map((err, idx) => (
                  <li key={idx} style={{ marginBottom: 3 }}>
                    <code style={{
                      fontSize: '11px',
                      backgroundColor: 'rgba(220,53,69,0.08)',
                      padding: '1px 5px',
                      borderRadius: '3px',
                      fontWeight: 600,
                    }}>{err.code}</code>{' '}
                    {err.message}
                  </li>
                ))}
                {planReport.blocking_errors.length > 8 && (
                  <li style={{ fontStyle: 'italic', color: '#999' }}>
                    ...and {planReport.blocking_errors.length - 8} more
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Per-event summary table from plan report */}
      {planReport && planReport.events.length > 0 && (
        <div className="card" style={{ padding: 24, marginBottom: 24 }}>
          <h3 style={{ marginTop: 0, marginBottom: 16 }}>Per-Event Plan Summary</h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900, fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid #333', textAlign: 'left' }}>
                  <th style={{ padding: '8px 10px' }}>Event</th>
                  <th style={{ padding: '8px 10px' }}>Teams</th>
                  <th style={{ padding: '8px 10px' }}>Template</th>
                  <th style={{ padding: '8px 10px' }}>WF Rounds</th>
                  <th style={{ padding: '8px 10px' }}>WF Matches</th>
                  <th style={{ padding: '8px 10px' }}>Pools</th>
                  <th style={{ padding: '8px 10px' }}>RR Matches</th>
                  <th style={{ padding: '8px 10px' }}>Brackets</th>
                  <th style={{ padding: '8px 10px' }}>Bracket Matches</th>
                  <th style={{ padding: '8px 10px' }}>Expected</th>
                  <th style={{ padding: '8px 10px' }}>Actual</th>
                </tr>
              </thead>
              <tbody>
                {planReport.events.map((ev) => {
                  const inventoryMatch = ev.inventory.expected_total === ev.inventory.actual_total
                  return (
                    <tr key={ev.event_id} style={{
                      borderBottom: '1px solid #ddd',
                      backgroundColor: !inventoryMatch && planReport.schedule_version_id
                        ? 'rgba(255, 0, 0, 0.06)' : undefined,
                    }}>
                      <td style={{ padding: '8px 10px', fontWeight: 500 }}>{ev.name}</td>
                      <td style={{ padding: '8px 10px' }}>{ev.teams_count}</td>
                      <td style={{ padding: '8px 10px' }}>
                        <code style={{ fontSize: '11px' }}>{ev.template_code}</code>
                      </td>
                      <td style={{ padding: '8px 10px' }}>{ev.waterfall.rounds}</td>
                      <td style={{ padding: '8px 10px' }}>
                        {ev.waterfall.r1_matches + ev.waterfall.r2_matches}
                        {ev.waterfall.rounds >= 2 && (
                          <span style={{ fontSize: '11px', color: '#888', marginLeft: 4 }}>
                            (R1:{ev.waterfall.r1_matches} R2:{ev.waterfall.r2_matches})
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '8px 10px' }}>
                        {ev.pools.pool_count > 0
                          ? `${ev.pools.pool_count}×${ev.pools.pool_size}`
                          : '—'}
                      </td>
                      <td style={{ padding: '8px 10px' }}>
                        {ev.pools.rr_matches > 0 ? ev.pools.rr_matches : '—'}
                        {ev.pools.rr_rounds > 0 && (
                          <span style={{ fontSize: '11px', color: '#888', marginLeft: 4 }}>
                            ({ev.pools.rr_rounds} rds)
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '8px 10px' }}>
                        {ev.brackets.divisions > 0
                          ? `${ev.brackets.divisions} div`
                          : '—'}
                      </td>
                      <td style={{ padding: '8px 10px' }}>
                        {ev.brackets.total_matches > 0
                          ? ev.brackets.total_matches
                          : '—'}
                        {ev.brackets.consolation_matches > 0 && (
                          <span style={{ fontSize: '11px', color: '#888', marginLeft: 4 }}>
                            (M:{ev.brackets.main_matches} C:{ev.brackets.consolation_matches})
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '8px 10px', fontWeight: 600 }}>{ev.inventory.expected_total}</td>
                      <td style={{
                        padding: '8px 10px',
                        fontWeight: 600,
                        color: !inventoryMatch && planReport.schedule_version_id ? '#dc3545' : undefined,
                      }}>
                        {planReport.schedule_version_id != null ? ev.inventory.actual_total : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '2px solid #333', fontWeight: 700 }}>
                  <td style={{ padding: '8px 10px' }}>Totals</td>
                  <td style={{ padding: '8px 10px' }}>—</td>
                  <td style={{ padding: '8px 10px' }}>—</td>
                  <td style={{ padding: '8px 10px' }}>—</td>
                  <td style={{ padding: '8px 10px' }}>
                    {planReport.events.reduce((s, e) => s + e.waterfall.r1_matches + e.waterfall.r2_matches, 0)}
                  </td>
                  <td style={{ padding: '8px 10px' }}>—</td>
                  <td style={{ padding: '8px 10px' }}>
                    {planReport.events.reduce((s, e) => s + e.pools.rr_matches, 0)}
                  </td>
                  <td style={{ padding: '8px 10px' }}>—</td>
                  <td style={{ padding: '8px 10px' }}>
                    {planReport.events.reduce((s, e) => s + e.brackets.total_matches, 0)}
                  </td>
                  <td style={{ padding: '8px 10px' }}>{planReport.totals.matches_total}</td>
                  <td style={{ padding: '8px 10px' }}>
                    {planReport.schedule_version_id != null
                      ? planReport.events.reduce((s, e) => s + e.inventory.actual_total, 0)
                      : '—'}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {/* Legacy inventory table (kept for backwards compatibility) */}
      <div className="card" style={{ padding: 24, marginBottom: 24 }}>
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>Match Inventory (Legacy View)</h3>
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

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getScheduleBuilder,
  getScheduleVersions,
  createScheduleVersion,
  getScheduleGrid,
  getPlanReport,
  getPlanReportVersioned,
  getActiveScheduleVersion,
  getTournament,
  publishScheduleVersion,
  unpublishSchedule,
  importSeededTeams,
  getEventTeams,
  ScheduleBuilderResponse,
  SchedulePlanReport,
  ScheduleVersion,
  ScheduleGridV1,
  TeamListItem,
  Tournament,
} from '../api/client'
import ScheduleBuilderTable from '../components/ScheduleBuilderTable'
import { SchedulePhasedPanel } from './schedule/components/SchedulePhasedPanel'
import ScheduleInventoryPanel, { type InventoryTab } from './schedule/components/ScheduleInventoryPanel'
import AvoidanceSummaryPanel from './schedule/components/AvoidanceSummaryPanel'
import { showToast } from '../utils/toast'

export default function ScheduleBuilderPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id, 10) : null

  const [data, setData] = useState<ScheduleBuilderResponse | null>(null)
  const [planReport, setPlanReport] = useState<SchedulePlanReport | null>(null)
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<ScheduleVersion | null>(null)
  const [gridData, setGridData] = useState<ScheduleGridV1 | null>(null)
  const [loading, setLoading] = useState(true)
  const [copiedJson, setCopiedJson] = useState(false)
  const [inventoryTab, setInventoryTab] = useState<InventoryTab>('slots')
  const [inventoryRefreshKey, setInventoryRefreshKey] = useState(0)
  const [focusedMatchIds, setFocusedMatchIds] = useState<number[] | null>(null)
  const [activeVersionFromBackend, setActiveVersionFromBackend] = useState<number | null>(null)
  const [tournament, setTournament] = useState<Tournament | null>(null)

  // Team import state
  const [importOpenEventId, setImportOpenEventId] = useState<number | null>(null)
  const [importText, setImportText] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [eventTeams, setEventTeams] = useState<Record<number, TeamListItem[]>>({})
  const [loadingTeamsFor, setLoadingTeamsFor] = useState<number | null>(null)

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

  const loadGridData = useCallback(async () => {
    if (!tournamentId || !selectedVersion) {
      setGridData(null)
      return
    }
    try {
      const grid = await getScheduleGrid(tournamentId, selectedVersion.id)
      setGridData(grid)
    } catch {
      setGridData(null)
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
    await loadGridData()
    await loadPlanReport()
  }, [loadVersions, loadGridData, loadPlanReport])

  const handleLocksChanged = useCallback(() => {
    loadGridData()
  }, [loadGridData])

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

  const handlePublish = useCallback(async (versionId: number) => {
    if (!tournamentId) return
    try {
      const resp = await publishScheduleVersion(tournamentId, versionId)
      if (resp.success) {
        setTournament(prev => prev ? { ...prev, public_schedule_version_id: versionId } : prev)
        showToast('Schedule published', 'success')
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to publish', 'error')
    }
  }, [tournamentId])

  const handleUnpublish = useCallback(async () => {
    if (!tournamentId) return
    try {
      const resp = await unpublishSchedule(tournamentId)
      if (resp.success) {
        setTournament(prev => prev ? { ...prev, public_schedule_version_id: null } : prev)
        showToast('Schedule unpublished', 'success')
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to unpublish', 'error')
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
      getActiveScheduleVersion(tournamentId).catch(() => null),
      getTournament(tournamentId).catch(() => null),
    ])
      .then(([res, vs, pr, activeVer, t]) => {
        if (cancelled) return
        setData(res)
        setPlanReport(pr)
        setVersions(vs)
        if (t) setTournament(t)
        if (activeVer && !activeVer.none_found) {
          setActiveVersionFromBackend(activeVer.schedule_version_id)
        }
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
      loadGridData()
      loadPlanReport()
    } else {
      setGridData(null)
    }
  }, [tournamentId, selectedVersion, loadGridData, loadPlanReport])

  // Contract gating: use plan report as single source of truth
  const reportOk = planReport?.ok === true
  const canProceed = !loading && planReport != null && reportOk && (planReport.events?.length ?? 0) > 0

  // Inventory panel helpers
  const handleInventoryAction = useCallback((tab: InventoryTab) => {
    setInventoryTab(tab)
    setInventoryRefreshKey(k => k + 1)
  }, [])

  const handleFocusMatchIds = useCallback((ids: number[]) => {
    setFocusedMatchIds(ids)
    setInventoryTab('assigned')
  }, [])

  const eventNamesById = useMemo(() => {
    const map: Record<number, string> = {}
    data?.events?.forEach((e: any) => {
      if (e.event_id && e.event_name) map[e.event_id] = e.event_name
    })
    // Also pull from plan report events
    planReport?.events?.forEach(e => {
      if (e.event_id && e.name) map[e.event_id] = e.name
    })
    return map
  }, [data, planReport])

  // Version mismatch detection
  const usingVersionId = selectedVersion?.id ?? null
  const versionMismatch = activeVersionFromBackend != null
    && usingVersionId != null
    && activeVersionFromBackend !== usingVersionId

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

  const handleLoadTeams = useCallback(async (eventId: number) => {
    setLoadingTeamsFor(eventId)
    try {
      const teams = await getEventTeams(eventId)
      setEventTeams(prev => ({ ...prev, [eventId]: teams }))
    } catch {
      showToast('Failed to load teams', 'error')
    } finally {
      setLoadingTeamsFor(null)
    }
  }, [])

  const handleImportTeams = useCallback(async (eventId: number) => {
    if (!tournamentId || !importText.trim()) return
    setImportLoading(true)
    try {
      const res = await importSeededTeams(tournamentId, eventId, importText)
      const parts: string[] = []
      if (res.imported_count > 0) parts.push(`${res.imported_count} imported`)
      if (res.updated_count > 0) parts.push(`${res.updated_count} updated`)
      if (res.rejected_rows.length > 0) parts.push(`${res.rejected_rows.length} rejected`)
      showToast(parts.join(', ') || 'No changes', res.rejected_rows.length > 0 ? 'warning' : 'success')
      if (res.warnings.length > 0) {
        res.warnings.forEach(w => showToast(w, 'warning'))
      }
      if (res.rejected_rows.length > 0) {
        res.rejected_rows.forEach(r => showToast(`Line ${r.line}: ${r.reason}`, 'error'))
      }
      setImportText('')
      setImportOpenEventId(null)
      handleLoadTeams(eventId)
    } catch (err: any) {
      showToast(err?.message || 'Import failed', 'error')
    } finally {
      setImportLoading(false)
    }
  }, [tournamentId, importText, handleLoadTeams])

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
          <button
            className="btn btn-primary"
            onClick={() => navigate(`/desk/t/${tournamentId}`)}
            style={{ backgroundColor: '#e65100', borderColor: '#e65100' }}
          >
            Open Desk
          </button>
        </div>
      </div>

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
          {selectedVersion && (
            <span>Status: <strong>{selectedVersion.status}</strong></span>
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

      {/* Team Import per Event */}
      {planReport && planReport.events.length > 0 && (
        <div className="card" style={{ padding: 24, marginBottom: 24 }}>
          <h3 style={{ marginTop: 0, marginBottom: 16 }}>Team Rosters</h3>
          {planReport.events.map((ev) => {
            const isOpen = importOpenEventId === ev.event_id
            const teams = eventTeams[ev.event_id]
            const isLoadingTeams = loadingTeamsFor === ev.event_id
            return (
              <div key={ev.event_id} style={{ marginBottom: 12, border: '1px solid #ddd', borderRadius: 6 }}>
                <div
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 14px', cursor: 'pointer', backgroundColor: 'rgba(0,0,0,0.02)',
                  }}
                  onClick={() => {
                    const nextOpen = isOpen ? null : ev.event_id
                    setImportOpenEventId(nextOpen)
                    if (nextOpen && !eventTeams[ev.event_id]) handleLoadTeams(ev.event_id)
                  }}
                >
                  <span style={{ fontWeight: 600 }}>
                    {isOpen ? '▾' : '▸'} {ev.name} ({ev.teams_count} teams)
                  </span>
                  {teams && (
                    <span style={{ fontSize: 12, color: '#666' }}>
                      {teams.length} team{teams.length !== 1 ? 's' : ''} in DB
                    </span>
                  )}
                </div>

                {isOpen && (
                  <div style={{ padding: '12px 14px' }}>
                    {/* Import paste area */}
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                        Import Seeded Teams (paste tab-separated or space-separated)
                      </div>
                      <textarea
                        value={importText}
                        onChange={(e) => setImportText(e.target.value)}
                        placeholder={"1\ta\t9\tHeather Robinson / Shea Butler\n2\tb\t8.5\tJane Doe / Mary Smith\n..."}
                        style={{
                          width: '100%', minHeight: 100, fontFamily: 'monospace', fontSize: 12,
                          padding: 8, border: '1px solid #ccc', borderRadius: 4, resize: 'vertical',
                        }}
                      />
                      <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                        <button
                          className="btn btn-primary"
                          disabled={importLoading || !importText.trim()}
                          onClick={() => handleImportTeams(ev.event_id)}
                          style={{ fontSize: 13, padding: '6px 14px' }}
                        >
                          {importLoading ? 'Importing...' : 'Import Teams'}
                        </button>
                        <span style={{ fontSize: 11, color: '#888', alignSelf: 'center' }}>
                          Format: seed [avoid_group] rating team_name (tab or space separated)
                        </span>
                      </div>
                    </div>

                    {/* Team roster table */}
                    {isLoadingTeams ? (
                      <div style={{ color: '#888', fontSize: 13 }}>Loading teams...</div>
                    ) : teams && teams.length > 0 ? (
                      <div style={{ overflowX: 'auto', maxHeight: 320, overflowY: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                          <thead style={{ position: 'sticky', top: 0, backgroundColor: '#fff' }}>
                            <tr style={{ borderBottom: '2px solid #333', textAlign: 'left' }}>
                              <th style={{ padding: '4px 8px' }}>Seed</th>
                              <th style={{ padding: '4px 8px' }}>Grp</th>
                              <th style={{ padding: '4px 8px' }}>Rating</th>
                              <th style={{ padding: '4px 8px' }}>Display Name</th>
                              <th style={{ padding: '4px 8px' }}>Full Name</th>
                            </tr>
                          </thead>
                          <tbody>
                            {teams.map((t) => (
                              <tr key={t.id} style={{ borderBottom: '1px solid #eee' }}>
                                <td style={{ padding: '4px 8px', fontWeight: 600 }}>{t.seed ?? '—'}</td>
                                <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{t.avoid_group ?? '—'}</td>
                                <td style={{ padding: '4px 8px' }}>{t.rating ?? '—'}</td>
                                <td style={{ padding: '4px 8px' }}>{t.display_name ?? '—'}</td>
                                <td style={{ padding: '4px 8px' }}>{t.name}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : teams && teams.length === 0 ? (
                      <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>
                        No teams imported yet. Paste data above and click Import.
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Legacy inventory table (kept for backwards compatibility) */}
      <div className="card" style={{ padding: 24, marginBottom: 24 }}>
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>Match Inventory (Legacy View)</h3>
        <ScheduleBuilderTable events={data.events} />
      </div>

      {selectedVersion && (
        <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <label style={{ fontWeight: 600 }}>Version:</label>
          <select
            value={selectedVersion.id}
            onChange={(e) => {
              const v = versions.find((x) => x.id === Number(e.target.value))
              if (v) setSelectedVersion(v)
            }}
            style={{ padding: '6px 12px', fontSize: 14 }}
          >
            {versions.map((v) => {
              const isPublic = tournament?.public_schedule_version_id === v.id
              return (
                <option key={v.id} value={v.id}>
                  v{v.version_number} ({v.status}){isPublic ? ' [PUBLIC]' : ''} — id {v.id}
                </option>
              )
            })}
          </select>

          {selectedVersion.status === 'final' && tournament?.public_schedule_version_id === selectedVersion.id && (
            <>
              <span style={{
                padding: '3px 10px',
                fontSize: 11,
                fontWeight: 700,
                backgroundColor: '#2e7d32',
                color: '#fff',
                borderRadius: 3,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
              }}>
                PUBLIC
              </span>
              <button
                onClick={handleUnpublish}
                style={{
                  padding: '5px 12px',
                  fontSize: 12,
                  fontWeight: 600,
                  backgroundColor: '#c62828',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 3,
                  cursor: 'pointer',
                }}
              >
                Unpublish
              </button>
            </>
          )}

          {selectedVersion.status === 'final' && tournament?.public_schedule_version_id !== selectedVersion.id && (
            <button
              onClick={() => handlePublish(selectedVersion.id)}
              style={{
                padding: '5px 12px',
                fontSize: 12,
                fontWeight: 600,
                backgroundColor: '#1a237e',
                color: '#fff',
                border: 'none',
                borderRadius: 3,
                cursor: 'pointer',
              }}
            >
              Set as Public
            </button>
          )}

          {!tournament?.public_schedule_version_id && (
            <span style={{ fontSize: 12, color: '#888', fontStyle: 'italic' }}>
              No schedule currently published.
            </span>
          )}
        </div>
      )}

      <SchedulePhasedPanel
        tournamentId={tournamentId}
        activeVersion={selectedVersion}
        onCreateDraft={createDraft}
        onRefresh={refresh}
        slotsCount={gridData?.conflicts_summary?.total_slots ?? 0}
        matchesCount={gridData?.conflicts_summary?.total_matches ?? 0}
        assignedCount={gridData?.conflicts_summary?.assigned_matches ?? 0}
        unassignedCount={gridData?.conflicts_summary?.unassigned_matches ?? 0}
        inventoryTotalMatches={data?.events?.reduce((s, e) => s + (e.total_matches ?? 0), 0)}
        onInventoryAction={handleInventoryAction}
        gridMatches={gridData?.matches ?? []}
        gridAssignments={gridData?.assignments ?? []}
        matchLockCount={gridData?.match_locks?.length ?? 0}
        slotLockCount={gridData?.slot_locks?.filter(sl => sl.status === 'BLOCKED')?.length ?? 0}
      />

      {/* ═══════ Avoidance Summary Panel ═══════ */}
      <AvoidanceSummaryPanel
        avoidanceSummary={planReport?.avoidance_summary}
        onFocusMatchIds={handleFocusMatchIds}
      />

      {/* ═══════ Schedule Inventory Panel ═══════ */}
      <ScheduleInventoryPanel
        tournamentId={tournamentId}
        versionId={usingVersionId}
        activeTab={inventoryTab}
        onTabChange={setInventoryTab}
        eventNamesById={eventNamesById}
        refreshKey={inventoryRefreshKey}
        focusedMatchIds={focusedMatchIds}
        onClearFocus={() => setFocusedMatchIds(null)}
        onLocksChanged={handleLocksChanged}
      />
    </div>
  )
}

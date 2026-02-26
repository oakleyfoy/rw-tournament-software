import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  getScheduleGrid,
  ScheduleGridV1,
  createMatchLock,
  deleteMatchLock,
  createSlotLock,
  deleteSlotLock,
} from '../../../api/client'
import { showToast } from '../../../utils/toast'

export type InventoryTab = 'slots' | 'unassigned' | 'assigned'

// ─── Day label helpers ──────────────────────────────────────────────────

const WEEKDAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/** "2026-02-20" → "Thu 2/20" */
function formatDayLabel(isoDate: string): string {
  // Parse YYYY-MM-DD as local date (avoid timezone offset from new Date())
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  const wd = WEEKDAY_SHORT[dt.getDay()]
  return `${wd} ${m}/${d}`
}

/** "2026-02-20" → "Thursday, Feb 20" */
function formatDayHeader(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  const weekday = dt.toLocaleDateString('en-US', { weekday: 'long' })
  const month = dt.toLocaleDateString('en-US', { month: 'short' })
  return `${weekday}, ${month} ${d}`
}

// ─── Props ──────────────────────────────────────────────────────────────

interface ScheduleInventoryPanelProps {
  tournamentId: number
  versionId: number | null
  activeTab: InventoryTab
  onTabChange: (tab: InventoryTab) => void
  eventNamesById?: Record<number, string>
  /** Increment to trigger data reload */
  refreshKey?: number
  /** When set, filter displayed matches to only these IDs (additive with other filters) */
  focusedMatchIds?: number[] | null
  /** Callback to clear the focus filter */
  onClearFocus?: () => void
  /** Called after a lock change so parent can refresh grid */
  onLocksChanged?: () => void
}

export default function ScheduleInventoryPanel({
  tournamentId,
  versionId,
  activeTab,
  onTabChange,
  eventNamesById = {},
  refreshKey = 0,
  focusedMatchIds,
  onClearFocus,
  onLocksChanged,
}: ScheduleInventoryPanelProps) {
  const [gridData, setGridData] = useState<ScheduleGridV1 | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copiedJson, setCopiedJson] = useState(false)

  // ─── Global day context (null = All) ─────────────────────────────────
  const [activeDay, setActiveDay] = useState<string | null>(null)

  // Per-tab filters
  const [courtFilter, setCourtFilter] = useState('')
  const [eventFilter, setEventFilter] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const [wfR1Only, setWfR1Only] = useState(false)

  // ─── Data loading ─────────────────────────────────────────────────────
  const loadData = useCallback(async () => {
    if (!versionId) return
    setLoading(true)
    setError(null)
    try {
      const data = await getScheduleGrid(tournamentId, versionId)
      setGridData(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load inventory')
      setGridData(null)
    } finally {
      setLoading(false)
    }
  }, [tournamentId, versionId])

  useEffect(() => {
    loadData()
  }, [loadData, refreshKey])

  // ─── Derived data ─────────────────────────────────────────────────────
  const slots = useMemo(() => {
    const raw = gridData?.slots ?? []
    return [...raw].sort((a, b) =>
      a.day_date.localeCompare(b.day_date) ||
      a.court_label.localeCompare(b.court_label) ||
      a.start_time.localeCompare(b.start_time)
    )
  }, [gridData])

  const assignedMatchIds = useMemo(() => {
    return new Set((gridData?.assignments ?? []).map(a => a.match_id))
  }, [gridData])

  const assignmentByMatchId = useMemo(() => {
    return new Map((gridData?.assignments ?? []).map(a => [a.match_id, a]))
  }, [gridData])

  const slotById = useMemo(() => {
    return new Map((gridData?.slots ?? []).map(s => [s.slot_id, s]))
  }, [gridData])

  const allMatches = useMemo(() => {
    const raw = gridData?.matches ?? []
    return [...raw].sort((a, b) =>
      a.event_id - b.event_id ||
      a.stage.localeCompare(b.stage) ||
      a.round_index - b.round_index ||
      a.sequence_in_round - b.sequence_in_round
    )
  }, [gridData])

  const unassignedMatches = useMemo(
    () => allMatches.filter(m => !assignedMatchIds.has(m.match_id)),
    [allMatches, assignedMatchIds]
  )

  const assignedMatches = useMemo(
    () => allMatches.filter(m => assignedMatchIds.has(m.match_id)),
    [allMatches, assignedMatchIds]
  )

  // Lock-related derived data
  const lockedMatchSet = useMemo(() => {
    return new Set((gridData?.match_locks ?? []).map(ml => ml.match_id))
  }, [gridData])

  const blockedSlotSet = useMemo(() => {
    return new Set(
      (gridData?.slot_locks ?? [])
        .filter(sl => sl.status === 'BLOCKED')
        .map(sl => sl.slot_id)
    )
  }, [gridData])

  const [lockBusy, setLockBusy] = useState<number | null>(null)

  const handleToggleMatchLock = useCallback(async (matchId: number, slotId: number, isLocked: boolean) => {
    if (!versionId) return
    setLockBusy(matchId)
    try {
      if (isLocked) {
        await deleteMatchLock(tournamentId, versionId, matchId)
      } else {
        await createMatchLock(tournamentId, versionId, matchId, slotId)
      }
      await loadData()
      onLocksChanged?.()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Lock operation failed', 'error')
    } finally {
      setLockBusy(null)
    }
  }, [tournamentId, versionId, loadData, onLocksChanged])

  const handleToggleSlotLock = useCallback(async (slotId: number, isBlocked: boolean) => {
    if (!versionId) return
    setLockBusy(slotId)
    try {
      if (isBlocked) {
        await deleteSlotLock(tournamentId, versionId, slotId)
      } else {
        await createSlotLock(tournamentId, versionId, slotId, 'BLOCKED')
      }
      await loadData()
      onLocksChanged?.()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Slot lock operation failed', 'error')
    } finally {
      setLockBusy(null)
    }
  }, [tournamentId, versionId, loadData, onLocksChanged])

  const teamMap = useMemo(() => {
    const map = new Map<number, { name: string; seed: number | null; display_name: string | null }>()
    for (const t of gridData?.teams ?? []) {
      map.set(t.id, { name: t.name, seed: t.seed, display_name: t.display_name })
    }
    return map
  }, [gridData])

  const teamLabel = (teamId: number | null, placeholder: string): string => {
    if (teamId === null) return placeholder
    const t = teamMap.get(teamId)
    if (!t) return placeholder
    const label = t.display_name || t.name
    return t.seed ? `#${t.seed} ${label}` : label
  }

  // ─── Day tabs — slot-driven ───────────────────────────────────────────
  const dayTabs = useMemo(() => {
    const rawDays = [...new Set(slots.map(s => s.day_date))].sort()
    return rawDays.map(d => ({ raw: d, label: formatDayLabel(d) }))
  }, [slots])

  // Reset day if it no longer exists in the data
  useEffect(() => {
    if (activeDay && !dayTabs.some(d => d.raw === activeDay)) {
      setActiveDay(null)
    }
  }, [dayTabs, activeDay])

  // ─── Day-filtered base data ───────────────────────────────────────────
  const daySlotsCount = useMemo(() => {
    if (!activeDay) return slots.length
    return slots.filter(s => s.day_date === activeDay).length
  }, [slots, activeDay])

  // Filter options (respect day context for courts)
  const uniqueCourts = useMemo(() => {
    const src = activeDay ? slots.filter(s => s.day_date === activeDay) : slots
    return [...new Set(src.map(s => s.court_label))].sort()
  }, [slots, activeDay])

  const uniqueEvents = useMemo(() => [...new Set(allMatches.map(m => m.event_id))].sort((a, b) => a - b), [allMatches])
  const uniqueStages = useMemo(() => [...new Set(allMatches.map(m => m.stage))].sort(), [allMatches])

  // ─── Filtered data ────────────────────────────────────────────────────
  const filteredSlots = useMemo(() => {
    let result = slots
    if (activeDay) result = result.filter(s => s.day_date === activeDay)
    if (courtFilter) result = result.filter(s => s.court_label === courtFilter)
    return result
  }, [slots, activeDay, courtFilter])

  const focusSet = useMemo(
    () => focusedMatchIds?.length ? new Set(focusedMatchIds) : null,
    [focusedMatchIds]
  )

  // Unassigned: IGNORES day filter (matches aren't tied to a day yet)
  const filteredUnassigned = useMemo(() => {
    let result = unassignedMatches
    if (eventFilter) result = result.filter(m => String(m.event_id) === eventFilter)
    if (stageFilter) result = result.filter(m => m.stage === stageFilter)
    if (wfR1Only) result = result.filter(m => m.stage === 'WF' && m.round_index === 1)
    if (focusSet) result = result.filter(m => focusSet.has(m.match_id))
    return result
  }, [unassignedMatches, eventFilter, stageFilter, wfR1Only, focusSet])

  // Assigned: respects day filter via slot lookup, sorted by TIME
  const filteredAssigned = useMemo(() => {
    let result = assignedMatches
    if (activeDay) {
      result = result.filter(m => {
        const asgn = assignmentByMatchId.get(m.match_id)
        if (!asgn) return false
        const slot = slotById.get(asgn.slot_id)
        return slot?.day_date === activeDay
      })
    }
    if (eventFilter) result = result.filter(m => String(m.event_id) === eventFilter)
    if (stageFilter) result = result.filter(m => m.stage === stageFilter)

    // Sort by Time (primary), then Event, then Court
    result = [...result].sort((a, b) => {
      const asgnA = assignmentByMatchId.get(a.match_id)
      const asgnB = assignmentByMatchId.get(b.match_id)
      const slotA = asgnA ? slotById.get(asgnA.slot_id) : undefined
      const slotB = asgnB ? slotById.get(asgnB.slot_id) : undefined
      // Day first (if showing all days)
      const dayComp = (slotA?.day_date ?? '').localeCompare(slotB?.day_date ?? '')
      if (dayComp !== 0) return dayComp
      // Start time
      const timeComp = (slotA?.start_time ?? '').localeCompare(slotB?.start_time ?? '')
      if (timeComp !== 0) return timeComp
      // Group by event within the same time slot
      const evComp = (a.event_id - b.event_id)
      if (evComp !== 0) return evComp
      // Court label
      const courtComp = (slotA?.court_label ?? '').localeCompare(slotB?.court_label ?? '')
      if (courtComp !== 0) return courtComp
      return a.match_id - b.match_id
    })

    if (focusSet) result = result.filter(m => focusSet.has(m.match_id))
    return result
  }, [assignedMatches, activeDay, assignmentByMatchId, slotById, eventFilter, stageFilter, focusSet])

  // ─── Helpers ──────────────────────────────────────────────────────────
  const eventName = (eventId: number) => eventNamesById[eventId] || `Event ${eventId}`

  const formatTime = (t: string) => {
    if (!t) return '—'
    return t.slice(0, 5)
  }

  const handleCopyUnassigned = useCallback(() => {
    const data = unassignedMatches.map(m => ({
      match_id: m.match_id,
      event_id: m.event_id,
      event_name: eventName(m.event_id),
      stage: m.stage,
      round_index: m.round_index,
      sequence_in_round: m.sequence_in_round,
      match_code: m.match_code,
      placeholder_a: m.placeholder_side_a,
      placeholder_b: m.placeholder_side_b,
    }))
    const json = JSON.stringify(data, null, 2)
    navigator.clipboard.writeText(json).then(() => {
      setCopiedJson(true)
      setTimeout(() => setCopiedJson(false), 2000)
    }).catch(() => showToast('Failed to copy', 'error'))
  }, [unassignedMatches, eventNamesById])

  // ─── No version selected ──────────────────────────────────────────────
  if (!versionId) {
    return (
      <div className="card" style={{ padding: 24, marginBottom: 24, textAlign: 'center', color: '#666' }}>
        Select or create a draft version to view inventory.
      </div>
    )
  }

  // ─── Styles ───────────────────────────────────────────────────────────
  const inventoryTabCounts = {
    slots: activeDay ? filteredSlots.length : slots.length,
    unassigned: unassignedMatches.length,
    assigned: activeDay ? filteredAssigned.length : assignedMatches.length,
  }

  const tabs: { id: InventoryTab; label: string; count: number }[] = [
    { id: 'slots', label: 'Slots', count: inventoryTabCounts.slots },
    { id: 'unassigned', label: 'Unassigned', count: inventoryTabCounts.unassigned },
    { id: 'assigned', label: 'Assigned', count: inventoryTabCounts.assigned },
  ]

  const tabBtnStyle = (isActive: boolean): React.CSSProperties => ({
    padding: '8px 16px',
    border: 'none',
    borderBottom: isActive ? '3px solid #007bff' : '3px solid transparent',
    backgroundColor: 'transparent',
    fontWeight: isActive ? 700 : 400,
    fontSize: '14px',
    cursor: 'pointer',
    color: isActive ? '#007bff' : '#555',
    transition: 'all 0.15s',
  })

  const dayBtnStyle = (isActive: boolean): React.CSSProperties => ({
    padding: '5px 12px',
    border: isActive ? '2px solid #007bff' : '1px solid #ccc',
    borderRadius: '16px',
    backgroundColor: isActive ? '#007bff' : 'transparent',
    color: isActive ? '#fff' : '#555',
    fontWeight: isActive ? 600 : 400,
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'all 0.15s',
    whiteSpace: 'nowrap' as const,
  })

  const thStyle: React.CSSProperties = {
    padding: '6px 10px',
    textAlign: 'left',
    borderBottom: '2px solid #333',
    fontSize: '12px',
    fontWeight: 600,
    whiteSpace: 'nowrap',
  }

  const tdStyle: React.CSSProperties = {
    padding: '5px 10px',
    borderBottom: '1px solid #eee',
    fontSize: '12px',
    whiteSpace: 'nowrap',
  }

  const filterBarStyle: React.CSSProperties = {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
    alignItems: 'center',
    marginBottom: 12,
    fontSize: '13px',
  }

  const selectStyle: React.CSSProperties = {
    padding: '4px 8px',
    fontSize: '12px',
    border: '1px solid #ccc',
    borderRadius: '3px',
  }

  return (
    <div className="card" style={{ padding: 24, marginBottom: 24 }}>
      {/* ═══════ Header ═══════ */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Schedule Inventory</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {loading && <span style={{ fontSize: 12, color: '#888' }}>Loading...</span>}
          <button
            onClick={loadData}
            disabled={loading}
            style={{
              fontSize: '12px',
              padding: '4px 10px',
              border: '1px solid rgba(0,0,0,0.15)',
              borderRadius: '4px',
              backgroundColor: 'transparent',
              cursor: 'pointer',
            }}
          >
            Reload
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          padding: '8px 12px',
          backgroundColor: 'rgba(220,53,69,0.08)',
          border: '1px solid rgba(220,53,69,0.2)',
          borderRadius: 4,
          color: '#dc3545',
          fontSize: 13,
          marginBottom: 12,
        }}>
          {error}
        </div>
      )}

      {/* ═══════ Day Tabs (primary navigation) ═══════ */}
      {dayTabs.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
          <button
            style={dayBtnStyle(activeDay === null)}
            onClick={() => setActiveDay(null)}
          >
            All ({slots.length})
          </button>
          {dayTabs.map(d => {
            const count = slots.filter(s => s.day_date === d.raw).length
            return (
              <button
                key={d.raw}
                style={dayBtnStyle(activeDay === d.raw)}
                onClick={() => setActiveDay(d.raw)}
              >
                {d.label} ({count})
              </button>
            )
          })}
        </div>
      )}

      {/* ═══════ Inventory Tab bar ═══════ */}
      <div style={{ display: 'flex', borderBottom: '1px solid #ddd', marginBottom: 16, alignItems: 'center' }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            style={tabBtnStyle(activeTab === tab.id)}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label} ({tab.count})
          </button>
        ))}
        {focusSet && (
          <span style={{
            marginLeft: 'auto',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 10px',
            borderRadius: 12,
            backgroundColor: '#007bff',
            color: '#fff',
            fontSize: 12,
            fontWeight: 600,
          }}>
            Focused ({focusedMatchIds!.length})
            <button
              onClick={onClearFocus}
              style={{
                background: 'none',
                border: 'none',
                color: '#fff',
                cursor: 'pointer',
                fontSize: 14,
                lineHeight: 1,
                padding: 0,
                fontWeight: 700,
              }}
              title="Clear focus filter"
            >
              &times;
            </button>
          </span>
        )}
      </div>

      {/* ═══════════ TAB 1: SLOTS ═══════════ */}
      {activeTab === 'slots' && (
        <div>
          {/* Day-scoped header */}
          <div style={{ marginBottom: 10, fontSize: 14, fontWeight: 600, color: '#333' }}>
            {activeDay
              ? `${formatDayHeader(activeDay)} \u2014 ${filteredSlots.length} slot${filteredSlots.length !== 1 ? 's' : ''}`
              : `All days \u2014 ${slots.length} slot${slots.length !== 1 ? 's' : ''}`}
          </div>

          {/* Filters (court only — day is handled by day tabs) */}
          <div style={filterBarStyle}>
            <label>Court:</label>
            <select value={courtFilter} onChange={e => setCourtFilter(e.target.value)} style={selectStyle}>
              <option value="">All</option>
              {uniqueCourts.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            {courtFilter && (
              <span style={{ color: '#888', fontSize: 12 }}>
                Showing {filteredSlots.length} of {daySlotsCount}
              </span>
            )}
          </div>

          {filteredSlots.length === 0 ? (
            <div style={{
              padding: 20,
              textAlign: 'center',
              color: slots.length === 0 ? '#dc3545' : '#666',
              backgroundColor: slots.length === 0 ? 'rgba(220,53,69,0.04)' : undefined,
              borderRadius: 4,
            }}>
              {slots.length === 0
                ? `0 slots found for version ${versionId}. Generate slots first.`
                : `0 slots match current filters.`}
            </div>
          ) : (
            <div style={{ overflowX: 'auto', maxHeight: 400, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 500 }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--theme-card-bg, #fff)' }}>
                  <tr>
                    {!activeDay && <th style={thStyle}>Day</th>}
                    <th style={thStyle}>Court</th>
                    <th style={thStyle}>Start</th>
                    <th style={thStyle}>Duration</th>
                    <th style={thStyle}>Slot ID</th>
                    <th style={thStyle}>Status</th>
                    <th style={{ ...thStyle, width: 70, textAlign: 'center' }}>Block</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSlots.map(s => {
                    const asgn = gridData?.assignments?.find(a => a.slot_id === s.slot_id)
                    const isBlocked = blockedSlotSet.has(s.slot_id)
                    return (
                      <tr key={s.slot_id} style={isBlocked ? { backgroundColor: 'rgba(220,53,69,0.06)' } : undefined}>
                        {!activeDay && <td style={tdStyle}>{s.day_date}</td>}
                        <td style={tdStyle}>{s.court_label}</td>
                        <td style={tdStyle}>{formatTime(s.start_time)}</td>
                        <td style={tdStyle}>{s.duration_minutes} min</td>
                        <td style={{ ...tdStyle, color: '#888', fontSize: 11 }}>{s.slot_id}</td>
                        <td style={tdStyle}>
                          {isBlocked ? (
                            <span style={{ color: '#dc3545', fontWeight: 500 }}>Blocked</span>
                          ) : asgn ? (
                            <span style={{ color: '#28a745', fontWeight: 500 }}>Assigned</span>
                          ) : (
                            <span style={{ color: '#888' }}>Open</span>
                          )}
                        </td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}>
                          <button
                            onClick={() => handleToggleSlotLock(s.slot_id, isBlocked)}
                            disabled={lockBusy === s.slot_id}
                            title={isBlocked ? 'Unblock slot' : 'Block slot'}
                            style={{
                              fontSize: 11,
                              padding: '2px 6px',
                              cursor: 'pointer',
                              border: '1px solid',
                              borderColor: isBlocked ? '#dc3545' : '#ccc',
                              borderRadius: 3,
                              backgroundColor: isBlocked ? '#f8d7da' : '#fff',
                              color: isBlocked ? '#721c24' : '#666',
                              fontWeight: isBlocked ? 600 : 400,
                            }}
                          >
                            {lockBusy === s.slot_id ? '...' : isBlocked ? 'Unblock' : 'Block'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══════════ TAB 2: UNASSIGNED ═══════════ */}
      {activeTab === 'unassigned' && (
        <div>
          {/* Day-agnostic badge */}
          {activeDay && (
            <div style={{
              marginBottom: 10,
              padding: '6px 12px',
              backgroundColor: 'rgba(0,123,255,0.06)',
              border: '1px solid rgba(0,123,255,0.15)',
              borderRadius: 4,
              fontSize: 12,
              color: '#0056b3',
            }}>
              Unassigned matches are not tied to a day yet — showing all {unassignedMatches.length} regardless of day selection.
            </div>
          )}

          {/* Filters */}
          <div style={filterBarStyle}>
            <label>Event:</label>
            <select value={eventFilter} onChange={e => setEventFilter(e.target.value)} style={selectStyle}>
              <option value="">All</option>
              {uniqueEvents.map(id => (
                <option key={id} value={String(id)}>{eventName(id)}</option>
              ))}
            </select>
            <label>Stage:</label>
            <select value={stageFilter} onChange={e => { setStageFilter(e.target.value); setWfR1Only(false) }} style={selectStyle}>
              <option value="">All</option>
              {uniqueStages.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={wfR1Only}
                onChange={e => { setWfR1Only(e.target.checked); if (e.target.checked) setStageFilter('') }}
              />
              WF R1 Only
            </label>
            <span style={{ color: '#888', fontSize: 12 }}>
              Showing {filteredUnassigned.length} of {unassignedMatches.length}
            </span>
            <button
              onClick={handleCopyUnassigned}
              style={{
                marginLeft: 'auto',
                fontSize: '11px',
                padding: '3px 8px',
                border: '1px solid rgba(0,0,0,0.15)',
                borderRadius: '3px',
                backgroundColor: copiedJson ? '#28a745' : 'transparent',
                color: copiedJson ? '#fff' : '#666',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              {copiedJson ? 'Copied!' : 'Copy Unassigned as JSON'}
            </button>
          </div>

          {filteredUnassigned.length === 0 ? (
            <div style={{
              padding: 20,
              textAlign: 'center',
              color: unassignedMatches.length === 0 ? '#28a745' : '#666',
            }}>
              {unassignedMatches.length === 0
                ? 'All matches are assigned!'
                : '0 matches match current filters.'}
            </div>
          ) : (
            <div style={{ overflowX: 'auto', maxHeight: 400, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--theme-card-bg, #fff)' }}>
                  <tr>
                    <th style={thStyle}>Event</th>
                    <th style={thStyle}>Stage</th>
                    <th style={thStyle}>Round</th>
                    <th style={thStyle}>Seq</th>
                    <th style={thStyle}>Match Code</th>
                    <th style={thStyle}>Side A</th>
                    <th style={thStyle}>Side B</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUnassigned.map(m => (
                    <tr key={m.match_id}>
                      <td style={tdStyle}>{eventName(m.event_id)}</td>
                      <td style={tdStyle}>
                        <code style={{ fontSize: 11, backgroundColor: 'rgba(0,0,0,0.04)', padding: '1px 4px', borderRadius: 2 }}>
                          {m.stage}
                        </code>
                      </td>
                      <td style={tdStyle}>{m.round_index}</td>
                      <td style={tdStyle}>{m.sequence_in_round}</td>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 11 }}>{m.match_code}</td>
                      <td style={{ ...tdStyle, fontSize: 11, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {teamLabel(m.team_a_id, m.placeholder_side_a)}
                      </td>
                      <td style={{ ...tdStyle, fontSize: 11, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {teamLabel(m.team_b_id, m.placeholder_side_b)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══════════ TAB 3: ASSIGNED ═══════════ */}
      {activeTab === 'assigned' && (
        <div>
          {/* Day-scoped header */}
          {activeDay && (
            <div style={{ marginBottom: 10, fontSize: 14, fontWeight: 600, color: '#333' }}>
              {formatDayHeader(activeDay)} — {filteredAssigned.length} assigned match{filteredAssigned.length !== 1 ? 'es' : ''}
            </div>
          )}

          {/* Filters */}
          <div style={filterBarStyle}>
            <label>Event:</label>
            <select value={eventFilter} onChange={e => setEventFilter(e.target.value)} style={selectStyle}>
              <option value="">All</option>
              {uniqueEvents.map(id => (
                <option key={id} value={String(id)}>{eventName(id)}</option>
              ))}
            </select>
            <label>Stage:</label>
            <select value={stageFilter} onChange={e => setStageFilter(e.target.value)} style={selectStyle}>
              <option value="">All</option>
              {uniqueStages.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <span style={{ color: '#888', fontSize: 12 }}>
              Showing {filteredAssigned.length} of {activeDay
                ? assignedMatches.filter(m => {
                    const a = assignmentByMatchId.get(m.match_id)
                    const sl = a ? slotById.get(a.slot_id) : undefined
                    return sl?.day_date === activeDay
                  }).length
                : assignedMatches.length}
            </span>
          </div>

          {filteredAssigned.length === 0 ? (
            <div style={{
              padding: 20,
              textAlign: 'center',
              color: assignedMatches.length === 0 ? '#888' : '#666',
            }}>
              {assignedMatches.length === 0
                ? 'No matches assigned yet. Run placement first.'
                : activeDay
                  ? `No assigned matches on ${formatDayLabel(activeDay)} match current filters.`
                  : '0 matches match current filters.'}
            </div>
          ) : (
            <div style={{ overflowX: 'auto', maxHeight: 400, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--theme-card-bg, #fff)' }}>
                  <tr>
                    <th style={thStyle}>Match Code</th>
                    <th style={thStyle}>Event</th>
                    <th style={thStyle}>Stage</th>
                    <th style={thStyle}>Round</th>
                    {!activeDay && <th style={thStyle}>Day</th>}
                    <th style={thStyle}>Court</th>
                    <th style={thStyle}>Time</th>
                    <th style={{ ...thStyle, width: 60, textAlign: 'center' }}>Lock</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAssigned.map(m => {
                    const asgn = assignmentByMatchId.get(m.match_id)
                    const slot = asgn ? slotById.get(asgn.slot_id) : undefined
                    const isLocked = lockedMatchSet.has(m.match_id)
                    return (
                      <tr key={m.match_id} style={isLocked ? { backgroundColor: 'rgba(255,193,7,0.08)' } : undefined}>
                        <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 11 }}>{m.match_code}</td>
                        <td style={tdStyle}>{eventName(m.event_id)}</td>
                        <td style={tdStyle}>
                          <code style={{ fontSize: 11, backgroundColor: 'rgba(0,0,0,0.04)', padding: '1px 4px', borderRadius: 2 }}>
                            {m.stage}
                          </code>
                        </td>
                        <td style={tdStyle}>{m.round_index}</td>
                        {!activeDay && <td style={tdStyle}>{slot?.day_date ?? '—'}</td>}
                        <td style={tdStyle}>{slot?.court_label ?? '—'}</td>
                        <td style={tdStyle}>{slot ? formatTime(slot.start_time) : '—'}</td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}>
                          <button
                            onClick={() => asgn && handleToggleMatchLock(m.match_id, asgn.slot_id, isLocked)}
                            disabled={lockBusy === m.match_id || !asgn}
                            title={isLocked ? 'Unlock match' : 'Lock match to this slot'}
                            style={{
                              fontSize: 11,
                              padding: '2px 6px',
                              cursor: 'pointer',
                              border: '1px solid',
                              borderColor: isLocked ? '#ffc107' : '#ccc',
                              borderRadius: 3,
                              backgroundColor: isLocked ? '#fff3cd' : '#fff',
                              color: isLocked ? '#856404' : '#666',
                              fontWeight: isLocked ? 600 : 400,
                            }}
                          >
                            {lockBusy === m.match_id ? '...' : isLocked ? 'Locked' : 'Lock'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

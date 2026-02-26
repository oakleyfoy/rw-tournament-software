import React, { useState, useMemo, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  generateMatchesOnly,
  generateSlotsOnly,
  placeMatchSubset,
  getMatchesPreview,
  wipeScheduleVersionMatches,
  getPolicyDays,
  previewPolicyPlan,
  runDailyPolicy,
  runFullPolicy,
  getScheduleReport,
  getQualityReport,
  listPolicyRuns,
  diffPolicyRuns,
  replayPolicyRun,
  ScheduleVersion,
  MatchesGenerateOnlyResponse,
  GridMatch,
  GridAssignment,
  PolicyRunResponse,
  PolicyPlanPreview,
  FullPolicyRunResponse,
  ScheduleReportResponse,
  QualityReport,
  PolicyRunSummary,
  PolicyRunDiffResponse,
} from '../../../api/client'
import { showToast } from '../../../utils/toast'
import type { InventoryTab } from './ScheduleInventoryPanel'

// ─── Helpers ────────────────────────────────────────────────────────────

function formatGenerateToast(r: MatchesGenerateOnlyResponse): string {
  const base = `Generated ${r.matches_generated} matches`
  if (r.events_included?.length) {
    const included = r.events_included.join(', ')
    if (r.events_skipped?.length) {
      return `${base} from ${included}. Failed: ${r.events_skipped.join(', ')} — check Draw Builder config.`
    }
    if (r.events_not_finalized?.length) {
      return `${base} from ${included}. Finalize ${r.events_not_finalized.join(', ')} in Draw Builder.`
    }
    return `${base} from ${included}`
  }
  if (r.events_not_finalized?.length && r.finalized_events_found?.length === 0) {
    return `${base}. No events finalized. Finalize events in Draw Builder first.`
  }
  if (r.events_not_finalized?.length) {
    return `${base}. Finalize ${r.events_not_finalized.join(', ')} in Draw Builder.`
  }
  return base
}

const WEEKDAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/** Format a policy day label: "Day 1 (Thu 2/20)" */
function formatPolicyDayLabel(isoDate: string, dayIndex: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  const wd = WEEKDAY_SHORT[dt.getDay()]
  return `Day ${dayIndex + 1} (${wd} ${m}/${d})`
}

/** Sort match IDs deterministically before sending to backend */
function sortedMatchIds(matches: GridMatch[]): number[] {
  return [...matches]
    .sort(
      (a, b) =>
        a.event_id - b.event_id ||
        a.stage.localeCompare(b.stage) ||
        a.round_index - b.round_index ||
        a.sequence_in_round - b.sequence_in_round ||
        a.match_id - b.match_id
    )
    .map((m) => m.match_id)
}

/**
 * Division display name mapping: bracket code → user-facing label.
 */
const DIVISION_DISPLAY_NAMES: Record<string, string> = {
  WW: 'Division I',
  WL: 'Division II',
  LW: 'Division III',
  LL: 'Division IV',
}

/** Get user-facing division name from bracket code. */
export function divisionDisplayName(code: string): string {
  return DIVISION_DISPLAY_NAMES[code] ?? code
}

/**
 * Extract division code from match_code.
 * Match codes contain B{div}_ patterns, e.g. "WOM_E11_BWW_M1" → "WW"
 */
function getDivisionCode(match: GridMatch): string {
  const m = match.match_code.match(/B(WW|WL|LW|LL)[_]/)
  return m ? m[1] : 'UNK'
}

/** Build group key: event|stage|division */
function getBracketGroupKey(m: GridMatch): string {
  return `${m.event_id}|${m.stage}|${getDivisionCode(m)}`
}

interface BracketBuckets {
  qf: GridMatch[]
  sf: GridMatch[]
  final: GridMatch[]
}

/**
 * Classify bracket matches within a single group by position from the end.
 *
 * round_index is sequential per match (1-7 for 8-team bracket), NOT a round
 * identifier. So we infer rounds from position:
 *   T=7  →  QF=[M1-M4] (4)   SF=[M5-M6] (2)   Final=[M7] (1)
 *   T=5  →  QF=[C1-C2] (2)   SF=[C3-C4] (2)   Final=[C5] (1)
 *   T=3  →  QF=[first 2]     SF=[]             Final=[last 1]
 *   T=1  →  QF=[]            SF=[]             Final=[1]
 */
function classifyBracketGroup(matches: GridMatch[]): BracketBuckets {
  const sorted = [...matches].sort(
    (a, b) => a.round_index - b.round_index || a.sequence_in_round - b.sequence_in_round || a.match_id - b.match_id
  )
  const T = sorted.length

  if (T === 0) return { qf: [], sf: [], final: [] }
  if (T === 1) return { qf: [], sf: [], final: sorted }
  if (T <= 3) return { qf: sorted.slice(0, T - 1), sf: [], final: sorted.slice(T - 1) }

  // T >= 4:  Final = last 1,  SF = 2 before that,  QF = everything else
  return {
    qf: sorted.slice(0, T - 3),
    sf: sorted.slice(T - 3, T - 1),
    final: sorted.slice(T - 1),
  }
}

// ─── Props ──────────────────────────────────────────────────────────────

interface SchedulePhasedPanelProps {
  tournamentId: number | null
  activeVersion: ScheduleVersion | null
  onCreateDraft: () => void
  onRefresh: () => void
  /** From grid: slots, matches, assigned counts */
  slotsCount?: number
  matchesCount?: number
  assignedCount?: number
  unassignedCount?: number
  /** Expected matches from inventory (sum of event totals). When > matchesCount, suggest Regenerate. */
  inventoryTotalMatches?: number
  /** Called after placement actions to switch inventory panel tab */
  onInventoryAction?: (tab: InventoryTab) => void
  /** Grid match data for computing per-round breakdowns */
  gridMatches?: GridMatch[]
  /** Grid assignment data for determining unassigned status */
  gridAssignments?: GridAssignment[]
  /** Lock counts for display near Run buttons */
  matchLockCount?: number
  slotLockCount?: number
}

// ─── Sub-button component ───────────────────────────────────────────────

interface PlaceButtonProps {
  label: string
  count: number
  busy: string | null
  busyLabel: string
  disabled: boolean
  onClick: () => void
  primary?: boolean
}

const PlaceButton: React.FC<PlaceButtonProps> = ({
  label,
  count,
  busy,
  busyLabel,
  disabled,
  onClick,
  primary,
}) => (
  <button
    className={primary ? 'btn btn-primary' : 'btn btn-secondary'}
    disabled={disabled || count === 0}
    onClick={onClick}
    title={count === 0 ? 'All matches in this slice are assigned' : `${count} unassigned matches`}
    style={{ fontSize: 13 }}
  >
    {busy === busyLabel ? '...' : `${label} (${count})`}
  </button>
)

// ─── Component ──────────────────────────────────────────────────────────

export const SchedulePhasedPanel: React.FC<SchedulePhasedPanelProps> = ({
  tournamentId,
  activeVersion,
  onCreateDraft,
  onRefresh,
  slotsCount = 0,
  matchesCount = 0,
  assignedCount = 0,
  unassignedCount = 0,
  inventoryTotalMatches,
  onInventoryAction,
  gridMatches = [],
  gridAssignments = [],
  matchLockCount = 0,
  slotLockCount = 0,
}) => {
  const [busy, setBusy] = useState<string | null>(null)
  const [showWipeConfirm, setShowWipeConfirm] = useState(false)
  const [wipeConfirmText, setWipeConfirmText] = useState('')
  const navigate = useNavigate()

  // ─── Policy state ──────────────────────────────────────────────────
  const [policyDays, setPolicyDays] = useState<string[]>([])
  const [policyPreview, setPolicyPreview] = useState<PolicyPlanPreview | null>(null)
  const [policyPreviewDay, setPolicyPreviewDay] = useState<string | null>(null)
  const [lastPolicyResult, setLastPolicyResult] = useState<PolicyRunResponse | null>(null)
  const [policyResultsExpanded, setPolicyResultsExpanded] = useState(false)

  // ─── Full policy run result state ──────────────────────────────────
  const [lastFullPolicyResult, setLastFullPolicyResult] = useState<FullPolicyRunResponse | null>(null)
  const [, setFullPolicyResultExpanded] = useState(false)

  // ─── Policy run history state ─────────────────────────────────────
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false)
  const [policyRunHistory, setPolicyRunHistory] = useState<PolicyRunSummary[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [diffSelection, setDiffSelection] = useState<{ a: number | null; b: number | null }>({ a: null, b: null })
  const [diffResult, setDiffResult] = useState<PolicyRunDiffResponse | null>(null)
  const [loadingDiff, setLoadingDiff] = useState(false)

  // ─── Report state ──────────────────────────────────────────────────
  const [showReportModal, setShowReportModal] = useState(false)
  const [scheduleReport, setScheduleReport] = useState<ScheduleReportResponse | null>(null)
  const [loadingReport, setLoadingReport] = useState(false)
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null)
  const [showQualityModal, setShowQualityModal] = useState(false)
  const [loadingQuality, setLoadingQuality] = useState(false)

  // Load policy days when version changes
  useEffect(() => {
    if (!tournamentId || !activeVersion) {
      setPolicyDays([])
      return
    }
    getPolicyDays(tournamentId, activeVersion.id)
      .then((r) => setPolicyDays(r.days))
      .catch(() => setPolicyDays([]))
  }, [tournamentId, activeVersion?.id, slotsCount])

  const handlePreviewPolicy = useCallback(
    async (day: string) => {
      if (!tournamentId || !activeVersion) return
      setBusy(`Preview ${day}`)
      try {
        const preview = await previewPolicyPlan(tournamentId, activeVersion.id, day)
        setPolicyPreview(preview)
        setPolicyPreviewDay(day)
      } catch (e) {
        showToast(e instanceof Error ? e.message : 'Failed to preview policy', 'error')
      } finally {
        setBusy(null)
      }
    },
    [tournamentId, activeVersion]
  )

  const handleRunPolicy = useCallback(
    async (day: string) => {
      if (!tournamentId || !activeVersion) return
      setBusy(`Run Policy ${day}`)
      try {
        const result = await runDailyPolicy(tournamentId, activeVersion.id, day)
        setLastPolicyResult(result)
        setPolicyResultsExpanded(true)
        showToast(
          `Policy ${day}: placed ${result.total_assigned} matches, ${result.total_failed} failed. ${result.reserved_slot_count} slots reserved.`,
          result.total_failed > 0 ? 'warning' : 'success'
        )
        onRefresh()
        onInventoryAction?.('unassigned')
      } catch (e) {
        showToast(e instanceof Error ? e.message : 'Policy run failed', 'error')
      } finally {
        setBusy(null)
      }
    },
    [tournamentId, activeVersion, onRefresh, onInventoryAction]
  )

  const handleRunFullPolicy = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    setBusy('Run Full Policy')
    try {
      const result: FullPolicyRunResponse = await runFullPolicy(
        tournamentId,
        activeVersion.id
      )
      setLastFullPolicyResult(result)
      setFullPolicyResultExpanded(true)
      const daysSummary = result.day_results
        .map((d) => `${d.day}: ${d.assigned} placed`)
        .join(' | ')
      const invariantMsg = result.invariant_ok === false
        ? ' [INVARIANT VIOLATIONS DETECTED]'
        : result.invariant_ok === true ? ' [ALL INVARIANTS PASS]' : ''
      showToast(
        `Full schedule: ${result.total_assigned} placed, ${result.total_failed} failed.${invariantMsg} ${daysSummary}`,
        result.total_failed > 0 ? 'warning' : 'success'
      )
      onRefresh()
      onInventoryAction?.('assigned')
    } catch (e: unknown) {
      // Handle 409 invariant violation response
      const err = e as { message?: string; response?: { status: number; json: () => Promise<{ detail: { message: string; invariant_report: { violations: Array<{ code: string; message: string }>; stats?: Record<string, number> } } }> } }
      if (err?.response?.status === 409) {
        try {
          const body = await err.response.json()
          const detail = body.detail
          const violationCount = detail?.invariant_report?.violations?.length ?? 0
          showToast(
            `Schedule rolled back: ${violationCount} invariant violation(s). ${detail?.message || ''}`,
            'error'
          )
          setLastFullPolicyResult({
            total_assigned: 0,
            total_failed: 0,
            total_reserved_spares: 0,
            duration_ms: null,
            day_results: [],
            invariant_ok: false,
            invariant_violations: detail?.invariant_report?.violations,
            invariant_stats: detail?.invariant_report?.stats as FullPolicyRunResponse['invariant_stats'],
          })
          setFullPolicyResultExpanded(true)
        } catch {
          showToast('Schedule rolled back due to invariant violations', 'error')
        }
      } else {
        showToast(
          e instanceof Error ? e.message : 'Full policy run failed',
          'error'
        )
      }
    } finally {
      setBusy(null)
    }
  }, [tournamentId, activeVersion, onRefresh, onInventoryAction])

  const handleLoadHistory = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    setLoadingHistory(true)
    try {
      const runs = await listPolicyRuns(tournamentId, activeVersion.id)
      setPolicyRunHistory(runs)
      setShowHistoryDrawer(true)
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to load run history', 'error')
    } finally {
      setLoadingHistory(false)
    }
  }, [tournamentId, activeVersion])

  const handleDiffRuns = useCallback(async () => {
    if (!tournamentId || !activeVersion || !diffSelection.a || !diffSelection.b) return
    setLoadingDiff(true)
    try {
      const result = await diffPolicyRuns(
        tournamentId,
        activeVersion.id,
        diffSelection.a,
        diffSelection.b
      )
      setDiffResult(result)
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to diff runs', 'error')
    } finally {
      setLoadingDiff(false)
    }
  }, [tournamentId, activeVersion, diffSelection])

  const handleReplayRun = useCallback(async (runId: number) => {
    if (!tournamentId || !activeVersion) return
    setBusy('Replay')
    try {
      const result = await replayPolicyRun(tournamentId, activeVersion.id, runId)
      if (result.deterministic) {
        showToast(
          `Replay verified: deterministic output confirmed (hash: ${result.replay_output_hash})`,
          'success'
        )
      }
      onRefresh()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Replay failed', 'error')
    } finally {
      setBusy(null)
    }
  }, [tournamentId, activeVersion, onRefresh])

  const handleGenerateReport = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    setLoadingReport(true)
    try {
      const report = await getScheduleReport(tournamentId, activeVersion.id)
      setScheduleReport(report)
      setShowReportModal(true)
    } catch (e) {
      showToast(
        e instanceof Error ? e.message : 'Failed to generate schedule report',
        'error'
      )
    } finally {
      setLoadingReport(false)
    }
  }, [tournamentId, activeVersion])

  const handleValidateSchedule = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    setLoadingQuality(true)
    try {
      const report = await getQualityReport(tournamentId, activeVersion.id)
      setQualityReport(report)
      setShowQualityModal(true)
    } catch (e) {
      showToast(
        e instanceof Error ? e.message : 'Failed to run quality check',
        'error'
      )
    } finally {
      setLoadingQuality(false)
    }
  }, [tournamentId, activeVersion])

  const handleDownloadCSV = useCallback(() => {
    if (!scheduleReport) return

    const rows: string[] = []
    rows.push('Day,Time,Event,Stage,Match Count,Total Courts,Reserved Courts,Assigned Matches,Spare Courts')

    for (const dayReport of scheduleReport.days) {
      for (const timeSlot of dayReport.time_slots) {
        if (timeSlot.breakdown.length === 0) {
          // Empty time slot - still include it
          rows.push(
            `${dayReport.day},${timeSlot.time},,,,${timeSlot.total_courts},${timeSlot.reserved_courts},${timeSlot.assigned_matches},${timeSlot.spare_courts}`
          )
        } else {
          for (const breakdown of timeSlot.breakdown) {
            rows.push(
              `${dayReport.day},${timeSlot.time},"${breakdown.event_name}",${breakdown.stage},${breakdown.match_count},${timeSlot.total_courts},${timeSlot.reserved_courts},${timeSlot.assigned_matches},${timeSlot.spare_courts}`
            )
          }
        }
      }
    }

    const csvContent = rows.join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.setAttribute('href', url)
    link.setAttribute('download', `schedule-report-${activeVersion?.id || 'unknown'}.csv`)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }, [scheduleReport, activeVersion])

  const isReadOnly = activeVersion?.status === 'final'

  // ─── Derived match breakdowns ───────────────────────────────────────
  const assignedMatchIds = useMemo(
    () => new Set(gridAssignments.map((a) => a.match_id)),
    [gridAssignments]
  )

  const unassignedMatches = useMemo(
    () => gridMatches.filter((m) => !assignedMatchIds.has(m.match_id)),
    [gridMatches, assignedMatchIds]
  )

  // ── WF breakdown ──
  const wfR1Unassigned = useMemo(
    () => unassignedMatches.filter((m) => m.stage === 'WF' && m.round_index === 1),
    [unassignedMatches]
  )
  const wfR2Unassigned = useMemo(
    () => unassignedMatches.filter((m) => m.stage === 'WF' && m.round_index === 2),
    [unassignedMatches]
  )

  // ── RR breakdown by round ──
  const rrByRound = useMemo(() => {
    const rr = unassignedMatches.filter((m) => m.stage === 'RR')
    const roundIndices = [...new Set(rr.map((m) => m.round_index))].sort((a, b) => a - b)
    return roundIndices.map((ri) => ({
      roundIndex: ri,
      matches: rr.filter((m) => m.round_index === ri),
    }))
  }, [unassignedMatches])

  // Also compute max RR rounds from ALL matches (not just unassigned) so buttons persist
  const rrAllRounds = useMemo(() => {
    const rr = gridMatches.filter((m) => m.stage === 'RR')
    return [...new Set(rr.map((m) => m.round_index))].sort((a, b) => a - b)
  }, [gridMatches])

  // ── Bracket breakdown — grouped by event/stage/division, classified by position ──
  const bracketSlices = useMemo(() => {
    const bracketStages = new Set(['MAIN', 'CONSOLATION', 'PLACEMENT'])
    const allBracket = gridMatches.filter((m) => bracketStages.has(m.stage))
    const hasMain = allBracket.some((m) => m.stage === 'MAIN')
    const hasCons = allBracket.some((m) => m.stage === 'CONSOLATION')
    const hasPlacement = allBracket.some((m) => m.stage === 'PLACEMENT')

    if (!hasMain && !hasCons && !hasPlacement) {
      const empty: GridMatch[] = []
      return {
        hasMain: false,
        hasCons: false,
        hasPlacement: false,
        qf: { matches: empty, exists: false },
        sf: { matches: empty, exists: false },
        finals: { matches: empty, exists: false },
        placement: { matches: empty, exists: false },
      }
    }

    // Step 1: Group ALL bracket matches by event|stage|division (for stable classification)
    const allGroups = new Map<string, GridMatch[]>()
    for (const m of allBracket) {
      if (m.stage === 'PLACEMENT') continue
      const key = getBracketGroupKey(m)
      if (!allGroups.has(key)) allGroups.set(key, [])
      allGroups.get(key)!.push(m)
    }

    // Step 2: Classify each group into QF/SF/Final buckets by position
    //   round_index is sequential (M1=1, M2=2, ..., M7=7), NOT a round identifier.
    //   Position-from-end gives: QF=[first T-3], SF=[T-3..T-2], Final=[last 1]
    const allGroupClassified = new Map<string, BracketBuckets>()
    for (const [key, matches] of allGroups) {
      allGroupClassified.set(key, classifyBracketGroup(matches))
    }

    // Step 3: Build match-ID → bucket lookup for FAST unassigned filtering
    const matchBucket = new Map<number, 'qf' | 'sf' | 'final'>()
    for (const buckets of allGroupClassified.values()) {
      for (const m of buckets.qf) matchBucket.set(m.match_id, 'qf')
      for (const m of buckets.sf) matchBucket.set(m.match_id, 'sf')
      for (const m of buckets.final) matchBucket.set(m.match_id, 'final')
    }

    // Step 4: Slice unassigned matches using the bucket map
    //   QFs button:              MAIN matches in 'qf' bucket
    //   SFs + Cons SFs button:   MAIN matches in 'sf' bucket  +  CONSOLATION matches in 'qf' bucket
    //   Finals + Remaining:      MAIN matches in 'final' bucket  +  CONSOLATION matches in 'sf'+'final' buckets
    const unPlacement = unassignedMatches.filter((m) => m.stage === 'PLACEMENT')

    const qfMatches = unassignedMatches.filter(
      (m) => m.stage === 'MAIN' && matchBucket.get(m.match_id) === 'qf'
    )

    const sfMatches = [
      ...unassignedMatches.filter(
        (m) => m.stage === 'MAIN' && matchBucket.get(m.match_id) === 'sf'
      ),
      ...unassignedMatches.filter(
        (m) => m.stage === 'CONSOLATION' && matchBucket.get(m.match_id) === 'qf'
      ),
    ]

    const finalsMatches = [
      ...unassignedMatches.filter(
        (m) => m.stage === 'MAIN' && matchBucket.get(m.match_id) === 'final'
      ),
      ...unassignedMatches.filter(
        (m) => m.stage === 'CONSOLATION' && matchBucket.get(m.match_id) !== 'qf'
      ),
    ]

    // Button existence from ALL matches (stable even when all assigned)
    const anyMainSf = [...allGroupClassified.entries()].some(
      ([key, b]) => key.includes('|MAIN|') && b.sf.length > 0
    )
    const anyMainFinal = [...allGroupClassified.entries()].some(
      ([key, b]) => key.includes('|MAIN|') && b.final.length > 0
    )

    return {
      hasMain,
      hasCons,
      hasPlacement,
      qf: { matches: qfMatches, exists: hasMain },
      sf: { matches: sfMatches, exists: anyMainSf || hasCons },
      finals: { matches: finalsMatches, exists: anyMainFinal || hasCons },
      placement: { matches: unPlacement, exists: hasPlacement },
    }
  }, [unassignedMatches, gridMatches])

  // ─── Run wrapper ────────────────────────────────────────────────────
  const run = async (label: string, fn: () => Promise<unknown>) => {
    if (!tournamentId || !activeVersion) return
    setBusy(label)
    try {
      await fn()
      onRefresh()
    } catch (e) {
      showToast(e instanceof Error ? e.message : `${label} failed`, 'error')
    } finally {
      setBusy(null)
    }
  }

  /** Place a subset of matches by IDs and show a toast */
  const placeSubset = async (label: string, matches: GridMatch[]) => {
    if (!tournamentId || !activeVersion) return
    const ids = sortedMatchIds(matches)
    if (ids.length === 0) {
      showToast(`No unassigned matches for ${label}`, 'warning')
      return
    }
    await run(label, async () => {
      const r = await placeMatchSubset(tournamentId, activeVersion.id, ids)
      showToast(
        `Placed ${r.assigned_count} ${label} matches, ${r.unassigned_count_remaining} could not be placed.`,
        r.unassigned_count_remaining > 0 ? 'warning' : 'success'
      )
      onInventoryAction?.('unassigned')
    })
  }

  // ─── Early returns ──────────────────────────────────────────────────
  if (isReadOnly) {
    return (
      <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
        <div style={{ textAlign: 'center', color: '#666' }}>
          <p>This schedule is finalized and read-only.</p>
        </div>
      </div>
    )
  }

  if (!activeVersion) {
    return (
      <div className="card" style={{ padding: '24px', marginBottom: '24px', textAlign: 'center' }}>
        <p style={{ marginBottom: '16px', color: '#666' }}>
          Create a draft version to generate matches and slots.
        </p>
        <button className="btn btn-primary" onClick={onCreateDraft} style={{ fontSize: '16px', padding: '12px 24px' }}>
          Create Draft
        </button>
      </div>
    )
  }

  const versionId = activeVersion.id
  const anyBusy = busy !== null
  const canPlace = slotsCount > 0 && matchesCount > 0

  const handleReviewMatchCards = async () => {
    if (!tournamentId || !versionId) return
    if (matchesCount > 0) {
      try {
        const preview = await getMatchesPreview(tournamentId, versionId)
        if (preview.matches.length === 0 && preview.diagnostics?.likely_version_mismatch) {
          showToast(
            'Matches exist in summary but not retrievable for this version. Likely version mismatch. Click Refresh.',
            'error'
          )
          onRefresh()
          return
        }
      } catch {
        /* proceed to navigate on error */
      }
    }
    navigate(`/tournaments/${tournamentId}/schedule/versions/${versionId}/matches`)
  }

  const handleWipeMatches = async () => {
    if (!tournamentId || !versionId) return
    setBusy('Wipe All Matches')
    try {
      const result = await wipeScheduleVersionMatches(tournamentId, versionId)
      showToast(`Deleted ${result.deleted_matches} matches`, 'success')
      setShowWipeConfirm(false)
      setWipeConfirmText('')
      onRefresh()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to wipe matches', 'error')
    } finally {
      setBusy(null)
    }
  }

  const sectionLabelStyle: React.CSSProperties = { display: 'block', marginBottom: 8, fontSize: 13, color: '#555' }

  return (
    <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
      <h3 style={{ marginTop: 0 }}>Phased Schedule Build</h3>

      {/* A) Setup */}
      <div style={{ marginBottom: '20px' }}>
        <strong style={{ display: 'block', marginBottom: 8 }}>A) Setup</strong>
        {inventoryTotalMatches != null && inventoryTotalMatches > matchesCount && matchesCount > 0 && (
          <div style={{ marginBottom: 8, padding: '8px 12px', background: '#fff8e6', borderRadius: 4, fontSize: 13 }}>
            Inventory shows {inventoryTotalMatches} matches but you have {matchesCount}. Click{' '}
            <strong>Regenerate Matches</strong> to include all finalized events.
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            style={{ fontSize: 13 }}
            onClick={handleReviewMatchCards}
            disabled={anyBusy}
          >
            Review Match Cards
          </button>
          <button
            className="btn btn-primary"
            disabled={anyBusy}
            onClick={() =>
              run('Generate Matches', () =>
                generateMatchesOnly(tournamentId!, versionId).then((r) => {
                  console.log('[GEN_MATCHES]', {
                    trace_id: r.trace_id,
                    seen_event_ids: r.seen_event_ids,
                    finalized_event_ids: r.finalized_event_ids,
                    events_expected: r.events_expected,
                    matches_generated: r.matches_generated,
                  })
                  const msg =
                    r.already_generated && r.matches_generated === 0
                      ? 'All events complete'
                      : formatGenerateToast(r)
                  showToast(msg, r.events_not_finalized?.length ? 'warning' : 'success')
                })
              )
            }
          >
            {busy === 'Generate Matches' ? '...' : 'Generate Matches'}
          </button>
          {matchesCount > 0 && (
            <>
              <button
                className="btn btn-secondary"
                disabled={anyBusy}
                title="Wipe existing matches and regenerate for all finalized events."
                onClick={() =>
                  run('Regenerate Matches', () =>
                    generateMatchesOnly(tournamentId!, versionId, { wipeExisting: true }).then((r) => {
                      console.log('[GEN_MATCHES] Regenerate', {
                        trace_id: r.trace_id,
                        seen_event_ids: r.seen_event_ids,
                        finalized_event_ids: r.finalized_event_ids,
                        events_expected: r.events_expected,
                        matches_generated: r.matches_generated,
                      })
                      const msg = formatGenerateToast(r)
                      showToast(msg, r.events_not_finalized?.length ? 'warning' : 'success')
                    })
                  )
                }
              >
                {busy === 'Regenerate Matches' ? '...' : 'Regenerate Matches'}
              </button>
              <button
                className="btn btn-secondary"
                style={{ fontSize: 13, backgroundColor: '#dc3545', color: 'white', borderColor: '#dc3545' }}
                disabled={anyBusy}
                title="Delete all matches for this version. This cannot be undone."
                onClick={() => setShowWipeConfirm(true)}
              >
                Wipe All Matches
              </button>
            </>
          )}
          <button
            className="btn btn-primary"
            disabled={anyBusy}
            onClick={() =>
              run('Generate Slots', async () => {
                const r = await generateSlotsOnly(tournamentId!, versionId)
                const msg = r.already_generated
                  ? `Already ${r.slots_generated} slots for Version ${versionId}`
                  : `Generated ${r.slots_generated} slots for Version ${versionId}`
                if (r.slots_generated === 0 && !r.already_generated) {
                  showToast(
                    'Slots generation returned success but zero slots were created. Check time windows and court configuration.',
                    'error'
                  )
                } else {
                  showToast(msg, 'success')
                }
                onInventoryAction?.('slots')
              })
            }
          >
            {busy === 'Generate Slots' ? '...' : 'Generate Slots'}
          </button>
        </div>
      </div>

      {/* B) Placement — Per-round buttons */}
      <div style={{ marginBottom: '20px' }}>
        <strong style={{ display: 'block', marginBottom: 8 }}>B) Placement (round at a time)</strong>

        {!canPlace && (
          <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>
            Generate matches and slots first to enable placement.
          </div>
        )}

        {/* ── B1: Waterfall ── */}
        {(wfR1Unassigned.length > 0 || wfR2Unassigned.length > 0 || gridMatches.some((m) => m.stage === 'WF')) && (
          <div style={{ marginBottom: 12 }}>
            <span style={sectionLabelStyle}>Waterfall</span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <PlaceButton
                label="Place WF Round 1"
                count={wfR1Unassigned.length}
                busy={busy}
                busyLabel="WF R1"
                disabled={anyBusy || !canPlace}
                onClick={() => placeSubset('WF R1', wfR1Unassigned)}
              />
              <PlaceButton
                label="Place WF Round 2"
                count={wfR2Unassigned.length}
                busy={busy}
                busyLabel="WF R2"
                disabled={anyBusy || !canPlace}
                onClick={() => placeSubset('WF R2', wfR2Unassigned)}
              />
            </div>
          </div>
        )}

        {/* ── B2: Round Robin (per-round) ── */}
        {rrAllRounds.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <span style={sectionLabelStyle}>Round Robin ({rrAllRounds.length} rounds)</span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {rrAllRounds.map((ri) => {
                const roundData = rrByRound.find((r) => r.roundIndex === ri)
                const count = roundData?.matches.length ?? 0
                return (
                  <PlaceButton
                    key={`rr-${ri}`}
                    label={`Place RR Round ${ri}`}
                    count={count}
                    busy={busy}
                    busyLabel={`RR R${ri}`}
                    disabled={anyBusy || !canPlace}
                    onClick={() => placeSubset(`RR R${ri}`, roundData?.matches ?? [])}
                  />
                )
              })}
            </div>
          </div>
        )}

        {/* ── B3: Bracket (QFs / SFs+ConsSFs / Finals+Remaining) ── */}
        {(bracketSlices.hasMain || bracketSlices.hasCons) && (
          <div style={{ marginBottom: 12 }}>
            <span style={sectionLabelStyle}>Bracket</span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {bracketSlices.qf.exists && (
                <PlaceButton
                  label="Place Bracket QFs"
                  count={bracketSlices.qf.matches.length}
                  busy={busy}
                  busyLabel="Bracket QFs"
                  disabled={anyBusy || !canPlace}
                  onClick={() => placeSubset('Bracket QFs', bracketSlices.qf.matches)}
                />
              )}
              {bracketSlices.sf.exists && (
                <PlaceButton
                  label="Place SFs + Cons SFs"
                  count={bracketSlices.sf.matches.length}
                  busy={busy}
                  busyLabel="Bracket SFs"
                  disabled={anyBusy || !canPlace}
                  onClick={() => placeSubset('Bracket SFs', bracketSlices.sf.matches)}
                />
              )}
              {bracketSlices.finals.exists && (
                <PlaceButton
                  label="Place Finals + Remaining Cons"
                  count={bracketSlices.finals.matches.length}
                  busy={busy}
                  busyLabel="Bracket Finals"
                  disabled={anyBusy || !canPlace}
                  onClick={() => placeSubset('Bracket Finals', bracketSlices.finals.matches)}
                />
              )}
            </div>
          </div>
        )}

        {/* ── B4: Placement matches ── */}
        {bracketSlices.hasPlacement && (
          <div style={{ marginBottom: 12 }}>
            <span style={sectionLabelStyle}>Placement</span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <PlaceButton
                label="Place Placement Matches"
                count={bracketSlices.placement.matches.length}
                busy={busy}
                busyLabel="Placement"
                disabled={anyBusy || !canPlace}
                onClick={() => placeSubset('Placement', bracketSlices.placement.matches)}
              />
            </div>
          </div>
        )}

      </div>

      {/* C) Policy Placement */}
      {policyDays.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          <strong style={{ display: 'block', marginBottom: 8 }}>C) Policy Placement (by day)</strong>
          <div style={{ fontSize: 12, color: '#888', marginBottom: 10 }}>
            Runs deterministic batch-based placement for each day: event priority rotation, team cap (2/day), spare court
            reservations, and layered stage ordering.
          </div>

          <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              className="btn btn-success"
              disabled={anyBusy}
              onClick={handleRunFullPolicy}
              style={{ fontSize: 14, fontWeight: 600, padding: '8px 20px' }}
              title="Run policy placement for ALL days in one click"
            >
              {busy === 'Run Full Policy' ? 'Scheduling...' : 'Schedule Entire Tournament'}
            </button>
            <button
              className="btn btn-info"
              disabled={anyBusy || !activeVersion || loadingReport}
              onClick={handleGenerateReport}
              style={{ fontSize: 14, padding: '8px 20px' }}
              title="Generate detailed schedule report by time slot"
            >
              {loadingReport ? 'Generating...' : 'Schedule Report'}
            </button>
            <button
              className="btn btn-warning"
              disabled={anyBusy || !activeVersion || loadingQuality}
              onClick={handleValidateSchedule}
              style={{ fontSize: 14, padding: '8px 20px', color: '#000' }}
              title="Validate schedule: completeness, sequencing, rest, daily cap, staggering, spare courts"
            >
              {loadingQuality ? 'Validating...' : 'Validate Schedule'}
            </button>
            <button
              className="btn btn-secondary"
              disabled={anyBusy || loadingHistory}
              onClick={handleLoadHistory}
              style={{ fontSize: 14, padding: '8px 20px' }}
              title="View run history and compare snapshots"
            >
              {loadingHistory ? 'Loading...' : 'Run History'}
            </button>
          </div>

          {/* Invariant & Hash Banner */}
          {lastFullPolicyResult && (lastFullPolicyResult.input_hash || lastFullPolicyResult.invariant_ok !== undefined) && (
            <div
              style={{
                marginBottom: 12,
                padding: '8px 14px',
                borderRadius: 6,
                border: `1px solid ${lastFullPolicyResult.invariant_ok === false ? '#f5c6cb' : '#c3e6cb'}`,
                backgroundColor: lastFullPolicyResult.invariant_ok === false ? '#fff5f5' : '#f0fff4',
                fontSize: 12,
                display: 'flex',
                flexWrap: 'wrap',
                gap: 16,
                alignItems: 'center',
              }}
            >
              <span style={{ fontWeight: 700, color: lastFullPolicyResult.invariant_ok === false ? '#dc3545' : '#28a745' }}>
                {lastFullPolicyResult.invariant_ok === false ? 'INVARIANT FAIL' : 'ALL INVARIANTS PASS'}
              </span>
              {lastFullPolicyResult.input_hash && (
                <span style={{ color: '#666' }}>
                  Input: <code style={{ fontSize: 11, backgroundColor: '#e9ecef', padding: '1px 4px', borderRadius: 3 }}>{lastFullPolicyResult.input_hash}</code>
                </span>
              )}
              {lastFullPolicyResult.output_hash && (
                <span style={{ color: '#666' }}>
                  Output: <code style={{ fontSize: 11, backgroundColor: '#e9ecef', padding: '1px 4px', borderRadius: 3 }}>{lastFullPolicyResult.output_hash}</code>
                </span>
              )}
              {lastFullPolicyResult.policy_run_id && (
                <span style={{ color: '#888' }}>
                  Run #{lastFullPolicyResult.policy_run_id}
                </span>
              )}
              {lastFullPolicyResult.invariant_stats && (
                <span style={{ color: '#666', fontSize: 11 }}>
                  Teams&gt;2: {lastFullPolicyResult.invariant_stats.teams_over_cap} |
                  Fairness: {lastFullPolicyResult.invariant_stats.fairness_violations} |
                  Deps: {lastFullPolicyResult.invariant_stats.unresolved_scheduled} |
                  Cons: {lastFullPolicyResult.invariant_stats.consolation_partial} |
                  Spare: {lastFullPolicyResult.invariant_stats.spare_violations}
                </span>
              )}
            </div>
          )}

          {/* Invariant violations detail */}
          {lastFullPolicyResult?.invariant_ok === false && lastFullPolicyResult.invariant_violations && lastFullPolicyResult.invariant_violations.length > 0 && (
            <div
              style={{
                marginBottom: 12,
                padding: '10px 14px',
                borderRadius: 6,
                border: '1px solid #f5c6cb',
                backgroundColor: '#fff5f5',
                fontSize: 12,
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              <strong style={{ color: '#dc3545', marginBottom: 6, display: 'block' }}>
                Violations ({lastFullPolicyResult.invariant_violations.length}):
              </strong>
              {lastFullPolicyResult.invariant_violations.map((v, i) => (
                <div key={i} style={{ marginBottom: 4, paddingLeft: 8, borderLeft: '2px solid #dc3545' }}>
                  <span style={{ fontWeight: 600, marginRight: 6 }}>[{v.code}]</span>
                  {v.message}
                </div>
              ))}
            </div>
          )}

          {(matchLockCount > 0 || slotLockCount > 0) && (
            <div style={{
              marginBottom: 8,
              padding: '4px 10px',
              fontSize: 12,
              color: '#856404',
              backgroundColor: '#fff3cd',
              borderRadius: 4,
              border: '1px solid #ffc107',
              display: 'inline-block',
            }}>
              Locks active: {matchLockCount} match lock{matchLockCount !== 1 ? 's' : ''}
              {slotLockCount > 0 && <>, {slotLockCount} blocked slot{slotLockCount !== 1 ? 's' : ''}</>}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {policyDays.map((day, idx) => {
              const label = formatPolicyDayLabel(day, idx)
              return (
                <div key={day} style={{ display: 'flex', gap: 4 }}>
                  <button
                    className="btn btn-primary"
                    disabled={anyBusy}
                    onClick={() => handleRunPolicy(day)}
                    title={`Run policy placement for ${day}`}
                    style={{ fontSize: 13 }}
                  >
                    {busy === `Run Policy ${day}` ? '...' : `Run ${label}`}
                  </button>
                  <button
                    className="btn btn-secondary"
                    disabled={anyBusy}
                    onClick={() => handlePreviewPolicy(day)}
                    title={`Preview batches for ${day} without placing`}
                    style={{ fontSize: 11, padding: '4px 8px' }}
                  >
                    {busy === `Preview ${day}` ? '...' : 'Preview'}
                  </button>
                </div>
              )
            })}
          </div>

          {/* Preview panel */}
          {policyPreview && policyPreviewDay && (
            <div
              style={{
                marginBottom: 12,
                padding: '10px 14px',
                backgroundColor: 'rgba(0,123,255,0.04)',
                border: '1px solid rgba(0,123,255,0.15)',
                borderRadius: 4,
                fontSize: 12,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <strong>
                  Preview: {policyPreviewDay} (Day {policyPreview.day_index + 1})
                </strong>
                <button
                  onClick={() => {
                    setPolicyPreview(null)
                    setPolicyPreviewDay(null)
                  }}
                  style={{
                    border: 'none',
                    background: 'none',
                    cursor: 'pointer',
                    fontSize: 14,
                    color: '#888',
                  }}
                >
                  ×
                </button>
              </div>
              <div style={{ marginBottom: 4 }}>
                Total matches: <strong>{policyPreview.total_match_ids}</strong> | Reserved slots:{' '}
                <strong>{policyPreview.reserved_slot_count}</strong>
              </div>
              {policyPreview.batches.map((batch, i) => (
                <div
                  key={i}
                  style={{
                    padding: '4px 8px',
                    borderLeft: '3px solid #007bff',
                    marginBottom: 4,
                    backgroundColor: 'rgba(255,255,255,0.8)',
                    borderRadius: '0 3px 3px 0',
                  }}
                >
                  <strong>{batch.name}</strong> — {batch.match_count} matches
                  {batch.description && (
                    <span style={{ color: '#666', marginLeft: 8 }}>{batch.description}</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Last run results */}
          {lastPolicyResult && (
            <div
              style={{
                padding: '10px 14px',
                backgroundColor:
                  lastPolicyResult.total_failed > 0 ? 'rgba(255,193,7,0.08)' : 'rgba(40,167,69,0.06)',
                border: `1px solid ${lastPolicyResult.total_failed > 0 ? 'rgba(255,193,7,0.3)' : 'rgba(40,167,69,0.2)'}`,
                borderRadius: 4,
                fontSize: 12,
              }}
            >
              <div
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                onClick={() => setPolicyResultsExpanded(!policyResultsExpanded)}
              >
                <span>
                  <strong>Last run: {lastPolicyResult.day_date}</strong> — Assigned:{' '}
                  <strong>{lastPolicyResult.total_assigned}</strong>, Failed:{' '}
                  <strong>{lastPolicyResult.total_failed}</strong>, Reserved slots:{' '}
                  <strong>{lastPolicyResult.reserved_slot_count}</strong>
                  {lastPolicyResult.duration_ms != null && (
                    <span style={{ color: '#888' }}> ({lastPolicyResult.duration_ms}ms)</span>
                  )}
                </span>
                <span style={{ color: '#888' }}>{policyResultsExpanded ? '▲' : '▼'}</span>
              </div>
              {policyResultsExpanded && (
                <div style={{ marginTop: 8 }}>
                  {lastPolicyResult.batches.map((b, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '4px 8px',
                        borderLeft: `3px solid ${b.failed_count > 0 ? '#ffc107' : '#28a745'}`,
                        marginBottom: 3,
                        backgroundColor: 'rgba(255,255,255,0.8)',
                        borderRadius: '0 3px 3px 0',
                      }}
                    >
                      <strong>{b.name}</strong>: {b.assigned}/{b.attempted} placed
                      {b.failed_count > 0 && (
                        <span style={{ color: '#dc3545', marginLeft: 8 }}>
                          ({b.failed_count} failed)
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* D) Status */}
      <div>
        <strong style={{ display: 'block', marginBottom: 8 }}>D) Status</strong>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 14 }}>
          <span>Version: {versionId} ({activeVersion.status})</span>
          <span>Slots: {slotsCount}</span>
          <span>Matches: {matchesCount}</span>
          <span>Assigned: {assignedCount}</span>
          <span>Unassigned: {unassignedCount}</span>
        </div>
      </div>

      {/* Wipe Confirmation Modal */}
      {showWipeConfirm && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => {
            setShowWipeConfirm(false)
            setWipeConfirmText('')
          }}
        >
          <div
            className="card"
            style={{
              padding: '24px',
              maxWidth: '400px',
              width: '90%',
              backgroundColor: 'white',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginTop: 0, color: '#dc3545' }}>Confirm Wipe All Matches</h3>
            <p style={{ marginBottom: 16 }}>
              This deletes ALL matches for version {versionId}. This cannot be undone.
            </p>
            <p style={{ marginBottom: 16, fontSize: 14, color: '#666' }}>
              Type <strong>WIPE</strong> to confirm:
            </p>
            <input
              type="text"
              value={wipeConfirmText}
              onChange={(e) => setWipeConfirmText(e.target.value)}
              placeholder="Type WIPE"
              style={{
                width: '100%',
                padding: '8px',
                marginBottom: 16,
                fontSize: 14,
                border: '1px solid #ddd',
                borderRadius: 4,
              }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setShowWipeConfirm(false)
                  setWipeConfirmText('')
                }}
                disabled={busy !== null}
              >
                Cancel
              </button>
              <button
                className="btn"
                style={{
                  backgroundColor: '#dc3545',
                  color: 'white',
                  borderColor: '#dc3545',
                }}
                onClick={handleWipeMatches}
                disabled={wipeConfirmText !== 'WIPE' || busy !== null}
              >
                {busy === 'Wipe All Matches' ? 'Deleting...' : 'Confirm Wipe'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Schedule Report Modal */}
      {showReportModal && scheduleReport && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
          onClick={() => {
            setShowReportModal(false)
            setScheduleReport(null)
          }}
        >
          <div
            className="card"
            style={{
              padding: '24px',
              maxWidth: '90%',
              maxHeight: '90vh',
              width: '1000px',
              backgroundColor: 'white',
              display: 'flex',
              flexDirection: 'column',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ marginTop: 0 }}>Schedule Report</h3>
              <button
                onClick={() => {
                  setShowReportModal(false)
                  setScheduleReport(null)
                }}
                style={{
                  border: 'none',
                  background: 'none',
                  cursor: 'pointer',
                  fontSize: '24px',
                  color: '#888',
                  padding: 0,
                  width: '30px',
                  height: '30px',
                }}
              >
                ×
              </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', marginBottom: '16px' }}>
              {scheduleReport.days.map((dayReport) => (
                <div key={dayReport.day} style={{ marginBottom: '24px' }}>
                  <h4 style={{ marginBottom: '12px', color: '#333' }}>
                    Day: {dayReport.day}
                  </h4>
                  {dayReport.time_slots.map((timeSlot) => (
                    <div
                      key={`${dayReport.day}-${timeSlot.time}`}
                      style={{
                        marginBottom: '16px',
                        padding: '12px',
                        backgroundColor: '#f8f9fa',
                        borderRadius: '4px',
                        border: '1px solid #dee2e6',
                      }}
                    >
                      <div style={{ marginBottom: '8px', fontWeight: 600 }}>
                        {timeSlot.time} — {timeSlot.total_courts} courts ({timeSlot.reserved_courts} reserved, {timeSlot.assigned_matches} assigned, {timeSlot.spare_courts} spare)
                      </div>
                      {timeSlot.breakdown.length > 0 ? (
                        <table
                          style={{
                            width: '100%',
                            borderCollapse: 'collapse',
                            fontSize: '13px',
                          }}
                        >
                          <thead>
                            <tr style={{ borderBottom: '1px solid #dee2e6' }}>
                              <th style={{ textAlign: 'left', padding: '6px 8px' }}>Event</th>
                              <th style={{ textAlign: 'left', padding: '6px 8px' }}>Stage</th>
                              <th style={{ textAlign: 'right', padding: '6px 8px' }}>Matches</th>
                            </tr>
                          </thead>
                          <tbody>
                            {timeSlot.breakdown.map((item, itemIdx) => (
                              <tr key={itemIdx} style={{ borderBottom: '1px solid #f0f0f0' }}>
                                <td style={{ padding: '6px 8px' }}>{item.event_name}</td>
                                <td style={{ padding: '6px 8px' }}>{item.stage}</td>
                                <td style={{ textAlign: 'right', padding: '6px 8px' }}>{item.match_count}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <div style={{ fontSize: '13px', color: '#888', fontStyle: 'italic' }}>
                          No matches assigned
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', borderTop: '1px solid #dee2e6', paddingTop: '16px' }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setShowReportModal(false)
                  setScheduleReport(null)
                }}
              >
                Close
              </button>
              <button className="btn btn-primary" onClick={handleDownloadCSV}>
                Download CSV
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Quality Report Modal */}
      {showQualityModal && qualityReport && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 2000,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setShowQualityModal(false)
              setQualityReport(null)
            }
          }}
        >
          <div
            style={{
              backgroundColor: '#fff',
              borderRadius: 12,
              padding: 24,
              maxWidth: 700,
              maxHeight: '85vh',
              width: '95%',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ margin: 0, fontSize: 20 }}>
                Schedule Quality Report
                <span
                  style={{
                    marginLeft: 12,
                    fontSize: 14,
                    fontWeight: 700,
                    color: qualityReport.overall_passed ? '#28a745' : '#dc3545',
                    backgroundColor: qualityReport.overall_passed ? '#d4edda' : '#f8d7da',
                    padding: '2px 10px',
                    borderRadius: 4,
                  }}
                >
                  {qualityReport.overall_passed ? 'ALL PASS' : 'ISSUES FOUND'}
                </span>
              </h2>
              <button
                className="btn btn-sm"
                onClick={() => {
                  setShowQualityModal(false)
                  setQualityReport(null)
                }}
                style={{
                  border: 'none',
                  fontSize: 20,
                  cursor: 'pointer',
                  padding: '0 8px',
                  lineHeight: 1,
                }}
              >
                x
              </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', marginBottom: 16 }}>
              {/* Checks */}
              {qualityReport.checks.map((check) => (
                <div
                  key={check.name}
                  style={{
                    marginBottom: 12,
                    padding: '10px 14px',
                    borderRadius: 8,
                    border: `1px solid ${check.passed ? '#c3e6cb' : '#f5c6cb'}`,
                    backgroundColor: check.passed ? '#f8fff9' : '#fff5f5',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        fontWeight: 700,
                        fontSize: 13,
                        color: check.passed ? '#155724' : '#721c24',
                        minWidth: 42,
                      }}
                    >
                      {check.passed ? 'PASS' : 'FAIL'}
                    </span>
                    <span style={{ fontWeight: 600, fontSize: 14, textTransform: 'capitalize' }}>
                      {check.name.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, color: '#555', marginTop: 4 }}>{check.summary}</div>
                  {check.details.length > 0 && (
                    <ul
                      style={{
                        margin: '6px 0 0 16px',
                        padding: 0,
                        fontSize: 12,
                        color: '#666',
                        listStyle: 'disc',
                      }}
                    >
                      {check.details.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                      {check.detail_count > check.details.length && (
                        <li style={{ fontStyle: 'italic' }}>
                          ...and {check.detail_count - check.details.length} more
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              ))}

              {/* Stats */}
              <div
                style={{
                  marginTop: 16,
                  padding: '12px 14px',
                  borderRadius: 8,
                  backgroundColor: '#f8f9fa',
                  border: '1px solid #dee2e6',
                }}
              >
                <h4 style={{ margin: '0 0 10px 0', fontSize: 15 }}>Summary Stats</h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px 16px', fontSize: 13 }}>
                  <div>
                    <strong>Total Matches:</strong> {qualityReport.stats.total_matches}
                  </div>
                  <div>
                    <strong>Assigned:</strong> {qualityReport.stats.assigned}
                  </div>
                  <div>
                    <strong>Unassigned:</strong> {qualityReport.stats.unassigned}
                  </div>
                  <div>
                    <strong>Total Slots:</strong> {qualityReport.stats.total_slots}
                  </div>
                  <div>
                    <strong>Utilization:</strong> {qualityReport.stats.utilization_pct}%
                  </div>
                </div>
                {Object.keys(qualityReport.stats.matches_per_day).length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <strong style={{ fontSize: 13 }}>Matches per Day:</strong>
                    <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 12 }}>
                      {Object.entries(qualityReport.stats.matches_per_day)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([day, count]) => (
                          <span key={day} style={{ backgroundColor: '#e9ecef', padding: '2px 8px', borderRadius: 4 }}>
                            {day}: {count}
                          </span>
                        ))}
                    </div>
                  </div>
                )}
                {Object.keys(qualityReport.stats.matches_per_event).length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <strong style={{ fontSize: 13 }}>By Event:</strong>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4, fontSize: 12 }}>
                      {Object.entries(qualityReport.stats.matches_per_event).map(([name, info]) => (
                        <span
                          key={name}
                          style={{
                            backgroundColor: info.assigned === info.total ? '#d4edda' : '#fff3cd',
                            padding: '2px 8px',
                            borderRadius: 4,
                          }}
                        >
                          {name}: {info.assigned}/{info.total}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setShowQualityModal(false)
                  setQualityReport(null)
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* History Drawer */}
      {showHistoryDrawer && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            right: 0,
            bottom: 0,
            width: 520,
            backgroundColor: '#fff',
            boxShadow: '-4px 0 20px rgba(0,0,0,0.15)',
            zIndex: 2000,
            display: 'flex',
            flexDirection: 'column',
            padding: 24,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0 }}>Policy Run History</h3>
            <button
              onClick={() => {
                setShowHistoryDrawer(false)
                setDiffResult(null)
                setDiffSelection({ a: null, b: null })
              }}
              style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 24, color: '#888' }}
            >
              x
            </button>
          </div>

          <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
            Select two runs to compare. Click a run to set Run A, then another for Run B.
          </div>

          {/* Diff controls */}
          {diffSelection.a && diffSelection.b && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <button
                className="btn btn-primary"
                disabled={loadingDiff}
                onClick={handleDiffRuns}
                style={{ fontSize: 13 }}
              >
                {loadingDiff ? 'Comparing...' : `Diff Run #${diffSelection.a} vs #${diffSelection.b}`}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setDiffSelection({ a: null, b: null })
                  setDiffResult(null)
                }}
                style={{ fontSize: 13 }}
              >
                Clear
              </button>
            </div>
          )}

          {/* Diff result */}
          {diffResult && (
            <div
              style={{
                marginBottom: 16,
                padding: '10px 14px',
                borderRadius: 6,
                border: `1px solid ${diffResult.hash_changed ? '#ffc107' : '#c3e6cb'}`,
                backgroundColor: diffResult.hash_changed ? '#fffef5' : '#f0fff4',
                fontSize: 12,
              }}
            >
              <div style={{ marginBottom: 6 }}>
                <strong>{diffResult.hash_changed ? 'Output Changed' : 'Identical Output'}</strong>
              </div>
              <div style={{ marginBottom: 4 }}>
                Assignments: {diffResult.assignment_delta.run_a_assigned} &rarr; {diffResult.assignment_delta.run_b_assigned}
                {diffResult.assignment_delta.delta !== 0 && (
                  <span style={{ color: diffResult.assignment_delta.delta > 0 ? '#28a745' : '#dc3545', marginLeft: 6 }}>
                    ({diffResult.assignment_delta.delta > 0 ? '+' : ''}{diffResult.assignment_delta.delta})
                  </span>
                )}
              </div>
              {diffResult.changed_batches.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <strong>Changed batches:</strong>
                  {diffResult.changed_batches.map((cb, i) => (
                    <div key={i} style={{ paddingLeft: 8, marginTop: 2 }}>
                      {cb.label}: {cb.run_a_count} &rarr; {cb.run_b_count}
                      <span style={{ color: cb.delta > 0 ? '#28a745' : '#dc3545', marginLeft: 6 }}>
                        ({cb.delta > 0 ? '+' : ''}{cb.delta})
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {diffResult.changed_batches.length === 0 && (
                <div style={{ color: '#28a745' }}>No batch-level changes</div>
              )}
            </div>
          )}

          {/* Run list */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {policyRunHistory.length === 0 && (
              <div style={{ color: '#888', fontSize: 13, textAlign: 'center', padding: 20 }}>
                No runs recorded yet. Run "Schedule Entire Tournament" to create a snapshot.
              </div>
            )}
            {policyRunHistory.map((run) => {
              const isSelectedA = diffSelection.a === run.id
              const isSelectedB = diffSelection.b === run.id
              return (
                <div
                  key={run.id}
                  onClick={() => {
                    if (!diffSelection.a || (diffSelection.a && diffSelection.b)) {
                      setDiffSelection({ a: run.id, b: null })
                      setDiffResult(null)
                    } else if (diffSelection.a && !diffSelection.b && diffSelection.a !== run.id) {
                      setDiffSelection({ ...diffSelection, b: run.id })
                    }
                  }}
                  style={{
                    padding: '10px 14px',
                    marginBottom: 8,
                    borderRadius: 6,
                    cursor: 'pointer',
                    border: `2px solid ${isSelectedA ? '#007bff' : isSelectedB ? '#6f42c1' : '#dee2e6'}`,
                    backgroundColor: isSelectedA ? '#e7f1ff' : isSelectedB ? '#f3eaff' : run.ok ? '#f8fff9' : '#fff5f5',
                    transition: 'border-color 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>
                      Run #{run.id}
                      {isSelectedA && <span style={{ color: '#007bff', marginLeft: 6, fontSize: 11 }}>(A)</span>}
                      {isSelectedB && <span style={{ color: '#6f42c1', marginLeft: 6, fontSize: 11 }}>(B)</span>}
                    </span>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: run.ok ? '#28a745' : '#dc3545',
                        backgroundColor: run.ok ? '#d4edda' : '#f8d7da',
                        padding: '1px 8px',
                        borderRadius: 4,
                      }}
                    >
                      {run.ok ? 'PASS' : 'FAIL'}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: '#666', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    <span>{new Date(run.created_at).toLocaleString()}</span>
                    <span>Assigned: {run.total_assigned}</span>
                    <span>{run.duration_ms}ms</span>
                  </div>
                  <div style={{ fontSize: 10, color: '#888', marginTop: 4, fontFamily: 'monospace' }}>
                    in: {run.input_hash} | out: {run.output_hash}
                  </div>
                  <div style={{ marginTop: 6, display: 'flex', gap: 6 }}>
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: 11, padding: '2px 8px' }}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleReplayRun(run.id)
                      }}
                      disabled={anyBusy}
                      title="Re-run with same inputs to verify determinism"
                    >
                      {busy === 'Replay' ? '...' : 'Replay'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
      {/* History drawer backdrop */}
      {showHistoryDrawer && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.2)',
            zIndex: 1999,
          }}
          onClick={() => {
            setShowHistoryDrawer(false)
            setDiffResult(null)
            setDiffSelection({ a: null, b: null })
          }}
        />
      )}
    </div>
  )
}

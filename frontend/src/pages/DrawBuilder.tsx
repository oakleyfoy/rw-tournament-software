import { useEffect, useState, useMemo, type CSSProperties } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  getTournament,
  getEvents,
  getPhase1Status,
  getScheduleBuilder,
  getPlanReport,
  getTournamentDays,
  getScheduleVersions,
  importSeededTeams,
  importCombinedTeams,
  getEventTeams,
  ScheduleBuilderResponse,
  SchedulePlanReport,
  updateDrawPlan,
  finalizeDrawPlan,
  reopenDrawPlan,
  updateEvent,
  updateTournament,
  Tournament,
  ScheduleVersion,
  Event,
  Phase1Status,
  TeamListItem,
  getMatches,
  wfR1SwapSlots,
  Match,
} from '../api/client'
import { showToast } from '../utils/toast'
import {
  TemplateType,
  DrawPlan,
  ScheduleProfile,
  calculateMatches,
  calculateMinutesRequired,
  MatchCounts,
} from '../utils/drawEstimation'
import { minutesToHours, minutesToHM } from '../utils/timeFormat'
import { EVENT_SUMMARY_HELP } from '../constants/eventSummaryHelp'
// Import Phase 1 rules from single source of truth
import {
  ALLOWED_TEAM_COUNTS,
  PHASE1_SUPPORTED_TEAM_COUNTS_SORTED,
  isPhase1TeamCount,
  requiredWfRounds,
  getValidFamilyForTeamCount,
  isTeamCountValidForFamily,
  type TemplateFamily,
} from '../utils/drawPlanRules'
import './TournamentSetup.css'

function parseStoredDayOrders(raw: string | null | undefined): number[][] | null {
  if (!raw?.trim()) return null
  try {
    const data = JSON.parse(raw) as unknown
    if (!data || typeof data !== 'object') return null
    const obj = data as { day_orders?: unknown }
    if (!Array.isArray(obj.day_orders)) return null
    return obj.day_orders.map((row): number[] => {
      if (!Array.isArray(row)) return []
      const seen = new Set<number>()
      const ids: number[] = []
      for (const x of row) {
        let id: number | null = null
        if (typeof x === 'number' && Number.isInteger(x) && x > 0) id = x
        else if (typeof x === 'string' && /^\d+$/.test(x.trim())) id = parseInt(x.trim(), 10)
        if (id != null && !seen.has(id)) {
          seen.add(id)
          ids.push(id)
        }
      }
      return ids
    })
  } catch {
    return null
  }
}

function defaultEventOrder(events: Event[]): number[] {
  return [...events].sort((a, b) => a.id - b.id).map((e) => e.id)
}

function mergeDayRow(stored: number[], allIds: number[]): number[] {
  const allowed = new Set(allIds)
  const seen = new Set<number>()
  const out: number[] = []
  for (const id of stored) {
    if (allowed.has(id) && !seen.has(id)) {
      seen.add(id)
      out.push(id)
    }
  }
  for (const id of allIds) {
    if (!seen.has(id)) out.push(id)
  }
  return out
}

function buildInitialDayOrders(
  daysCount: number,
  events: Event[],
  stored: number[][] | null,
): number[][] {
  const allIds = defaultEventOrder(events)
  const rows: number[][] = []
  for (let i = 0; i < daysCount; i++) {
    const row = stored?.[i]
    rows.push(row?.length ? mergeDayRow(row, allIds) : [...allIds])
  }
  return rows
}

function formatTournamentDayLabel(isoDate: string): string {
  try {
    const d = new Date(`${isoDate}T12:00:00`)
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  } catch {
    return isoDate
  }
}

/** Same schedule version the Schedule page prefers for editing: draft first, else published, else newest. */
function resolveCalendarScheduleVersionId(tournament: Tournament, versions: ScheduleVersion[]): number | undefined {
  const draft = versions.find((v) => (v.status || '').toLowerCase() === 'draft')
  if (draft?.id != null) return draft.id
  const pub = tournament.public_schedule_version_id
  if (pub != null) return pub
  const sorted = [...versions].sort((a, b) => {
    if (b.version_number !== a.version_number) return b.version_number - a.version_number
    return b.id - a.id
  })
  return sorted[0]?.id
}

function wfR1LookupTeam(teams: TeamListItem[] | undefined, teamId: number | null | undefined): TeamListItem | undefined {
  if (teamId == null) return undefined
  return teams?.find((t) => t.id === teamId)
}

/** Doubles pair rating stored on the team row (combined). */
function formatTeamRating(rating: number | null | undefined): string {
  if (rating == null || Number.isNaN(rating)) return '—'
  const x = Math.round(rating * 100) / 100
  return Number.isInteger(x) ? String(x) : x.toFixed(2).replace(/\.?0+$/, '')
}

/** Avoid-group / who-knows-who letters from roster import. */
function formatAvoidGroup(raw: string | null | undefined): string {
  if (raw == null || !String(raw).trim()) return '—'
  return String(raw).trim().toUpperCase()
}

function SortableDayEventRow({ id, label }: { id: string; label: string }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.88 : 1,
  }
  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 10px',
        marginBottom: 6,
        backgroundColor: 'var(--theme-table-row-hover)',
        borderRadius: 6,
        cursor: 'grab',
        touchAction: 'none',
        border: '1px solid rgba(0,0,0,0.06)',
      }}
      {...attributes}
      {...listeners}
    >
      <span style={{ flex: 1, fontSize: 14 }}>{label}</span>
    </div>
  )
}

function DayEventOrderColumn({
  title,
  orderedIds,
  eventNames,
  onReorder,
  onClear,
}: {
  title: string
  orderedIds: number[]
  eventNames: Map<number, string>
  onReorder: (next: number[]) => void
  onClear: () => void
}) {
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor))

  const handleDragEnd = (e: DragEndEvent) => {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const oldIndex = orderedIds.indexOf(Number(active.id))
    const newIndex = orderedIds.indexOf(Number(over.id))
    if (oldIndex < 0 || newIndex < 0) return
    onReorder(arrayMove(orderedIds, oldIndex, newIndex))
  }

  const items = orderedIds.map(String)

  return (
    <div style={{ flex: '1 1 220px', minWidth: 200 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ fontWeight: 600 }}>{title}</div>
        <button type="button" className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: 12 }} onClick={onClear}>
          Clear
        </button>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={items} strategy={verticalListSortingStrategy}>
          {orderedIds.map((eid) => (
            <SortableDayEventRow
              key={eid}
              id={String(eid)}
              label={eventNames.get(eid) ?? `Event #${eid}`}
            />
          ))}
        </SortableContext>
      </DndContext>
    </div>
  )
}

// Match length options for dropdown (value in minutes, label in H:MM format)
// Supported: 1:00, 1:30, 1:45, 2:00
const MATCH_LENGTH_OPTIONS = [
  { minutes: 60, label: '1:00' },
  { minutes: 90, label: '1:30' },
  { minutes: 105, label: '1:45' },
  { minutes: 120, label: '2:00' },
]

// Standard block options (same as match length options)
const STANDARD_BLOCK_OPTIONS = MATCH_LENGTH_OPTIONS

// Waterfall block options (same as match length options)
const WATERFALL_BLOCK_OPTIONS = MATCH_LENGTH_OPTIONS

interface EventEditorState {
  templateType: TemplateType
  wfRounds: number
  standardMinutes: number
  waterfallMinutes: number
  scheduleProfile: ScheduleProfile
}

function createDefaultScheduleProfile(): ScheduleProfile {
  return {
    preferred: { fri: 2, sat: 2, sun: 1 },
    fallback: { fri: 2, sat: 1, sun: 2 },
    schedule_order: null,
  }
}

function normalizeScheduleOrder(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null
}

function normalizeScheduleProfile(value: unknown): ScheduleProfile {
  const defaults = createDefaultScheduleProfile()
  if (!value || typeof value !== 'object') return defaults
  const raw = value as Partial<ScheduleProfile>
  return {
    preferred: raw.preferred ?? defaults.preferred,
    fallback: raw.fallback ?? defaults.fallback,
    schedule_order: normalizeScheduleOrder(raw.schedule_order),
  }
}

function DrawBuilder() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id) : null

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [phase1Status, setPhase1Status] = useState<Phase1Status | null>(null)
  const [inventoryByEventId, setInventoryByEventId] = useState<Record<number, { total_matches: number }>>({})
  const [, setScheduleBuilderData] = useState<ScheduleBuilderResponse | null>(null)
  const [planReport, setPlanReport] = useState<SchedulePlanReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<number, boolean>>({})
  const [eventEditorStates, setEventEditorStates] = useState<Record<number, EventEditorState>>({})
  const [expandedExplanations, setExpandedExplanations] = useState<Record<number, boolean>>({})

  // Combined roster + towel import state
  const [importText, setImportText] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [legacyImportOpenEventId, setLegacyImportOpenEventId] = useState<number | null>(null)
  const [legacyImportText, setLegacyImportText] = useState('')
  const [legacyImportLoading, setLegacyImportLoading] = useState(false)
  const [eventTeams, setEventTeams] = useState<Record<number, TeamListItem[]>>({})
  const [loadingTeamsFor, setLoadingTeamsFor] = useState<number | null>(null)
  /** ISO dates; order matches backend schedule policy day_index for the resolved schedule version. */
  const [schedulePolicyDayIsoDates, setSchedulePolicyDayIsoDates] = useState<string[]>([])
  const [dayOrdersLocal, setDayOrdersLocal] = useState<number[][]>([])
  const [dayOrdersSaving, setDayOrdersSaving] = useState(false)
  const [calendarScheduleVersionId, setCalendarScheduleVersionId] = useState<number | null>(null)
  const [scheduleVersions, setScheduleVersions] = useState<ScheduleVersion[]>([])
  const [wfR1MatchesByEvent, setWfR1MatchesByEvent] = useState<Record<number, Match[]>>({})
  const [wfR1MatchesLoading, setWfR1MatchesLoading] = useState<Record<number, boolean>>({})
  const [wfR1SwapPick, setWfR1SwapPick] = useState<{ eventId: number; matchId: number; slot: 'A' | 'B' } | null>(
    null,
  )

  // Scroll to top when component mounts
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    if (tournamentId) {
      loadData()
    }
  }, [tournamentId])

  const loadData = async () => {
    if (!tournamentId) return
    
    try {
      setLoading(true)
      const tournamentData = await getTournament(tournamentId)
      const [eventsData, statusData, versionsData, planReportData, daysData] = await Promise.all([
        getEvents(tournamentId),
        getPhase1Status(tournamentId),
        getScheduleVersions(tournamentId).catch(() => [] as ScheduleVersion[]),
        getPlanReport(tournamentId).catch(() => null),
        getTournamentDays(tournamentId).catch(() => []),
      ])
      const calendarVid = resolveCalendarScheduleVersionId(tournamentData, versionsData)
      setCalendarScheduleVersionId(calendarVid ?? null)
      setScheduleVersions(versionsData)
      const sbData = await getScheduleBuilder(
        tournamentId,
        calendarVid != null ? { scheduleVersionId: calendarVid } : undefined,
      ).catch(() => ({ tournament_id: tournamentId, events: [] } as ScheduleBuilderResponse))
      
      setTournament(tournamentData)
      setEvents(eventsData)

      const policyDays = sbData.policy_calendar_days ?? []
      let calendarIsoDates: string[]
      if (policyDays.length > 0) {
        calendarIsoDates = policyDays
      } else {
        const sortedDayRows = [...daysData].sort((a, b) => a.date.localeCompare(b.date))
        calendarIsoDates =
          sortedDayRows.length > 0 ? sortedDayRows.map((d) => d.date) : [tournamentData.start_date]
      }
      setSchedulePolicyDayIsoDates(calendarIsoDates)

      const dayColumnCount = Math.max(1, calendarIsoDates.length)
      const parsedOrders = parseStoredDayOrders(tournamentData.event_schedule_day_orders_json)
      setDayOrdersLocal(buildInitialDayOrders(dayColumnCount, eventsData, parsedOrders))
      setPhase1Status(statusData)
      const inv: Record<number, { total_matches: number }> = {}
      sbData.events?.forEach((e: { event_id: number; total_matches: number }) => {
        inv[e.event_id] = { total_matches: e.total_matches }
      })
      setInventoryByEventId(inv)
      setScheduleBuilderData(sbData)
      setPlanReport(planReportData)
      
      // Initialize editor states from event data
      const states: Record<number, EventEditorState> = {}
      eventsData.forEach(event => {
        states[event.id] = initializeEditorState(event)
      })
      setEventEditorStates(states)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load data', 'error')
    } finally {
      setLoading(false)
    }
  }

  const refetchInventory = async () => {
    if (!tournamentId) return
    try {
      const [tData, vs] = await Promise.all([
        tournament ? Promise.resolve(tournament) : getTournament(tournamentId),
        getScheduleVersions(tournamentId).catch(() => [] as ScheduleVersion[]),
      ])
      const calendarVid = resolveCalendarScheduleVersionId(tData, vs)
      setCalendarScheduleVersionId(calendarVid ?? null)
      setScheduleVersions(vs)
      const [sb, pr] = await Promise.all([
        getScheduleBuilder(tournamentId, calendarVid != null ? { scheduleVersionId: calendarVid } : undefined),
        getPlanReport(tournamentId).catch(() => null),
      ])
      const inv: Record<number, { total_matches: number }> = {}
      sb.events?.forEach((e: { event_id: number; total_matches: number }) => {
        inv[e.event_id] = { total_matches: e.total_matches }
      })
      setInventoryByEventId(inv)
      setScheduleBuilderData(sb)
      setPlanReport(pr)
      const pc = sb.policy_calendar_days ?? []
      if (pc.length > 0) {
        setSchedulePolicyDayIsoDates(pc)
      }
    } catch {
      /* ignore */
    }
  }

  const eventNameById = useMemo(() => {
    const m = new Map<number, string>()
    events.forEach((e) => m.set(e.id, e.name))
    return m
  }, [events])

  const fetchWfR1Matches = async (eventId: number) => {
    if (!tournamentId || calendarScheduleVersionId == null) return
    setWfR1MatchesLoading((prev) => ({ ...prev, [eventId]: true }))
    try {
      const [rows, teams] = await Promise.all([
        getMatches(tournamentId, calendarScheduleVersionId, eventId),
        getEventTeams(eventId),
      ])
      const wfR1 = rows
        .filter((m) => m.match_type === 'WF' && (m.round_index ?? 0) === 1)
        .sort((a, b) => a.sequence_in_round - b.sequence_in_round)
      setEventTeams((prev) => ({ ...prev, [eventId]: teams }))
      setWfR1MatchesByEvent((prev) => ({ ...prev, [eventId]: wfR1 }))
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load WF matches', 'error')
    } finally {
      setWfR1MatchesLoading((prev) => ({ ...prev, [eventId]: false }))
    }
  }

  const handleWfR1SlotClick = async (eventId: number, matchId: number, slot: 'A' | 'B') => {
    if (!tournamentId || calendarScheduleVersionId == null) return
    const versFinal =
      (scheduleVersions.find((v) => v.id === calendarScheduleVersionId)?.status || '').toLowerCase() === 'final'
    if (versFinal) return

    const pick = wfR1SwapPick
    if (!pick || pick.eventId !== eventId) {
      setWfR1SwapPick({ eventId, matchId, slot })
      return
    }
    if (pick.matchId === matchId && pick.slot === slot) {
      setWfR1SwapPick(null)
      return
    }
    try {
      await wfR1SwapSlots(tournamentId, {
        schedule_version_id: calendarScheduleVersionId,
        event_id: eventId,
        match_id_a: pick.matchId,
        slot_a: pick.slot,
        match_id_b: matchId,
        slot_b: slot,
      })
      setWfR1SwapPick(null)
      await fetchWfR1Matches(eventId)
      await refetchInventory()
      showToast('Sides swapped.', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Swap failed', 'error')
    }
  }

  const handleSaveDayOrders = async () => {
    if (!tournamentId || dayOrdersSaving) return
    try {
      setDayOrdersSaving(true)
      const updated = await updateTournament(tournamentId, {
        event_schedule_day_orders_json: JSON.stringify({ day_orders: dayOrdersLocal }),
      })
      setTournament(updated)
      showToast('Event order by tournament day saved.', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save event order', 'error')
    } finally {
      setDayOrdersSaving(false)
    }
  }

  const reorderDayOrders = (dayIdx: number, next: number[]) => {
    setDayOrdersLocal((prev) => prev.map((row, i) => (i === dayIdx ? [...next] : [...row])))
  }

  const clearDayOrdersRow = (dayIdx: number) => {
    const allIds = defaultEventOrder(events)
    setDayOrdersLocal((prev) => {
      const copy = [...prev]
      copy[dayIdx] = [...allIds]
      return copy
    })
  }

  const initializeEditorState = (event: Event): EventEditorState => {
    const n = event.team_count
    
    // Phase 1 default template selection using rules module
    const validFamily = getValidFamilyForTeamCount(n)
    let templateType: TemplateType = validFamily ?? 'RR_ONLY'
    let wfRounds = validFamily ? requiredWfRounds(validFamily, n) : 0
    
    let standardMinutes = event.standard_block_minutes || 120
    let waterfallMinutes = 60 // Default to 1 hour
    let scheduleProfile: ScheduleProfile = createDefaultScheduleProfile()

    // Parse from existing data if present
    if (event.draw_plan_json) {
      try {
        const plan: DrawPlan = JSON.parse(event.draw_plan_json)
        const savedTemplate = plan.template_type
        const savedWfRounds = plan.wf_rounds || 0
        
        if (plan.timing?.standard_block_minutes) {
          standardMinutes = plan.timing.standard_block_minutes
        }
        if (plan.timing?.wf_block_minutes) {
          waterfallMinutes = plan.timing.wf_block_minutes
        }
        
        // VALIDATION: Only use saved template if valid for team_count (using rules module)
        const isValidTemplate = (
          isTeamCountValidForFamily(savedTemplate as TemplateFamily, n) ||
          (savedTemplate === 'WF_TO_POOLS_4' && n === 16) // Legacy support
        )
        
        if (isValidTemplate) {
          templateType = savedTemplate
          wfRounds = savedWfRounds
        } else if (validFamily) {
          templateType = validFamily as TemplateType
          wfRounds = requiredWfRounds(validFamily, n)
        }
      } catch (e) {
        // Invalid JSON, use auto-selected defaults
      }
    }

    if (event.schedule_profile_json) {
      try {
        scheduleProfile = normalizeScheduleProfile(JSON.parse(event.schedule_profile_json))
      } catch (e) {
        // Invalid JSON, use defaults
      }
    }

    if (!event.draw_plan_json && event.standard_block_minutes) {
      standardMinutes = event.standard_block_minutes
    }

    // Fallback to event.wf_block_minutes only when timing is absent from draw_plan_json.
    if (!event.draw_plan_json && event.wf_block_minutes) {
      waterfallMinutes = event.wf_block_minutes
    }

    // 14-team events always use the dedicated WF template (ignore stale RR_ONLY drafts).
    if (n === 14) {
      templateType = 'WF_14_TOP2_BYE'
      wfRounds = requiredWfRounds('WF_14_TOP2_BYE', 14)
    }

    return {
      templateType,
      wfRounds,
      standardMinutes,
      waterfallMinutes,
      scheduleProfile,
    }
  }

  const updateEventEditorState = (eventId: number, updates: Partial<EventEditorState>) => {
    setEventEditorStates(prev => ({
      ...prev,
      [eventId]: {
        ...prev[eventId],
        ...updates,
      },
    }))
  }

  const validateEvent = (event: Event, state: EventEditorState): string[] => {
    const errors: string[] = []
    const n = event.team_count

    // Even team count
    if (n % 2 !== 0) {
      errors.push('Team count must be even')
    }

    // Phase 1 supported team counts (using rules module)
    if (!isPhase1TeamCount(n)) {
      errors.push(
        `Team count ${n} is not supported in Phase 1 (supported: ${PHASE1_SUPPORTED_TEAM_COUNTS_SORTED.join(', ')})`,
      )
    }

    if (n === 14 && state.templateType !== 'WF_14_TOP2_BYE') {
      errors.push(
        '14 teams require template "14-team WF (top-2 rating byes + consolation flight)"',
      )
    }

    // Template-specific validations using rules module
    if (state.templateType === 'WF_TO_POOLS_DYNAMIC') {
      if (!isTeamCountValidForFamily('WF_TO_POOLS_DYNAMIC', n)) {
        const allowed = ALLOWED_TEAM_COUNTS.WF_TO_POOLS_DYNAMIC.join(',')
        errors.push(`WF_TO_POOLS_DYNAMIC requires team count in {${allowed}}, got ${n}`)
      }
      const expectedWfRounds = requiredWfRounds('WF_TO_POOLS_DYNAMIC', n)
      if (state.wfRounds !== expectedWfRounds) {
        errors.push(`WF_TO_POOLS_DYNAMIC with ${n} teams requires ${expectedWfRounds} waterfall rounds`)
      }
    }

    if (state.templateType === 'WF_TO_BRACKETS_8') {
      if (!isTeamCountValidForFamily('WF_TO_BRACKETS_8', n)) {
        errors.push('WF_TO_BRACKETS_8 requires exactly 32 teams')
      }
      const expectedWfRounds = requiredWfRounds('WF_TO_BRACKETS_8', n)
      if (state.wfRounds !== expectedWfRounds) {
        errors.push(`WF_TO_BRACKETS_8 requires ${expectedWfRounds} waterfall rounds`)
      }
    }

    if (state.templateType === 'WF_14_TOP2_BYE') {
      if (!isTeamCountValidForFamily('WF_14_TOP2_BYE', n)) {
        errors.push('WF_14_TOP2_BYE requires exactly 14 teams')
      }
      const expectedWfRounds = requiredWfRounds('WF_14_TOP2_BYE', n)
      if (state.wfRounds !== expectedWfRounds) {
        errors.push(`WF_14_TOP2_BYE requires ${expectedWfRounds} waterfall rounds (R1 on 12 + R2 on 8)`)
      }
    }

    // Legacy template validations (deprecated but kept for backwards compat)
    if (state.templateType === 'CANONICAL_32' && n !== 32) {
      errors.push('CANONICAL_32 requires exactly 32 teams')
    }

    if (state.templateType === 'WF_TO_POOLS_4' && n !== 16) {
      errors.push('WF_TO_POOLS_4 requires exactly 16 teams')
    }

    if (state.wfRounds < 0 || state.wfRounds > 2) {
      errors.push('Waterfall rounds must be 0, 1, or 2')
    }

    return errors
  }

  const handleSaveDraft = async (event: Event) => {
    if (!tournamentId) return

    const state = eventEditorStates[event.id]
    if (!state) return

    const errors = validateEvent(event, state)
    if (errors.length > 0) {
      showToast(`Validation errors: ${errors.join(', ')}`, 'error')
      return
    }

    try {
      setSaving(prev => ({ ...prev, [event.id]: true }))

      // Build draw_plan_json
      const drawPlan: DrawPlan = {
        version: '1.0',
        template_type: state.templateType,
        wf_rounds: state.wfRounds,
        post_wf: state.templateType === 'WF_TO_POOLS_4' ? 'rr_pools_4' : undefined,
        pool_assignment: state.templateType === 'WF_TO_POOLS_4' ? 'straight' : undefined,
        natural_flow: true,
        timing: {
          wf_block_minutes: state.waterfallMinutes,
          standard_block_minutes: state.standardMinutes,
        },
        cadence_hint: state.scheduleProfile,
      }

      await updateDrawPlan(event.id, {
        draw_plan_json: JSON.stringify(drawPlan),
        schedule_profile_json: JSON.stringify(state.scheduleProfile),
        wf_block_minutes: state.waterfallMinutes,
        standard_block_minutes: state.standardMinutes,
      })

      showToast('Draft saved successfully', 'success')
      await loadData() // Reload to get updated data
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save draft', 'error')
    } finally {
      setSaving(prev => ({ ...prev, [event.id]: false }))
    }
  }

  const handleFinalize = async (event: Event) => {
    if (!tournamentId || !phase1Status) return

    const state = eventEditorStates[event.id]
    if (!state) return

    const errors = validateEvent(event, state)
    if (errors.length > 0) {
      showToast(`Cannot finalize: ${errors.join(', ')}`, 'error')
      return
    }

    // Store scroll position before finalize
    const scrollY = window.scrollY

    try {
      setSaving(prev => ({ ...prev, [event.id]: true }))

      // Calculate match counts
      let matchCounts: MatchCounts
      try {
        matchCounts = calculateMatches(state.templateType, event.team_count, state.wfRounds)
      } catch (err) {
        showToast(err instanceof Error ? err.message : 'Invalid template configuration', 'error')
        return
      }

      // Check for estimation error (unsupported template)
      if (matchCounts.estimationError) {
        showToast(matchCounts.estimationError, 'error')
        return
      }

      // Use selected guarantee (default to 5)
      const selectedGuarantee = event.guarantee_selected ?? 5
      
      // Check if selected guarantee fits in remaining capacity
      const capacity = calculateTournamentCapacity()
      if (capacity) {
        const requiredMinutes = calculateMinutesRequired(
          matchCounts,
          state.waterfallMinutes,
          state.standardMinutes,
          selectedGuarantee as 4 | 5
        )
        
        // Check against remaining capacity (excluding this event since it's not finalized yet)
        if (requiredMinutes > capacity.remainingMinutes) {
          showToast(`Cannot finalize: Guarantee ${selectedGuarantee} requires ${minutesToHours(requiredMinutes)} but only ${minutesToHours(capacity.remainingMinutes)} remaining`, 'error')
          return
        }
      }

      // Save draft first with guarantee
      const drawPlan: DrawPlan = {
        version: '1.0',
        template_type: state.templateType,
        wf_rounds: state.wfRounds,
        post_wf: state.templateType === 'WF_TO_POOLS_4' ? 'rr_pools_4' : undefined,
        pool_assignment: state.templateType === 'WF_TO_POOLS_4' ? 'straight' : undefined,
        natural_flow: true,
        timing: {
          wf_block_minutes: state.waterfallMinutes,
          standard_block_minutes: state.standardMinutes,
        },
        cadence_hint: state.scheduleProfile,
      }

      await updateDrawPlan(event.id, {
        draw_plan_json: JSON.stringify(drawPlan),
        schedule_profile_json: JSON.stringify(state.scheduleProfile),
        wf_block_minutes: state.waterfallMinutes,
        standard_block_minutes: state.standardMinutes,
      })

      // Ensure guarantee_selected is saved
      await updateEvent(event.id, { guarantee_selected: selectedGuarantee })

      // Then finalize with guarantee
      await finalizeDrawPlan(event.id, selectedGuarantee)

      showToast(`Event finalized with guarantee ${selectedGuarantee} matches`, 'success')
      await loadData()
      
      // Restore scroll position after React re-renders
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to finalize', 'error')
      // Restore scroll position even on error
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } finally {
      setSaving(prev => ({ ...prev, [event.id]: false }))
    }
  }

  const handleReopenDraft = async (event: Event) => {
    // Store scroll position before reopen
    const scrollY = window.scrollY

    const confirmed = window.confirm(
      `Reopen "${event.name}" as a draft?\n\nThis clears the generated matches for this event so the roster can be edited/re-imported. ` +
      `Any scheduled slots and entered results for this event's matches will be removed. You can re-finalize afterward to regenerate matches.`
    )
    if (!confirmed) return

    try {
      setSaving(prev => ({ ...prev, [event.id]: true }))

      // Reopen clears this event's matches (releasing teams locked into a
      // finalized schedule) and sets the draw back to draft.
      const result = await reopenDrawPlan(event.id)

      showToast(
        result.matches_cleared > 0
          ? `Event reopened as draft — ${result.matches_cleared} match(es) cleared. Re-import roster if needed, then finalize to regenerate.`
          : 'Event reopened as draft',
        'success'
      )
      await loadData()
      
      // Restore scroll position after React re-renders
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to reopen draft', 'error')
      // Restore scroll position even on error
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } finally {
      setSaving(prev => ({ ...prev, [event.id]: false }))
    }
  }

  // Helper to calculate minutes for an event given a guarantee
  const calcEventMinutesForGuarantee = (event: Event, guarantee: 4 | 5): number | null => {
    try {
      let state = eventEditorStates[event.id]
      if (!state) {
        state = initializeEditorState(event)
      }
      const matchCounts = calculateMatches(state.templateType, event.team_count, state.wfRounds)
      // Skip if estimation error (unsupported template)
      if (matchCounts.estimationError) {
        console.warn(`Estimation error for event ${event.id}: ${matchCounts.estimationError}`)
        return null
      }
      return calculateMinutesRequired(matchCounts, state.waterfallMinutes, state.standardMinutes, guarantee)
    } catch (e) {
      console.warn(`Failed to calculate minutes for event ${event.id}:`, e)
      return null
    }
  }

  const handleImportTeams = async () => {
    if (!tournamentId || !importText.trim()) return
    setImportLoading(true)
    try {
      const res = await importCombinedTeams(tournamentId, importText)
      const parts: string[] = []
      if (res.imported_count > 0) parts.push(`${res.imported_count} imported`)
      if (res.updated_count > 0) parts.push(`${res.updated_count} updated`)
      if (res.events_touched > 0) parts.push(`${res.events_touched} draw${res.events_touched === 1 ? '' : 's'} updated`)
      if (res.towel_rows_imported > 0) {
        parts.push(`${res.towel_rows_imported} towel row${res.towel_rows_imported === 1 ? '' : 's'}`)
      }
      if (res.rejected_rows.length > 0) parts.push(`${res.rejected_rows.length} rejected`)
      showToast(parts.join(', ') || 'No changes', res.rejected_rows.length > 0 ? 'warning' : 'success')
      if (res.warnings.length > 0) {
        res.warnings.forEach(w => showToast(w, 'warning'))
      }
      if (res.rejected_rows.length > 0) {
        res.rejected_rows.forEach(r => showToast(`Line ${r.line}: ${r.reason}`, 'error'))
      }
      setImportText('')
      await loadData()
    } catch (err: any) {
      showToast(err?.message || 'Import failed', 'error')
    } finally {
      setImportLoading(false)
    }
  }

  const handleLoadTeams = async (eventId: number) => {
    setLoadingTeamsFor(eventId)
    try {
      const teams = await getEventTeams(eventId)
      setEventTeams(prev => ({ ...prev, [eventId]: teams }))
    } catch {
      showToast('Failed to load teams', 'error')
    } finally {
      setLoadingTeamsFor(null)
    }
  }

  const handleLegacyImportTeams = async (eventId: number) => {
    if (!tournamentId || !legacyImportText.trim()) return
    setLegacyImportLoading(true)
    try {
      const res = await importSeededTeams(tournamentId, eventId, legacyImportText)
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
      setLegacyImportText('')
      setLegacyImportOpenEventId(null)
      await Promise.all([handleLoadTeams(eventId), loadData()])
    } catch (err: any) {
      showToast(err?.message || 'Import failed', 'error')
    } finally {
      setLegacyImportLoading(false)
    }
  }

  // Calculate tournament-level capacity consumption
  const calculateTournamentCapacity = () => {
    if (!phase1Status) return null

    const totalCourtMinutes = phase1Status.summary.total_court_minutes
    let consumedMinutes = 0

    // Sum up minutes required by finalized events
    events.forEach(event => {
      if (event.draw_status === 'final' && event.draw_plan_json) {
        const guarantee = (event.guarantee_selected ?? 5) as 4 | 5
        const requiredMinutes = calcEventMinutesForGuarantee(event, guarantee)
        if (requiredMinutes !== null) {
          consumedMinutes += requiredMinutes
        }
      }
    })

    const remainingMinutes = totalCourtMinutes - consumedMinutes

    return {
      totalCourtMinutes,
      consumedMinutes,
      remainingMinutes,
    }
  }

  // Type for capacity event breakdown rows
  type CapacityEventRow = {
    id: number
    name: string
    guarantee: 4 | 5
    minutes: number
  }

  // Calculate finalized events breakdown for display
  const finalizedRows: CapacityEventRow[] = useMemo(() => {
    const rows: CapacityEventRow[] = events
      .filter(e => e.draw_status === 'final')
      .map(e => {
        const guarantee = (e.guarantee_selected ?? 5) as 4 | 5
        const minutes = calcEventMinutesForGuarantee(e, guarantee)
        
        if (minutes === null) {
          return null
        }

        return {
          id: e.id,
          name: e.name || `Event ${e.id}`,
          guarantee,
          minutes,
        }
      })
      .filter((row): row is CapacityEventRow => row !== null)

    // Sort highest hours first (largest lever to drop from 5 → 4)
    rows.sort((a, b) => b.minutes - a.minutes)

    return rows
  }, [events, eventEditorStates])

  const renderEventCard = (event: Event) => {
    // Ensure state exists
    if (!eventEditorStates[event.id]) {
      setEventEditorStates(prev => ({
        ...prev,
        [event.id]: initializeEditorState(event),
      }))
      return null // Will re-render
    }
    const state = eventEditorStates[event.id]
    const errors = validateEvent(event, state)
    
    // Calculate match counts and minutes using selected guarantee
    const selectedGuarantee = (event.guarantee_selected ?? 5) as 4 | 5
    let matchCounts: MatchCounts | null = null
    let requiredMinutes: number | null = null
    let estimationError: string | null = null

    try {
      matchCounts = calculateMatches(state.templateType, event.team_count, state.wfRounds)
      // Check for estimation error (unsupported template)
      if (matchCounts.estimationError) {
        estimationError = matchCounts.estimationError
      }
      requiredMinutes = calculateMinutesRequired(
        matchCounts,
        state.waterfallMinutes,
        state.standardMinutes,
        selectedGuarantee
      )
    } catch (e) {
      // Invalid configuration, show errors
      estimationError = e instanceof Error ? e.message : 'Failed to calculate matches'
    }

    // Can finalize only if no validation errors, even team count, and no estimation error
    const canFinalize = errors.length === 0 && event.team_count % 2 === 0 && !estimationError

    // Removed per-event headroom - now shown only at tournament level

    return (
      <div key={event.id} className="card" style={{ marginBottom: '24px' }}>
        <div className="info-tooltip-wrapper" style={{ marginBottom: '16px' }}>
          <h3 style={{ marginBottom: 0, display: 'inline-block' }}>
            {event.name} ({event.category}) - {event.team_count} teams
          </h3>
          <button
            type="button"
            className="info-icon-button"
            aria-label="Event summary help"
            title="Click for help"
          >
            i
          </button>
          <div className="info-tooltip" style={{ width: '600px', maxWidth: '90vw' }}>
            <div className="info-tooltip-title">{EVENT_SUMMARY_HELP.title}</div>
            {EVENT_SUMMARY_HELP.sections.map((section, idx) => (
              <div key={idx} className="info-tooltip-section">
                <div className="info-tooltip-section-heading">{section.heading}</div>
                <ul className="info-tooltip-list">
                  {section.bullets.map((bullet, bulletIdx) => (
                    <li key={bulletIdx}>{bullet}</li>
                  ))}
                </ul>
              </div>
            ))}
            <div className="info-tooltip-section" style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--theme-input-border)' }}>
              <div style={{ fontSize: '12px', color: 'var(--theme-text)' }}>
                <span style={{ fontWeight: '600' }}>In one sentence:</span> {EVENT_SUMMARY_HELP.oneSentence}
              </div>
            </div>
          </div>
        </div>

        <div style={{ marginBottom: '16px', display: 'flex', gap: '24px', alignItems: 'center' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label style={{ marginRight: '8px' }}>Status:</label>
            <span style={{ 
              display: 'inline-block',
              padding: '4px 12px',
              borderRadius: '12px',
              backgroundColor: 'var(--theme-table-row-hover)',
              color: 'var(--theme-text)',
              fontSize: '14px',
              fontWeight: '500'
            }}>
              {event.draw_status || 'not_started'}
            </span>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label style={{ marginRight: '8px' }}>Guarantee Matches:</label>
            <select
              value={event.guarantee_selected ?? 5}
              onChange={async (e) => {
                const newGuarantee = parseInt(e.target.value) as 4 | 5
                try {
                  await updateEvent(event.id, { guarantee_selected: newGuarantee })
                  // Update local event state
                  setEvents(prev => prev.map(ev => 
                    ev.id === event.id ? { ...ev, guarantee_selected: newGuarantee } : ev
                  ))
                  // Refetch inventory so totals update immediately from backend
                  await refetchInventory()
                } catch (err) {
                  showToast(err instanceof Error ? err.message : 'Failed to update guarantee', 'error')
                }
              }}
              style={{ padding: '4px 8px', fontSize: '14px', width: '80px', boxSizing: 'border-box' }}
            >
              <option value={4}>4</option>
              <option value={5}>5</option>
            </select>
          </div>
          {event.draw_status === 'final' && state.templateType !== 'RR_ONLY' && (
            <Link
              to={`/t/${tournamentId}/draws/${event.id}/waterfall`}
              target="_blank"
              style={{
                fontSize: 12,
                padding: '4px 12px',
                borderRadius: 4,
                backgroundColor: '#1a237e',
                color: '#fff',
                textDecoration: 'none',
                fontWeight: 500,
                whiteSpace: 'nowrap',
              }}
            >
              View Waterfall
            </Link>
          )}
        </div>

        <div style={{ marginTop: '-8px', marginBottom: '16px', fontSize: '12px', color: '#666' }}>
          Per-draw schedule order was removed from this screen. Use{' '}
          <strong>Event order by tournament day</strong> below; column dates match your schedule grid (published schedule version)
          when slots exist.
        </div>

        {errors.length > 0 && (
          <div style={{ padding: '12px', backgroundColor: '#f8d7da', color: '#721c24', borderRadius: '4px', marginBottom: '16px' }}>
            <strong>Errors:</strong>
            <ul style={{ margin: '8px 0 0 0', paddingLeft: '20px' }}>
              {errors.map((error, idx) => (
                <li key={idx}>{error}</li>
              ))}
            </ul>
          </div>
        )}

        {estimationError && (
          <div style={{ padding: '12px', backgroundColor: '#fff3cd', color: '#856404', borderRadius: '4px', marginBottom: '16px', border: '1px solid #ffc107' }}>
            <strong>Template Warning:</strong> {estimationError}
            <div style={{ fontSize: '12px', marginTop: '4px' }}>
              Finalize is disabled until a supported template is selected.
            </div>
          </div>
        )}

        <div className="form-group" style={{ marginBottom: '16px' }}>
          <label>Template Type</label>
          <select
            value={state.templateType}
            onChange={(e) => {
              const newType = e.target.value as TemplateType
              const n = event.team_count
              const updates: Partial<EventEditorState> = { templateType: newType }
              
              // Auto-set wfRounds based on template + team count (using rules module)
              if (newType === 'WF_TO_POOLS_DYNAMIC' || newType === 'WF_TO_BRACKETS_8' || newType === 'WF_14_TOP2_BYE' || newType === 'RR_ONLY') {
                updates.wfRounds = requiredWfRounds(newType, n)
              }
              
              updateEventEditorState(event.id, updates)
            }}
            disabled={event.draw_status === 'final'}
            style={{ width: '400px', maxWidth: '400px', boxSizing: 'border-box' }}
          >
            <option value="RR_ONLY">
              Round Robin Only ({ALLOWED_TEAM_COUNTS.RR_ONLY.join(', ')} teams)
            </option>
            <option 
              value="WF_TO_POOLS_DYNAMIC" 
              disabled={!isTeamCountValidForFamily('WF_TO_POOLS_DYNAMIC', event.team_count)}
            >
              Waterfall to Pools ({ALLOWED_TEAM_COUNTS.WF_TO_POOLS_DYNAMIC.join(',')})
              {!isTeamCountValidForFamily('WF_TO_POOLS_DYNAMIC', event.team_count) && ` — requires ${ALLOWED_TEAM_COUNTS.WF_TO_POOLS_DYNAMIC.join(',')}`}
            </option>
            <option 
              value="WF_TO_BRACKETS_8" 
              disabled={!isTeamCountValidForFamily('WF_TO_BRACKETS_8', event.team_count)}
            >
              Waterfall to Brackets ({ALLOWED_TEAM_COUNTS.WF_TO_BRACKETS_8.join(',')} teams)
              {!isTeamCountValidForFamily('WF_TO_BRACKETS_8', event.team_count) && ' — requires 32 teams'}
            </option>
            <option
              value="WF_14_TOP2_BYE"
              disabled={!isTeamCountValidForFamily('WF_14_TOP2_BYE', event.team_count)}
            >
              14-team WF (top-2 rating byes + consolation flight)
              {!isTeamCountValidForFamily('WF_14_TOP2_BYE', event.team_count) && ' — requires 14 teams'}
            </option>
          </select>
        </div>

        {(state.templateType === 'WF_TO_POOLS_DYNAMIC' || state.templateType === 'WF_TO_BRACKETS_8' || state.templateType === 'WF_14_TOP2_BYE') && (
          <div className="form-group" style={{ marginBottom: '16px' }}>
            <label>Waterfall Rounds</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ 
                padding: '4px 12px', 
                backgroundColor: 'var(--theme-table-row-hover)', 
                borderRadius: '4px',
                fontWeight: '500'
              }}>
                {state.wfRounds}
              </span>
              <span style={{ fontSize: '12px', color: '#666' }}>
                {state.templateType === 'WF_TO_POOLS_DYNAMIC' && 
                  (event.team_count === 8 || event.team_count === 10 
                    ? '(Fixed at 1 for 8-10 teams)' 
                    : '(Fixed at 2 for 12+ teams)')}
                {state.templateType === 'WF_TO_BRACKETS_8' && '(Fixed at 2 for 32 teams)'}
                {state.templateType === 'WF_14_TOP2_BYE' && '(R1: 12 teams / 6 matches; R2: 8 teams / 4 matches; top 2 combined rating byes)'}
              </span>
            </div>
          </div>
        )}

        {(state.templateType === 'WF_TO_POOLS_DYNAMIC' || state.templateType === 'WF_TO_POOLS_4' || state.templateType === 'WF_TO_BRACKETS_8' || state.templateType === 'WF_14_TOP2_BYE' || state.templateType === 'CANONICAL_32') && state.wfRounds > 0 && (
          <div className="form-group" style={{ marginBottom: '16px' }}>
            <label>Waterfall Match Length</label>
            <select
              value={state.waterfallMinutes}
              onChange={(e) => updateEventEditorState(event.id, { waterfallMinutes: parseInt(e.target.value) })}
              disabled={event.draw_status === 'final'}
              style={{ width: '120px', maxWidth: '120px', boxSizing: 'border-box' }}
            >
              {WATERFALL_BLOCK_OPTIONS.map((opt) => (
                <option key={opt.minutes} value={opt.minutes}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        )}

        {(state.templateType === 'WF_TO_POOLS_DYNAMIC' || state.templateType === 'WF_TO_BRACKETS_8' || state.templateType === 'WF_14_TOP2_BYE') && state.wfRounds > 0 && (
          <div
            className="form-group"
            style={{
              marginBottom: '16px',
              padding: '12px',
              borderRadius: '8px',
              border: '1px solid var(--theme-input-border)',
              backgroundColor: 'var(--theme-card-bg)',
            }}
          >
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>WF round 1 pairings (before play)</label>
            <p style={{ margin: '0 0 10px', fontSize: '12px', color: 'var(--theme-text)', opacity: 0.75 }}>
              Swap teams between sides on generated WF round 1 matches: click one side, then another. Columns Rt / Avoid show combined pair rating and avoid-group letters when roster data exists. Uses the schedule version the calendar prefers (draft when available).
            </p>
            {calendarScheduleVersionId == null && (
              <div style={{ fontSize: '13px', color: '#856404' }}>No schedule version available yet — generate matches from Schedule first.</div>
            )}
            {calendarScheduleVersionId != null &&
              (scheduleVersions.find((v) => v.id === calendarScheduleVersionId)?.status || '').toLowerCase() === 'final' && (
                <div style={{ fontSize: '13px', color: '#856404' }}>The active calendar version is finalized; swaps are blocked.</div>
              )}
            {calendarScheduleVersionId != null &&
              (scheduleVersions.find((v) => v.id === calendarScheduleVersionId)?.status || '').toLowerCase() !== 'final' && (
                <>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '10px', alignItems: 'center' }}>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={!!wfR1MatchesLoading[event.id]}
                      onClick={() => void fetchWfR1Matches(event.id)}
                    >
                      {wfR1MatchesLoading[event.id] ? 'Loading…' : 'Load WF R1 rows'}
                    </button>
                    {wfR1SwapPick?.eventId === event.id && (
                      <button type="button" className="btn btn-secondary" onClick={() => setWfR1SwapPick(null)}>
                        Clear selection
                      </button>
                    )}
                  </div>
                  {(wfR1MatchesByEvent[event.id]?.length ?? 0) === 0 && !wfR1MatchesLoading[event.id] && (
                    <div style={{ fontSize: '13px', opacity: 0.8 }}>Load rows after matches exist for this event.</div>
                  )}
                  {(wfR1MatchesByEvent[event.id]?.length ?? 0) > 0 && (
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                        <thead>
                          <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--theme-input-border)' }}>
                            <th style={{ padding: '6px 8px' }}>Match</th>
                            <th style={{ padding: '6px 8px' }}>Side A</th>
                            <th style={{ padding: '6px 8px', width: 56, textAlign: 'right' }} title="Combined doubles rating">
                              Rt
                            </th>
                            <th style={{ padding: '6px 8px', width: 52 }} title="Avoid group (who-knows-who letters)">
                              Avoid
                            </th>
                            <th style={{ padding: '6px 8px' }}>Side B</th>
                            <th style={{ padding: '6px 8px', width: 56, textAlign: 'right' }} title="Combined doubles rating">
                              Rt
                            </th>
                            <th style={{ padding: '6px 8px', width: 52 }} title="Avoid group (who-knows-who letters)">
                              Avoid
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {wfR1MatchesByEvent[event.id]!.map((m) => {
                            const pickA =
                              wfR1SwapPick?.eventId === event.id && wfR1SwapPick.matchId === m.id && wfR1SwapPick.slot === 'A'
                            const pickB =
                              wfR1SwapPick?.eventId === event.id && wfR1SwapPick.matchId === m.id && wfR1SwapPick.slot === 'B'
                            const teamsRow = eventTeams[event.id]
                            const ta = wfR1LookupTeam(teamsRow, m.team_a_id)
                            const tb = wfR1LookupTeam(teamsRow, m.team_b_id)
                            const metaCell: CSSProperties = {
                              padding: '6px 8px',
                              fontSize: '12px',
                              color: 'var(--theme-text)',
                              opacity: 0.85,
                              verticalAlign: 'middle',
                              whiteSpace: 'nowrap',
                            }
                            return (
                              <tr key={m.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.06)' }}>
                                <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>{m.match_code}</td>
                                <td style={{ padding: '6px 8px' }}>
                                  <button
                                    type="button"
                                    onClick={() => void handleWfR1SlotClick(event.id, m.id, 'A')}
                                    style={{
                                      display: 'block',
                                      width: '100%',
                                      textAlign: 'left',
                                      padding: '6px 8px',
                                      borderRadius: '6px',
                                      border: '1px solid var(--theme-input-border)',
                                      backgroundColor: 'var(--theme-table-row-hover)',
                                      cursor: 'pointer',
                                      fontSize: '13px',
                                      boxShadow: pickA ? '0 0 0 2px var(--theme-primary-btn-bg, #1a237e)' : undefined,
                                    }}
                                  >
                                    {m.placeholder_side_a}
                                  </button>
                                </td>
                                <td style={{ ...metaCell, textAlign: 'right' }}>{formatTeamRating(ta?.rating)}</td>
                                <td style={metaCell}>{formatAvoidGroup(ta?.avoid_group)}</td>
                                <td style={{ padding: '6px 8px' }}>
                                  <button
                                    type="button"
                                    onClick={() => void handleWfR1SlotClick(event.id, m.id, 'B')}
                                    style={{
                                      display: 'block',
                                      width: '100%',
                                      textAlign: 'left',
                                      padding: '6px 8px',
                                      borderRadius: '6px',
                                      border: '1px solid var(--theme-input-border)',
                                      backgroundColor: 'var(--theme-table-row-hover)',
                                      cursor: 'pointer',
                                      fontSize: '13px',
                                      boxShadow: pickB ? '0 0 0 2px var(--theme-primary-btn-bg, #1a237e)' : undefined,
                                    }}
                                  >
                                    {m.placeholder_side_b}
                                  </button>
                                </td>
                                <td style={{ ...metaCell, textAlign: 'right' }}>{formatTeamRating(tb?.rating)}</td>
                                <td style={metaCell}>{formatAvoidGroup(tb?.avoid_group)}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
          </div>
        )}

        <div className="form-group" style={{ marginBottom: '16px' }}>
          <label>Standard Match Length</label>
          <select
            value={state.standardMinutes}
            onChange={(e) => updateEventEditorState(event.id, { standardMinutes: parseInt(e.target.value) })}
            disabled={event.draw_status === 'final'}
            style={{ width: '120px', maxWidth: '120px', boxSizing: 'border-box' }}
          >
            {STANDARD_BLOCK_OPTIONS.map((opt) => (
              <option key={opt.minutes} value={opt.minutes}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {matchCounts && (
          <div style={{ padding: '12px', backgroundColor: 'var(--theme-card-bg)', borderRadius: '4px', marginBottom: '16px', color: 'var(--theme-text)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <strong>Capacity Metrics:</strong>
              {inventoryByEventId[event.id] != null && (
                <span style={{ fontWeight: 600 }}>
                  Total Matches: {inventoryByEventId[event.id].total_matches}
                </span>
              )}
              <button
                type="button"
                onClick={() => setExpandedExplanations(prev => ({ ...prev, [event.id]: !prev[event.id] }))}
                style={{
                  fontSize: '11px',
                  padding: '4px 8px',
                  border: '1px solid var(--theme-input-border)',
                  borderRadius: '4px',
                  backgroundColor: expandedExplanations[event.id] ? 'var(--theme-table-header)' : 'transparent',
                  color: expandedExplanations[event.id] ? 'var(--theme-primary-btn-text)' : 'var(--theme-text)',
                  cursor: 'pointer',
                  fontWeight: '500'
                }}
              >
                {expandedExplanations[event.id] ? 'Hide Why?' : 'Why?'}
              </button>
            </div>
            <div style={{ marginTop: '8px' }}>
              <div>
                Standard: {matchCounts.standardMatchesFor4 && matchCounts.standardMatchesFor5
                  ? (selectedGuarantee === 5 ? matchCounts.standardMatchesFor5 : matchCounts.standardMatchesFor4)
                  : matchCounts.standardMatches}
                {matchCounts.standardMatchesFor4 && matchCounts.standardMatchesFor5 && (
                  <> (
                    <span style={{ fontWeight: selectedGuarantee === 4 ? 'bold' : 'normal' }}>4: {matchCounts.standardMatchesFor4}</span>
                    {', '}
                    <span style={{ fontWeight: selectedGuarantee === 5 ? 'bold' : 'normal' }}>5: {matchCounts.standardMatchesFor5}</span>
                    )
                  </>
                )}
                <> × {minutesToHM(state.standardMinutes)}</>
                {matchCounts.wfMatches > 0 && (
                  <> | Waterfall: {matchCounts.wfMatches} × {minutesToHM(state.waterfallMinutes)}</>
                )}
              </div>
              
              {/* Explanation text */}
              {expandedExplanations[event.id] && (
              <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--theme-text)', lineHeight: '1.5', backgroundColor: 'var(--theme-card-bg)', padding: '8px', borderRadius: '4px' }}>
                <div style={{ marginBottom: '6px' }}>
                  <strong>How to read this calculation:</strong>
                </div>
                <div style={{ marginBottom: '6px' }}>
                  <strong>Standard:</strong> Standard matches are the non-waterfall matches in this event.
                  {matchCounts.standardMatchesFor4 && matchCounts.standardMatchesFor5 ? (
                    <>
                      {' '}The number {selectedGuarantee === 5 ? matchCounts.standardMatchesFor5 : matchCounts.standardMatchesFor4} is the total standard matches currently required.
                      {' '}The values in parentheses explain why: <strong style={{ fontWeight: selectedGuarantee === 4 ? 'bold' : 'normal' }}>4: {matchCounts.standardMatchesFor4}</strong> → If the guarantee were 4 matches per team, this event would require {matchCounts.standardMatchesFor4} standard matches.
                      {' '}<strong style={{ fontWeight: selectedGuarantee === 5 ? 'bold' : 'normal' }}>5: {matchCounts.standardMatchesFor5}</strong> → With the guarantee set to 5 matches per team, the event requires {matchCounts.standardMatchesFor5} standard matches.
                    </>
                  ) : (
                    <>
                      {' '}This event requires {matchCounts.standardMatches} total standard matches.
                    </>
                  )}
                  {' '}Each standard match is {minutesToHM(state.standardMinutes)}, so: {matchCounts.standardMatchesFor4 && matchCounts.standardMatchesFor5 
                    ? `${selectedGuarantee === 5 ? matchCounts.standardMatchesFor5 : matchCounts.standardMatchesFor4} × ${minutesToHM(state.standardMinutes)} = ${minutesToHours((selectedGuarantee === 5 ? matchCounts.standardMatchesFor5 : matchCounts.standardMatchesFor4) * state.standardMinutes)} court-hours`
                    : `${matchCounts.standardMatches} × ${minutesToHM(state.standardMinutes)} = ${minutesToHours(matchCounts.standardMatches * state.standardMinutes)} court-hours`}.
                </div>
                {matchCounts.wfMatches > 0 && (
                  <div style={{ marginBottom: '6px' }}>
                    <strong>Waterfall:</strong> Waterfall matches are the matches played before pool or bracket placement.
                    {' '}This event requires {matchCounts.wfMatches} waterfall match{matchCounts.wfMatches !== 1 ? 'es' : ''}.
                    {' '}Each waterfall match is {minutesToHM(state.waterfallMinutes)}, so: {matchCounts.wfMatches} × {minutesToHM(state.waterfallMinutes)} = {minutesToHours(matchCounts.wfMatches * state.waterfallMinutes)} court-hours.
                  </div>
                )}
                <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--theme-input-border)' }}>
                  <strong>Total impact:</strong> These values together determine how much total court time this event consumes.
                  {' '}Changing the guarantee or match length will immediately change these numbers.
                  {' '}No teams are assigned yet — these are placeholder calculations used for capacity planning.
                </div>
              </div>
              )}
              {requiredMinutes !== null && (
                <div>
                  <strong>Hours Required (Guarantee {selectedGuarantee}):</strong> {minutesToHours(requiredMinutes)}
                </div>
              )}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          {event.draw_status !== 'final' && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => handleSaveDraft(event)}
                disabled={saving[event.id]}
              >
                {saving[event.id] ? 'Saving...' : 'Save Draft'}
              </button>
              <button
                className="btn btn-success"
                onClick={() => handleFinalize(event)}
                disabled={saving[event.id] || !canFinalize}
                title={!canFinalize ? errors.join(', ') : ''}
              >
                {saving[event.id] ? 'Finalizing...' : 'Finalize'}
              </button>
            </>
          )}
          {event.draw_status === 'final' && (
            <button
              className="btn btn-secondary"
              onClick={() => handleReopenDraft(event)}
              disabled={saving[event.id]}
            >
              {saving[event.id] ? 'Reopening...' : 'Reopen Draft'}
            </button>
          )}
        </div>
      </div>
    )
  }

  if (loading) {
    return <div className="container"><div className="loading">Loading...</div></div>
  }

  if (!tournament || !phase1Status) {
    return <div className="container"><div className="error-message">Tournament not found</div></div>
  }

  return (
    <div className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1>Draw Builder</h1>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn btn-secondary" onClick={() => navigate(`/tournaments/${tournament.id}/setup`)}>
            Back to Setup
          </button>
          <button className="btn btn-primary" onClick={() => navigate(`/tournaments/${tournament.id}/schedule-builder`)}>
            Review Schedule Plan
          </button>
        </div>
      </div>

      {/* Tournament Summary */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <h2 className="section-title">Tournament Summary</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
          <div>
            <strong>Total Court Hours:</strong>
            <div>{minutesToHours(phase1Status.summary.total_court_minutes)}</div>
          </div>
          <div>
            <strong>Estimated Standard Slots (@2hr):</strong>
            <div>{Math.floor(phase1Status.summary.total_court_minutes / 120)}</div>
          </div>
          <div>
            <strong>Estimated WF Slots (@1hr):</strong>
            <div>{Math.floor(phase1Status.summary.total_court_minutes / 60)}</div>
          </div>
          <div>
            <strong>Events:</strong>
            <div>{phase1Status.summary.events_count}</div>
          </div>
        </div>
        <div style={{ marginTop: '12px', fontSize: '12px', color: '#666' }}>
          Note: This is informational only. Day-level scheduling happens on the Schedule page.
        </div>
      </div>

      {/* Per-day event ranking for schedule / WF ordering */}
      {events.length > 0 && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <h2 className="section-title">Event order by tournament day</h2>
          <p style={{ fontSize: 13, color: '#666', marginBottom: 16, maxWidth: 900 }}>
            Drag events to set placement priority for each calendar day that appears on your schedule. When a day&apos;s list is
            saved, scheduling uses this order first (including WF round batches), then fills remaining events using automatic
            rules. Column dates match the sorted slot dates for the schedule version you are editing (
            <strong>draft version first</strong>, otherwise the published version), which is the same{' '}
            <code style={{ fontSize: 12 }}>day_index</code> the policy planner uses when you run auto-assign on that draft.
            If there are no slots yet, we fall back to Setup days; generate slots, reload, verify columns, then Save event order again.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'flex-start' }}>
            {schedulePolicyDayIsoDates.map((iso, idx) => {
              const title = formatTournamentDayLabel(iso)
              const orderedIds = dayOrdersLocal[idx]?.length ? dayOrdersLocal[idx] : defaultEventOrder(events)
              return (
                <DayEventOrderColumn
                  key={`${iso}-${idx}`}
                  title={title}
                  orderedIds={orderedIds}
                  eventNames={eventNameById}
                  onReorder={(next) => reorderDayOrders(idx, next)}
                  onClear={() => clearDayOrdersRow(idx)}
                />
              )
            })}
          </div>
          <div style={{ marginTop: 20 }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={dayOrdersSaving}
              onClick={() => void handleSaveDayOrders()}
            >
              {dayOrdersSaving ? 'Saving…' : 'Save event order'}
            </button>
          </div>
        </div>
      )}

      {/* Event Cards */}
      <div>
        <h2 className="section-title">Events</h2>
        {events.length === 0 ? (
          <div className="card">
            <p>No events found. Add events in Tournament Setup first.</p>
          </div>
        ) : (
          events.map(event => renderEventCard(event))
        )}
      </div>

      {/* Tournament Capacity Panel */}
      {phase1Status && (() => {
        const capacity = calculateTournamentCapacity()
        if (!capacity) return null

        const isOverCapacity = capacity.remainingMinutes < 0

        return (
          <div className="card" style={{ marginTop: '24px' }}>
            <h2 className="section-title">Tournament Capacity</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
              <div>
                <strong>Total Court Hours:</strong>
                <div style={{ fontSize: '18px', fontWeight: 'bold', marginTop: '4px' }}>
                  {minutesToHours(capacity.totalCourtMinutes)}
                </div>
              </div>
              <div>
                <strong>Hours Committed (Finalized Events):</strong>
                <div style={{ fontSize: '18px', fontWeight: 'bold', marginTop: '4px' }}>
                  {minutesToHours(capacity.consumedMinutes)}
                </div>
              </div>
              <div>
                <strong>Hours Remaining:</strong>
                <div
                  style={{
                    fontSize: '18px',
                    fontWeight: 'bold',
                    marginTop: '4px',
                    color: isOverCapacity ? '#dc3545' : '#28a745',
                  }}
                >
                  {isOverCapacity
                    ? `Over capacity by ${minutesToHours(Math.abs(capacity.remainingMinutes))}`
                    : minutesToHours(capacity.remainingMinutes)}
                </div>
                {isOverCapacity && (
                  <div style={{ fontSize: '12px', color: '#dc3545', marginTop: '4px' }}>
                    ⚠️ Insufficient capacity
                  </div>
                )}
              </div>
            </div>

            {/* Per-event breakdown */}
            <div style={{ marginTop: '24px', paddingTop: '24px', borderTop: '1px solid rgba(0,0,0,0.1)' }}>
              <div style={{ fontWeight: 600, marginBottom: '12px', fontSize: '16px' }}>Finalized Events Breakdown</div>

              {finalizedRows.length === 0 ? (
                <div style={{ opacity: 0.7, fontSize: '14px' }}>No finalized events yet.</div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ textAlign: 'left', opacity: 0.85 }}>
                        <th style={{ padding: '8px 12px', borderBottom: '1px solid rgba(0,0,0,0.08)', fontWeight: 600 }}>
                          Event
                        </th>
                        <th style={{ padding: '8px 12px', borderBottom: '1px solid rgba(0,0,0,0.08)', width: 110, fontWeight: 600 }}>
                          Guarantee
                        </th>
                        <th style={{ padding: '8px 12px', borderBottom: '1px solid rgba(0,0,0,0.08)', width: 140, fontWeight: 600 }}>
                          Hours
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {finalizedRows.map((r) => (
                        <tr key={r.id}>
                          <td style={{ padding: '8px 12px', borderBottom: '1px solid rgba(0,0,0,0.06)' }}>
                            {r.name}
                          </td>
                          <td style={{ padding: '8px 12px', borderBottom: '1px solid rgba(0,0,0,0.06)' }}>
                            {r.guarantee}
                          </td>
                          <td style={{ padding: '8px 12px', borderBottom: '1px solid rgba(0,0,0,0.06)' }}>
                            {minutesToHours(r.minutes)}
                            <span style={{ marginLeft: 6, opacity: 0.7, fontSize: 12 }}>
                              ({r.minutes.toLocaleString()} min)
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Optional: quick hint for operators */}
              {finalizedRows.length > 0 && (
                <div style={{ marginTop: '12px', fontSize: '12px', opacity: 0.7, fontStyle: 'italic' }}>
                  Tip: If you're over capacity, reduce the guarantee from 5 to 4 on the events with the highest total hours first — they free up the most court time with one change.
                </div>
              )}
            </div>
          </div>
        )
      })()}

      {/* Combined roster + towel import */}
      {events.filter(e => e.draw_status === 'final').length > 0 && (
        <div className="card" style={{ marginTop: 24 }}>
          <h2 className="section-title">Combined Team + Towel Import</h2>
          <div style={{ fontSize: 13, color: 'var(--theme-text)', lineHeight: 1.5, marginBottom: 12 }}>
            Paste one tournament-wide sheet here. The <strong>Draw</strong> column routes each row into the right finalized draw automatically,
            and this same upload also refreshes the towel/contact rows used at check-in.
          </div>
          <textarea
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            placeholder={
              "Seed\tWho knows who\tFirst names team\tFull name, city, state team\tDraw\tLevel\ttowel color first player\tcellphone first player\temail first player\ttowel color second player\tcellphone second player\temail second player\n1\tB\tAlex / Torrie\tAlex Quiros, PA / Torrie Kline, PA\tWomens\t8.5\tBlue\t8123612060\talex@mail.com\tPink\t6109696386\ttorrie@mail.com\n2\tA\tJeni / Marina\tJeni Dao, TX / Marina Wang, TX\tMixed\t8.5\tGreen\t2819199929\tjeni@mail.com\tYellow\t7133068878\tmarina@mail.com"
            }
            style={{
              width: '100%',
              minHeight: 180,
              fontFamily: 'monospace',
              fontSize: 12,
              padding: 8,
              border: '1px solid #ccc',
              borderRadius: 4,
              resize: 'vertical',
              boxSizing: 'border-box',
            }}
          />
          <div style={{ display: 'flex', gap: 12, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              disabled={importLoading || !importText.trim()}
              onClick={() => handleImportTeams()}
              style={{ fontSize: 13, padding: '6px 14px' }}
            >
              {importLoading ? 'Importing...' : 'Import Teams + Towels'}
            </button>
            <span style={{ fontSize: 11, color: '#888' }}>
              Uses `Seed`, `Who knows who`, `First names team`, `Full name, city, state team`, `Draw`, `Level`,
              and both players&apos; towel/cell/email columns.
            </span>
          </div>
          <div style={{ marginTop: 12, fontSize: 12, color: '#666', lineHeight: 1.5 }}>
            Finalized draws ready for import:{' '}
            {events
              .filter(e => e.draw_status === 'final')
              .map(e => e.name)
              .join(', ')}
          </div>
        </div>
      )}

      {events.filter(e => e.draw_status === 'final').length > 0 && (
        <div className="card" style={{ marginTop: 24 }}>
          <h2 className="section-title">Legacy Per-Event Team Import</h2>
          {events.filter(e => e.draw_status === 'final').map((ev) => {
            const isOpen = legacyImportOpenEventId === ev.id
            const teams = eventTeams[ev.id]
            const isLoadingTeams = loadingTeamsFor === ev.id
            return (
              <div key={ev.id} style={{ marginBottom: 12, border: '1px solid #ddd', borderRadius: 6 }}>
                <div
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 14px', cursor: 'pointer', backgroundColor: 'rgba(0,0,0,0.02)',
                    borderRadius: 6,
                  }}
                  onClick={() => {
                    const nextOpen = isOpen ? null : ev.id
                    setLegacyImportOpenEventId(nextOpen)
                    if (nextOpen && !eventTeams[ev.id]) handleLoadTeams(ev.id)
                  }}
                >
                  <span style={{ fontWeight: 600 }}>
                    {isOpen ? '▾' : '▸'} {ev.name} ({ev.team_count} teams)
                  </span>
                  {teams && (
                    <span style={{ fontSize: 12, color: '#666' }}>
                      {teams.length} team{teams.length !== 1 ? 's' : ''} in DB
                    </span>
                  )}
                </div>

                {isOpen && (
                  <div style={{ padding: '12px 14px' }}>
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                        Import Seeded Teams (legacy path)
                      </div>
                      <textarea
                        value={legacyImportText}
                        onChange={(e) => setLegacyImportText(e.target.value)}
                        placeholder={"1\tB\tAlex / Torrie\tAlex Quiros, PA / Torrie Kline, PA\tWomens\t8.5\t8123612060\talex@mail.com\t6109696386\ttorrie@mail.com\n2\tA\tJeni / Marina\tJeni Dao, TX / Marina Wang, TX\tWomens\t8.5\t2819199929\tjeni@mail.com\t7133068878\tmarina@mail.com\n..."}
                        style={{
                          width: '100%', minHeight: 120, fontFamily: 'monospace', fontSize: 12,
                          padding: 8, border: '1px solid #ccc', borderRadius: 4, resize: 'vertical',
                          boxSizing: 'border-box',
                        }}
                      />
                      <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
                        <button
                          className="btn btn-primary"
                          disabled={legacyImportLoading || !legacyImportText.trim()}
                          onClick={() => handleLegacyImportTeams(ev.id)}
                          style={{ fontSize: 13, padding: '6px 14px' }}
                        >
                          {legacyImportLoading ? 'Importing...' : 'Import Teams'}
                        </button>
                        <span style={{ fontSize: 11, color: '#888' }}>
                          Format: seed  group  display_name  full_name  event  rating  p1_cell  p1_email  p2_cell  p2_email (tab separated)
                        </span>
                      </div>
                    </div>

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
                              <th style={{ padding: '4px 8px' }}>P1 Cell</th>
                              <th style={{ padding: '4px 8px' }}>P1 Email</th>
                              <th style={{ padding: '4px 8px' }}>P2 Cell</th>
                              <th style={{ padding: '4px 8px' }}>P2 Email</th>
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
                                <td style={{ padding: '4px 8px', fontSize: 11 }}>{t.p1_cell ?? '—'}</td>
                                <td style={{ padding: '4px 8px', fontSize: 11 }}>{t.p1_email ?? '—'}</td>
                                <td style={{ padding: '4px 8px', fontSize: 11 }}>{t.p2_cell ?? '—'}</td>
                                <td style={{ padding: '4px 8px', fontSize: 11 }}>{t.p2_email ?? '—'}</td>
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

      {/* Bottom navigation — gated by plan report contract */}
      {tournament && (() => {
        // Contract gating: use plan report as single source of truth
        const reportOk = planReport?.ok === true
        const reportLoaded = planReport != null
        const hasEvents = (planReport?.events?.length ?? 0) > 0
        const canGoToSchedule = !loading && reportLoaded && reportOk && hasEvents

        // First blocking error for display
        const firstBlockingError = planReport?.blocking_errors?.[0]

        return (
          <div style={{ marginTop: '32px', paddingTop: '24px', borderTop: '1px solid rgba(0,0,0,0.1)' }}>
            {/* Plan Report Status Banner */}
            {reportLoaded && (
              <div style={{
                marginBottom: '16px',
                padding: '12px 16px',
                borderRadius: '6px',
                backgroundColor: reportOk
                  ? 'rgba(40, 167, 69, 0.08)'
                  : 'rgba(220, 53, 69, 0.08)',
                border: `1px solid ${reportOk ? 'rgba(40, 167, 69, 0.2)' : 'rgba(220, 53, 69, 0.2)'}`,
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
              }}>
                <span style={{
                  fontSize: '18px',
                  fontWeight: 700,
                  color: reportOk ? '#28a745' : '#dc3545',
                }}>
                  {reportOk ? 'Ready to schedule' : 'Fix required'}
                </span>
                {!reportOk && firstBlockingError && (
                  <span style={{ fontSize: '13px', color: '#dc3545' }}>
                    {firstBlockingError.code}: {firstBlockingError.message}
                  </span>
                )}
                {reportOk && (
                  <span style={{ fontSize: '13px', color: '#28a745' }}>
                    {planReport.totals.events} event{planReport.totals.events !== 1 ? 's' : ''}, {planReport.totals.matches_total} total matches
                  </span>
                )}
              </div>
            )}

            {/* Blocking errors list (if any, grouped by event) */}
            {!reportOk && planReport && planReport.blocking_errors.length > 1 && (
              <div style={{
                marginBottom: '16px',
                padding: '12px 16px',
                backgroundColor: 'rgba(220, 53, 69, 0.04)',
                borderRadius: '4px',
                fontSize: '13px',
              }}>
                <strong style={{ color: '#dc3545' }}>Blocking errors ({planReport.blocking_errors.length}):</strong>
                <ul style={{ margin: '8px 0 0 0', paddingLeft: '20px', color: '#721c24' }}>
                  {planReport.blocking_errors.slice(0, 10).map((err, idx) => (
                    <li key={idx}>
                      <code style={{ fontSize: '11px', backgroundColor: 'rgba(0,0,0,0.05)', padding: '1px 4px', borderRadius: '2px' }}>{err.code}</code>{' '}
                      {err.message}
                    </li>
                  ))}
                  {planReport.blocking_errors.length > 10 && (
                    <li style={{ fontStyle: 'italic' }}>...and {planReport.blocking_errors.length - 10} more</li>
                  )}
                </ul>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-secondary"
                onClick={() => navigate(`/tournaments/${tournament.id}/schedule-builder`)}
                style={{ fontSize: '16px', padding: '12px 24px' }}
              >
                Review Schedule Plan
              </button>
              <button
                className={canGoToSchedule ? 'btn btn-primary' : 'btn btn-secondary'}
                onClick={() => navigate(`/tournaments/${tournament.id}/schedule`)}
                disabled={!canGoToSchedule}
                title={!canGoToSchedule
                  ? firstBlockingError
                    ? `${firstBlockingError.code}: ${firstBlockingError.message}`
                    : 'Complete Draw Builder steps first.'
                  : ''}
                style={{
                  fontSize: '16px',
                  padding: '12px 24px',
                  opacity: canGoToSchedule ? 1 : 0.6,
                  cursor: canGoToSchedule ? 'pointer' : 'not-allowed',
                }}
              >
                Go to Schedule
              </button>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

export default DrawBuilder


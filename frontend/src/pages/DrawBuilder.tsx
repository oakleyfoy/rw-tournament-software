import { useEffect, useState, useMemo } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  getTournament,
  getEvents,
  getPhase1Status,
  getScheduleBuilder,
  getPlanReport,
  importSeededTeams,
  getEventTeams,
  ScheduleBuilderResponse,
  SchedulePlanReport,
  updateDrawPlan,
  finalizeDrawPlan,
  updateEvent,
  Tournament,
  Event,
  Phase1Status,
  TeamListItem,
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
  PHASE1_SUPPORTED_TEAM_COUNTS,
  requiredWfRounds,
  getValidFamilyForTeamCount,
  isTeamCountValidForFamily,
} from '../utils/drawPlanRules'
import './TournamentSetup.css'

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

function DrawBuilder() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id) : null

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [phase1Status, setPhase1Status] = useState<Phase1Status | null>(null)
  const [inventoryByEventId, setInventoryByEventId] = useState<Record<number, { total_matches: number }>>({})
  const [scheduleBuilderData, setScheduleBuilderData] = useState<ScheduleBuilderResponse | null>(null)
  const [planReport, setPlanReport] = useState<SchedulePlanReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<number, boolean>>({})
  const [eventEditorStates, setEventEditorStates] = useState<Record<number, EventEditorState>>({})
  const [expandedExplanations, setExpandedExplanations] = useState<Record<number, boolean>>({})

  // Team import state
  const [importOpenEventId, setImportOpenEventId] = useState<number | null>(null)
  const [importText, setImportText] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [eventTeams, setEventTeams] = useState<Record<number, TeamListItem[]>>({})
  const [loadingTeamsFor, setLoadingTeamsFor] = useState<number | null>(null)

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
      const [tournamentData, eventsData, statusData, scheduleBuilderData, planReportData] = await Promise.all([
        getTournament(tournamentId),
        getEvents(tournamentId),
        getPhase1Status(tournamentId),
        getScheduleBuilder(tournamentId).catch(() => ({ events: [] } as ScheduleBuilderResponse)),
        getPlanReport(tournamentId).catch(() => null),
      ])
      
      setTournament(tournamentData)
      setEvents(eventsData)
      setPhase1Status(statusData)
      const inv: Record<number, { total_matches: number }> = {}
      scheduleBuilderData.events?.forEach((e: { event_id: number; total_matches: number }) => {
        inv[e.event_id] = { total_matches: e.total_matches }
      })
      setInventoryByEventId(inv)
      setScheduleBuilderData(scheduleBuilderData)
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
      const [sb, pr] = await Promise.all([
        getScheduleBuilder(tournamentId),
        getPlanReport(tournamentId).catch(() => null),
      ])
      const inv: Record<number, { total_matches: number }> = {}
      sb.events?.forEach((e: { event_id: number; total_matches: number }) => {
        inv[e.event_id] = { total_matches: e.total_matches }
      })
      setInventoryByEventId(inv)
      setScheduleBuilderData(sb)
      setPlanReport(pr)
    } catch {
      /* ignore */
    }
  }

  const initializeEditorState = (event: Event): EventEditorState => {
    const n = event.team_count
    
    // Phase 1 default template selection using rules module
    const validFamily = getValidFamilyForTeamCount(n)
    let templateType: TemplateType = validFamily ?? 'RR_ONLY'
    let wfRounds = validFamily ? requiredWfRounds(validFamily, n) : 0
    
    let standardMinutes = event.standard_block_minutes || 120
    let waterfallMinutes = 60 // Default to 1 hour
    let scheduleProfile: ScheduleProfile = {
      preferred: { fri: 2, sat: 2, sun: 1 },
      fallback: { fri: 2, sat: 1, sun: 2 },
    }

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
          isTeamCountValidForFamily(savedTemplate as 'RR_ONLY' | 'WF_TO_POOLS_DYNAMIC' | 'WF_TO_BRACKETS_8', n) ||
          (savedTemplate === 'WF_TO_POOLS_4' && n === 16) // Legacy support
        )
        
        if (isValidTemplate) {
          templateType = savedTemplate
          wfRounds = savedWfRounds
        }
      } catch (e) {
        // Invalid JSON, use auto-selected defaults
      }
    }

    if (event.schedule_profile_json) {
      try {
        scheduleProfile = JSON.parse(event.schedule_profile_json)
      } catch (e) {
        // Invalid JSON, use defaults
      }
    }

    if (event.standard_block_minutes) {
      standardMinutes = event.standard_block_minutes
    }

    // Fallback to event.wf_block_minutes if available (for backwards compatibility)
    if (event.wf_block_minutes) {
      waterfallMinutes = event.wf_block_minutes
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
    if (!PHASE1_SUPPORTED_TEAM_COUNTS.includes(n)) {
      errors.push(`Team count ${n} is not supported in Phase 1 (supported: ${PHASE1_SUPPORTED_TEAM_COUNTS.join(', ')})`)
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

    try {
      setSaving(prev => ({ ...prev, [event.id]: true }))

      await updateDrawPlan(event.id, {
        draw_plan_json: event.draw_plan_json,
        schedule_profile_json: event.schedule_profile_json || null,
        wf_block_minutes: event.wf_block_minutes || null,
        standard_block_minutes: event.standard_block_minutes || null,
      })

      // Manually update event status to draft via updateEvent
      const { updateEvent } = await import('../api/client')
      await updateEvent(event.id, {
        draw_status: 'draft',
        guarantee_selected: null,
      })

      showToast('Event reopened as draft', 'success')
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

  const handleImportTeams = async (eventId: number) => {
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
              if (newType === 'WF_TO_POOLS_DYNAMIC' || newType === 'WF_TO_BRACKETS_8' || newType === 'RR_ONLY') {
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
          </select>
        </div>

        {(state.templateType === 'WF_TO_POOLS_DYNAMIC' || state.templateType === 'WF_TO_BRACKETS_8') && (
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
              </span>
            </div>
          </div>
        )}

        {(state.templateType === 'WF_TO_POOLS_DYNAMIC' || state.templateType === 'WF_TO_POOLS_4' || state.templateType === 'WF_TO_BRACKETS_8' || state.templateType === 'CANONICAL_32') && state.wfRounds > 0 && (
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

      {/* Team Rosters — import seeded teams per event */}
      {events.filter(e => e.draw_status === 'final').length > 0 && (
        <div className="card" style={{ marginTop: 24 }}>
          <h2 className="section-title">Team Rosters</h2>
          {events.filter(e => e.draw_status === 'final').map((ev) => {
            const isOpen = importOpenEventId === ev.id
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
                    setImportOpenEventId(nextOpen)
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
                        Import Seeded Teams (paste tab-separated or space-separated)
                      </div>
                      <textarea
                        value={importText}
                        onChange={(e) => setImportText(e.target.value)}
                        placeholder={"1\ta\t9\tHeather Robinson / Shea Butler\n2\tb\t8.5\tJane Doe / Mary Smith\n..."}
                        style={{
                          width: '100%', minHeight: 120, fontFamily: 'monospace', fontSize: 12,
                          padding: 8, border: '1px solid #ccc', borderRadius: 4, resize: 'vertical',
                          boxSizing: 'border-box',
                        }}
                      />
                      <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
                        <button
                          className="btn btn-primary"
                          disabled={importLoading || !importText.trim()}
                          onClick={() => handleImportTeams(ev.id)}
                          style={{ fontSize: 13, padding: '6px 14px' }}
                        >
                          {importLoading ? 'Importing...' : 'Import Teams'}
                        </button>
                        <span style={{ fontSize: 11, color: '#888' }}>
                          Format: seed [avoid_group] rating team_name (tab or space separated)
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


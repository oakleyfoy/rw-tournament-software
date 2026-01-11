import { useState, useEffect, useCallback } from 'react'
import {
  getTournament,
  getEvents,
  getScheduleVersions,
  createScheduleVersion,
  finalizeScheduleVersion,
  cloneScheduleVersion,
  getSlots,
  getMatches,
  createAssignment,
  deleteAssignment,
  buildSchedule,
  Tournament,
  Event,
  ScheduleVersion,
  ScheduleSlot,
  Match,
} from '../../../api/client'
import { showToast } from '../../../utils/toast'
import { BuildSummary, UnscheduledMatch } from '../types'

interface UseScheduleAutoBuildReturn {
  // Data
  tournament: Tournament | null
  events: Event[]
  versions: ScheduleVersion[]
  activeVersion: ScheduleVersion | null
  slots: ScheduleSlot[]
  matches: Match[]
  unscheduledMatches: UnscheduledMatch[]
  buildSummary: BuildSummary | null
  
  // Loading states
  loading: boolean
  building: boolean
  
  // Actions
  createDraft: () => Promise<void>
  buildSchedule: () => Promise<void>
  finalizeDraft: () => Promise<void>
  cloneFinalToDraft: () => Promise<void>
  assign: (slotId: number, matchId: number) => Promise<void>
  unassign: (slotId: number) => Promise<void>
  
  // Version selection
  setActiveVersion: (version: ScheduleVersion | null) => void
}

export function useScheduleAutoBuild(tournamentId: number | null): UseScheduleAutoBuildReturn {
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [activeVersion, setActiveVersion] = useState<ScheduleVersion | null>(null)
  const [slots, setSlots] = useState<ScheduleSlot[]>([])
  const [matches, setMatches] = useState<Match[]>([])
  const [buildSummary, setBuildSummary] = useState<BuildSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)

  // Load tournament and events
  const loadTournamentData = useCallback(async () => {
    if (!tournamentId) return
    
    try {
      const [tournamentData, eventsData] = await Promise.all([
        getTournament(tournamentId),
        getEvents(tournamentId),
      ])
      
      setTournament(tournamentData)
      setEvents(eventsData)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load tournament data', 'error')
    }
  }, [tournamentId])

  // Load versions
  const loadVersions = useCallback(async () => {
    if (!tournamentId) return
    
    try {
      const versionsData = await getScheduleVersions(tournamentId)
      setVersions(versionsData)
      
      // Determine active version: draft preferred, otherwise first version
      const draft = versionsData.find(v => v.status === 'draft')
      if (draft) {
        setActiveVersion(draft)
      } else if (versionsData.length > 0) {
        setActiveVersion(versionsData[0])
      } else {
        setActiveVersion(null)
      }
    } catch (err) {
      console.warn('Failed to load schedule versions:', err)
      setVersions([])
      setActiveVersion(null)
    }
  }, [tournamentId])

  // Load slots and matches for active version
  const loadSlotsAndMatches = useCallback(async () => {
    if (!tournamentId || !activeVersion) {
      setSlots([])
      setMatches([])
      return
    }
    
    try {
      const [slotsData, matchesData] = await Promise.all([
        getSlots(tournamentId, activeVersion.id),
        getMatches(tournamentId, activeVersion.id),
      ])
      
      setSlots(slotsData)
      setMatches(matchesData)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load slots/matches', 'error')
    }
  }, [tournamentId, activeVersion])

  // Initial load
  useEffect(() => {
    const loadAll = async () => {
      setLoading(true)
      await loadTournamentData()
      await loadVersions()
      setLoading(false)
    }
    loadAll()
  }, [loadTournamentData, loadVersions])

  // Load slots/matches when active version changes
  useEffect(() => {
    loadSlotsAndMatches()
  }, [loadSlotsAndMatches])

  // Create draft version
  const createDraft = useCallback(async () => {
    if (!tournamentId) return
    
    try {
      const version = await createScheduleVersion(tournamentId)
      setVersions(prev => [version, ...prev])
      setActiveVersion(version)
      showToast('Draft schedule version created', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to create draft', 'error')
    }
  }, [tournamentId])

  // Build schedule (one-click)
  const handleBuildSchedule = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    if (activeVersion.status === 'final') {
      showToast('Cannot build a finalized schedule', 'error')
      return
    }
    
    try {
      setBuilding(true)
      const result = await buildSchedule(tournamentId, activeVersion.id)
      
      // Refresh slots and matches
      await loadSlotsAndMatches()
      
      // Store build summary
      setBuildSummary({
        slots_created: result.slots_created,
        matches_created: result.matches_created,
        matches_assigned: result.matches_assigned,
        matches_unassigned: result.matches_unassigned,
        conflicts: result.conflicts,
        warnings: result.warnings,
      })
      
      showToast(
        `Schedule built: ${result.matches_assigned} matches assigned, ${result.matches_unassigned} unassigned`,
        'success'
      )
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to build schedule', 'error')
    } finally {
      setBuilding(false)
    }
  }, [tournamentId, activeVersion, loadSlotsAndMatches])

  // Finalize draft
  const finalizeDraft = useCallback(async () => {
    if (!tournamentId || !activeVersion || activeVersion.status !== 'draft') return
    
    try {
      const finalized = await finalizeScheduleVersion(tournamentId, activeVersion.id)
      setVersions(prev => prev.map(v => v.id === finalized.id ? finalized : v))
      setActiveVersion(finalized)
      showToast('Schedule finalized', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to finalize schedule', 'error')
    }
  }, [tournamentId, activeVersion])

  // Clone final to draft
  const cloneFinalToDraft = useCallback(async () => {
    if (!tournamentId || !activeVersion || activeVersion.status !== 'final') return
    
    try {
      const cloned = await cloneScheduleVersion(tournamentId, activeVersion.id)
      setVersions(prev => [cloned, ...prev])
      setActiveVersion(cloned)
      showToast('Final schedule cloned to draft', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to clone schedule', 'error')
    }
  }, [tournamentId, activeVersion])

  // Assign match to slot (exception handling only)
  const assign = useCallback(async (slotId: number, matchId: number) => {
    if (!tournamentId || !activeVersion || activeVersion.status === 'final') return
    
    try {
      await createAssignment(tournamentId, {
        schedule_version_id: activeVersion.id,
        match_id: matchId,
        slot_id: slotId,
      })
      showToast('Match assigned', 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to assign match', 'error')
    }
  }, [tournamentId, activeVersion, loadSlotsAndMatches])

  // Unassign match from slot
  const unassign = useCallback(async (slotId: number) => {
    if (!tournamentId || !activeVersion || activeVersion.status === 'final') return
    
    const slot = slots.find(s => s.id === slotId)
    if (!slot || !slot.assignment_id) return
    
    try {
      await deleteAssignment(tournamentId, slot.assignment_id)
      showToast('Match unassigned', 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to unassign match', 'error')
    }
  }, [tournamentId, activeVersion, slots, loadSlotsAndMatches])

  // Compute unscheduled matches
  const unscheduledMatches: UnscheduledMatch[] = matches
    .filter(m => m.status === 'unscheduled')
    .map(m => ({
      ...m,
      event_id: m.event_id,
      match_code: m.match_code,
      match_type: m.match_type,
      duration_minutes: m.duration_minutes,
      status: m.status,
    }))

  return {
    tournament,
    events,
    versions,
    activeVersion,
    slots,
    matches, // Expose matches for components
    unscheduledMatches,
    buildSummary,
    loading,
    building,
    createDraft,
    buildSchedule: handleBuildSchedule,
    finalizeDraft,
    cloneFinalToDraft,
    assign,
    unassign,
    setActiveVersion,
  }
}


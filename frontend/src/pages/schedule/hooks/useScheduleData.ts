import { useState, useEffect, useCallback } from 'react'
import {
  getTournament,
  getEvents,
  getScheduleVersions,
  createScheduleVersion,
  finalizeScheduleVersion,
  deleteScheduleVersion,
  generateSlots,
  getSlots,
  generateMatches,
  getMatches,
  createAssignment,
  deleteAssignment,
  Tournament,
  Event,
  ScheduleVersion,
  ScheduleSlot,
  Match,
} from '../../../api/client'
import { showToast } from '../../../utils/toast'
import { confirmDialog } from '../../../utils/confirm'

interface UseScheduleDataReturn {
  // Data
  tournament: Tournament | null
  events: Event[]
  versions: ScheduleVersion[]
  currentVersion: ScheduleVersion | null
  slots: ScheduleSlot[]
  matches: Match[]
  unscheduledMatches: Match[]
  
  // Loading states
  loading: boolean
  generating: boolean
  
  // Actions
  createDraft: () => Promise<void>
  generateSlotsAction: () => Promise<void>
  generateMatchesAction: () => Promise<void>
  assignMatch: (slotId: number, matchId: number) => Promise<void>
  unassignMatch: (assignmentId: number) => Promise<void>
  finalizeDraft: () => Promise<void>
  deleteVersion: () => Promise<void>
  cloneFinalToDraft: () => Promise<void>
  
  // Refresh
  refresh: () => Promise<void>
}

export function useScheduleData(tournamentId: number | null): UseScheduleDataReturn {
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [currentVersion, setCurrentVersion] = useState<ScheduleVersion | null>(null)
  const [slots, setSlots] = useState<ScheduleSlot[]>([])
  const [matches, setMatches] = useState<Match[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)

  const loadData = useCallback(async () => {
    if (!tournamentId) return
    
    try {
      setLoading(true)
      const [tournamentData, eventsData] = await Promise.all([
        getTournament(tournamentId),
        getEvents(tournamentId),
      ])
      
      setTournament(tournamentData)
      setEvents(eventsData)
      
      try {
        const versionsData = await getScheduleVersions(tournamentId)
        setVersions(versionsData)
        
        const draft = versionsData.find(v => v.status === 'draft')
        if (draft) {
          setCurrentVersion(draft)
        } else if (versionsData.length > 0) {
          setCurrentVersion(versionsData[0])
        } else {
          setCurrentVersion(null)
        }
      } catch (versionsErr) {
        console.warn('Failed to load schedule versions:', versionsErr)
        setVersions([])
        setCurrentVersion(null)
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load data', 'error')
    } finally {
      setLoading(false)
    }
  }, [tournamentId])

  const loadSlotsAndMatches = useCallback(async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      const [slotsData, matchesData] = await Promise.all([
        getSlots(tournamentId, currentVersion.id),
        getMatches(tournamentId, currentVersion.id),
      ])
      
      setSlots(slotsData)
      setMatches(matchesData)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load slots/matches', 'error')
    }
  }, [tournamentId, currentVersion])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    if (currentVersion) {
      loadSlotsAndMatches()
    }
  }, [currentVersion, loadSlotsAndMatches])

  const createDraft = useCallback(async () => {
    if (!tournamentId) return
    
    try {
      const version = await createScheduleVersion(tournamentId)
      setVersions(prev => [version, ...prev])
      setCurrentVersion(version)
      showToast('Draft schedule version created', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to create draft', 'error')
    }
  }, [tournamentId])

  const generateSlotsAction = useCallback(async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      setGenerating(true)
      const result = await generateSlots(tournamentId, {
        source: 'auto',
        schedule_version_id: currentVersion.id,
        wipe_existing: true,
      })
      showToast(`Generated ${result.slots_created} slots`, 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to generate slots', 'error')
    } finally {
      setGenerating(false)
    }
  }, [tournamentId, currentVersion, loadSlotsAndMatches])

  const generateMatchesAction = useCallback(async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      setGenerating(true)
      const result = await generateMatches(tournamentId, {
        schedule_version_id: currentVersion.id,
        wipe_existing: true,
      })
      showToast(`Generated ${result.total_matches_created} matches`, 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to generate matches', 'error')
    } finally {
      setGenerating(false)
    }
  }, [tournamentId, currentVersion, loadSlotsAndMatches])

  const assignMatch = useCallback(async (slotId: number, matchId: number) => {
    if (!tournamentId || !currentVersion) return
    
    try {
      // Optimistic update
      const slot = slots.find(s => s.id === slotId)
      const match = matches.find(m => m.id === matchId)
      if (slot && match) {
        setSlots(prev => prev.map(s => s.id === slotId ? { ...s, match_id: matchId } : s))
      }
      
      await createAssignment(tournamentId, {
        schedule_version_id: currentVersion.id,
        match_id: matchId,
        slot_id: slotId,
      })
      showToast('Match assigned', 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      // Revert on error
      await loadSlotsAndMatches()
      showToast(err instanceof Error ? err.message : 'Failed to assign match', 'error')
    }
  }, [tournamentId, currentVersion, slots, matches, loadSlotsAndMatches])

  const unassignMatch = useCallback(async (assignmentId: number) => {
    if (!tournamentId) return
    
    try {
      // Optimistic update
      setSlots(prev => prev.map(s => s.assignment_id === assignmentId ? { ...s, match_id: null, assignment_id: null } : s))
      
      await deleteAssignment(tournamentId, assignmentId)
      showToast('Match unassigned', 'success')
      await loadSlotsAndMatches()
    } catch (err) {
      // Revert on error
      await loadSlotsAndMatches()
      showToast(err instanceof Error ? err.message : 'Failed to unassign match', 'error')
    }
  }, [tournamentId, loadSlotsAndMatches])

  const finalizeDraft = useCallback(async () => {
    if (!tournamentId || !currentVersion) return
    
    try {
      const finalized = await finalizeScheduleVersion(tournamentId, currentVersion.id)
      setVersions(prev => prev.map(v => v.id === finalized.id ? finalized : v))
      setCurrentVersion(finalized)
      showToast('Schedule finalized', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to finalize schedule', 'error')
    }
  }, [tournamentId, currentVersion])

  const deleteVersion = useCallback(async () => {
    if (!tournamentId || !currentVersion) return
    
    const confirmed = await confirmDialog(
      `Are you sure you want to delete Version ${currentVersion.version_number}?\n\nThis will permanently delete all associated data.`
    )
    if (!confirmed) return
    
    try {
      await deleteScheduleVersion(tournamentId, currentVersion.id)
      showToast('Schedule version deleted successfully', 'success')
      setCurrentVersion(null)
      await loadData()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to delete schedule version', 'error')
    }
  }, [tournamentId, currentVersion, loadData])

  const cloneFinalToDraft = useCallback(async () => {
    if (!tournamentId || !currentVersion || currentVersion.status !== 'final') return
    
    try {
      // This would need a backend endpoint to clone a version
      // For now, just show a message
      showToast('Clone functionality not yet implemented', 'warning')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to clone version', 'error')
    }
  }, [tournamentId, currentVersion])

  const unscheduledMatches = matches.filter(m => m.status === 'unscheduled')

  return {
    tournament,
    events,
    versions,
    currentVersion,
    slots,
    matches,
    unscheduledMatches,
    loading,
    generating,
    createDraft,
    generateSlotsAction,
    generateMatchesAction,
    assignMatch,
    unassignMatch,
    finalizeDraft,
    deleteVersion,
    cloneFinalToDraft,
    refresh: loadSlotsAndMatches,
  }
}


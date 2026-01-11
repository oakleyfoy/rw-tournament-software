import { useState, useEffect, useCallback } from 'react'
import {
  getTournament,
  getEvents,
  getScheduleVersions,
  createScheduleVersion,
  finalizeScheduleVersion,
  cloneScheduleVersion,
  buildSchedule,
  getScheduleGrid,
  Tournament,
  Event,
  ScheduleVersion,
  ScheduleGridV1,
} from '../../../api/client'
import { showToast } from '../../../utils/toast'
import { BuildSummary } from '../types'

interface UseScheduleGridReturn {
  // Data
  tournament: Tournament | null
  events: Event[]
  versions: ScheduleVersion[]
  activeVersion: ScheduleVersion | null
  gridData: ScheduleGridV1 | null
  buildSummary: BuildSummary | null
  
  // Loading states
  loading: boolean
  building: boolean
  
  // Actions
  createDraft: () => Promise<void>
  buildSchedule: () => Promise<void>
  finalizeDraft: () => Promise<void>
  cloneFinalToDraft: () => Promise<void>
  refresh: () => Promise<void>
  
  // Version selection
  setActiveVersion: (version: ScheduleVersion | null) => void
}

export function useScheduleGrid(tournamentId: number | null): UseScheduleGridReturn {
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [versions, setVersions] = useState<ScheduleVersion[]>([])
  const [activeVersion, setActiveVersion] = useState<ScheduleVersion | null>(null)
  const [gridData, setGridData] = useState<ScheduleGridV1 | null>(null)
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

  // Load grid data
  const loadGridData = useCallback(async () => {
    if (!tournamentId || !activeVersion) {
      setGridData(null)
      return
    }
    
    try {
      const data = await getScheduleGrid(tournamentId, activeVersion.id)
      setGridData(data)
    } catch (err) {
      console.error('Failed to load grid data:', err)
      showToast(err instanceof Error ? err.message : 'Failed to load schedule grid', 'error')
      setGridData(null)
    }
  }, [tournamentId, activeVersion])

  // Initial load
  useEffect(() => {
    if (!tournamentId) {
      setLoading(false)
      return
    }

    const load = async () => {
      setLoading(true)
      await loadTournamentData()
      await loadVersions()
      setLoading(false)
    }

    load()
  }, [tournamentId, loadTournamentData, loadVersions])

  // Load grid data when active version changes
  useEffect(() => {
    if (activeVersion) {
      loadGridData()
    }
  }, [activeVersion, loadGridData])

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
  const buildScheduleAction = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    
    try {
      setBuilding(true)
      setBuildSummary(null)
      
      const result = await buildSchedule(tournamentId, activeVersion.id)
      
      // Show summary (map backend response to frontend BuildSummary type)
      setBuildSummary({
        slots_created: result.slots_created || 0,
        matches_created: result.matches_created || 0,
        matches_assigned: result.matches_assigned || 0,
        matches_unassigned: result.matches_unassigned || 0,
        conflicts: result.conflicts,
        warnings: result.warnings,
      })
      
      // Reload grid data
      await loadGridData()
      
      showToast('Schedule built successfully', 'success')
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to build schedule'
      showToast(errorMessage, 'error')
      
      // If there's detailed error info, try to reload anyway to show partial state
      await loadGridData()
    } finally {
      setBuilding(false)
    }
  }, [tournamentId, activeVersion, loadGridData])

  // Finalize draft
  const finalizeDraft = useCallback(async () => {
    if (!tournamentId || !activeVersion) return
    
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
      showToast('Schedule cloned to draft', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to clone schedule', 'error')
    }
  }, [tournamentId, activeVersion])

  // Refresh grid data
  const refresh = useCallback(async () => {
    await loadGridData()
  }, [loadGridData])

  return {
    tournament,
    events,
    versions,
    activeVersion,
    gridData,
    buildSummary,
    loading,
    building,
    createDraft,
    buildSchedule: buildScheduleAction,
    finalizeDraft,
    cloneFinalToDraft,
    refresh,
    setActiveVersion,
  }
}


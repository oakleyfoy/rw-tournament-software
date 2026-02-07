import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getTournament,
  updateTournament,
  createTournament,
  getTournamentDays,
  updateTournamentDays,
  getEvents,
  createEvent,
  updateEvent,
  deleteEvent,
  getPhase1Status,
  getTimeWindows,
  createTimeWindow,
  updateTimeWindow,
  deleteTimeWindow,
  getTimeWindowsSummary,
  getScheduleVersions,
  Tournament,
  TournamentDay,
  Event,
  Phase1Status,
  DayUpdate,
  EventCreate,
  TimeWindow,
  TimeWindowCreate,
  TimeWindowUpdate,
  TimeWindowSummary,
  ScheduleVersion,
} from '../api/client'
import { showToast } from '../utils/toast'
import { confirmDialog } from '../utils/confirm'
import { minutesToHours, timeTo12Hour } from '../utils/timeFormat'
import { CAPACITY_SOURCE_HELP } from '../constants/capacitySourceHelp'
import { DAYS_COURTS_HELP } from '../constants/daysCourtsHelp'
import { TIME_WINDOWS_HELP } from '../constants/timeWindowsHelp'
import './TournamentSetup.css'

function TournamentSetup() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isNew = id === 'new'

  const [tournament, setTournament] = useState<Partial<Tournament>>({
    name: '',
    location: '',
    timezone: 'America/New_York',
    start_date: '',
    end_date: '',
    notes: '',
    use_time_windows: false,
    court_names: null,
  })
  const [days, setDays] = useState<TournamentDay[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [phase1Status, setPhase1Status] = useState<Phase1Status | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingEventId, setEditingEventId] = useState<number | null>(null)
  const [editingEvents, setEditingEvents] = useState<Record<number, Partial<Event>>>({})
  const [newEvent, setNewEvent] = useState<Partial<EventCreate>>({
    category: 'mixed',
    name: '',
    team_count: 2,
    notes: '',
  })
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})
  const [courtNamesInput, setCourtNamesInput] = useState<string>('')
  
  // Time Windows state
  const [timeWindows, setTimeWindows] = useState<TimeWindow[]>([])
  const [editingWindows, setEditingWindows] = useState<Record<number, Partial<TimeWindow>>>({})
  const [newWindow, setNewWindow] = useState<Partial<TimeWindowCreate>>({
    day_date: '',
    start_time: '',
    end_time: '',
    courts_available: 1,
    block_minutes: 120,
    label: '',
    is_active: true,
  })
  const [timeWindowSummary, setTimeWindowSummary] = useState<TimeWindowSummary | null>(null)
  const [isAutoGenerating, setIsAutoGenerating] = useState(false)
  const [scheduleVersions, setScheduleVersions] = useState<ScheduleVersion[]>([])
  const [originalCourtNames, setOriginalCourtNames] = useState<string[] | null>(null)

  // Helper functions for date/time normalization
  const formatDateMDY = (iso: string): string => {
    // iso: YYYY-MM-DD
    // Format as M/D/YY without using Date objects (no timezone issues)
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (!m) return iso
    const [, y, mo, d] = m
    return `${Number(mo)}/${Number(d)}/${y.slice(2)}`
  }

  const toISODate = (d: any): string => {
    if (!d) return ''

    // ✅ If already YYYY-MM-DD, return as-is (NO Date conversion)
    if (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d)) {
      const out = d
      console.log('toISODate input=', d, 'output=', out)
      return out
    }

    // Extract date part from ISO datetime string if needed
    if (typeof d === 'string') {
      const match = d.match(/^(\d{4}-\d{2}-\d{2})/)
      if (match) {
        const out = match[1]
        console.log('toISODate input=', d, 'output=', out)
        return out
      }
    }

    // ❌ Do NOT use new Date() for date-only values (timezone issues)
    // If we get here, the format is invalid
    console.error('Invalid date format for day_date:', d)
    return ''
  }

  const toHHMM = (t: any): string => {
    // Accepts "HH:mm", "HH:mm:ss", minutes int, or Date
    if (t == null) return ''
    if (typeof t === 'number') {
      const hh = Math.floor(t / 60)
      const mm = t % 60
      return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
    }
    if (typeof t === 'string') {
      // If HH:mm:ss -> HH:mm
      const m = t.match(/^(\d{2}:\d{2})/)
      return m ? m[1] : t
    }
    if (t instanceof Date) return t.toTimeString().slice(0, 5)
    return ''
  }

  useEffect(() => {
    if (!isNew) {
      loadData()
    } else {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    if (!isNew && tournament.id) {
      loadPhase1Status()
    }
  }, [tournament.id, days, events])

  useEffect(() => {
    const loadWindows = async () => {
      if (!isNew && tournament.id && tournament.use_time_windows) {
        try {
          const windows = await getTimeWindows(tournament.id)
          setTimeWindows(windows)
        } catch (err) {
          console.error('Failed to load time windows:', err)
          setTimeWindows([])
        }
        try {
          const summary = await getTimeWindowsSummary(tournament.id)
          setTimeWindowSummary(summary)
        } catch (err) {
          console.error('Failed to load time window summary:', err)
          setTimeWindowSummary(null)
        }
      } else if (!tournament.use_time_windows) {
        // Clear windows when mode is disabled
        setTimeWindows([])
        setTimeWindowSummary(null)
      }
    }
    loadWindows()
  }, [tournament.id, tournament.use_time_windows, isNew])

  const loadData = async () => {
    try {
      setLoading(true)
      if (!id || id === 'new') return

      const [tournamentData, daysData, eventsData] = await Promise.all([
        getTournament(parseInt(id)),
        getTournamentDays(parseInt(id)),
        getEvents(parseInt(id)),
      ])

      setTournament(tournamentData)
      // Initialize court names input from loaded data
      const loadedCourtNames = tournamentData.court_names && tournamentData.court_names.length > 0 
        ? tournamentData.court_names.join(',') 
        : ''
      setCourtNamesInput(loadedCourtNames)
      setOriginalCourtNames(tournamentData.court_names || null)
      setDays(daysData)
      setEvents(eventsData)
      
      // Load schedule versions to check if schedule exists
      if (tournamentData.id) {
        const versions = await getScheduleVersions(tournamentData.id).catch(() => [])
        setScheduleVersions(versions)
      }
      
      // Load time windows if advanced mode is enabled
      if (tournamentData.use_time_windows && tournamentData.id) {
        const windows = await getTimeWindows(tournamentData.id).catch(() => [])
        const summary = await getTimeWindowsSummary(tournamentData.id).catch(() => null)
        setTimeWindows(windows)
        setTimeWindowSummary(summary)
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load data', 'error')
    } finally {
      setLoading(false)
    }
  }

  const loadPhase1Status = async () => {
    try {
      if (!tournament.id) return
      const status = await getPhase1Status(tournament.id)
      setPhase1Status(status)
    } catch (err) {
      console.error('Failed to load phase 1 status:', err)
    }
  }

  const handleSaveTournament = async () => {
    // Store scroll position before save
    const scrollY = window.scrollY
    
    try {
      setSaving(true)
      if (isNew) {
        const created = await createTournament(tournament as any)
        showToast('Tournament created successfully', 'success')
        navigate(`/tournaments/${created.id}/setup`)
      } else {
        // Explicitly construct the update payload to ensure court_names is included
        const updatePayload: any = {}
        if (tournament.name !== undefined) updatePayload.name = tournament.name
        if (tournament.location !== undefined) updatePayload.location = tournament.location
        if (tournament.timezone !== undefined) updatePayload.timezone = tournament.timezone
        if (tournament.start_date !== undefined) updatePayload.start_date = tournament.start_date
        if (tournament.end_date !== undefined) updatePayload.end_date = tournament.end_date
        if (tournament.notes !== undefined) updatePayload.notes = tournament.notes
        if (tournament.use_time_windows !== undefined) updatePayload.use_time_windows = tournament.use_time_windows
        // Always include court_names, even if null (to clear it)
        updatePayload.court_names = tournament.court_names !== undefined ? tournament.court_names : null
        
        console.log('Saving tournament payload:', updatePayload)
        const saved = await updateTournament(tournament.id!, updatePayload)
        console.log('Saved tournament returned court_names:', saved.court_names)
        showToast('Tournament updated successfully', 'success')
        
        // Update tournament state with saved data, but preserve courtNamesInput
        setTournament(saved)
        
        // Restore scroll position after React re-renders
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            window.scrollTo({ top: scrollY, behavior: 'auto' })
          })
        })
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save tournament', 'error')
      // Restore scroll position even on error
      requestAnimationFrame(() => {
        window.scrollTo({ top: scrollY, behavior: 'auto' })
      })
    } finally {
      setSaving(false)
    }
  }

  const handleSaveDays = async () => {
    // Store scroll position before save
    const scrollY = window.scrollY
    
    try {
      if (!tournament.id) {
        showToast('Please save tournament first', 'error')
        return
      }
      
      // Validate all active days
      let isValid = true
      const errors: Record<string, string> = {}
      days.forEach((day, index) => {
        if (day.is_active) {
          if (!day.start_time || !day.end_time) {
            errors[`day-${index}-times`] = 'Start time and end time are required for active days'
            isValid = false
          } else if (day.end_time <= day.start_time) {
            errors[`day-${index}-times`] = 'End time must be greater than start time'
            isValid = false
          }
          if (day.courts_available < 1) {
            errors[`day-${index}-courts_available`] = 'At least 1 court is required for active days'
            isValid = false
          }
        }
      })
      
      if (!isValid) {
        setValidationErrors(errors)
        showToast('Please fix validation errors before saving', 'error')
        return
      }
      
      setSaving(true)
      setValidationErrors({})
      const dayUpdates: DayUpdate[] = days.map((day) => ({
        date: day.date,
        is_active: day.is_active,
        start_time: day.start_time || undefined,
        end_time: day.end_time || undefined,
        courts_available: day.courts_available,
      }))
      await updateTournamentDays(tournament.id, dayUpdates)
      showToast('Days updated successfully', 'success')
      await loadData()
      // Restore scroll position after React re-renders
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save days'
      showToast(errorMessage, 'error')
      // Restore scroll position even on error
      requestAnimationFrame(() => {
        window.scrollTo({ top: scrollY, behavior: 'auto' })
      })
    } finally {
      setSaving(false)
    }
  }

  const handleDayChange = (index: number, field: keyof TournamentDay, value: any) => {
    const updatedDays = [...days]
    updatedDays[index] = { ...updatedDays[index], [field]: value }
    setDays(updatedDays)
    
    // Clear validation errors for this field
    const errorKey = `day-${index}-${field}`
    if (validationErrors[errorKey]) {
      const newErrors = { ...validationErrors }
      delete newErrors[errorKey]
      setValidationErrors(newErrors)
    }
  }

  const validateEvent = (event: Partial<EventCreate>): boolean => {
    if (!event.name || event.name.trim() === '') {
      showToast('Event name is required', 'error')
      return false
    }
    if (!event.team_count || event.team_count < 2) {
      showToast('Team count must be at least 2', 'error')
      return false
    }
    return true
  }

  const handleAddEvent = async (e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }
    try {
      if (!tournament.id) {
        showToast('Please save tournament first', 'error')
        return
      }
      if (!validateEvent(newEvent as EventCreate)) {
        return
      }
      // Store current scroll position
      const scrollY = window.scrollY
      
      await createEvent(tournament.id, newEvent as EventCreate)
      showToast('Event added successfully', 'success')
      setNewEvent({ category: 'mixed', name: '', team_count: 2, notes: '' })
      await loadData()
      
      // Restore scroll position after React re-renders
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to add event'
      showToast(errorMessage, 'error')
    }
  }

  const handleUpdateEvent = async (eventId: number, updates: Partial<Event>) => {
    // Store scroll position before update
    const scrollY = window.scrollY
    
    try {
      await updateEvent(eventId, updates)
      showToast('Event updated successfully', 'success')
      setEditingEventId(null)
      // Clear editing state
      const newEditingEvents = { ...editingEvents }
      delete newEditingEvents[eventId]
      setEditingEvents(newEditingEvents)
      await loadData()
      // Restore scroll position after React re-renders
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update event', 'error')
      // Restore scroll position even on error
      requestAnimationFrame(() => {
        window.scrollTo({ top: scrollY, behavior: 'auto' })
      })
    }
  }

  const handleEventFieldChange = (eventId: number, field: keyof Event, value: any) => {
    // Update local editing state instead of saving immediately
    const event = events.find(e => e.id === eventId)
    if (event) {
      setEditingEvents({
        ...editingEvents,
        [eventId]: {
          ...editingEvents[eventId],
          ...event,
          [field]: value
        }
      })
    }
  }

  const handleSaveEvent = async (eventId: number) => {
    // Validate team_count before saving
    const updates = { ...editingEvents[eventId] }
    if (updates) {
      if (!updates.team_count || updates.team_count < 2) {
        updates.team_count = 2
      }
      await handleUpdateEvent(eventId, updates)
    }
  }

  const handleStartEditEvent = (eventId: number) => {
    const event = events.find(e => e.id === eventId)
    if (event) {
      setEditingEventId(eventId)
      setEditingEvents({
        ...editingEvents,
        [eventId]: { ...event }
      })
    }
  }

  const handleDeleteEvent = async (eventId: number) => {
    // Show custom confirm dialog (without "localhost:3000 says")
    const confirmed = await confirmDialog('Are you sure you want to delete this event?')
    if (!confirmed) return
    
    // Store scroll position before delete
    const scrollY = window.scrollY
    
    try {
      await deleteEvent(eventId)
      showToast('Event deleted successfully', 'success')
      await loadData()
      // Restore scroll position after React re-renders
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to delete event', 'error')
      // Restore scroll position even on error
      requestAnimationFrame(() => {
        window.scrollTo({ top: scrollY, behavior: 'auto' })
      })
    }
  }

  const handleProceedToPhase2 = () => {
    if (tournament.id) {
      navigate(`/tournaments/${tournament.id}/draw-builder`)
    }
  }

  // Time Windows functions
  const loadTimeWindows = async () => {
    if (!tournament.id) return
    try {
      const windows = await getTimeWindows(tournament.id)
      setTimeWindows(windows)
    } catch (err) {
      console.error('Failed to load time windows:', err)
      // If error (maybe no windows exist yet), set empty array
      setTimeWindows([])
    }
  }

  const loadTimeWindowSummary = async () => {
    if (!tournament.id) return
    try {
      const summary = await getTimeWindowsSummary(tournament.id)
      setTimeWindowSummary(summary)
    } catch (err) {
      console.error('Failed to load time window summary:', err)
      setTimeWindowSummary(null)
    }
  }

  const handleToggleTimeWindowsMode = async (useTimeWindows: boolean) => {
    if (!tournament.id) return
    const scrollY = window.scrollY

    try {
      await updateTournament(tournament.id, { use_time_windows: useTimeWindows })
      setTournament({ ...tournament, use_time_windows: useTimeWindows })

      await loadPhase1Status()

      if (useTimeWindows) {
        await loadTimeWindows()
        await loadTimeWindowSummary()
      }

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update mode', 'error')
    }
  }

  const handleWindowChange = (windowId: number | 'new', field: string, value: any) => {
    if (windowId === 'new') {
      setNewWindow({ ...newWindow, [field]: value })
    } else {
      setEditingWindows({
        ...editingWindows,
        [windowId]: { ...editingWindows[windowId], [field]: value },
      })
    }
  }

  const validateWindow = (window: Partial<TimeWindowCreate | TimeWindowUpdate>): string | null => {
    if (!window.day_date) return 'Day date is required'
    if (!window.start_time) return 'Start time is required'
    if (!window.end_time) return 'End time is required'
    if (window.end_time <= window.start_time) return 'End time must be greater than start time'
    if (!window.courts_available || window.courts_available < 1) return 'Courts available must be at least 1'
    if (!window.block_minutes || ![60, 90, 105, 120].includes(window.block_minutes)) {
      return 'Block minutes must be 60, 90, 105, or 120'
    }
    return null
  }

  const handleSaveWindow = async (windowId: number) => {
    if (!tournament.id) return
    
    const windowData = editingWindows[windowId]
    if (!windowData) return

    const error = validateWindow(windowData)
    if (error) {
      showToast(error, 'error')
      return
    }

    const scrollY = window.scrollY

    try {
      await updateTimeWindow(windowId, windowData as TimeWindowUpdate)
      showToast('Time window updated successfully', 'success')
      
      const newEditingWindows = { ...editingWindows }
      delete newEditingWindows[windowId]
      setEditingWindows(newEditingWindows)
      
      await loadTimeWindows()
      await loadTimeWindowSummary()

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update time window', 'error')
    }
  }

  const handleCreateWindow = async () => {
    if (!tournament.id) return

    const error = validateWindow(newWindow)
    if (error) {
      showToast(error, 'error')
      return
    }

    const scrollY = window.scrollY

    try {
      await createTimeWindow(tournament.id, newWindow as TimeWindowCreate)
      showToast('Time window created successfully', 'success')
      setNewWindow({
        day_date: '',
        start_time: '',
        end_time: '',
        courts_available: 1,
        block_minutes: 120,
        label: '',
        is_active: true,
      })
      await loadTimeWindows()
      await loadTimeWindowSummary()

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to create time window', 'error')
    }
  }

  const handleDeleteWindow = async (windowId: number) => {
    const confirmed = await confirmDialog('Are you sure you want to delete this time window?')
    if (!confirmed) return

    const scrollY = window.scrollY

    try {
      await deleteTimeWindow(windowId)
      showToast('Time window deleted successfully', 'success')
      await loadTimeWindows()
      await loadTimeWindowSummary()

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to delete time window', 'error')
    }
  }

  const handleStartEditWindow = (window: TimeWindow) => {
    setEditingWindows({
      ...editingWindows,
      [window.id]: { ...window },
    })
  }

  const handleAutoGenerateWindows = async () => {
    if (!tournament.id) return

    if (timeWindows.length > 0) {
      const confirmed = await confirmDialog(
        'You already have time windows. Auto-generate will ADD new windows. Continue?'
      )
      if (!confirmed) return
    }

    const scrollY = window.scrollY
    setIsAutoGenerating(true)

    try {
      // Log for debugging
      console.log('AUTO-GEN: days raw =', days)
      console.log('AUTO-GEN: tournament =', tournament)
      console.log('AUTO-GEN: tournamentId =', tournament.id)
      console.log('AUTO-GEN: API base URL =', import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api')

      // Filter active days with required fields
      const activeDays = days.filter(d => d.is_active && d.start_time && d.end_time && d.courts_available > 0)
      
      if (activeDays.length === 0) {
        showToast('No active days with valid time and courts data found', 'error')
        return
      }

      // Build payloads with normalized dates/times
      const payloads = activeDays.map((d) => {
        const dayDate = toISODate(d.date)
        const startTime = toHHMM(d.start_time)
        const endTime = toHHMM(d.end_time)
        const courts = Number(d.courts_available)

        return {
          day_date: dayDate,
          start_time: startTime,
          end_time: endTime,
          courts_available: courts,
          block_minutes: 120,
          label: 'Auto',
          is_active: true,
        }
      })

      // Validate payloads
      const invalid = payloads.filter(p => !p.day_date || !p.start_time || !p.end_time || !p.courts_available || p.courts_available < 1)
      if (invalid.length > 0) {
        console.warn('AUTO-GEN invalid payloads:', invalid)
        showToast(`Auto-generate failed: ${invalid.length} day(s) missing valid date/time/courts data`, 'error')
        return
      }

      console.log('AUTO-GEN: valid payloads =', payloads)

      // Post windows sequentially
      for (const payload of payloads) {
        console.log('AUTO-GEN posting:', payload)
        console.log('AUTO-GEN tournament.id type:', typeof tournament.id, 'value:', tournament.id)
        if (!tournament.id || isNaN(Number(tournament.id))) {
          throw new Error(`Invalid tournament ID: ${tournament.id}`)
        }
        await createTimeWindow(tournament.id, payload)
      }

      showToast(`Created ${payloads.length} time window(s) from days`, 'success')
      await loadTimeWindows()
      await loadTimeWindowSummary()

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, behavior: 'auto' })
        })
      })
    } catch (err) {
      console.error('AUTO-GEN error:', err)
      showToast(err instanceof Error ? err.message : 'Failed to auto-generate windows (see console for details)', 'error')
    } finally {
      setIsAutoGenerating(false)
    }
  }

  const BLOCK_OPTIONS = [
    { minutes: 60, label: '1 hour' },
    { minutes: 90, label: '1 1/2 hours' },
    { minutes: 105, label: '1 3/4 hours' },
    { minutes: 120, label: '2 hours' },
  ]

  if (loading) {
    return <div className="container"><div className="loading">Loading...</div></div>
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1>{isNew ? 'Create Tournament' : tournament.name || 'Tournament Setup'}</h1>
        <button className="btn btn-secondary" onClick={() => navigate('/tournaments')}>
          Back to List
        </button>
      </div>

      {/* Navigation to other phases */}
      {!isNew && tournament.id && (
        <div className="card" style={{ marginBottom: '24px', backgroundColor: 'var(--theme-card-bg)' }}>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 'bold', marginRight: '8px', color: 'var(--theme-text)' }}>Navigate to:</span>
            <button
              className="btn btn-secondary"
              onClick={() => navigate(`/tournaments/${tournament.id}/draw-builder`)}
              style={{ fontSize: '14px' }}
            >
              Draw Builder
            </button>
          </div>
        </div>
      )}

      {/* Section 1: Tournament Info */}
      <div className="card">
        <h2 className="section-title">Tournament Information</h2>
        <div className="form-grid">
          <div className="form-group">
            <label>Name *</label>
            <input
              type="text"
              value={tournament.name || ''}
              onChange={(e) => setTournament({ ...tournament, name: e.target.value })}
              required
            />
          </div>
          <div className="form-group">
            <label>Location *</label>
            <input
              type="text"
              value={tournament.location || ''}
              onChange={(e) => setTournament({ ...tournament, location: e.target.value })}
              required
            />
          </div>
          <div className="form-group date-row">
            <label>Timezone *</label>
            <select
              value={tournament.timezone || ''}
              onChange={(e) => setTournament({ ...tournament, timezone: e.target.value })}
              required
              style={{ width: '200px', maxWidth: '200px' }}
            >
              <option value="America/New_York">Eastern (ET)</option>
              <option value="America/Chicago">Central (CT)</option>
              <option value="America/Denver">Mountain (MT)</option>
              <option value="America/Los_Angeles">Pacific (PT)</option>
            </select>
          </div>
          <div className="form-group date-row">
            <label>Start Date *</label>
            <input
              type="date"
              value={tournament.start_date || ''}
              onChange={(e) => setTournament({ ...tournament, start_date: e.target.value })}
              required
              style={{ width: '160px', maxWidth: '160px' }}
            />
          </div>
          <div className="form-group date-row">
            <label>End Date *</label>
            <input
              type="date"
              value={tournament.end_date || ''}
              onChange={(e) => setTournament({ ...tournament, end_date: e.target.value })}
              min={tournament.start_date || ''}
              required
              style={{ width: '160px', maxWidth: '160px' }}
            />
          </div>
          <div className="form-group full-width">
            <label>Notes</label>
            <textarea
              value={tournament.notes || ''}
              onChange={(e) => setTournament({ ...tournament, notes: e.target.value })}
              rows={3}
            />
          </div>
        </div>
        <button
          className="btn btn-primary"
          onClick={handleSaveTournament}
          disabled={saving}
        >
          {saving ? 'Saving...' : 'Save Tournament'}
        </button>
      </div>

      {/* Capacity Mode Toggle */}
      {!isNew && tournament.id && (
        <div className="card">
          <div className="info-tooltip-wrapper" style={{ marginBottom: '16px' }}>
            <h2 className="section-title" style={{ marginBottom: 0 }}>Capacity Source</h2>
            <button
              type="button"
              className="info-icon-button"
              aria-label="Capacity Source help"
              title="Click for help"
            >
              i
            </button>
            <div className="info-tooltip">
              <div className="info-tooltip-title">{CAPACITY_SOURCE_HELP.title}</div>
              {CAPACITY_SOURCE_HELP.bullets.map((section, idx) => (
                <div key={idx} className="info-tooltip-section">
                  <div className="info-tooltip-section-heading">{section.heading}</div>
                  <ul className="info-tooltip-list">
                    {section.lines.map((line, lineIdx) => (
                      <li key={lineIdx}>{line}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <input
                type="radio"
                name="timeWindowsMode"
                checked={!tournament.use_time_windows}
                onChange={() => handleToggleTimeWindowsMode(false)}
              />
              <span>Use Day Courts/Hours (Simple)</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '16px', marginTop: '8px' }}>
              <input
                type="radio"
                name="timeWindowsMode"
                checked={tournament.use_time_windows === true}
                onChange={() => handleToggleTimeWindowsMode(true)}
              />
              <span>Use Time Windows (Advanced)</span>
            </label>
          </div>

          {/* Advanced Mode Warning */}
          {tournament.use_time_windows && (
            <div style={{ 
              padding: '16px', 
              backgroundColor: 'var(--theme-card-bg)', 
              borderLeft: '4px solid var(--theme-table-header)', 
              borderRadius: '4px',
              marginTop: '16px'
            }}>
              <h3 style={{ margin: '0 0 8px 0', color: 'var(--theme-text)', fontSize: '16px' }}>
                Advanced Mode Active
              </h3>
              <p style={{ margin: '0 0 8px 0', color: 'var(--theme-text)' }}>
                Capacity calculations will use Time Windows only. Days & Courts are not used for capacity while Advanced mode is selected.
              </p>
              <p style={{ margin: '0 0 12px 0', color: 'var(--theme-text)', fontSize: '14px', opacity: 0.8 }}>
                Use Auto-generate to start from Days & Courts, then split windows as needed.
              </p>
              <button
                type="button"
                onClick={() => {
                  document.getElementById('time-windows-section')?.scrollIntoView({ behavior: 'smooth' })
                }}
                style={{
                  padding: '8px 16px',
                  backgroundColor: 'var(--theme-primary-btn)',
                  color: 'var(--theme-primary-btn-text)',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontWeight: '500'
                }}
              >
                Jump to Time Windows →
              </button>
            </div>
          )}

          {/* Simple Mode Note */}
          {!tournament.use_time_windows && (
            <div style={{ 
              padding: '12px', 
              backgroundColor: 'var(--theme-card-bg)', 
              borderLeft: '4px solid var(--theme-section-border)', 
              borderRadius: '4px',
              marginTop: '16px',
              fontSize: '14px',
              color: 'var(--theme-text)'
            }}>
              Simple Mode Active — capacity uses Days & Courts.
            </div>
          )}
        </div>
      )}

      {/* Section 2: Days & Courts Table */}
      {!isNew && tournament.id && !tournament.use_time_windows && (
        <div className="card capacity-simple">
          <div className="info-tooltip-wrapper" style={{ marginBottom: '16px' }}>
            <h2 className="section-title" style={{ marginBottom: 0 }}>Days & Courts</h2>
            <button
              type="button"
              className="info-icon-button"
              aria-label="Days & Courts help"
              title="Click for help"
            >
              i
            </button>
            <div className="info-tooltip" style={{ width: '600px', maxWidth: '90vw' }}>
              <div className="info-tooltip-title">{DAYS_COURTS_HELP.title}</div>
              
              {tournament.use_time_windows && (
                <div className="info-tooltip-section" style={{ padding: '6px', backgroundColor: 'var(--theme-table-row-hover)', borderRadius: '4px', marginBottom: '10px' }}>
                  <p style={{ margin: 0, color: 'var(--theme-text)', fontWeight: '600', fontSize: '12px' }}>
                    ⚠️ This section is inactive because Time Windows mode is selected.
                  </p>
                </div>
              )}
              
              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">What this is</div>
                <ul className="info-tooltip-list">
                  {DAYS_COURTS_HELP.summary.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">What it controls</div>
                <ul className="info-tooltip-list">
                  {DAYS_COURTS_HELP.whatItControls.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">What it does NOT control</div>
                <ul className="info-tooltip-list">
                  {DAYS_COURTS_HELP.whatItDoesNotControl.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">How the math works</div>
                <ul className="info-tooltip-list">
                  {DAYS_COURTS_HELP.howTheMathWorks.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">Examples</div>
                <div style={{ marginTop: '6px' }}>
                  {DAYS_COURTS_HELP.examples.map((ex, exIdx) => (
                    <div key={exIdx} style={{ marginBottom: '8px', padding: '6px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', backgroundColor: 'var(--theme-table-row-hover)' }}>
                      <div style={{ fontWeight: '600', fontSize: '12px', marginBottom: '2px', color: 'var(--theme-text)' }}>{ex.label}</div>
                      <ul className="info-tooltip-list" style={{ marginTop: '2px' }}>
                        {ex.lines.map((line, lineIdx) => (
                          <li key={lineIdx} style={{ fontSize: '12px' }}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">When to use</div>
                <ul className="info-tooltip-list">
                  {DAYS_COURTS_HELP.whenToUse.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">When NOT to use</div>
                <ul className="info-tooltip-list">
                  {DAYS_COURTS_HELP.whenNotToUse.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--theme-input-border)', fontSize: '12px' }}>
                <span style={{ fontWeight: '600' }}>In one sentence:</span> {DAYS_COURTS_HELP.oneSentence.join(' ')}
              </div>
            </div>
          </div>
          {days.length === 0 ? (
            <p>No days found. Days will be auto-generated when you save the tournament.</p>
          ) : (
            <>
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Active</th>
                    <th>Start Time</th>
                    <th>End Time</th>
                    <th>Courts Available</th>
                  </tr>
                </thead>
                <tbody>
                  {days.map((day, index) => {
                    // Parse date string properly to avoid timezone issues
                    const dateStr = day.date.split('T')[0] // Get just the date part
                    const [year, month, dayNum] = dateStr.split('-').map(Number)
                    const displayDate = new Date(year, month - 1, dayNum)
                    
                    return (
                    <tr key={day.id}>
                      <td>{displayDate.toLocaleDateString()}</td>
                      <td>
                        <label className="toggle-switch">
                          <input
                            type="checkbox"
                            checked={day.is_active}
                            onChange={(e) =>
                              handleDayChange(index, 'is_active', e.target.checked)
                            }
                          />
                          <span className="slider"></span>
                        </label>
                      </td>
                      <td>
                        <input
                          type="time"
                          value={day.start_time || ''}
                          onChange={(e) =>
                            handleDayChange(index, 'start_time', e.target.value || null)
                          }
                          disabled={!day.is_active}
                          className={validationErrors[`day-${index}-times`] ? 'error' : ''}
                        />
                      </td>
                      <td>
                        <input
                          type="time"
                          value={day.end_time || ''}
                          onChange={(e) =>
                            handleDayChange(index, 'end_time', e.target.value || null)
                          }
                          disabled={!day.is_active}
                          className={validationErrors[`day-${index}-times`] ? 'error' : ''}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          max="99"
                          value={day.courts_available || ''}
                          onChange={(e) => {
                            const value = e.target.value === '' ? 0 : parseInt(e.target.value) || 0
                            handleDayChange(index, 'courts_available', value)
                          }}
                          disabled={!day.is_active}
                          className={validationErrors[`day-${index}-courts_available`] ? 'error' : ''}
                          style={{ width: '60px', maxWidth: '60px' }}
                        />
                        {validationErrors[`day-${index}-courts_available`] && (
                          <div className="error-message">
                            {validationErrors[`day-${index}-courts_available`]}
                          </div>
                        )}
                        {validationErrors[`day-${index}-times`] && (
                          <div className="error-message">
                            {validationErrors[`day-${index}-times`]}
                          </div>
                        )}
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
              <button
                className="btn btn-primary"
                onClick={handleSaveDays}
                disabled={saving}
                style={{ marginTop: '16px' }}
              >
                {saving ? 'Saving...' : 'Save Days'}
              </button>
            </>
          )}
        </div>
      )}

      {/* Section 2.5: Time Windows (Advanced) */}
      {!isNew && tournament.id && tournament.use_time_windows && (
        <div id="time-windows-section" className="card capacity-advanced">
          <div className="info-tooltip-wrapper" style={{ marginBottom: '16px' }}>
            <h2 className="section-title" style={{ marginBottom: 0 }}>Time Windows</h2>
            <button
              type="button"
              className="info-icon-button"
              aria-label="Time Windows help"
              title="Click for help"
            >
              i
            </button>
            <div className="info-tooltip" style={{ width: '600px', maxWidth: '90vw' }}>
              <div className="info-tooltip-title">{TIME_WINDOWS_HELP.title}</div>
              
              {!tournament.use_time_windows && (
                <div className="info-tooltip-section" style={{ padding: '6px', backgroundColor: 'var(--theme-table-row-hover)', borderRadius: '4px', marginBottom: '10px' }}>
                  <p style={{ margin: 0, color: 'var(--theme-text)', fontWeight: '600', fontSize: '12px' }}>
                    ⚠️ This section is inactive because Simple mode is selected.
                  </p>
                </div>
              )}
              
              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">What this is</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.summary.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">What it controls</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.whatItControls.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">What it does NOT control</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.whatItDoesNotControl.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">When to use</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.whenToUse.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">When NOT to use</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.whenNotToUse.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">Core concepts</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.coreConcepts.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">How to enter windows</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.howToEnter.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">Examples</div>
                <div style={{ marginTop: '6px' }}>
                  {TIME_WINDOWS_HELP.examples.map((ex, exIdx) => (
                    <div key={exIdx} style={{ marginBottom: '8px', padding: '6px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', backgroundColor: 'var(--theme-table-row-hover)' }}>
                      <div style={{ fontWeight: '600', fontSize: '12px', marginBottom: '2px', color: 'var(--theme-text)' }}>{ex.label}</div>
                      <ul className="info-tooltip-list" style={{ marginTop: '2px' }}>
                        {ex.lines.map((line, lineIdx) => (
                          <li key={lineIdx} style={{ fontSize: '12px' }}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">Important rules</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.importantRules.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div className="info-tooltip-section">
                <div className="info-tooltip-section-heading">Common mistakes</div>
                <ul className="info-tooltip-list">
                  {TIME_WINDOWS_HELP.commonMistakes.map((text, idx) => (
                    <li key={idx}>{text}</li>
                  ))}
                </ul>
              </div>

              <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--theme-input-border)', fontSize: '12px' }}>
                <span style={{ fontWeight: '600' }}>In one sentence:</span> {TIME_WINDOWS_HELP.oneSentence.join(' ')}
              </div>
            </div>
          </div>

          {tournament.use_time_windows ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ margin: 0 }}>Time Windows</h3>
                <button
                  className="btn btn-secondary"
                  onClick={handleAutoGenerateWindows}
                  disabled={isAutoGenerating || days.filter(d => d.is_active && d.start_time && d.end_time && d.courts_available > 0).length === 0}
                  title={days.filter(d => d.is_active && d.start_time && d.end_time && d.courts_available > 0).length === 0 ? 'No active days with valid time and courts data' : ''}
                >
                  {isAutoGenerating ? 'Generating...' : 'Auto-generate from Days/Courts'}
                </button>
              </div>

              {timeWindows.length === 0 ? (
                <p>No time windows configured. Use "Auto-generate from Days/Courts" or add manually below.</p>
              ) : (
                <table style={{ marginBottom: '16px' }}>
                  <thead>
                    <tr>
                      <th>Day</th>
                      <th>Start Time</th>
                      <th>End Time</th>
                      <th>Courts</th>
                      <th>Block Length</th>
                      <th>Label</th>
                      <th>Active</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {timeWindows.map((window) => {
                      const isEditing = editingWindows[window.id]
                      const win = isEditing ? { ...window, ...editingWindows[window.id] } : window
                      return (
                        <tr key={window.id}>
                          <td>
                            {isEditing ? (
                              <input
                                type="date"
                                value={win.day_date || ''}
                                onChange={(e) => handleWindowChange(window.id, 'day_date', e.target.value)}
                                min={tournament.start_date}
                                max={tournament.end_date}
                              />
                            ) : (
                              win.day_date ? formatDateMDY(win.day_date) : ''
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <input
                                type="time"
                                value={win.start_time || ''}
                                onChange={(e) => handleWindowChange(window.id, 'start_time', e.target.value)}
                              />
                            ) : (
                              timeTo12Hour(win.start_time)
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <input
                                type="time"
                                value={win.end_time || ''}
                                onChange={(e) => handleWindowChange(window.id, 'end_time', e.target.value)}
                              />
                            ) : (
                              timeTo12Hour(win.end_time)
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <input
                                type="number"
                                min="1"
                                value={win.courts_available || ''}
                                onChange={(e) => handleWindowChange(window.id, 'courts_available', parseInt(e.target.value) || 1)}
                              />
                            ) : (
                              win.courts_available
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <select
                                value={win.block_minutes || 120}
                                onChange={(e) => handleWindowChange(window.id, 'block_minutes', parseInt(e.target.value))}
                              >
                                {BLOCK_OPTIONS.map(opt => (
                                  <option key={opt.minutes} value={opt.minutes}>{opt.label}</option>
                                ))}
                              </select>
                            ) : (
                              BLOCK_OPTIONS.find(opt => opt.minutes === win.block_minutes)?.label || `${win.block_minutes} min`
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <input
                                type="text"
                                value={win.label || ''}
                                onChange={(e) => handleWindowChange(window.id, 'label', e.target.value)}
                                placeholder="Optional"
                              />
                            ) : (
                              win.label || '-'
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <input
                                type="checkbox"
                                checked={win.is_active !== false}
                                onChange={(e) => handleWindowChange(window.id, 'is_active', e.target.checked)}
                              />
                            ) : (
                              win.is_active ? '✓' : '✗'
                            )}
                          </td>
                          <td>
                            {isEditing ? (
                              <button
                                className="btn btn-success"
                                onClick={() => handleSaveWindow(window.id)}
                                style={{ marginRight: '8px' }}
                              >
                                Save
                              </button>
                            ) : (
                              <>
                                <button
                                  className="btn btn-secondary"
                                  onClick={() => handleStartEditWindow(window)}
                                  style={{ marginRight: '8px' }}
                                >
                                  Edit
                                </button>
                                <button
                                  className="btn btn-danger"
                                  onClick={() => handleDeleteWindow(window.id)}
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}

              {/* New Window Form */}
              <div style={{ padding: '16px', backgroundColor: 'var(--theme-card-bg)', borderRadius: '4px', marginBottom: '16px' }}>
                <h3 style={{ marginTop: 0, marginBottom: '12px', color: 'var(--theme-text)' }}>Add New Time Window</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px', alignItems: 'end' }}>
                  <div>
                    <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: '500', color: 'var(--theme-text)' }}>Day</label>
                    <input
                      type="date"
                      value={newWindow.day_date || ''}
                      onChange={(e) => handleWindowChange('new', 'day_date', e.target.value)}
                      min={tournament.start_date}
                      max={tournament.end_date}
                      style={{ width: '100%', padding: '8px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', fontSize: '16px', fontFamily: 'inherit', backgroundColor: 'var(--theme-input-bg)', color: 'var(--theme-input-text)' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: '500', color: 'var(--theme-text)' }}>Start Time</label>
                    <input
                      type="time"
                      value={newWindow.start_time || ''}
                      onChange={(e) => handleWindowChange('new', 'start_time', e.target.value)}
                      style={{ width: '100%', padding: '8px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', fontSize: '16px', fontFamily: 'inherit', backgroundColor: 'var(--theme-input-bg)', color: 'var(--theme-input-text)' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: '500', color: 'var(--theme-text)' }}>End Time</label>
                    <input
                      type="time"
                      value={newWindow.end_time || ''}
                      onChange={(e) => handleWindowChange('new', 'end_time', e.target.value)}
                      style={{ width: '100%', padding: '8px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', fontSize: '16px', fontFamily: 'inherit', backgroundColor: 'var(--theme-input-bg)', color: 'var(--theme-input-text)' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: '500', color: 'var(--theme-text)' }}>Courts</label>
                    <input
                      type="number"
                      min="1"
                      value={newWindow.courts_available || ''}
                      onChange={(e) => handleWindowChange('new', 'courts_available', parseInt(e.target.value) || 1)}
                      style={{ width: '100%', padding: '8px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', fontSize: '16px', fontFamily: 'inherit', backgroundColor: 'var(--theme-input-bg)', color: 'var(--theme-input-text)' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: '500', color: 'var(--theme-text)' }}>Block Length</label>
                    <select
                      value={newWindow.block_minutes || 120}
                      onChange={(e) => handleWindowChange('new', 'block_minutes', parseInt(e.target.value))}
                      style={{ width: '100%', padding: '8px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', fontSize: '16px', fontFamily: 'inherit', backgroundColor: 'var(--theme-input-bg)', color: 'var(--theme-input-text)' }}
                    >
                      {BLOCK_OPTIONS.map(opt => (
                        <option key={opt.minutes} value={opt.minutes}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '4px', fontSize: '14px', fontWeight: '500', color: 'var(--theme-text)' }}>Label (Optional)</label>
                    <input
                      type="text"
                      value={newWindow.label || ''}
                      onChange={(e) => handleWindowChange('new', 'label', e.target.value)}
                      placeholder="e.g., Friday AM"
                      style={{ width: '100%', padding: '8px', border: '1px solid var(--theme-input-border)', borderRadius: '4px', fontSize: '16px', fontFamily: 'inherit', backgroundColor: 'var(--theme-input-bg)', color: 'var(--theme-input-text)' }}
                    />
                  </div>
                </div>
                <button
                  className="btn btn-primary"
                  onClick={handleCreateWindow}
                  style={{ marginTop: '12px' }}
                >
                  Add Window
                </button>
              </div>

              {/* Summary Panel */}
              {timeWindowSummary && (
                <div style={{ padding: '16px', backgroundColor: 'var(--theme-card-bg)', borderRadius: '4px' }}>
                  <h3 style={{ marginTop: 0, color: 'var(--theme-text)' }}>Time Windows Capacity Summary</h3>
                  <div style={{ marginBottom: '12px', color: 'var(--theme-text)' }}>
                    <strong>Total Court Hours:</strong> {minutesToHours(timeWindowSummary.total_capacity_minutes)}
                  </div>
                  <div style={{ marginBottom: '12px', color: 'var(--theme-text)' }}>
                    <strong>Capacity by Block (matches):</strong>
                    <ul style={{ margin: '8px 0', paddingLeft: '24px' }}>
                      <li>1 hour blocks (60): {timeWindowSummary.slot_capacity_by_block[60] || 0} matches</li>
                      <li>1 1/2 hour blocks (90): {timeWindowSummary.slot_capacity_by_block[90] || 0} matches</li>
                      <li>1 3/4 hour blocks (105): {timeWindowSummary.slot_capacity_by_block[105] || 0} matches</li>
                      <li>2 hour blocks (120): {timeWindowSummary.slot_capacity_by_block[120] || 0} matches</li>
                    </ul>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--theme-text)', opacity: 0.8, fontStyle: 'italic' }}>
                    Note: These are theoretical maximum match counts per block length; scheduling determines exact placement.
                  </div>
                </div>
              )}
            </>
          ) : (
            <p style={{ padding: '16px', backgroundColor: 'var(--theme-card-bg)', borderRadius: '4px', color: 'var(--theme-text)', opacity: 0.8 }}>
              Enable Advanced mode above to configure time windows.
            </p>
          )}
        </div>
      )}

      {/* Court Names Section - shown after Time Windows if enabled, or after Days & Courts if not */}
      {!isNew && tournament.id && (
        <div className="card">
          <h2 className="section-title">Court Names</h2>
          <div className="form-group full-width">
            <label>Court Names (comma-separated, e.g., "1,2,3,4,5" or "A,B,C,D,E" or "10,11,12,13,14")</label>
            <input
              type="text"
              value={courtNamesInput}
              onChange={(e) => {
                const value = e.target.value
                setCourtNamesInput(value)
                // Parse and update tournament state, allowing trailing commas
                const names = value ? value.split(',').map(n => n.trim()).filter(n => n.length > 0) : null
                setTournament({ ...tournament, court_names: names && names.length > 0 ? names : null })
              }}
              onBlur={(e) => {
                // On blur, clean up any trailing commas/whitespace
                const value = e.target.value.trim()
                setCourtNamesInput(value)
                const names = value ? value.split(',').map(n => n.trim()).filter(n => n.length > 0) : null
                setTournament({ ...tournament, court_names: names && names.length > 0 ? names : null })
              }}
              placeholder="e.g., 1,2,3,4,5 or A,B,C,D,E"
            />
            <div style={{ fontSize: '12px', color: 'var(--theme-text)', marginTop: '4px', opacity: 0.7 }}>
              Enter the names/numbers/letters for your courts. Leave empty to use default numbering (1, 2, 3...)
            </div>
            
            {/* Validation Warnings */}
            {(() => {
              const courtNames = tournament.court_names || []
              const maxCourts = Math.max(...days.filter(d => d.is_active).map(d => d.courts_available), 0)
              const hasSchedule = scheduleVersions.length > 0
              const labelsChanged = originalCourtNames && 
                JSON.stringify(originalCourtNames) !== JSON.stringify(courtNames)
              
              // Check for duplicates
              const duplicates: string[] = []
              const seen = new Set<string>()
              courtNames.forEach(label => {
                if (seen.has(label)) {
                  duplicates.push(label)
                }
                seen.add(label)
              })
              
              // Check count mismatch
              const countMismatch = courtNames.length > 0 && maxCourts > 0 && courtNames.length !== maxCourts
              
              return (
                <>
                  {duplicates.length > 0 && (
                    <div style={{ 
                      marginTop: '8px', 
                      padding: '8px 12px', 
                      backgroundColor: '#fff3cd', 
                      border: '1px solid #ffc107',
                      borderRadius: '4px',
                      fontSize: '13px',
                      color: '#856404'
                    }}>
                      ⚠️ Court labels must be unique. Duplicate label found: '{duplicates[0]}'.
                    </div>
                  )}
                  
                  {countMismatch && (
                    <div style={{ 
                      marginTop: '8px', 
                      padding: '8px 12px', 
                      backgroundColor: '#fff3cd', 
                      border: '1px solid #ffc107',
                      borderRadius: '4px',
                      fontSize: '13px',
                      color: '#856404'
                    }}>
                      ⚠️ Court labels count ({courtNames.length}) does not match maximum court count ({maxCourts}). Missing labels will be auto-filled when generating slots.
                    </div>
                  )}
                  
                  {hasSchedule && labelsChanged && (
                    <div style={{ 
                      marginTop: '8px', 
                      padding: '8px 12px', 
                      backgroundColor: '#d1ecf1', 
                      border: '1px solid #0c5460',
                      borderRadius: '4px',
                      fontSize: '13px',
                      color: '#0c5460'
                    }}>
                      ℹ️ Court labels changed. Existing schedule drafts may need rebuild to use new labels.
                    </div>
                  )}
                </>
              )
            })()}
            
            <button
              className="btn btn-primary"
              onClick={handleSaveTournament}
              disabled={saving}
              style={{ marginTop: '16px' }}
            >
              {saving ? 'Saving...' : 'Save Court Names'}
            </button>
          </div>
        </div>
      )}

      {/* Section 3: Events Table */}
      {!isNew && tournament.id && (
        <div className="card">
          <h2 className="section-title">Events</h2>
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th>Name</th>
                <th>Team Count</th>
                <th>Notes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  {editingEventId === event.id ? (
                    <>
                      <td>
                        <select
                          value={editingEvents[event.id]?.category || event.category}
                          onChange={(e) => {
                            handleEventFieldChange(event.id, 'category', e.target.value as 'mixed' | 'womens')
                          }}
                        >
                          <option value="mixed">Mixed</option>
                          <option value="womens">Women's</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          value={editingEvents[event.id]?.name || event.name}
                          onChange={(e) => handleEventFieldChange(event.id, 'name', e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="2"
                          value={editingEvents[event.id]?.team_count !== undefined ? editingEvents[event.id].team_count : (event.team_count || '')}
                          onChange={(e) => {
                            const inputValue = e.target.value
                            if (inputValue === '') {
                              handleEventFieldChange(event.id, 'team_count', undefined)
                            } else {
                              const value = parseInt(inputValue)
                              // Allow any numeric value while typing (including 1, 10, 12, etc.)
                              if (!isNaN(value)) {
                                handleEventFieldChange(event.id, 'team_count', value)
                              }
                            }
                          }}
                          onBlur={(e) => {
                            // Validate on blur - set to 2 if invalid (but don't save)
                            const value = parseInt(e.target.value)
                            if (isNaN(value) || value < 2) {
                              handleEventFieldChange(event.id, 'team_count', 2)
                            }
                          }}
                          style={{ width: '80px', maxWidth: '80px', textAlign: 'center' }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={editingEvents[event.id]?.notes || event.notes || ''}
                          onChange={(e) => handleEventFieldChange(event.id, 'notes', e.target.value)}
                        />
                      </td>
                      <td>
                        <button
                          className="btn btn-success"
                          onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            handleSaveEvent(event.id)
                          }}
                        >
                          Done
                        </button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{event.category === 'mixed' ? 'Mixed' : "Women's"}</td>
                      <td>{event.name}</td>
                      <td>{event.team_count}</td>
                      <td>{event.notes || '-'}</td>
                      <td>
                        <button
                          className="btn btn-secondary"
                          onClick={() => handleStartEditEvent(event.id)}
                          style={{ marginRight: '8px' }}
                        >
                          Edit
                        </button>
                        <button
                          className="btn btn-danger"
                          onClick={() => handleDeleteEvent(event.id)}
                        >
                          Delete
                        </button>
                      </td>
                    </>
                  )}
                </tr>
              ))}
              <tr>
                <td>
                  <select
                    value={newEvent.category}
                    onChange={(e) =>
                      setNewEvent({ ...newEvent, category: e.target.value as 'mixed' | 'womens' })
                    }
                  >
                    <option value="mixed">Mixed</option>
                    <option value="womens">Women's</option>
                  </select>
                </td>
                <td>
                  <input
                    type="text"
                    placeholder="Event name"
                    value={newEvent.name || ''}
                    onChange={(e) => setNewEvent({ ...newEvent, name: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min="2"
                    placeholder="Team count"
                    value={newEvent.team_count || ''}
                    onChange={(e) => {
                      const inputValue = e.target.value
                      if (inputValue === '') {
                        // Allow empty temporarily for typing
                        setNewEvent({ ...newEvent, team_count: undefined })
                      } else {
                        const value = parseInt(inputValue)
                        // Allow any numeric value while typing (including 1, 10, 12, etc.)
                        if (!isNaN(value)) {
                          setNewEvent({ ...newEvent, team_count: value })
                        }
                      }
                    }}
                    onBlur={(e) => {
                      // Validate on blur - set to 2 if invalid
                      const value = parseInt(e.target.value)
                      if (isNaN(value) || value < 2) {
                        setNewEvent({ ...newEvent, team_count: 2 })
                      }
                    }}
                    style={{ width: '80px', maxWidth: '80px', textAlign: 'center' }}
                  />
                  {newEvent.team_count !== undefined && newEvent.team_count < 2 && (
                    <div className="error-message">Team count must be at least 2</div>
                  )}
                </td>
                <td>
                  <input
                    type="text"
                    placeholder="Notes"
                    value={newEvent.notes || ''}
                    onChange={(e) => setNewEvent({ ...newEvent, notes: e.target.value })}
                  />
                </td>
                <td>
                  <button className="btn btn-primary" onClick={handleAddEvent}>
                    Add Event
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Section 4: Phase 1 Status */}
      {!isNew && tournament.id && phase1Status && (
        <div className="card">
          <h2 className="section-title">Phase 1 Status</h2>
          <div className="status-summary">
            <div className={`status-indicator ${phase1Status.is_ready ? 'ready' : 'not-ready'}`}>
              {phase1Status.is_ready ? '✓ Ready' : '✗ Not Ready'}
            </div>
            <div className="status-details">
              <p>
                <strong>Active Days:</strong> {phase1Status.summary.active_days}
              </p>
              <p>
                <strong>Total Court Hours Available:</strong> {minutesToHours(phase1Status.summary.total_court_minutes)}
              </p>
              <p>
                <strong>Events:</strong> {phase1Status.summary.events_count}
              </p>
            </div>
            {phase1Status.errors.length > 0 && (
              <div className="status-errors">
                <strong>Errors:</strong>
                <ul>
                  {phase1Status.errors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: '12px', marginTop: '16px', flexWrap: 'wrap' }}>
            <button
              className="btn btn-success"
              onClick={handleProceedToPhase2}
              disabled={!phase1Status.is_ready}
            >
              Proceed to Draw Builder
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default TournamentSetup


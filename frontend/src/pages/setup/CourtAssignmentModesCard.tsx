import { useEffect, useState } from 'react'
import {
  CourtAssignmentMode,
  CourtAssignmentModes,
  getCourtAssignmentModes,
  saveCourtAssignmentModes,
} from '../../api/client'
import { showToast } from '../../utils/toast'

const MODE_OPTIONS: Array<{ value: CourtAssignmentMode; label: string }> = [
  { value: 'DYNAMIC_CHECKIN', label: 'Dynamic check-in' },
  { value: 'PREASSIGNED', label: 'Preassigned' },
]

export default function CourtAssignmentModesCard({ tournamentId }: { tournamentId: number }) {
  const [data, setData] = useState<CourtAssignmentModes | null>(null)
  const [draft, setDraft] = useState<Record<number, Record<string, CourtAssignmentMode>>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getCourtAssignmentModes(tournamentId)
      .then((response) => {
        if (cancelled) return
        setData(response)
        setDraft(Object.fromEntries(response.events.map((event) => [event.event_id, { ...event.modes }])))
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          showToast(err instanceof Error ? err.message : 'Failed to load court assignment modes', 'error')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tournamentId])

  const updateMode = (eventId: number, day: string, mode: CourtAssignmentMode) => {
    setDraft((current) => ({
      ...current,
      [eventId]: { ...current[eventId], [day]: mode },
    }))
  }

  const handleSave = async () => {
    if (!data) return
    setSaving(true)
    try {
      const saved = await saveCourtAssignmentModes(
        tournamentId,
        data.events.map((event) => ({
          event_id: event.event_id,
          modes: draft[event.event_id] || {},
        })),
      )
      setData(saved)
      setDraft(Object.fromEntries(saved.events.map((event) => [event.event_id, { ...event.modes }])))
      showToast('Court assignment modes saved', 'success')
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Failed to save court assignment modes', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <h2 className="section-title">Court Assignment Mode</h2>
      <p style={{ marginTop: 0, maxWidth: 760 }}>
        Set this per event and date. Dynamic check-in is the default: both teams check in, then staff assigns a court.
        Preassigned dates use the time and court already on the schedule. Players report to that court. Check-in can
        still be recorded, but it does not assign the court.
      </p>
      {loading ? <p>Loading court assignment modes...</p> : null}
      {!loading && data && data.events.length === 0 ? <p>Add an event before setting court assignment modes.</p> : null}
      {!loading && data && data.events.length > 0 && data.days.length === 0 ? (
        <p>Add tournament days before setting court assignment modes.</p>
      ) : null}
      {!loading && data && data.events.length > 0 && data.days.length > 0 ? (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Event</th>
                  {data.days.map((day) => (
                    <th key={day.date}>{day.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.events.map((event) => (
                  <tr key={event.event_id}>
                    <td>{event.event_name}</td>
                    {data.days.map((day) => {
                      const value = draft[event.event_id]?.[day.date] || 'DYNAMIC_CHECKIN'
                      return (
                        <td key={day.date}>
                          <select
                            aria-label={`${event.event_name} ${day.label} court assignment mode`}
                            value={value}
                            onChange={(e) => updateMode(event.event_id, day.date, e.target.value as CourtAssignmentMode)}
                          >
                            {MODE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="btn btn-primary" type="button" onClick={handleSave} disabled={saving} style={{ marginTop: 16 }}>
            {saving ? 'Saving...' : 'Save Court Assignment Modes'}
          </button>
        </>
      ) : null}
    </div>
  )
}

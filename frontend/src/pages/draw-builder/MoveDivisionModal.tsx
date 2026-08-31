import { useState } from 'react'
import type { Event, MoveDivisionResponse, TeamListItem } from '../../api/client'
import { moveTeamToAnotherDivision } from '../../api/client'
import { showToast } from '../../utils/toast'

const DRAWS_EXIST_WARNING =
  'Draws already exist for one or both events. Moving this team will NOT regenerate either draw. The team may need to be manually removed or placed in the appropriate WF matchup.'

function correctionCode(err: unknown): string | undefined {
  const detail = (err as { detail?: { detail?: { code?: string }; code?: string } } | null)?.detail
  return detail?.detail?.code || detail?.code
}

type Props = {
  tournamentId: number
  team: TeamListItem
  sourceEvent: Event
  events: Event[]
  onClose: () => void
  onMoved: (result: MoveDivisionResponse) => void
}

export default function MoveDivisionModal({
  tournamentId,
  team,
  sourceEvent,
  events,
  onClose,
  onMoved,
}: Props) {
  const destinations = events.filter((e) => e.id !== sourceEvent.id)
  const [destinationEventId, setDestinationEventId] = useState<number | ''>(
    destinations[0]?.id ?? '',
  )
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (destinationEventId === '') {
      showToast('Select a destination event/division.', 'error')
      return
    }
    setSaving(true)
    try {
      let result: MoveDivisionResponse
      try {
        result = await moveTeamToAnotherDivision(
          tournamentId,
          team.id,
          destinationEventId,
          false,
        )
      } catch (err) {
        if (correctionCode(err) !== 'DRAWS_EXIST_CONFIRMATION_REQUIRED') throw err
        const confirmed = window.confirm(DRAWS_EXIST_WARNING)
        if (!confirmed) return
        result = await moveTeamToAnotherDivision(
          tournamentId,
          team.id,
          destinationEventId,
          true,
        )
      }
      onMoved(result)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to move team', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.45)',
        zIndex: 80,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: 'min(560px, 100%)', maxHeight: '90vh', overflowY: 'auto', margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="section-title" style={{ marginTop: 0 }}>
          Move Team to Another Division
        </h2>
        <p style={{ fontSize: 13, marginTop: 0 }}>
          Both partners move together. Player and registration records are preserved. Draws are not regenerated.
        </p>
        <div style={{ display: 'grid', gap: 10, fontSize: 14, marginBottom: 16 }}>
          <div>
            <strong>Team:</strong> {team.display_name || team.name}
          </div>
          <div>
            <strong>Current event/division:</strong> {sourceEvent.name}
          </div>
          <label style={{ display: 'grid', gap: 4 }}>
            <strong>Destination event/division</strong>
            <select
              value={destinationEventId}
              onChange={(e) => setDestinationEventId(e.target.value ? Number(e.target.value) : '')}
              style={{ padding: '6px 8px', fontSize: 14 }}
            >
              {destinations.length === 0 && <option value="">No other events</option>}
              {destinations.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.name} ({ev.category}) — {ev.team_count} teams
                </option>
              ))}
            </select>
          </label>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void handleSave()}
            disabled={saving || destinationEventId === ''}
          >
            {saving ? 'Moving…' : 'Move Team'}
          </button>
        </div>
      </div>
    </div>
  )
}

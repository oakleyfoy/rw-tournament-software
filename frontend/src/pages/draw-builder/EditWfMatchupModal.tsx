import { useEffect, useMemo, useState } from 'react'
import type { WfR1MatchupContext } from '../../api/client'
import { editWfR1Matchup, getWfR1MatchupContext } from '../../api/client'
import { showToast } from '../../utils/toast'

type Props = {
  tournamentId: number
  matchId: number
  onClose: () => void
  onSaved: () => void
}

function teamLabel(team: { name: string; display_name: string | null; seed: number | null } | null): string {
  if (!team) return '—'
  const seed = team.seed != null ? `#${team.seed} ` : ''
  return `${seed}${team.display_name || team.name}`
}

export default function EditWfMatchupModal({ tournamentId, matchId, onClose, onSaved }: Props) {
  const [ctx, setCtx] = useState<WfR1MatchupContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [teamAId, setTeamAId] = useState<number | null>(null)
  const [teamBId, setTeamBId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getWfR1MatchupContext(tournamentId, matchId)
      .then((data) => {
        if (cancelled) return
        setCtx(data)
        setTeamAId(data.team_a?.id ?? null)
        setTeamBId(data.team_b?.id ?? null)
      })
      .catch((err) => {
        if (!cancelled) {
          showToast(err instanceof Error ? err.message : 'Failed to load matchup', 'error')
          onClose()
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tournamentId, matchId])

  const options = useMemo(() => {
    if (!ctx) return []
    return ctx.available_teams.filter((t) => !t.is_defaulted)
  }, [ctx])

  const swap = () => {
    setTeamAId(teamBId)
    setTeamBId(teamAId)
  }

  const handleSave = async () => {
    if (!ctx) return
    if (ctx.edit_blocked) {
      showToast(ctx.edit_block_reason || 'This match cannot be edited.', 'error')
      return
    }
    const availableIds = new Set(ctx.available_teams.filter((t) => !t.is_defaulted).map((t) => t.id))
    if (teamAId != null && !availableIds.has(teamAId)) {
      showToast('Team 1 must be a non-defaulted team in this event/division.', 'error')
      return
    }
    if (teamBId != null && !availableIds.has(teamBId)) {
      showToast('Team 2 must be a non-defaulted team in this event/division.', 'error')
      return
    }
    setSaving(true)
    try {
      await editWfR1Matchup(tournamentId, matchId, teamAId, teamBId)
      showToast('WF matchup updated.', 'success')
      onSaved()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save matchup', 'error')
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
        style={{ width: 'min(640px, 100%)', maxHeight: '90vh', overflowY: 'auto', margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="section-title" style={{ marginTop: 0 }}>
          Edit Matchup
        </h2>
        {loading || !ctx ? (
          <div style={{ fontSize: 13 }}>Loading matchup…</div>
        ) : (
          <>
            <div style={{ display: 'grid', gap: 6, fontSize: 13, marginBottom: 14 }}>
              <div>
                <strong>Event:</strong> {ctx.event_name}
              </div>
              <div>
                <strong>Stage:</strong> {ctx.stage} &nbsp; <strong>Round:</strong> {ctx.round_index}
              </div>
              <div>
                <strong>Match:</strong> #{ctx.sequence_in_round} &nbsp; {ctx.match_code} &nbsp; (ID {ctx.match_id})
              </div>
              <div>
                <strong>Scheduled time:</strong> {ctx.day_date || '—'} {ctx.scheduled_time || ''}
              </div>
              <div>
                <strong>Court:</strong> {ctx.court_label || '—'}
              </div>
              <div>
                <strong>Status:</strong> {ctx.status} / {ctx.runtime_status}
                {ctx.winner_team_id != null ? ` · winner team ${ctx.winner_team_id}` : ''}
                {ctx.has_score ? ' · has score' : ''}
              </div>
              <div>
                <strong>Current Team 1:</strong> {teamLabel(ctx.team_a)}
                {ctx.team_a && !ctx.team_a.belongs_to_event ? ' (moved to another division)' : ''}
              </div>
              <div>
                <strong>Current Team 2:</strong> {teamLabel(ctx.team_b)}
                {ctx.team_b && !ctx.team_b.belongs_to_event ? ' (moved to another division)' : ''}
              </div>
            </div>
            {ctx.edit_blocked && (
              <div
                style={{
                  marginBottom: 12,
                  padding: '10px 12px',
                  backgroundColor: 'rgba(220,53,69,0.08)',
                  border: '1px solid rgba(220,53,69,0.25)',
                  borderRadius: 6,
                  fontSize: 13,
                  color: '#721c24',
                }}
              >
                {ctx.edit_block_reason}
              </div>
            )}
            <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
              <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>
                <strong>Team 1</strong>
                <select
                  value={teamAId ?? ''}
                  onChange={(e) => setTeamAId(e.target.value ? Number(e.target.value) : null)}
                  disabled={ctx.edit_blocked}
                  style={{ padding: '6px 8px', fontSize: 14 }}
                >
                  <option value="">— empty / bye —</option>
                  {options.map((t) => (
                    <option key={t.id} value={t.id}>
                      {teamLabel(t)}
                      {!t.belongs_to_event ? ' (other division)' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>
                <strong>Team 2</strong>
                <select
                  value={teamBId ?? ''}
                  onChange={(e) => setTeamBId(e.target.value ? Number(e.target.value) : null)}
                  disabled={ctx.edit_blocked}
                  style={{ padding: '6px 8px', fontSize: 14 }}
                >
                  <option value="">— empty / bye —</option>
                  {options.map((t) => (
                    <option key={t.id} value={t.id}>
                      {teamLabel(t)}
                      {!t.belongs_to_event ? ' (other division)' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={swap}
                disabled={ctx.edit_blocked}
                style={{ width: 'fit-content' }}
              >
                Swap teams
              </button>
              <div style={{ fontSize: 12, opacity: 0.75 }}>
                Only teams currently assigned to this event/division can be saved. Court, time, match ID, stage, and round are not changed.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void handleSave()}
                disabled={saving || ctx.edit_blocked}
              >
                {saving ? 'Saving…' : 'Save matchup'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

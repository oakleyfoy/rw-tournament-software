import { useEffect, useState } from 'react'
import {
  listTrophies,
  markTrophyDistributed,
  undoTrophyDistributed,
  type TrophyAward,
  type TrophyBoard,
} from '../../api/client'
import { divisionAbbreviation, drawAbbreviation } from './courtSheet'

type Props = {
  tournamentId: number
  versionId: number
  onClose: () => void
  onChanged: () => void
}

export default function TrophyDistributionDialog({ tournamentId, versionId, onClose, onChanged }: Props) {
  const [board, setBoard] = useState<TrophyBoard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const load = async () => {
    const next = await listTrophies(tournamentId, versionId)
    setBoard(next)
  }

  useEffect(() => {
    let cancelled = false
    listTrophies(tournamentId, versionId)
      .then((next) => { if (!cancelled) setBoard(next) })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Trophy list failed') })
    return () => { cancelled = true }
  }, [tournamentId, versionId])

  const run = async (award: TrophyAward, action: 'mark' | 'undo') => {
    setBusyKey(award.award_key)
    setError(null)
    try {
      if (action === 'mark') await markTrophyDistributed(tournamentId, { version_id: versionId, award_key: award.award_key, team_id: award.team_id })
      else await undoTrophyDistributed(tournamentId, { version_id: versionId, award_key: award.award_key })
      await load()
      onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Trophy update failed')
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div role="dialog" aria-label="Trophy distribution" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div style={{ width: 'min(560px, 100%)', maxHeight: '80vh', overflow: 'auto', background: '#fff', borderRadius: 8, padding: 12, boxShadow: '0 8px 24px rgba(0,0,0,0.2)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <strong>Trophy distribution</strong>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        {error && <div style={{ color: '#b71c1c', fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{error}</div>}
        {!board && !error && <div style={{ fontSize: 12 }}>Loading trophies…</div>}
        {board && board.finals.length === 0 && board.groups.length === 0 && (
          <div style={{ fontSize: 12, color: '#546e7a' }}>No completed championship finals or round-robin groups yet.</div>
        )}
        {board?.finals.map((final) => (
          <section key={final.match_id} style={{ borderTop: '1px solid #eceff1', padding: '8px 0' }}>
            <div style={{ fontSize: 12, fontWeight: 800 }}>{drawAbbreviation(final.event_name, final.match_code)} {divisionAbbreviation(final.division_name)} · Championship final</div>
            {final.awards.map((award) => <AwardRow key={award.award_key} award={award} busy={busyKey === award.award_key} onRun={run} />)}
          </section>
        ))}
        {board?.groups.map((group) => (
          <section key={`${group.event_id}-${group.pool}`} style={{ borderTop: '1px solid #eceff1', padding: '8px 0' }}>
            <div style={{ fontSize: 12, fontWeight: 800 }}>{drawAbbreviation(group.event_name, group.pool)} {divisionAbbreviation(group.division_name)} · Round robin</div>
            {!group.official && <div style={{ fontSize: 12, fontWeight: 800, color: '#e65100' }}>{group.unresolved_reason || 'Tiebreak Review Required'}</div>}
            {group.awards.map((award) => <AwardRow key={award.award_key} award={award} busy={busyKey === award.award_key} onRun={run} />)}
          </section>
        ))}
      </div>
    </div>
  )
}

function AwardRow({ award, busy, onRun }: { award: TrophyAward; busy: boolean; onRun: (award: TrophyAward, action: 'mark' | 'undo') => void }) {
  const names = award.players.length ? award.players.join(' / ') : award.team_name
  const label = award.role === 'champion' ? 'Championship' : 'Runner-up'
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', fontSize: 12, padding: '4px 0' }}>
      <div>
        <div style={{ fontWeight: 800 }}>{label}: {award.team_name}</div>
        <div>{names}</div>
        {award.review_required && (
          <div style={{ color: '#b71c1c', fontWeight: 700 }}>
            Score changed. Previously confirmed for {award.confirmed_team_name}. Undo that confirmation before marking the current team.
          </div>
        )}
      </div>
      {award.distributed ? (
        <button type="button" disabled={busy} onClick={() => onRun(award, 'undo')}>Undo</button>
      ) : (
        <button type="button" disabled={busy || award.review_required} onClick={() => onRun(award, 'mark')}>
          {award.review_required ? 'Review' : 'Mark received'}
        </button>
      )}
    </div>
  )
}

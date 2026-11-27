import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { deskPreviewNextMatches, type DeskMatchItem, type NextPreviewCard, type NextPreviewResponse } from '../../api/client'
import { TeamPhotoThumb } from '../../components/TeamPhotoThumb'
import MatchTextDialog, { type MatchTextPlayer, type MatchTextResult } from './MatchTextDialog'

export type ScoreRosterPlayer = {
  id: number
  name: string
  phone: string | null
  consent: string | null
  team: 1 | 2
}

function winningScore(score: string): boolean {
  const parts = score.replace(/,/g, ' ').trim().split(/\s+/).filter(Boolean)
  let winner = 0
  let loser = 0
  for (const part of parts) {
    const pair = part.split('-')
    if (pair.length !== 2) return false
    const left = Number(pair[0])
    const right = Number(pair[1])
    if (!Number.isFinite(left) || !Number.isFinite(right) || left === right) return false
    if (left > right) winner += 1
    else loser += 1
  }
  return parts.length > 0 && winner > loser
}

function shortTeam(label: string): string {
  if (!label.includes('/')) return label
  const parts = label.split('/').map((part) => part.trim().split(/\s+/)[0]).filter(Boolean)
  return parts.length ? parts.join(' / ') : label
}

function formatWhen(match: DeskMatchItem): string {
  const bits = [`Match #${match.match_id}`]
  if (match.day_label) bits.push(match.day_label)
  if (match.court_name) bits.push(match.court_name.startsWith('Court') ? match.court_name : `Court ${match.court_name}`)
  if (match.scheduled_time) bits.push(match.scheduled_time)
  return bits.join(' · ')
}

export default function MatchScoreDrawer({
  match,
  isDraft,
  versionId,
  tournamentId,
  isCopy,
  completed,
  score,
  onScore,
  winnerId,
  onWinner,
  submitting,
  error,
  notice,
  warnings,
  showBackToWaiting,
  roster,
  hasNotes,
  onClose,
  onSave,
  onDefault,
  onRetired,
  onReopen,
  onSetInProgress,
  onSetNotStarted,
  onBackToWaiting,
  onOpenNotes,
  onOpenTrophies,
  onSendTexts,
  onComplete,
  history,
}: {
  match: DeskMatchItem
  isDraft: boolean
  versionId: number
  tournamentId: number
  isCopy: boolean
  completed: boolean
  score: string
  onScore: (value: string) => void
  winnerId: number | null
  onWinner: (teamId: number | null) => void
  submitting: boolean
  error: string | null
  notice: string | null
  warnings: string[]
  showBackToWaiting: boolean
  roster: ScoreRosterPlayer[]
  hasNotes: boolean
  onClose: () => void
  onSave: () => Promise<boolean>
  onDefault: () => Promise<boolean>
  onRetired: () => Promise<boolean>
  onReopen: () => void
  onSetInProgress: () => void
  onSetNotStarted: () => void
  onBackToWaiting: () => void
  onOpenNotes: () => void
  onOpenTrophies: () => void
  onSendTexts: (items: Array<{ playerId: number; message: string }>) => Promise<number>
  onComplete?: () => void
  history?: ReactNode
}) {
  const scoreRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<NextPreviewResponse | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [textOpen, setTextOpen] = useState(false)
  const [previewMessages, setPreviewMessages] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [holdForTexts, setHoldForTexts] = useState(false)
  const [localNotice, setLocalNotice] = useState<string | null>(null)
  const [resultKind, setResultKind] = useState<'normal' | 'default' | 'retired'>('normal')
  const approvedKey = useRef<string>('')

  const waterfall = match.stage === 'WF' || (match.match_code || '').includes('_WF_')
  const defaultScore = waterfall ? '8-0' : '6-0, 6-0'
  const formatLabel = waterfall ? '8-game pro set · Tiebreak at 8–8' : 'Best of three sets · Match tiebreak for third set'
  const scoreOk = score.trim().length > 0 && winnerId != null && (resultKind === 'retired' || winningScore(score))
  const eligibleIds = useMemo(
    () => (preview?.cards || []).flatMap((card) => card.players.filter((player) => player.eligible && player.player_id).map((player) => player.player_id as number)),
    [preview],
  )
  const selectedCount = selected.filter((id) => eligibleIds.includes(id)).length

  useEffect(() => {
    setResultKind('normal')
    if (!completed) scoreRef.current?.focus()
  }, [match.match_id, completed])

  const chooseResult = (kind: 'normal' | 'default' | 'retired') => {
    setResultKind(kind)
    if (kind === 'default') onScore(defaultScore)
  }

  const saveForKind = () => {
    if (completed && !holdForTexts) return onSave()
    if (resultKind === 'default') return onDefault()
    if (resultKind === 'retired') return onRetired()
    return onSave()
  }

  useEffect(() => {
    if (!winnerId || !isDraft) {
      setPreview(null)
      return
    }
    let cancel = false
    deskPreviewNextMatches(tournamentId, match.match_id, { version_id: versionId, winner_team_id: winnerId })
      .then((next) => {
        if (cancel) return
        setPreview(next)
        setSelected(next.cards.flatMap((card) => card.players.filter((player) => player.eligible && player.player_id).map((player) => player.player_id as number)))
      })
      .catch(() => {
        if (!cancel) setPreview(null)
      })
    return () => { cancel = true }
  }, [winnerId, match.match_id, tournamentId, versionId, isDraft, completed])

  const toggle = (playerId: number) => {
    setSelected((current) => current.includes(playerId) ? current.filter((id) => id !== playerId) : [...current, playerId])
  }

  const sendApproved = async (source: NextPreviewResponse) => {
    const items = source.cards.flatMap((card) => card.players
      .filter((player) => player.eligible && player.player_id && selected.includes(player.player_id) && player.message)
      .map((player) => ({ playerId: player.player_id as number, message: player.message })))
    if (!items.length) return 0
    return onSendTexts(items)
  }

  const finishSaved = async (send: boolean) => {
    if (!send || selectedCount === 0 || !winnerId) {
      setLocalNotice(send ? null : 'Match finalized without sending texts.')
      onComplete?.()
      return
    }
    const after = await deskPreviewNextMatches(tournamentId, match.match_id, { version_id: versionId, winner_team_id: winnerId })
    setPreview(after)
    if (after.preview_key !== approvedKey.current) {
      setHoldForTexts(true)
      setSelected(after.cards.flatMap((card) => card.players.filter((player) => player.eligible && player.player_id).map((player) => player.player_id as number)))
      setLocalNotice('The next match changed after the score was saved. Review it before sending texts.')
      return
    }
    const failed = await sendApproved(after)
    setLocalNotice(failed > 0 ? 'Score saved. Some texts could not be sent.' : isCopy ? `Simulated ${selectedCount} texts. No SMS was sent.` : `Sent ${selectedCount} texts.`)
    if (failed === 0) onComplete?.()
  }

  const finalize = async (save: () => Promise<boolean>, send: boolean) => {
    if (holdForTexts && preview) {
      const failed = await sendApproved(preview)
      setHoldForTexts(false)
      setLocalNotice(failed > 0 ? 'Score saved. Some texts could not be sent.' : isCopy ? `Simulated ${selectedCount} texts. No SMS was sent.` : `Sent ${selectedCount} texts.`)
      if (failed === 0) onComplete?.()
      return
    }
    approvedKey.current = preview?.preview_key || ''
    const saved = await save()
    if (!saved) return
    await finishSaved(send)
  }

  const primaryLabel = (() => {
    if (completed && !holdForTexts) return 'Save Corrected Score'
    const verb = isCopy ? 'Simulate' : 'Send'
    if (holdForTexts) return selectedCount ? `${verb} ${selectedCount} Text${selectedCount === 1 ? '' : 's'}` : 'No Texts'
    if (!selectedCount) return 'Finalize Match — No Texts'
    return `Finalize Match & ${verb} ${selectedCount} Text${selectedCount === 1 ? '' : 's'}`
  })()

  const textPlayers: MatchTextPlayer[] = roster.filter((player) => player.id).map((player) => ({
    id: player.id,
    name: player.name,
    phone: player.phone,
    consent: player.consent,
    team: player.team,
  }))

  return (
    <div className="match-score-drawer">
      <style>{`
        .match-score-drawer { position: fixed; top: 0; right: 0; width: min(640px, 100vw); height: 100vh; background: #fff; box-shadow: -4px 0 20px rgba(0,0,0,.15); z-index: 1000; display: flex; flex-direction: column; }
        .match-score-body { flex: 1; overflow: auto; padding: 18px 22px 28px; }
        .match-score-teams, .match-score-next { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .match-team-card, .match-next-card { border: 1px solid #d7dde3; border-radius: 10px; background: #fff; }
        .match-team-card { display: flex; gap: 10px; align-items: center; padding: 10px; cursor: pointer; text-align: left; width: 100%; }
        .match-team-card.selected { background: #e8f5e9; border: 2px solid #2e7d32; }
        @media (max-width: 720px) {
          .match-score-teams, .match-score-next { grid-template-columns: 1fr; }
        }
      `}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '16px 18px 8px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {match.championship_final && <TrophyMark />}
            <div style={{ fontSize: 22, fontWeight: 800, color: '#1a237e' }}>
              {match.event_name}{match.division_name ? ` — ${match.division_name}` : ''}
            </div>
          </div>
          <div style={{ marginTop: 4, fontSize: 13, color: '#607d8b' }}>{formatWhen(match)}</div>
          <div style={{ marginTop: 6, fontSize: 12, fontWeight: 700, color: completed ? '#2e7d32' : '#455a64' }}>{completed ? 'Completed' : match.status.replace('_', ' ')}</div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
          <IconButton label="Text players" amber={false} onClick={() => setTextOpen(true)} glyph="text" />
          <IconButton label="Notes" amber={hasNotes} onClick={onOpenNotes} glyph="note" />
          <button onClick={onClose} aria-label="Close" style={{ border: 'none', background: 'transparent', fontSize: 22, cursor: 'pointer', color: '#607d8b' }}>×</button>
        </div>
      </div>
      <div className="match-score-body">
        {isCopy && <div style={{ marginBottom: 10, padding: '6px 10px', borderRadius: 6, background: '#fff8e1', color: '#e65100', fontSize: 12, fontWeight: 700 }}>Test Mode — Texts Off. Nothing is sent to a real phone.</div>}
        <div style={{ fontSize: 13, fontWeight: 800, color: '#263238', marginBottom: 8 }}>Select Winning Team</div>
        <div className="match-score-teams" data-testid="score-entry-photos">
          <TeamCard teamId={match.team1_id} label={preview?.cards.find((card) => card.team_id === match.team1_id)?.team_label || match.team1_display} selected={winnerId === match.team1_id} onSelect={() => onWinner(match.team1_id)} />
          <TeamCard teamId={match.team2_id} label={preview?.cards.find((card) => card.team_id === match.team2_id)?.team_label || match.team2_display} selected={winnerId === match.team2_id} onSelect={() => onWinner(match.team2_id)} />
        </div>
        <div style={{ marginTop: 16, fontSize: 13, fontWeight: 800, color: '#263238' }}>Final Score</div>
        <input
          ref={scoreRef}
          value={score}
          onChange={(event) => onScore(event.target.value)}
          readOnly={resultKind === 'default'}
          placeholder={waterfall ? '8-4' : '6-4, 6-3'}
          aria-label="Final score"
          style={{ width: '100%', marginTop: 6, padding: '10px 12px', fontSize: 18, border: '1px solid #90caf9', borderRadius: 8, boxSizing: 'border-box', background: resultKind === 'default' ? '#f7f9fb' : '#fff' }}
        />
        <div style={{ marginTop: 4, fontSize: 12, color: '#78909c' }}>{preview?.format_label || formatLabel}. Enter the winner's games first.</div>
        {winnerId && score.trim() && resultKind !== 'retired' && !winningScore(score) && <div style={{ marginTop: 6, color: '#c62828', fontSize: 12 }}>The selected winner does not match this score.</div>}

        {(!completed || holdForTexts) && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 18 }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#263238' }}>Next Matches</div>
              <button type="button" onClick={() => setPreviewMessages((open) => !open)} style={{ border: 'none', background: 'transparent', color: '#1565c0', fontWeight: 700, cursor: 'pointer' }}>Text Preview</button>
            </div>
            {!winnerId && <div style={{ marginTop: 8, fontSize: 13, color: '#78909c' }}>Select the winning team to project the next matches.</div>}
            <div className="match-score-next" style={{ marginTop: 8 }}>
              {(preview?.cards || []).map((card) => (
                <NextCard key={`${card.team_id}-${card.role}-${card.next_match_id || card.kind}`} card={card} selected={selected} onToggle={toggle} />
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12 }}>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={eligibleIds.length > 0 && selectedCount === eligibleIds.length} onChange={() => setSelected(selectedCount === eligibleIds.length ? [] : eligibleIds)} />
                Select all eligible players
              </label>
              <span style={{ color: '#607d8b' }}>{selectedCount} text{selectedCount === 1 ? '' : 's'} selected</span>
            </div>
            {previewMessages && (
              <div style={{ marginTop: 8 }}>
                {(preview?.cards || []).flatMap((card) => card.players.filter((player) => player.eligible && player.player_id && selected.includes(player.player_id))).map((player) => (
                  <pre key={player.player_id || player.name} style={{ whiteSpace: 'pre-wrap', background: '#f7f9fb', border: '1px solid #eceff1', borderRadius: 8, padding: 10, fontSize: 12 }}>{player.message}</pre>
                ))}
              </div>
            )}
          </>
        )}

        {match.championship_final && winnerId && (
          <div style={{ marginTop: 14, padding: 10, borderRadius: 8, background: '#fff8e1', fontSize: 13 }}>
            <div style={{ fontWeight: 800 }}>{completed ? 'Championship' : 'Projected until the score is finalized'}</div>
            <div>Champions — {winnerId === match.team1_id ? match.team1_display : match.team2_display} — 2 trophies</div>
            <div>Runners-up — {winnerId === match.team1_id ? match.team2_display : match.team1_display} — 2 trophies</div>
            <button type="button" onClick={onOpenTrophies} style={{ marginTop: 6, border: 'none', background: 'transparent', color: '#1565c0', fontWeight: 700, cursor: 'pointer' }}>Open trophy distribution</button>
          </div>
        )}

        {(localNotice || notice) && <div style={{ marginTop: 10, color: '#2e7d32', fontSize: 13 }}>{localNotice || notice}</div>}
        {error && <div style={{ marginTop: 10, color: '#c62828', fontSize: 13 }}>{error}</div>}
        {warnings.map((warning) => <div key={warning} style={{ marginTop: 6, color: '#e65100', fontSize: 12 }}>{warning}</div>)}

        {isDraft && (
          <button
            type="button"
            disabled={submitting || (!holdForTexts && (!scoreOk || (completed && false))) || (!completed && !holdForTexts && !scoreOk)}
            onClick={() => {
              void (completed && !holdForTexts
                ? onSave().then((saved) => { if (saved) onComplete?.() })
                : finalize(saveForKind, !completed || holdForTexts))
            }}
            style={{ width: '100%', marginTop: 14, padding: '12px 14px', border: 'none', borderRadius: 8, background: scoreOk || holdForTexts ? '#2e7d32' : '#cfd8dc', color: '#fff', fontWeight: 800, fontSize: 16, cursor: 'pointer' }}
          >
            {submitting ? 'Saving...' : primaryLabel}
          </button>
        )}
        {isDraft && !completed && (
          <button type="button" disabled={submitting || !scoreOk} onClick={() => { void finalize(saveForKind, false) }} style={{ width: '100%', marginTop: 8, padding: '10px 14px', borderRadius: 8, border: '1px solid #b0bec5', background: '#fff', fontWeight: 700, cursor: 'pointer' }}>
            Finalize Match Without Texting
          </button>
        )}
        {isDraft && !completed && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: '#263238', marginBottom: 6 }}>Result</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" aria-pressed={resultKind === 'normal'} onClick={() => chooseResult('normal')} style={resultButton(resultKind === 'normal', '#1565c0', '#e3f2fd')}>Normal</button>
              <button type="button" aria-pressed={resultKind === 'default'} onClick={() => chooseResult('default')} style={resultButton(resultKind === 'default', '#e65100', '#fff3e0')}>Default Win</button>
              <button type="button" aria-pressed={resultKind === 'retired'} onClick={() => chooseResult('retired')} style={resultButton(resultKind === 'retired', '#6a1b9a', '#f3e5f5')}>Retired</button>
            </div>
          </div>
        )}

        <details open={adminOpen} onToggle={(event) => setAdminOpen((event.target as HTMLDetailsElement).open)} style={{ marginTop: 16 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 800, color: '#455a64' }}>Administrative Actions</summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
            {!completed && <button type="button" onClick={onSetInProgress} style={adminButton}>Set In Progress</button>}
            {!completed && (match.status === 'IN_PROGRESS' || match.status === 'PAUSED') && (
              <button type="button" onClick={onSetNotStarted} style={adminButton}>Set Not Started</button>
            )}
            {showBackToWaiting && !completed && <button type="button" onClick={onBackToWaiting} style={adminButton}>Back To Waiting for Check-In</button>}
            {completed && <button type="button" onClick={onReopen} style={adminButton}>Reopen Match</button>}
          </div>
        </details>
        <details open={historyOpen} onToggle={(event) => setHistoryOpen((event.target as HTMLDetailsElement).open)} style={{ marginTop: 10 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 800, color: '#455a64' }}>Match History</summary>
          {history || <HistoryList match={match} />}
        </details>
      </div>
      {textOpen && (
        <MatchTextDialog
          drawLabel={`${match.event_name}${match.division_name ? ` — ${match.division_name}` : ''}`}
          team1Label={match.team1_display}
          team2Label={match.team2_display}
          players={textPlayers}
          isCopy={isCopy}
          onClose={() => setTextOpen(false)}
          onSend={async (players, message) => {
            const failed = await onSendTexts(players.map((player) => ({ playerId: player.id, message })))
            const results: MatchTextResult[] = players.map((player) => ({ playerId: player.id, status: failed ? 'failed' : (isCopy ? 'dry_run' : 'sent'), error: null }))
            return results
          }}
        />
      )}
    </div>
  )
}

function resultButton(selected: boolean, color: string, fill: string): CSSProperties {
  return {
    flex: 1,
    padding: '8px 10px',
    borderRadius: 8,
    border: `2px solid ${selected ? color : '#cfd8dc'}`,
    background: selected ? fill : '#fff',
    color,
    fontWeight: 800,
    cursor: 'pointer',
  }
}

const adminButton: CSSProperties = { padding: '8px 10px', borderRadius: 8, border: '1px solid #cfd8dc', background: '#fff', textAlign: 'left', cursor: 'pointer' }

function TeamCard({ teamId, label, selected, onSelect }: { teamId: number | null; label: string; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" className={`match-team-card${selected ? ' selected' : ''}`} onClick={onSelect}>
      <TeamPhotoThumb teamId={teamId} size={54} surface="score-entry" />
      <span style={{ flex: 1 }}>
        <span style={{ display: 'block', fontWeight: 800, color: '#263238' }}>{shortTeam(label)}</span>
        {selected && <span style={{ color: '#2e7d32', fontSize: 12, fontWeight: 800 }}>Winner</span>}
      </span>
      <span style={{ width: 22, height: 22, borderRadius: 11, border: selected ? 'none' : '2px solid #b0bec5', background: selected ? '#2e7d32' : '#fff', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 14 }}>{selected ? '✓' : ''}</span>
    </button>
  )
}

function NextCard({ card, selected, onToggle }: { card: NextPreviewCard; selected: number[]; onToggle: (playerId: number) => void }) {
  const names = card.team_label
  return (
    <div className="match-next-card" style={{ padding: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <strong>{names}</strong>
        <span style={{ fontSize: 11, fontWeight: 800, color: card.role === 'winner' ? '#2e7d32' : '#607d8b' }}>{card.role === 'winner' ? 'Winner' : 'Other Team'}</span>
      </div>
      {card.kind === 'next' ? (
        <>
          <div style={{ marginTop: 6, color: '#546e7a', fontSize: 12 }}>{card.date_label}</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#1b5e20' }}>{card.time_label || 'Time pending'} <span style={{ color: '#37474f' }}>{card.court_label || ''}</span></div>
          <div style={{ fontSize: 13, color: '#455a64' }}>{card.opponent_pending ? 'vs. Awaiting previous result' : `vs. ${card.opponent_label}`}</div>
          {card.schedule_pending && <div style={{ color: '#e65100', fontSize: 12 }}>Court or time is pending. No text will be prepared.</div>}
        </>
      ) : (
        <div style={{ marginTop: 8, fontWeight: 700 }}>{card.status_label}</div>
      )}
      {card.players.map((player) => (
        <label key={`${card.team_id}-${player.player_id || player.name}`} style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, fontSize: 13, color: player.eligible ? '#263238' : '#90a4ae' }}>
          <input type="checkbox" disabled={!player.eligible || !player.player_id} checked={!!player.player_id && selected.includes(player.player_id)} onChange={() => player.player_id && onToggle(player.player_id)} />
          <span>{player.name}{player.phone ? <span style={{ color: '#90a4ae' }}> {player.phone}</span> : null}</span>
          {!player.eligible && <span style={{ fontSize: 11 }}>{player.ineligible_reason}</span>}
        </label>
      ))}
    </div>
  )
}

function HistoryList({ match }: { match: DeskMatchItem }) {
  const rows = [
    match.started_at ? `Started ${match.started_at}` : '',
    match.completed_at ? `Completed ${match.completed_at}` : '',
    ...(match.score_corrections || []).map((row) => `Score corrected${row.staff_name ? ` by ${row.staff_name}` : ''}: ${row.previous_score} → ${row.corrected_score}. Winner: ${row.previous_winner} → ${row.corrected_winner}. ${row.corrected_at}`),
  ].filter(Boolean)
  if (!rows.length) return <div style={{ marginTop: 8, fontSize: 12, color: '#90a4ae' }}>No history yet.</div>
  return <div style={{ marginTop: 8, fontSize: 12, color: '#455a64' }}>{rows.map((row) => <div key={row} style={{ marginBottom: 4 }}>{row}</div>)}</div>
}

function TrophyMark() {
  return <span title="Championship Final — Trophy Match." aria-label="Championship Final — Trophy Match."><svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><path fill="#c9a227" d="M7 3h10v2h3v3a5 5 0 01-4 4.9V14h2v2H6v-2h2v-1.1A5 5 0 014 8V5h3V3zm0 4H6v1a3 3 0 003 3V7zm10 0v4a3 3 0 003-3V7h-3zM8 18h8v2H8v-2z" /></svg></span>
}

function IconButton({ label, amber, onClick, glyph }: { label: string; amber: boolean; onClick: () => void; glyph: 'text' | 'note' }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} style={{ width: 32, height: 32, borderRadius: 8, border: `1px solid ${amber ? '#ffb74d' : '#cfd8dc'}`, background: amber ? '#fff3e0' : '#fff', color: amber ? '#ef6c00' : '#546e7a', cursor: 'pointer' }}>
      {glyph === 'text' ? 'T' : 'N'}
    </button>
  )
}

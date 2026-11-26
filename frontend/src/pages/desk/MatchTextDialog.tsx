import { useState, type CSSProperties } from 'react'

export type MatchTextPlayer = {
  id: number
  name: string
  phone: string | null
  consent: string | null
  team: 1 | 2
}

export type MatchTextResult = { playerId: number; status: string; error: string | null }

const ACCEPTED = new Set(['queued', 'sent', 'dry_run', 'sent_redirect', 'shared_number'])

function eligible(player: MatchTextPlayer): boolean {
  return Boolean(player.phone) && player.consent !== 'opted_out'
}

function reason(player: MatchTextPlayer): string {
  if (!player.phone) return 'No cellphone on file'
  if (player.consent === 'opted_out') return 'Opted out of texts'
  return player.phone
}

export default function MatchTextDialog({
  drawLabel, team1Label, team2Label, players, isCopy, onClose, onSend,
}: {
  drawLabel: string
  team1Label: string
  team2Label: string
  players: MatchTextPlayer[]
  isCopy: boolean
  onClose: () => void
  onSend: (players: MatchTextPlayer[], message: string) => Promise<MatchTextResult[]>
}) {
  const [selected, setSelected] = useState<number[]>(() => players.filter(eligible).map((player) => player.id))
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState('')
  const chosen = players.filter((player) => selected.includes(player.id) && eligible(player))
  const selectTeam = (team: 1 | 2 | 'all' | 'none') => {
    if (team === 'none') {
      setSelected([])
      return
    }
    setSelected(players.filter((player) => eligible(player) && (team === 'all' || player.team === team)).map((player) => player.id))
  }
  const send = async () => {
    if (!message.trim()) {
      setNotice('Enter a message.')
      return
    }
    if (chosen.length === 0) {
      setNotice('Select a player with a cellphone number.')
      return
    }
    setSending(true)
    setNotice('')
    try {
      const results = await onSend(chosen, message.trim())
      const failed = results.filter((result) => !ACCEPTED.has(result.status))
      if (results.some((result) => result.status === 'dry_run')) {
        setNotice('Test Mode — Texts Off. Nothing was transmitted.')
        return
      }
      if (failed.length === 0) {
        onClose()
        return
      }
      const failedIds = new Set(failed.map((result) => result.playerId))
      setSelected((current) => current.filter((id) => failedIds.has(id)))
      setNotice(failed.map((result) => result.error || result.status).filter(Boolean).join(' '))
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Text failed')
    } finally {
      setSending(false)
    }
  }
  const teamBlock = (team: 1 | 2, label: string) => {
    const rows = players.filter((player) => player.team === team)
    return (
      <div style={{ display: 'grid', gap: 4 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: '#37474f' }}>{label}</div>
        {rows.length === 0 && <div style={{ fontSize: 12, color: '#90a4ae' }}>No resolved players</div>}
        {rows.map((player) => {
          const ready = eligible(player)
          return (
            <label key={player.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
              <input
                type="checkbox"
                aria-label={player.name}
                checked={ready && selected.includes(player.id)}
                disabled={!ready || sending}
                onChange={(event) => setSelected((current) => event.target.checked ? [...current, player.id] : current.filter((id) => id !== player.id))}
              />
              <span style={{ fontWeight: 800, color: '#1a1a1a' }}>{player.name}</span>
              <span style={{ color: ready ? '#1a1a1a' : '#c62828' }}>{reason(player)}</span>
            </label>
          )
        })}
      </div>
    )
  }
  return (
    <div role="presentation" onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1200, padding: 16 }}>
      <div role="dialog" aria-label="Text players" onClick={(event) => event.stopPropagation()} style={{ width: 460, maxWidth: '100%', background: '#fff', borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 800 }}>Text players{drawLabel ? ` · ${drawLabel}` : ''}</div>
        {isCopy && <div style={{ fontWeight: 800, color: '#b71c1c' }}>Test Mode — Texts Off</div>}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          <button type="button" onClick={() => selectTeam('all')} style={chip}>All 4 Players</button>
          <button type="button" onClick={() => selectTeam(1)} style={chip}>Team 1</button>
          <button type="button" onClick={() => selectTeam(2)} style={chip}>Team 2</button>
          <button type="button" onClick={() => selectTeam('none')} style={chip}>Clear Selection</button>
        </div>
        {teamBlock(1, team1Label || 'Team 1')}
        {teamBlock(2, team2Label || 'Team 2')}
        <textarea aria-label="Message" value={message} onChange={(event) => setMessage(event.target.value)} rows={4} style={{ width: '100%', boxSizing: 'border-box', fontSize: 14, padding: 8 }} />
        <div style={{ fontSize: 12, color: '#607d8b' }}>{message.length} characters · {chosen.length} selected</div>
        {notice && <div style={{ color: notice.startsWith('Test Mode') ? '#b71c1c' : '#c62828', fontSize: 13, fontWeight: 700 }}>{notice}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose} disabled={sending} style={actionButton(false, sending)}>Cancel</button>
          <button type="button" onClick={() => { void send() }} disabled={sending || chosen.length === 0} style={actionButton(true, sending || chosen.length === 0)}>{sending ? 'Sending…' : isCopy ? 'Simulate Send' : 'Send Text'}</button>
        </div>
      </div>
    </div>
  )
}

const chip: CSSProperties = { border: '1px solid #90a4ae', background: '#fff', borderRadius: 999, padding: '3px 8px', fontSize: 12, fontWeight: 800, cursor: 'pointer' }

function actionButton(primary: boolean, busy: boolean): CSSProperties {
  return {
    border: primary ? 'none' : '1px solid #cfd8dc',
    background: primary ? '#111' : '#fff',
    color: primary ? '#fff' : '#455a64',
    borderRadius: 999,
    padding: '8px 14px',
    fontSize: 12,
    fontWeight: 800,
    lineHeight: 1,
    cursor: busy ? 'default' : 'pointer',
    opacity: busy ? 0.6 : 1,
  }
}

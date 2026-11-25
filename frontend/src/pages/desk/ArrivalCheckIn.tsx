import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import {
  buildArrivalBoard,
  filterTiles,
  matrixLayout,
  pickArrivalSlot,
  searchTiles,
  type ArrivalPlayer,
  type ArrivalTile,
} from './firstMatchCheckIn'
import type { CheckInMatchItem, DeskMatchItem } from '../../api/client'
import PlayerNotesDialog, { type StaffNote } from './PlayerNotesDialog'
import { TowelColorPill } from './towelColor'

export type PlayerStaffNote = StaffNote

export type TeamPhones = { p1: string | null; p2: string | null }

export type TextSendResult = {
  playerId: number
  status: string
  error: string | null
}

type Props = {
  checkins: CheckInMatchItem[]
  matches: DeskMatchItem[]
  nowMinutes: number | null
  isToday: (day: string) => boolean
  pendingIds: number[]
  photographedTeamIds?: number[]
  playerNotes?: PlayerStaffNote[]
  phonesByTeam?: Record<number, TeamPhones>
  onCheckIn: (player: ArrivalPlayer) => void
  onUndo: (player: ArrivalPlayer) => void
  onCheckBoth: (tile: ArrivalTile) => void
  onSendText?: (players: ArrivalPlayer[], message: string) => Promise<TextSendResult[]>
  onSaveNote?: (playerIds: number[], body: string) => Promise<void>
}

const SLOT_TINTS = [
  { bg: '#fff8e1', border: '#ffe082', accent: '#f57f17' },
  { bg: '#e8f5e9', border: '#a5d6a7', accent: '#2e7d32' },
  { bg: '#e3f2fd', border: '#90caf9', accent: '#1565c0' },
  { bg: '#f3e5f5', border: '#ce93d8', accent: '#6a1b9a' },
  { bg: '#fce4ec', border: '#f8bbd0', accent: '#ad1457' },
  { bg: '#e0f7fa', border: '#80deea', accent: '#00695c' },
  { bg: '#f9fbe7', border: '#dce775', accent: '#558b2f' },
  { bg: '#efebe9', border: '#bcaaa4', accent: '#4e342e' },
]

function dayButtonLabel(day: string, fallback: string): string {
  const date = new Date(`${day}T12:00:00`)
  if (day === 'unscheduled') return 'Unscheduled'
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
}

function TowelEgg({ colorName, eggHeight }: { colorName: string | null; eggHeight: number }) {
  if (!colorName) {
    return <span title="No towel assigned" style={{ width: eggHeight - 2, height: eggHeight, borderRadius: '50%', border: '1px dashed #90a4ae', display: 'inline-block', flexShrink: 0 }} />
  }
  return <TowelColorPill colorName={colorName} labelMode="egg" eggHeight={eggHeight} />
}

export default function FirstMatchCheckIn({
  checkins, matches, nowMinutes, isToday, pendingIds, photographedTeamIds = [], playerNotes = [], phonesByTeam = {},
  onCheckIn, onUndo, onCheckBoth, onSendText, onSaveNote,
}: Props) {
  const board = buildArrivalBoard(checkins, matches)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const matrixRef = useRef<HTMLDivElement | null>(null)
  const [day, setDay] = useState('')
  const [pinnedSlot, setPinnedSlot] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'all' | 'outstanding' | 'complete'>('all')
  const [box, setBox] = useState({ width: 1200, height: 640 })
  const [textTile, setTextTile] = useState<ArrivalTile | null>(null)
  const [notesTile, setNotesTile] = useState<ArrivalTile | null>(null)
  const photoTeams = new Set(photographedTeamIds)
  const notesFor = (playerId: number) => playerNotes.filter((note) => note.playerId === playerId)

  const selectedDay = board.days.includes(day) ? day : (board.days.find((item) => isToday(item)) || board.days[0] || '')
  const daySlots = board.slots.filter((slot) => slot.day === selectedDay)
  const slotKey = pickArrivalSlot(daySlots, isToday(selectedDay) ? nowMinutes : null, pinnedSlot)
  const slot = daySlots.find((item) => item.key === slotKey) || daySlots[0]
  const searching = query.trim().length > 0
  const tiles = searching
    ? searchTiles(board, query)
    : filterTiles(slot?.tiles || [], mode, '')
  const dateLabel = slot?.dayLabel || dayButtonLabel(selectedDay, selectedDay)

  useEffect(() => {
    const node = matrixRef.current
    if (!node) return
    const measure = () => setBox({ width: node.clientWidth, height: node.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [selectedDay, slotKey, searching, tiles.length])

  const layout = matrixLayout(box.width, box.height, tiles.length)

  return (
    <div ref={rootRef} data-testid="first-match-checkin" style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 10px', background: '#f7f8fa', overflow: 'hidden' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        {board.days.length > 1 ? board.days.map((item) => (
          <button key={item} type="button" onClick={() => { setDay(item); setPinnedSlot(null) }} style={chip(item === selectedDay, 15)}>
            {dayButtonLabel(item, item)}
          </button>
        )) : (
          <span style={{ fontSize: 16, fontWeight: 800, color: '#1a237e' }}>{dateLabel}</span>
        )}
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search player"
          style={{ marginLeft: 'auto', width: 200, padding: '7px 10px', border: '1px solid #90a4ae', borderRadius: 6, fontSize: 15 }}
        />
        {(['all', 'outstanding', 'complete'] as const).map((item) => (
          <button key={item} type="button" onClick={() => setMode(item)} style={chip(mode === item, 15)}>
            {item === 'all' ? 'All' : item === 'outstanding' ? 'Outstanding' : 'Done'}
          </button>
        ))}
      </div>
      {!searching && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {daySlots.map((item, index) => {
            const tint = SLOT_TINTS[index % SLOT_TINTS.length]
            const selected = item.key === slotKey
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setPinnedSlot(item.key)}
                style={{
                  ...chip(selected, 16),
                  background: selected ? '#1a237e' : tint.bg,
                  borderColor: selected ? '#1a237e' : tint.border,
                  color: selected ? '#fff' : tint.accent,
                  padding: '8px 14px',
                }}
              >
                {item.timeLabel}
              </button>
            )
          })}
        </div>
      )}
      {!layout.fits && (
        <div style={{ fontSize: 13, color: '#b71c1c', fontWeight: 700 }}>
          {tiles.length} teams need about {layout.neededHeight}px. This window is {box.width}×{box.height}.
        </div>
      )}
      <div ref={matrixRef} style={{ flex: 1, minHeight: 0, overflow: layout.fits ? 'hidden' : 'auto' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${layout.columns}, ${layout.tileWidth}px)`,
          gridAutoRows: `${layout.tileHeight}px`,
          justifyContent: 'start',
          alignContent: 'start',
          gap: 8,
        }}>
          {tiles.map((tile) => (
            <TeamTile
              key={searching ? `${tile.day}|${tile.key}` : tile.key}
              tile={tile}
              fontSize={layout.fontSize}
              eggHeight={layout.eggHeight}
              pendingIds={pendingIds}
              hasPhoto={tile.teamId != null && photoTeams.has(tile.teamId)}
              notes={tile.players.flatMap((player) => notesFor(player.playerId))}
              hasTeamNote={Boolean(tile.teamNote)}
              onCheckIn={onCheckIn}
              onUndo={onUndo}
              onCheckBoth={onCheckBoth}
              onText={() => setTextTile(tile)}
              onNotes={() => setNotesTile(tile)}
            />
          ))}
        </div>
      </div>
      {textTile && (
        <TextModal
          tile={textTile}
          phonesByTeam={phonesByTeam}
          onClose={() => setTextTile(null)}
          onSend={onSendText}
        />
      )}
      {notesTile && (
        <PlayerNotesDialog
          players={notesTile.players.map((player) => ({ id: player.playerId, name: player.fullName }))}
          notes={notesTile.players.flatMap((player) => notesFor(player.playerId))}
          teamNotes={notesTile.teamNote ? [{ label: 'Team note', body: notesTile.teamNote }] : []}
          canAdd
          onAdd={onSaveNote}
          onClose={() => setNotesTile(null)}
        />
      )}
    </div>
  )
}

function TeamPhotoIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-label="Official team photo taken." style={{ flexShrink: 0 }}>
      <title>Official team photo taken.</title>
      <path fill="#2e7d32" d="M9 4l1.5 2h3L15 4h4a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2h4zm3 4a5 5 0 100 10 5 5 0 000-10zm0 2.2a2.8 2.8 0 110 5.6 2.8 2.8 0 010-5.6z" />
    </svg>
  )
}

function contactPhone(player: ArrivalPlayer, phonesByTeam: Record<number, TeamPhones>): string | null {
  const team = player.teamId != null ? phonesByTeam[player.teamId] : undefined
  if (player.slot === 1 && team?.p1) return team.p1
  if (player.slot === 2 && team?.p2) return team.p2
  return player.phone
}

function TeamTile({
  tile, fontSize, eggHeight, pendingIds, hasPhoto, notes, hasTeamNote, onCheckIn, onUndo, onCheckBoth, onText, onNotes,
}: {
  tile: ArrivalTile
  fontSize: number
  eggHeight: number
  pendingIds: number[]
  hasPhoto: boolean
  notes: PlayerStaffNote[]
  hasTeamNote: boolean
  onCheckIn: (player: ArrivalPlayer) => void
  onUndo: (player: ArrivalPlayer) => void
  onCheckBoth: (tile: ArrivalTile) => void
  onText: () => void
  onNotes: () => void
}) {
  const checked = tile.players.filter((player) => player.checkedIn).length
  const total = tile.players.length
  const bothDone = total > 0 && checked === total
  const border = bothDone ? '#2e7d32' : '#cfd8dc'
  return (
    <div style={{ border: `1px solid ${border}`, borderRadius: 10, background: '#fff', padding: '4px 6px', minWidth: 0, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: 4, boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0, flex: 1 }}>
        {tile.players.map((player) => {
          const pending = pendingIds.includes(player.playerId)
          return (
            <div key={player.playerId} style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
              <button
                type="button"
                aria-disabled={player.checkedIn || !player.canCheckIn || pending}
                title={player.fullName}
                onClick={() => {
                  if (player.checkedIn || !player.canCheckIn || pending) return
                  onCheckIn(player)
                }}
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  border: '1px solid #e0e0e0',
                  borderRadius: 8,
                  background: player.checkedIn ? '#e8f5e9' : '#fff',
                  padding: '4px 8px',
                  cursor: player.checkedIn ? 'default' : 'pointer',
                  textAlign: 'left',
                  opacity: 1,
                }}
              >
                <TowelEgg colorName={player.towelColor} eggHeight={eggHeight} />
                <span style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', color: '#1a1a1a', fontSize, fontWeight: 800 }}>{player.firstName}</span>
                <span style={{ width: 18, textAlign: 'center', color: player.checkedIn ? '#2e7d32' : '#90a4ae', fontSize: 16, fontWeight: 800 }}>
                  {player.checkedIn ? '✓' : '☐'}
                </span>
              </button>
              {player.checkedIn && (
                <button type="button" title="Undo check-in" onClick={() => onUndo(player)} style={{ border: 'none', background: 'transparent', color: '#90a4ae', cursor: 'pointer', fontSize: 11, fontWeight: 700 }}>Undo</button>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, minHeight: 22 }}>
        {hasPhoto && <TeamPhotoIcon />}
        <button type="button" onClick={onText} style={miniButton(false)}>Text</button>
        <button type="button" title={notes.length > 0 || hasTeamNote ? 'Player notes exist.' : 'No player notes'} onClick={onNotes} style={miniButton(notes.length > 0 || hasTeamNote)}>Notes</button>
      </div>
      <button
        type="button"
        aria-disabled={bothDone || tile.players.some((player) => pendingIds.includes(player.playerId) || !player.canCheckIn)}
        onClick={() => {
          if (bothDone || tile.players.some((player) => pendingIds.includes(player.playerId) || !player.canCheckIn)) return
          onCheckBoth(tile)
        }}
        style={{
          border: 'none',
          borderRadius: 8,
          background: bothDone ? '#eceff1' : '#111',
          color: bothDone ? '#2e7d32' : '#fff',
          fontSize: 13,
          fontWeight: 800,
          padding: '5px 8px',
          cursor: bothDone ? 'default' : 'pointer',
        }}
      >
        {bothDone ? 'Checked In' : 'Check In Both'}
      </button>
    </div>
  )
}

function chip(active: boolean, fontSize = 14): CSSProperties {
  return {
    border: '1px solid #1a237e',
    background: active ? '#1a237e' : '#fff',
    color: active ? '#fff' : '#1a237e',
    borderRadius: 8,
    padding: '6px 12px',
    fontSize,
    fontWeight: 800,
    cursor: 'pointer',
  }
}

function miniButton(alerted: boolean): CSSProperties {
  return {
    border: `1px solid ${alerted ? '#f9a825' : '#cfd8dc'}`,
    background: alerted ? '#fff8e1' : '#fff',
    color: alerted ? '#e65100' : '#455a64',
    borderRadius: 999,
    padding: '2px 8px',
    fontSize: 12,
    fontWeight: 800,
    cursor: 'pointer',
  }
}

const ACCEPTED_TEXT = new Set(['queued', 'sent', 'dry_run', 'sent_redirect'])

function phoneReady(player: ArrivalPlayer, phone: string | null): boolean {
  return Boolean(phone) && player.smsConsent !== 'opted_out'
}

function TextModal({
  tile, phonesByTeam, onClose, onSend,
}: {
  tile: ArrivalTile
  phonesByTeam: Record<number, TeamPhones>
  onClose: () => void
  onSend?: (players: ArrivalPlayer[], message: string) => Promise<TextSendResult[]>
}) {
  const shown = tile.players.map((player) => ({ player, phone: contactPhone(player, phonesByTeam) }))
  const [selected, setSelected] = useState<number[]>(() => shown.filter(({ player, phone }) => phoneReady(player, phone)).map(({ player }) => player.playerId))
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState('')
  const send = async () => {
    const recipients = shown.filter(({ player, phone }) => selected.includes(player.playerId) && phoneReady(player, phone)).map(({ player }) => player)
    if (!message.trim()) {
      setNotice('Enter a message.')
      return
    }
    if (recipients.length === 0) {
      setNotice('Select a player with a cellphone number.')
      return
    }
    if (!onSend) {
      setNotice('Texting is not available.')
      return
    }
    setSending(true)
    setNotice('')
    try {
      const results = await onSend(recipients, message.trim())
      const failed = results.filter((result) => !ACCEPTED_TEXT.has(result.status) && result.status !== 'shared_number')
      if (failed.length === 0) {
        onClose()
        return
      }
      const failedIds = new Set(failed.map((result) => result.playerId))
      setSelected((current) => current.filter((id) => failedIds.has(id)))
      setNotice(failed.map((result) => result.error || result.status).join(' '))
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Text failed')
    } finally {
      setSending(false)
    }
  }
  return (
    <Modal title="Text players" onClose={onClose}>
      {shown.map(({ player, phone }) => {
        const ready = phoneReady(player, phone)
        const reason = !phone ? 'No cellphone on file' : player.smsConsent === 'opted_out' ? 'Opted out of texts' : phone
        return (
          <label key={player.playerId} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
            <input
              type="checkbox"
              checked={selected.includes(player.playerId)}
              disabled={!ready || sending}
              onChange={(event) => setSelected((current) => event.target.checked ? [...current, player.playerId] : current.filter((id) => id !== player.playerId))}
            />
            <span style={{ fontWeight: 800 }}>{player.fullName}</span>
            <span style={{ color: ready ? '#1a1a1a' : '#c62828' }}>{reason}</span>
          </label>
        )
      })}
      <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={4} style={{ width: '100%', boxSizing: 'border-box', fontSize: 14, padding: 8 }} />
      <div style={{ fontSize: 12, color: '#607d8b' }}>{message.trim().length} characters</div>
      {notice && <div style={{ color: '#c62828', fontSize: 13, fontWeight: 700 }}>{notice}</div>}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" onClick={onClose} disabled={sending} style={dialogButton(false, sending)}>Close</button>
        <button type="button" onClick={() => { void send() }} disabled={sending} style={dialogButton(true, sending)}>{sending ? 'Sending…' : 'Send Text'}</button>
      </div>
    </Modal>
  )
}

function dialogButton(primary: boolean, busy: boolean): CSSProperties {
  return {
    border: primary ? 'none' : '1px solid #cfd8dc',
    background: primary ? '#111' : '#fff',
    color: primary ? '#fff' : '#455a64',
    borderRadius: 999,
    padding: '8px 14px',
    fontSize: 12,
    fontWeight: 800,
    cursor: busy ? 'default' : 'pointer',
    opacity: busy ? 0.6 : 1,
  }
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div role="presentation" onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 20, padding: 16 }}>
      <div role="dialog" aria-label={title} onClick={(event) => event.stopPropagation()} style={{ width: 420, maxWidth: '100%', background: '#fff', borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 800 }}>{title}</div>
        {children}
      </div>
    </div>
  )
}

import { useEffect, useRef, useState, type CSSProperties } from 'react'
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

type Props = {
  checkins: CheckInMatchItem[]
  matches: DeskMatchItem[]
  nowMinutes: number | null
  isToday: (day: string) => boolean
  pendingIds: number[]
  onCheckIn: (player: ArrivalPlayer) => void
  onUndo: (player: ArrivalPlayer) => void
  onCheckBoth: (tile: ArrivalTile) => void
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
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

function towelEggStyle(colorName: string): { background: string; border: string } {
  const key = colorName.trim().toLowerCase()
  const presets: Record<string, { background: string; border: string }> = {
    lime: { background: '#c6ff00', border: '#99cc00' },
    black: { background: '#111111', border: '#000000' },
    royal: { background: '#4169e1', border: '#2746a6' },
    navy: { background: '#001f5b', border: '#00143d' },
    red: { background: '#d32f2f', border: '#9a0007' },
    purple: { background: '#8e24aa', border: '#5c007a' },
    orange: { background: '#ef6c00', border: '#b53d00' },
    pink: { background: '#d81b60', border: '#8e0038' },
    blue: { background: '#1976d2', border: '#0d47a1' },
    green: { background: '#2e7d32', border: '#1b5e20' },
    yellow: { background: '#ffd54f', border: '#c8a415' },
    white: { background: '#fafafa', border: '#90a4ae' },
  }
  return presets[key] || { background: key, border: '#546e7a' }
}

function TowelEgg({ colorName }: { colorName: string | null }) {
  if (!colorName) {
    return <span title="No towel assigned" style={{ width: 16, height: 18, borderRadius: '50%', border: '1px dashed #90a4ae', display: 'inline-block' }} />
  }
  const styles = towelEggStyle(colorName)
  return (
    <span
      title={colorName}
      style={{
        width: 16,
        height: 18,
        borderRadius: '50%',
        border: `1px solid ${styles.border}`,
        background: styles.background,
        display: 'inline-block',
        flexShrink: 0,
      }}
    />
  )
}

export default function FirstMatchCheckIn({
  checkins, matches, nowMinutes, isToday, pendingIds, onCheckIn, onUndo, onCheckBoth,
}: Props) {
  const board = buildArrivalBoard(checkins, matches)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const matrixRef = useRef<HTMLDivElement | null>(null)
  const [day, setDay] = useState('')
  const [pinnedSlot, setPinnedSlot] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'all' | 'outstanding' | 'complete'>('all')
  const [box, setBox] = useState({ width: 1200, height: 640 })

  const selectedDay = board.days.includes(day) ? day : (board.days.find((item) => isToday(item)) || board.days[0] || '')
  const daySlots = board.slots.filter((slot) => slot.day === selectedDay)
  const slotKey = pickArrivalSlot(daySlots, isToday(selectedDay) ? nowMinutes : null, pinnedSlot)
  const slot = daySlots.find((item) => item.key === slotKey) || daySlots[0]
  const searching = query.trim().length > 0
  const tiles = searching
    ? searchTiles(board, query)
    : filterTiles(slot?.tiles || [], mode, '')

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
  const tournamentChecked = board.checkedPlayerIds.length
  const tournamentTotal = board.playerIds.length
  const slotChecked = slot?.checkedPlayerIds.length || 0
  const slotTotal = slot?.expectedPlayerIds.length || 0

  return (
    <div ref={rootRef} data-testid="first-match-checkin" style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 6, padding: '6px 8px', background: '#f4f6f8', overflow: 'hidden' }}>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {board.days.map((item) => (
          <button key={item} type="button" onClick={() => { setDay(item); setPinnedSlot(null) }} style={chip(item === selectedDay)}>
            {dayButtonLabel(item, item)}
          </button>
        ))}
        <button type="button" onClick={() => {
          const node = rootRef.current
          if (!node) return
          if (document.fullscreenElement) void document.exitFullscreen()
          else void node.requestFullscreen()
        }} style={chip(false)}>Full screen</button>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, fontWeight: 800 }}>
        <span>First-match check-in</span>
        <span style={{ color: '#2e7d32' }}>Tournament: {tournamentChecked}/{tournamentTotal} checked in</span>
        <span style={{ color: tournamentTotal - tournamentChecked > 0 ? '#e65100' : '#2e7d32' }}>{tournamentTotal - tournamentChecked} remaining</span>
        {!searching && slot && (
          <>
            <span style={{ color: '#2e7d32' }}>{slot.timeLabel}: {slotChecked}/{slotTotal} checked in</span>
            <span style={{ color: slotTotal - slotChecked > 0 ? '#e65100' : '#2e7d32' }}>{slotTotal - slotChecked} remaining</span>
          </>
        )}
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search player"
          style={{ marginLeft: 'auto', width: 180, padding: '3px 6px', border: '1px solid #90a4ae', borderRadius: 4 }}
        />
        {(['all', 'outstanding', 'complete'] as const).map((item) => (
          <button key={item} type="button" onClick={() => setMode(item)} style={chip(mode === item)}>
            {item === 'all' ? 'All' : item === 'outstanding' ? 'Outstanding' : 'Done'}
          </button>
        ))}
      </div>
      {!searching && (
        <div style={{ display: 'flex', gap: 4, overflow: 'hidden' }}>
          {daySlots.map((item, index) => {
            const done = item.expectedPlayerIds.length > 0 && item.checkedPlayerIds.length === item.expectedPlayerIds.length
            const tint = SLOT_TINTS[index % SLOT_TINTS.length]
            const selected = item.key === slotKey
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setPinnedSlot(item.key)}
                style={{
                  ...chip(selected),
                  background: selected ? '#1a237e' : tint.bg,
                  borderColor: selected ? '#1a237e' : tint.border,
                  color: selected ? '#fff' : tint.accent,
                }}
              >
                {item.timeLabel} — {item.checkedPlayerIds.length}/{item.expectedPlayerIds.length}{done ? ' ✓' : ''}
              </button>
            )
          })}
        </div>
      )}
      {!layout.fits && (
        <div style={{ fontSize: 11, color: '#b71c1c', fontWeight: 700 }}>
          {tiles.length} teams need about {layout.neededHeight}px. This window is {box.width}×{box.height}. Widen the display or use full screen.
        </div>
      )}
      <div ref={matrixRef} style={{ flex: 1, minHeight: 0, overflow: layout.fits ? 'hidden' : 'auto' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${layout.columns}, minmax(0, 1fr))`,
          gridAutoRows: `${layout.tileHeight}px`,
          gap: 4,
        }}>
          {tiles.map((tile) => (
            <TeamTile
              key={searching ? `${tile.day}|${tile.key}` : tile.key}
              tile={tile}
              showWhen={searching}
              fontSize={layout.fontSize}
              pendingIds={pendingIds}
              onCheckIn={onCheckIn}
              onUndo={onUndo}
              onCheckBoth={onCheckBoth}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function TeamTile({
  tile, showWhen, fontSize, pendingIds, onCheckIn, onUndo, onCheckBoth,
}: {
  tile: ArrivalTile
  showWhen: boolean
  fontSize: number
  pendingIds: number[]
  onCheckIn: (player: ArrivalPlayer) => void
  onUndo: (player: ArrivalPlayer) => void
  onCheckBoth: (tile: ArrivalTile) => void
}) {
  const checked = tile.players.filter((player) => player.checkedIn).length
  const total = tile.players.length
  const border = checked === 0 ? '#cfd8dc' : checked < total ? '#ffb300' : '#2e7d32'
  const bothDone = total > 0 && checked === total
  return (
    <div style={{ border: `1px solid ${border}`, borderRadius: 4, background: '#fff', padding: '2px 4px', minWidth: 0, display: 'flex', alignItems: 'center', gap: 4, overflow: 'hidden' }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: '#1a237e', width: 54, flexShrink: 0 }}>
        Ct {tile.courtLabel} · {tile.division}
        <div>{checked}/{total}</div>
        {showWhen && <div>{tile.day === 'unscheduled' ? 'Unscheduled' : tile.day.slice(5)} {tile.timeLabel}</div>}
      </div>
      <div style={{ display: 'flex', gap: 3, minWidth: 0, flex: 1 }}>
        {tile.players.map((player) => (
          <div key={player.playerId} style={{ display: 'flex', alignItems: 'center', gap: 2, minWidth: 0, flex: 1, background: player.checkedIn ? '#e8f5e9' : 'transparent', borderRadius: 3, padding: '0 2px' }}>
            <button
              type="button"
              disabled={player.checkedIn || pendingIds.includes(player.playerId)}
              title={player.fullName}
              onClick={() => onCheckIn(player)}
              style={{ display: 'flex', alignItems: 'center', gap: 3, border: 'none', background: 'transparent', padding: 0, minWidth: 0, cursor: player.checkedIn ? 'default' : 'pointer', fontSize, fontWeight: 700 }}
            >
              <TowelEgg colorName={player.towelColor} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{player.firstName}</span>
              {player.checkedIn && <span style={{ color: '#2e7d32' }}>✓</span>}
            </button>
            {player.checkedIn && (
              <button type="button" title="Undo check-in" onClick={() => onUndo(player)} style={{ border: 'none', background: 'transparent', color: '#90a4ae', cursor: 'pointer', fontSize: 10 }}>×</button>
            )}
          </div>
        ))}
      </div>
      <button
        type="button"
        title="Check In Both Players"
        disabled={bothDone || tile.players.some((player) => pendingIds.includes(player.playerId))}
        onClick={() => onCheckBoth(tile)}
        style={{ border: 'none', background: bothDone ? '#c8e6c9' : '#1a237e', color: bothDone ? '#1b5e20' : '#fff', borderRadius: 4, fontSize: 11, fontWeight: 800, padding: '2px 4px', cursor: bothDone ? 'default' : 'pointer' }}
      >
        ✓✓
      </button>
    </div>
  )
}

function chip(active: boolean): CSSProperties {
  return {
    border: '1px solid #1a237e',
    background: active ? '#1a237e' : '#fff',
    color: active ? '#fff' : '#1a237e',
    borderRadius: 4,
    padding: '2px 8px',
    fontSize: 12,
    fontWeight: 800,
    cursor: 'pointer',
  }
}

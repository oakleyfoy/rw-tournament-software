import type { CheckInMatchItem, DeskMatchItem } from '../../api/client'
import { getCompactDivisionLabel } from '../../utils/matchDivisionLabel'

export type ArrivalPlayer = {
  playerId: number
  firstName: string
  fullName: string
  towelColor: string | null
  checkedIn: boolean
  side: 'A' | 'B'
  matchId: number
}

export type ArrivalTile = {
  key: string
  matchId: number
  side: 'A' | 'B'
  courtNumber: number | null
  courtLabel: string
  division: string
  day: string
  sortTime: string
  timeLabel: string
  players: ArrivalPlayer[]
}

export type ArrivalSlot = {
  key: string
  day: string
  dayLabel: string
  sortTime: string
  timeLabel: string
  tiles: ArrivalTile[]
  expectedPlayerIds: number[]
  checkedPlayerIds: number[]
}

export type ArrivalBoard = {
  days: string[]
  slots: ArrivalSlot[]
  playerIds: number[]
  checkedPlayerIds: number[]
}

type Appearance = {
  playerId: number
  fullName: string
  towelColor: string | null
  checkedIn: boolean
  side: 'A' | 'B'
  matchId: number
  day: string
  sortTime: string
  timeLabel: string
  dayLabel: string
  courtNumber: number | null
  courtLabel: string
  division: string
  teamKey: string
}

export function playerFirstName(display: string): string {
  const cleaned = (display || '').replace(/\(.*?\)/g, '').trim()
  const token = cleaned.split(/[\s,/]+/).filter(Boolean)[0]
  return token || 'Player'
}

export function matrixLayout(width: number, height: number, teamCount: number): {
  columns: number
  tileHeight: number
  fontSize: number
  fits: boolean
  neededHeight: number
} {
  if (teamCount <= 0 || width <= 0 || height <= 0) {
    return { columns: 1, tileHeight: 48, fontSize: 12, fits: true, neededHeight: 0 }
  }
  const gap = 4
  const minTile = 36
  const minTileWidth = 150
  const maxColumns = Math.max(1, Math.floor((width + gap) / (minTileWidth + gap)))
  let columns = teamCount <= 12 ? 4 : teamCount <= 36 ? 6 : teamCount <= 48 ? 8 : 10
  columns = Math.min(teamCount, maxColumns, Math.max(1, columns))
  const fitColumns = () => {
    const rows = Math.ceil(teamCount / columns)
    const tileHeight = Math.floor((height - gap * Math.max(0, rows - 1)) / rows)
    return { rows, tileHeight }
  }
  let layout = fitColumns()
  while (layout.tileHeight < minTile && columns < teamCount && columns < maxColumns) {
    columns += 1
    layout = fitColumns()
  }
  const tileHeight = Math.max(minTile, Math.min(52, layout.tileHeight))
  const neededHeight = layout.rows * minTile + gap * Math.max(0, layout.rows - 1)
  const fits = layout.tileHeight >= minTile
  const fontSize = tileHeight >= 48 ? 12 : tileHeight >= 40 ? 11 : 10
  return { columns, tileHeight: fits ? tileHeight : minTile, fontSize, fits, neededHeight }
}

function rank(day: string, sortTime: string): string {
  return `${day}|${sortTime}`
}

export function buildArrivalBoard(checkins: CheckInMatchItem[], matches: DeskMatchItem[]): ArrivalBoard {
  const deskById = new Map(matches.map((match) => [match.match_id, match]))
  const appearances: Appearance[] = []
  for (const checkin of checkins) {
    const desk = deskById.get(checkin.match_id)
    if (desk && (desk.court_assignment_mode || '').toUpperCase() !== 'PREASSIGNED') continue
    const scheduledDay = desk?.day_date || ''
    const scheduledTime = checkin.sort_time || desk?.sort_time || ''
    const unscheduled = !scheduledDay || !scheduledTime
    const day = unscheduled ? 'unscheduled' : scheduledDay
    const sortTime = unscheduled ? '99:99' : scheduledTime
    const courtNumber = desk?.court_number ?? null
    const courtLabel = courtNumber != null ? String(courtNumber) : (desk?.court_name || '').replace(/^Court\s+/i, '')
    const division = getCompactDivisionLabel(desk?.match_code || checkin.match_code)
    for (const side of ['A', 'B'] as const) {
      const state = side === 'A' ? checkin.side_a : checkin.side_b
      for (const player of state.players) {
        if (player.player_id == null) continue
        appearances.push({
          playerId: player.player_id,
          fullName: player.player_display || 'Player',
          towelColor: player.towel_color,
          checkedIn: Boolean(player.checked_in || state.team_checked_in),
          side,
          matchId: checkin.match_id,
          day,
          sortTime,
          timeLabel: unscheduled ? 'Unscheduled' : (checkin.scheduled_time || desk?.scheduled_time || sortTime),
          dayLabel: checkin.day_label || desk?.day_label || day,
          courtNumber,
          courtLabel,
          division,
          teamKey: `${checkin.match_id}|${side}`,
        })
      }
    }
  }

  const earliest = new Map<number, string>()
  const checked = new Set<number>()
  for (const row of appearances) {
    const key = rank(row.day, row.sortTime)
    const prev = earliest.get(row.playerId)
    if (!prev || key < prev) earliest.set(row.playerId, key)
    if (row.checkedIn) checked.add(row.playerId)
  }

  const tileMap = new Map<string, ArrivalTile>()
  for (const row of appearances) {
    if (earliest.get(row.playerId) !== rank(row.day, row.sortTime)) continue
    const tile = tileMap.get(row.teamKey) || {
      key: row.teamKey,
      matchId: row.matchId,
      side: row.side,
      courtNumber: row.courtNumber,
      courtLabel: row.courtLabel || '—',
      division: row.division,
      day: row.day,
      sortTime: row.sortTime,
      timeLabel: row.timeLabel,
      players: [],
    }
    tile.players.push({
      playerId: row.playerId,
      firstName: playerFirstName(row.fullName),
      fullName: row.fullName,
      towelColor: row.towelColor,
      checkedIn: checked.has(row.playerId),
      side: row.side,
      matchId: row.matchId,
    })
    tileMap.set(row.teamKey, tile)
  }

  const slots = new Map<string, ArrivalSlot>()
  for (const tile of tileMap.values()) {
    const key = rank(tile.day, tile.sortTime)
    const slot = slots.get(key) || {
      key,
      day: tile.day,
      dayLabel: appearances.find((row) => row.day === tile.day)?.dayLabel || tile.day,
      sortTime: tile.sortTime,
      timeLabel: tile.timeLabel,
      tiles: [],
      expectedPlayerIds: [],
      checkedPlayerIds: [],
    }
    slot.tiles.push(tile)
    slots.set(key, slot)
  }
  for (const slot of slots.values()) {
    slot.tiles.sort((a, b) => (a.courtNumber ?? 999) - (b.courtNumber ?? 999) || a.matchId - b.matchId || a.side.localeCompare(b.side))
    const ids = new Set<number>()
    for (const tile of slot.tiles) {
      for (const player of tile.players) ids.add(player.playerId)
    }
    slot.expectedPlayerIds = Array.from(ids)
    slot.checkedPlayerIds = slot.expectedPlayerIds.filter((id) => checked.has(id))
  }

  const ordered = Array.from(slots.values()).sort((a, b) => a.key.localeCompare(b.key))
  return {
    days: Array.from(new Set(ordered.map((slot) => slot.day))),
    slots: ordered,
    playerIds: Array.from(earliest.keys()),
    checkedPlayerIds: Array.from(checked),
  }
}

export function filterTiles(tiles: ArrivalTile[], mode: 'all' | 'outstanding' | 'complete', query: string): ArrivalTile[] {
  const needle = query.trim().toLowerCase()
  return tiles.filter((tile) => {
    const done = tile.players.length > 0 && tile.players.every((player) => player.checkedIn)
    if (mode === 'complete' && !done) return false
    if (mode === 'outstanding' && done) return false
    if (!needle) return true
    const names = tile.players.map((player) => `${player.fullName} ${player.firstName}`.toLowerCase()).join(' ')
    return names.includes(needle)
  })
}

export function searchTiles(board: ArrivalBoard, query: string): ArrivalTile[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  return board.slots.flatMap((slot) => slot.tiles).filter((tile) => (
    tile.players.some((player) => `${player.fullName} ${player.firstName}`.toLowerCase().includes(needle))
  ))
}

export function pickArrivalSlot(slots: ArrivalSlot[], nowMinutes: number | null, manualKey: string | null): string {
  if (manualKey && slots.some((slot) => slot.key === manualKey)) return manualKey
  if (nowMinutes == null || slots.length === 0) return slots[0]?.key || ''
  const scored = slots.map((slot) => {
    const [hour, minute] = slot.sortTime.split(':').map(Number)
    return { key: slot.key, minutes: hour * 60 + (minute || 0) }
  }).filter((row) => Number.isFinite(row.minutes))
  const upcoming = scored.find((row) => row.minutes >= nowMinutes - 30)
  return (upcoming || scored[scored.length - 1])?.key || slots[0].key
}

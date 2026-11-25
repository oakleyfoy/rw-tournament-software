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
  countsInSlot: boolean
  canCheckIn: boolean
  phone: string | null
  smsConsent: string | null
}

export type ArrivalTile = {
  key: string
  matchId: number
  side: 'A' | 'B'
  courtNumber: number | null
  courtLabel: string
  division: string
  teamId: number | null
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
  teamId: number | null
  canCheckIn: boolean
  phone: string | null
  smsConsent: string | null
}

export function playerFirstName(display: string): string {
  const cleaned = (display || '').replace(/\(.*?\)/g, '').trim()
  const token = cleaned.split(/[\s,/]+/).filter(Boolean)[0]
  return token || 'Player'
}

export function matrixLayout(width: number, height: number, teamCount: number): {
  columns: number
  tileWidth: number
  tileHeight: number
  fontSize: number
  eggHeight: number
  fits: boolean
  neededHeight: number
} {
  const preferred = { columns: 1, tileWidth: 280, tileHeight: 48, fontSize: 14, eggHeight: 18, fits: true, neededHeight: 0 }
  if (teamCount <= 0 || width <= 0 || height <= 0) return preferred
  const gap = 8
  const minWidth = 156
  const targetWidth = 176
  const maxWidth = 230
  const minHeight = 128
  const maxHeight = 150
  const rowsFor = (count: number) => Math.ceil(teamCount / count)
  const heightFor = (rows: number, rowHeight: number) => rows * rowHeight + gap * Math.max(0, rows - 1)
  const maxColumns = Math.max(1, Math.floor((width + gap) / (minWidth + gap)))
  let columns = Math.min(teamCount, Math.max(1, Math.floor((width + gap) / (targetWidth + gap))))
  while (columns < maxColumns && heightFor(rowsFor(columns), minHeight) > height) columns += 1
  const tileWidth = Math.min(maxWidth, Math.floor((width - gap * Math.max(0, columns - 1)) / columns))
  const rows = rowsFor(columns)
  const available = Math.floor((height - gap * Math.max(0, rows - 1)) / rows)
  const tileHeight = Math.max(minHeight, Math.min(maxHeight, available || minHeight))
  const neededHeight = heightFor(rows, minHeight)
  const fits = tileWidth >= minWidth && heightFor(rows, tileHeight) <= height + 1
  const fontSize = tileWidth >= 170 ? 16 : 15
  const eggHeight = tileHeight >= 120 ? 22 : 20
  return { columns, tileWidth, tileHeight: fits ? tileHeight : minHeight, fontSize, eggHeight, fits, neededHeight }
}

function rank(day: string, sortTime: string): string {
  return `${day}|${sortTime}`
}

export function buildArrivalBoard(checkins: CheckInMatchItem[], matches: DeskMatchItem[]): ArrivalBoard {
  const deskById = new Map(matches.map((match) => [match.match_id, match]))
  const appearances: Appearance[] = []
  for (const checkin of checkins) {
    if (checkin.is_opening_entry === false) continue
    const desk = deskById.get(checkin.match_id)
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
        if (player.player_id == null || player.player_id <= 0) continue
        const fullName = player.player_display || 'Player'
        const playerId = player.player_id
        appearances.push({
          playerId,
          fullName,
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
          teamKey: state.team_id != null ? `team:${state.team_id}` : `side:${checkin.match_id}|${side}`,
          teamId: state.team_id,
          canCheckIn: checkin.match_id > 0,
          phone: player.phone_e164 || null,
          smsConsent: player.sms_consent || null,
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

  const groups = new Map<string, Appearance[]>()
  for (const row of appearances) {
    const list = groups.get(row.teamKey) || []
    list.push(row)
    groups.set(row.teamKey, list)
  }

  const tileMap = new Map<string, ArrivalTile>()
  for (const group of groups.values()) {
    const ordered = [...group].sort((a, b) => rank(a.day, a.sortTime).localeCompare(rank(b.day, b.sortTime)) || (a.courtNumber ?? 999) - (b.courtNumber ?? 999) || a.matchId - b.matchId)
    const first = ordered[0]
    const tileRows = ordered.filter((row) => row.matchId === first.matchId && row.side === first.side)
    const players = new Map<number, Appearance>()
    for (const row of tileRows) players.set(row.playerId, row)
    const tileKey = `${first.matchId}|${first.side}`
    tileMap.set(tileKey, {
      key: tileKey,
      matchId: first.matchId,
      side: first.side,
      courtNumber: first.courtNumber,
      courtLabel: first.courtLabel || '—',
      division: first.division,
      teamId: first.teamId,
      day: first.day,
      sortTime: first.sortTime,
      timeLabel: first.timeLabel,
      players: Array.from(players.values()).map((row) => ({
        playerId: row.playerId,
        firstName: playerFirstName(row.fullName),
        fullName: row.fullName,
        towelColor: row.towelColor,
        checkedIn: checked.has(row.playerId),
        side: row.side,
        matchId: row.matchId,
        countsInSlot: earliest.get(row.playerId) === rank(first.day, first.sortTime),
        canCheckIn: row.canCheckIn,
        phone: row.phone,
        smsConsent: row.smsConsent,
      })),
    })
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
    slot.tiles.sort(compareArrivalTiles)
    const ids = new Set<number>()
    for (const tile of slot.tiles) {
      for (const player of tile.players) {
        if (player.countsInSlot) ids.add(player.playerId)
      }
    }
    slot.expectedPlayerIds = Array.from(ids)
    slot.checkedPlayerIds = slot.expectedPlayerIds.filter((id) => checked.has(id))
  }

  const ordered = Array.from(slots.values()).sort((a, b) => a.key.localeCompare(b.key))
  const days = Array.from(new Set(ordered.map((slot) => slot.day))).sort((a, b) => a.localeCompare(b))
  return {
    days,
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

export function compareArrivalTiles(a: ArrivalTile, b: ArrivalTile): number {
  const topA = a.players[0]
  const topB = b.players[0]
  const first = (topA?.firstName || '').localeCompare(topB?.firstName || '', undefined, { sensitivity: 'base' })
  if (first !== 0) return first
  const full = (topA?.fullName || '').localeCompare(topB?.fullName || '', undefined, { sensitivity: 'base' })
  if (full !== 0) return full
  return (a.teamId ?? a.matchId) - (b.teamId ?? b.matchId)
}

export function searchTiles(board: ArrivalBoard, query: string): ArrivalTile[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  return board.slots.flatMap((slot) => slot.tiles).filter((tile) => (
    tile.players.some((player) => `${player.fullName} ${player.firstName}`.toLowerCase().includes(needle))
  )).sort(compareArrivalTiles)
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

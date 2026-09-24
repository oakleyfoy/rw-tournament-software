import type { CheckInMatchItem, TemporaryPlayerLookupItem } from '../api/client'

export type TowelColorCount = { colorName: string; count: number }

function playerTowelKey(playerId: number | null | undefined, display: string): string {
  if (playerId != null) return `id:${playerId}`
  const name = display.trim().toLowerCase()
  return name ? `name:${name}` : ''
}

/** Packing totals: one towel per unique player (not per match appearance). */
export function summarizeTowelCountsFromMatches(matches: CheckInMatchItem[]): TowelColorCount[] {
  const colorByPlayer = new Map<string, string>()
  for (const match of matches) {
    for (const side of [match.side_a, match.side_b]) {
      for (const player of side.players || []) {
        const colorName = (player.towel_color || '').trim()
        if (!colorName) continue
        const key = playerTowelKey(player.player_id, player.player_display || '')
        if (!key || colorByPlayer.has(key)) continue
        colorByPlayer.set(key, colorName)
      }
    }
  }
  const counts = new Map<string, number>()
  for (const colorName of colorByPlayer.values()) {
    counts.set(colorName, (counts.get(colorName) || 0) + 1)
  }
  return Array.from(counts.entries())
    .map(([colorName, count]) => ({ colorName, count }))
    .sort((a, b) => b.count - a.count || a.colorName.localeCompare(b.colorName))
}

/** Overall packing from the imported towel list (unique rows). */
export function summarizeTowelCountsFromLookup(items: TemporaryPlayerLookupItem[]): TowelColorCount[] {
  const counts = new Map<string, number>()
  for (const item of items) {
    const colorName = (item.towel_color || '').trim()
    if (!colorName) continue
    counts.set(colorName, (counts.get(colorName) || 0) + 1)
  }
  return Array.from(counts.entries())
    .map(([colorName, count]) => ({ colorName, count }))
    .sort((a, b) => b.count - a.count || a.colorName.localeCompare(b.colorName))
}

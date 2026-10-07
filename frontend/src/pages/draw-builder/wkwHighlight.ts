/** Pairwise Who Knows Who highlight helpers for Draw Builder (frontend inspection only). */

export type AvoidEdgeLike = {
  team_id_a: number
  team_id_b: number
  reason?: string | null
}

export type WkwHighlightRole = 'selected' | 'connected'

export type WkwInspection = {
  eventId: number
  teamId: number
} | null

/** Matches backend `is_group_reason` — group letter edges are not pairwise WKW. */
export function isGroupAvoidReason(reason?: string | null): boolean {
  return Boolean(reason && String(reason).startsWith('group:'))
}

/** Build undirected pairwise neighbor IDs per team (excludes group: edges). */
export function buildPairwiseNeighborMap(edges: AvoidEdgeLike[]): Map<number, number[]> {
  const sets = new Map<number, Set<number>>()
  const add = (from: number, to: number) => {
    let bucket = sets.get(from)
    if (!bucket) {
      bucket = new Set<number>()
      sets.set(from, bucket)
    }
    bucket.add(to)
  }
  for (const edge of edges) {
    if (isGroupAvoidReason(edge.reason)) continue
    if (edge.team_id_a === edge.team_id_b) continue
    add(edge.team_id_a, edge.team_id_b)
    add(edge.team_id_b, edge.team_id_a)
  }
  const out = new Map<number, number[]>()
  for (const [teamId, neighbors] of sets) {
    out.set(teamId, [...neighbors].sort((a, b) => a - b))
  }
  return out
}

export function neighborIdsForTeam(
  neighborMap: Map<number, number[]> | undefined,
  teamId: number | null | undefined,
): number[] {
  if (teamId == null || !neighborMap) return []
  return neighborMap.get(teamId) ?? []
}

export function wkwHighlightRole(
  teamId: number | null | undefined,
  inspection: WkwInspection,
  eventId: number,
  neighborMap: Map<number, number[]> | undefined,
): WkwHighlightRole | null {
  if (teamId == null || inspection == null || inspection.eventId !== eventId) return null
  if (teamId === inspection.teamId) return 'selected'
  const neighbors = neighborIdsForTeam(neighborMap, inspection.teamId)
  if (neighbors.includes(teamId)) return 'connected'
  return null
}

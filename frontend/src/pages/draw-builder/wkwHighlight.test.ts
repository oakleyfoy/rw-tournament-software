import { describe, expect, it } from 'vitest'
import {
  buildPairwiseNeighborMap,
  isGroupAvoidReason,
  neighborIdsForTeam,
  wkwHighlightRole,
} from './wkwHighlight'

describe('wkwHighlight helpers', () => {
  it('treats group: reasons as non-pairwise', () => {
    expect(isGroupAvoidReason('group:A')).toBe(true)
    expect(isGroupAvoidReason('rw_os_wkw')).toBe(false)
    expect(isGroupAvoidReason(null)).toBe(false)
  })

  it('builds pairwise neighbor IDs and ignores group edges', () => {
    const map = buildPairwiseNeighborMap([
      { team_id_a: 1, team_id_b: 2, reason: 'rw_os_wkw' },
      { team_id_a: 1, team_id_b: 3, reason: 'rw_os_wkw' },
      { team_id_a: 2, team_id_b: 4, reason: 'group:B' },
    ])
    expect(neighborIdsForTeam(map, 1)).toEqual([2, 3])
    expect(neighborIdsForTeam(map, 2)).toEqual([1])
    expect(neighborIdsForTeam(map, 3)).toEqual([1])
    expect(neighborIdsForTeam(map, 4)).toEqual([])
  })

  it('does not treat A–B and A–C as implying B–C', () => {
    const map = buildPairwiseNeighborMap([
      { team_id_a: 10, team_id_b: 20, reason: 'rw_os_wkw' },
      { team_id_a: 10, team_id_b: 30, reason: 'rw_os_wkw' },
    ])
    const inspection = { eventId: 1, teamId: 20 }
    expect(wkwHighlightRole(20, inspection, 1, map)).toBe('selected')
    expect(wkwHighlightRole(10, inspection, 1, map)).toBe('connected')
    expect(wkwHighlightRole(30, inspection, 1, map)).toBeNull()
  })

  it('scopes highlights to the inspected event only', () => {
    const map = buildPairwiseNeighborMap([{ team_id_a: 1, team_id_b: 2, reason: 'rw_os_wkw' }])
    const inspection = { eventId: 19, teamId: 1 }
    expect(wkwHighlightRole(1, inspection, 19, map)).toBe('selected')
    expect(wkwHighlightRole(2, inspection, 19, map)).toBe('connected')
    expect(wkwHighlightRole(1, inspection, 20, map)).toBeNull()
    expect(wkwHighlightRole(2, inspection, 20, map)).toBeNull()
  })
})

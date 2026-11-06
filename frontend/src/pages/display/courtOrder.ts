import { DisplayMatch } from '../../api/client'

/** Court 2 before Court 10. Labels without a number sort after numbered courts. */
export function compareCourts(a: string | null | undefined, b: string | null | undefined): number {
  const aLabel = (a || '').trim().toLowerCase()
  const bLabel = (b || '').trim().toLowerCase()
  const aNumber = aLabel.match(/\d+/)
  const bNumber = bLabel.match(/\d+/)
  const aRank = aNumber ? 0 : 1
  const bRank = bNumber ? 0 : 1
  if (aRank !== bRank) return aRank - bRank
  if (aNumber && bNumber) {
    const delta = Number(aNumber[0]) - Number(bNumber[0])
    if (delta !== 0) return delta
  }
  return aLabel < bLabel ? -1 : aLabel > bLabel ? 1 : 0
}

export function sortMatchesByCourt(matches: DisplayMatch[]): DisplayMatch[] {
  return matches.slice().sort((a, b) => {
    const court = compareCourts(a.court, b.court)
    if (court !== 0) return court
    return a.match_id - b.match_id
  })
}

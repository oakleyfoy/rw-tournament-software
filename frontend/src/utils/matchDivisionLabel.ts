/** Compact / phrase division labels derived from match_code. */

const WIN_POOL_RE = /_WIN_(?:FRI|SAT1|SAT2)_([AB])\d+/i
const FUN_RE = /_FUN_(?:FRI|SAT1|SAT2)_\d+/i
const LOSS_RR_RE = /_LOSS_(?:FRI|SAT1|SAT2)_\d+/i
const WIN_SUN_RE = /_WIN_SUN_\d+/i
const LOSS_SUN_RE = /_LOSS_SUN_\d+/i

/**
 * Short badge text for desk check-in / court boards (e.g. "DIV I", "FUNMATCH").
 */
export function getCompactDivisionLabel(matchCode?: string | null): string {
  const code = (matchCode || '').toUpperCase()
  if (!code) return 'DIV'
  if (code.includes('_WF_')) return 'WF'

  if (FUN_RE.test(code)) return 'FUNMATCH'
  if (WIN_SUN_RE.test(code)) return 'PLACE'
  if (LOSS_SUN_RE.test(code)) return 'L PLACE'
  if (LOSS_RR_RE.test(code)) return 'DIV III'

  const winPool = code.match(WIN_POOL_RE)
  if (winPool) {
    return winPool[1] === 'A' ? 'DIV I' : 'DIV II'
  }

  if (code.includes('BWW') || code.includes('POOLA')) return 'DIV I'
  if (code.includes('BWL') || code.includes('POOLB')) return 'DIV II'
  if (code.includes('BLW') || code.includes('POOLC')) return 'DIV III'
  if (code.includes('BLL') || code.includes('POOLD')) return 'DIV IV'
  if (code.includes('POOLE')) return 'DIV V'

  // WF_14 consolation mini-pools: ..._CONS_FRI_C01 / _D02
  if (/_CONS_(?:FRI|SAT1|SAT2)_C\d+/i.test(code)) return 'DIV III'
  if (/_CONS_(?:FRI|SAT1|SAT2)_D\d+/i.test(code)) return 'DIV III'
  if (/_CONS_SUN_/i.test(code)) return 'PLACE'

  return 'DIV'
}

/**
 * Title-case phrase for ready-queue labels (e.g. "Div II", "Fun Match").
 */
export function getDivisionPhrase(matchCode?: string | null): string {
  const compact = getCompactDivisionLabel(matchCode)
  switch (compact) {
    case 'WF':
      return 'WF'
    case 'DIV I':
      return 'Div I'
    case 'DIV II':
      return 'Div II'
    case 'DIV III':
      return 'Div III'
    case 'DIV IV':
      return 'Div IV'
    case 'DIV V':
      return 'Div V'
    case 'FUNMATCH':
      return 'Fun Match'
    case 'PLACE':
      return 'Place'
    case 'L PLACE':
      return 'Loss Place'
    default:
      return ''
  }
}

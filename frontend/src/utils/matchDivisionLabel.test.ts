import { describe, expect, it } from 'vitest'
import { getCompactDivisionLabel, getDivisionPhrase } from './matchDivisionLabel'

describe('getCompactDivisionLabel', () => {
  it('maps classic pool and bracket codes', () => {
    expect(getCompactDivisionLabel('WOM_POOLA_RR_01')).toBe('DIV I')
    expect(getCompactDivisionLabel('WOM_POOLB_RR_01')).toBe('DIV II')
    expect(getCompactDivisionLabel('WOM_BWW_R1_01')).toBe('DIV I')
    expect(getCompactDivisionLabel('WOM_WF_R1_01')).toBe('WF')
  })

  it('maps WF_10 winners / fun / losers / sunday codes', () => {
    expect(getCompactDivisionLabel('MIX_WIN_FRI_A01')).toBe('DIV I')
    expect(getCompactDivisionLabel('MIX_WIN_SAT1_B02')).toBe('DIV II')
    expect(getCompactDivisionLabel('MIX_FUN_FRI_01')).toBe('FUNMATCH')
    expect(getCompactDivisionLabel('MIX_LOSS_FRI_01')).toBe('DIV III')
    expect(getCompactDivisionLabel('MIX_WIN_SUN_01')).toBe('PLACE')
    expect(getCompactDivisionLabel('MIX_LOSS_SUN_01')).toBe('L PLACE')
  })

  it('does not treat WIN_SUN as a winners mini-pool', () => {
    expect(getCompactDivisionLabel('MIX_WIN_SUN_01')).not.toBe('DIV I')
  })
})

describe('getDivisionPhrase', () => {
  it('title-cases compact labels for ready queue', () => {
    expect(getDivisionPhrase('MIX_WIN_FRI_B02')).toBe('Div II')
    expect(getDivisionPhrase('MIX_FUN_SAT2_01')).toBe('Fun Match')
    expect(getDivisionPhrase('MIX_LOSS_SAT1_02')).toBe('Div III')
  })
})

import { describe, expect, it } from 'vitest'
import { savedFinalWaterfall } from './finalWaterfallTemplate'

describe('savedFinalWaterfall', () => {
  it('keeps a finished waterfall after the roster count no longer matches', () => {
    expect(savedFinalWaterfall('final', 'WF_TO_BRACKETS_8', 2)).toEqual({
      templateType: 'WF_TO_BRACKETS_8',
      wfRounds: 2,
    })
  })

  it('does not keep a draft or a round-robin plan', () => {
    expect(savedFinalWaterfall('draft', 'WF_TO_BRACKETS_8', 2)).toBeNull()
    expect(savedFinalWaterfall('final', 'RR_ONLY', 0)).toBeNull()
    expect(savedFinalWaterfall('final', 'WF_TO_BRACKETS_8', 0)).toBeNull()
  })
})

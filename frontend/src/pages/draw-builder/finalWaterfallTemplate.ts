import type { TemplateType } from '../../utils/drawEstimation'

const WATERFALL_TEMPLATES = new Set<TemplateType>([
  'WF_TO_POOLS_4',
  'WF_TO_POOLS_DYNAMIC',
  'WF_TO_BRACKETS_8',
  'WF_14_TOP2_BYE',
  'WF_10_SIX_FOUR',
  'CANONICAL_32',
])

export function savedFinalWaterfall(
  drawStatus: string | null | undefined,
  template: string | null | undefined,
  wfRounds: number,
): { templateType: TemplateType; wfRounds: number } | null {
  if ((drawStatus || '') !== 'final') return null
  if (!template || !WATERFALL_TEMPLATES.has(template as TemplateType)) return null
  if (wfRounds <= 0) return null
  return { templateType: template as TemplateType, wfRounds }
}

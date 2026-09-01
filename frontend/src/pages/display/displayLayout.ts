/** Upcoming / 12-hour card floor. 130px yields ~13 columns at 1920. */
export const UPCOMING_CARD_MIN_PX = 130
/** Waiting stays only slightly wider than upcoming. */
export const WAITING_CARD_MIN_PX = 140
/** Currently Playing stays a bit larger so court stays readable. */
export const PLAYING_CARD_MIN_PX = 180
export const DISPLAY_GRID_GAP_PX = 6
export const DISPLAY_BODY_PAD_X_PX = 18

export function columnsAtViewport(
  viewportWidth: number,
  minCardPx: number,
  gapPx: number = DISPLAY_GRID_GAP_PX,
  padXPx: number = DISPLAY_BODY_PAD_X_PX,
): number {
  const available = Math.max(0, viewportWidth - padXPx * 2)
  return Math.max(1, Math.floor((available + gapPx) / (minCardPx + gapPx)))
}

export function upcomingColumnsAt(viewportWidth: number): number {
  return columnsAtViewport(viewportWidth, UPCOMING_CARD_MIN_PX)
}

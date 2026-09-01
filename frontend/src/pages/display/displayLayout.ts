/** Upcoming / 12-hour board card floor. 220px yields ~8 columns at 1920. */
export const UPCOMING_CARD_MIN_PX = 220
/** Waiting cards stay a bit wider than upcoming, still compact. */
export const WAITING_CARD_MIN_PX = 260
/** Currently Playing stays readable; court number needs room. */
export const PLAYING_CARD_MIN_PX = 340
export const DISPLAY_GRID_GAP_PX = 8
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

export const QR_BOARD_WIDTH_IN = 32
export const QR_BOARD_HEIGHT_IN = 24
export const QR_BOARD_POINTS_PER_INCH = 72
export const QR_BOARD_WIDTH_PT = QR_BOARD_WIDTH_IN * QR_BOARD_POINTS_PER_INCH
export const QR_BOARD_HEIGHT_PT = QR_BOARD_HEIGHT_IN * QR_BOARD_POINTS_PER_INCH
export const QR_BOARD_MARGIN_PT = 0.6 * QR_BOARD_POINTS_PER_INCH

export function qrBoardGrid(count: number): { cols: number; rows: number } {
  if (count <= 0) return { cols: 0, rows: 0 }
  if (count <= 4) return { cols: 2, rows: 2 }
  if (count <= 6) return { cols: 3, rows: 2 }
  if (count <= 8) return { cols: 4, rows: 2 }
  if (count === 9) return { cols: 3, rows: 3 }
  if (count <= 12) return { cols: 4, rows: 3 }
  if (count <= 16) return { cols: 4, rows: 4 }
  if (count <= 20) return { cols: 5, rows: 4 }
  const cols = 5
  return { cols, rows: Math.ceil(count / cols) }
}

export function drawQrFilename(slug: string | number): string {
  const safe = String(slug || 'tournament')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `draw-qr-board-${safe || 'tournament'}.pdf`
}

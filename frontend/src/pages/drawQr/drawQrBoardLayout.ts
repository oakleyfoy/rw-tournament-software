export const QR_BOARD_WIDTH_IN = 32
export const QR_BOARD_HEIGHT_IN = 24
export const QR_BOARD_POINTS_PER_INCH = 72
export const QR_BOARD_WIDTH_PT = QR_BOARD_WIDTH_IN * QR_BOARD_POINTS_PER_INCH
export const QR_BOARD_HEIGHT_PT = QR_BOARD_HEIGHT_IN * QR_BOARD_POINTS_PER_INCH
export const QR_BOARD_MARGIN_PT = 0.6 * QR_BOARD_POINTS_PER_INCH

export const QR_BOARD_LETTER_WIDTH_IN = 8.5
export const QR_BOARD_LETTER_HEIGHT_IN = 11
export const QR_BOARD_LETTER_WIDTH_PT = QR_BOARD_LETTER_WIDTH_IN * QR_BOARD_POINTS_PER_INCH
export const QR_BOARD_LETTER_HEIGHT_PT = QR_BOARD_LETTER_HEIGHT_IN * QR_BOARD_POINTS_PER_INCH
export const QR_BOARD_LETTER_MARGIN_PT = 0.45 * QR_BOARD_POINTS_PER_INCH

export type QrBoardFormat = 'poster' | 'letter'

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

export function drawQrSheetHeading(tournamentName: string): string {
  const name = tournamentName.trim()
  if (!name) return 'Draws'
  if (/draws$/i.test(name)) return name
  return `${name} Draws`
}

/** Letter sheets hold up to six codes. Extra draws continue on the next page. */
export function letterQrBoardGrid(count: number): { cols: number; rows: number; perPage: number } {
  if (count <= 1) return { cols: 1, rows: 1, perPage: 1 }
  if (count === 2) return { cols: 2, rows: 1, perPage: 2 }
  if (count <= 4) return { cols: 2, rows: 2, perPage: 4 }
  return { cols: 2, rows: 3, perPage: 6 }
}

export function drawQrFilename(slug: string | number, format: QrBoardFormat = 'poster'): string {
  const safe = String(slug || 'tournament')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const size = format === 'letter' ? '-letter' : ''
  return `draw-qr-board-${safe || 'tournament'}${size}.pdf`
}

import { describe, expect, it } from 'vitest'
import {
  QR_BOARD_HEIGHT_PT,
  QR_BOARD_WIDTH_PT,
  drawQrFilename,
  qrBoardGrid,
} from './drawQrBoardLayout'

describe('draw QR board layout', () => {
  it('uses a true 32×24 landscape page in points', () => {
    expect(QR_BOARD_WIDTH_PT).toBe(2304)
    expect(QR_BOARD_HEIGHT_PT).toBe(1728)
  })

  it('selects an auto-fill grid from the draw count', () => {
    expect(qrBoardGrid(1)).toEqual({ cols: 2, rows: 2 })
    expect(qrBoardGrid(4)).toEqual({ cols: 2, rows: 2 })
    expect(qrBoardGrid(5)).toEqual({ cols: 3, rows: 2 })
    expect(qrBoardGrid(8)).toEqual({ cols: 4, rows: 2 })
    expect(qrBoardGrid(9)).toEqual({ cols: 3, rows: 3 })
    expect(qrBoardGrid(12)).toEqual({ cols: 4, rows: 3 })
    expect(qrBoardGrid(16)).toEqual({ cols: 4, rows: 4 })
  })

  it('builds the requested filename from the tournament slug', () => {
    expect(drawQrFilename('destin-september-2026')).toBe('draw-qr-board-destin-september-2026.pdf')
    expect(drawQrFilename(42)).toBe('draw-qr-board-42.pdf')
  })
})

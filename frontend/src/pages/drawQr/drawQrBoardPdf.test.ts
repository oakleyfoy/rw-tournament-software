import { describe, expect, it } from 'vitest'
import { DrawQrBoardItem } from '../../api/client'
import { QR_BOARD_HEIGHT_PT, QR_BOARD_WIDTH_PT } from './drawQrBoardLayout'
import { buildDrawQrBoardPdf } from './drawQrBoardPdf'

function item(overrides: Partial<DrawQrBoardItem> = {}): DrawQrBoardItem {
  return {
    event_id: 1,
    event_name: "Women's A",
    label: "Women's A",
    draw_type: 'waterfall',
    draw_type_label: 'Waterfall',
    division_code: null,
    public_path: '/t/9/draws/1/waterfall',
    public_url: 'https://players.example.com/t/9/draws/1/waterfall',
    ...overrides,
  }
}

describe('draw QR board PDF', () => {
  it('builds a 2304×1728 landscape PDF from all returned items', async () => {
    const items = [
      item(),
      item({
        event_id: 2,
        event_name: "Women's B",
        label: "Women's B",
        draw_type: 'round_robin',
        draw_type_label: 'Round Robin',
        public_path: '/t/9/draws/2/roundrobin',
        public_url: 'https://players.example.com/t/9/draws/2/roundrobin',
      }),
      item({
        event_id: 3,
        event_name: 'Mixed A',
        label: 'Mixed A',
        draw_type: 'bracket',
        draw_type_label: 'Bracket',
        division_code: 'BWW',
        public_path: '/t/9/draws/3/bracket/BWW',
        public_url: 'https://players.example.com/t/9/draws/3/bracket/BWW',
      }),
    ]
    const pdf = await buildDrawQrBoardPdf(items, {
      tournamentName: 'Racquet War Destin',
      filenameSlug: 'destin-september-2026',
    })
    expect(pdf.width).toBe(QR_BOARD_WIDTH_PT)
    expect(pdf.height).toBe(QR_BOARD_HEIGHT_PT)
    expect(pdf.filename).toBe('draw-qr-board-destin-september-2026.pdf')
    expect(pdf.blob.size).toBeGreaterThan(1000)
    expect(pdf.blob.type).toContain('pdf')
  })
})

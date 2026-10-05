import { inflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'
import { DrawQrBoardItem } from '../../api/client'
import {
  QR_BOARD_HEIGHT_PT,
  QR_BOARD_LETTER_HEIGHT_PT,
  QR_BOARD_LETTER_WIDTH_PT,
  QR_BOARD_WIDTH_PT,
} from './drawQrBoardLayout'
import { buildDrawQrBoardPdf } from './drawQrBoardPdf'

function decodedPdfText(raw: string): string {
  const chunks: string[] = []
  for (const match of raw.matchAll(/stream\r?\n([\s\S]*?)endstream/g)) {
    const body = match[1].replace(/\r?\n$/, '')
    try {
      chunks.push(inflateSync(Buffer.from(body, 'latin1')).toString('latin1'))
    } catch {
      chunks.push(body)
    }
  }
  return chunks.join('\n')
}

function pdfText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsBinaryString(blob)
  })
}

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
    expect(pdf.pageCount).toBe(1)
    expect(pdf.blob.size).toBeGreaterThan(1000)
    expect(pdf.blob.type).toContain('pdf')
    const text = await pdfText(pdf.blob)
    expect(text).toContain('MediaBox [0 0 2304. 1728.]')
    expect(decodedPdfText(text)).toContain('Racquet War Destin Draws')
  })

  it('builds a portrait 8.5×11 PDF with the tournament heading on every sheet', async () => {
    const items = Array.from({ length: 7 }, (_, index) =>
      item({
        event_id: index + 1,
        event_name: `Event ${index + 1}`,
        label: `Event ${index + 1}`,
        public_path: `/t/9/draws/${index + 1}/waterfall`,
        public_url: `https://players.example.com/t/9/draws/${index + 1}/waterfall`,
      }),
    )
    const pdf = await buildDrawQrBoardPdf(items, {
      tournamentName: 'Scottsdale 2026',
      filenameSlug: 'scottsdale-2026',
      format: 'letter',
    })
    expect(pdf.width).toBe(QR_BOARD_LETTER_WIDTH_PT)
    expect(pdf.height).toBe(QR_BOARD_LETTER_HEIGHT_PT)
    expect(pdf.pageCount).toBe(2)
    expect(pdf.filename).toBe('draw-qr-board-scottsdale-2026-letter.pdf')
    const text = await pdfText(pdf.blob)
    expect(text.match(/MediaBox \[0 0 612\. 792\.\]/g)).toHaveLength(2)
    const decoded = decodedPdfText(text)
    expect(decoded.split('Scottsdale 2026 Draws').length - 1).toBe(2)
  })
})

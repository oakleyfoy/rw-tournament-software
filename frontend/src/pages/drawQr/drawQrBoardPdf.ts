import { jsPDF } from 'jspdf'
import QRCode from 'qrcode'
import { DrawQrBoardItem } from '../../api/client'
import {
  QR_BOARD_HEIGHT_PT,
  QR_BOARD_LETTER_HEIGHT_PT,
  QR_BOARD_LETTER_MARGIN_PT,
  QR_BOARD_LETTER_WIDTH_PT,
  QR_BOARD_MARGIN_PT,
  QR_BOARD_WIDTH_PT,
  QrBoardFormat,
  drawQrFilename,
  drawQrSheetHeading,
  letterQrBoardGrid,
  qrBoardGrid,
} from './drawQrBoardLayout'

export async function qrDataUrlForPublicUrl(publicUrl: string): Promise<string> {
  return QRCode.toDataURL(publicUrl, {
    errorCorrectionLevel: 'H',
    margin: 4,
    color: { dark: '#000000', light: '#FFFFFF' },
    width: 1024,
  })
}

function drawSheetHeading(
  doc: jsPDF,
  pageWidth: number,
  pageHeight: number,
  margin: number,
  heading: string,
  compact: boolean,
): number {
  doc.setFillColor(255, 255, 255)
  doc.rect(0, 0, pageWidth, pageHeight, 'F')
  doc.setTextColor(17, 32, 74)
  doc.setFont('helvetica', 'bold')
  if (compact) {
    doc.setFontSize(18)
    doc.text(heading, pageWidth / 2, margin + 18, { align: 'center', maxWidth: pageWidth - margin * 2 })
    doc.setFontSize(11)
    doc.text('Scan to view your draw', pageWidth / 2, margin + 36, { align: 'center' })
    return margin + 52
  }
  doc.setFontSize(42)
  doc.text(heading, pageWidth / 2, margin + 48, { align: 'center', maxWidth: pageWidth - margin * 2 })
  doc.setFontSize(22)
  doc.text('SCAN TO VIEW YOUR DRAW', pageWidth / 2, margin + 86, { align: 'center' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(16)
  doc.setTextColor(80, 90, 110)
  doc.text('Select your division below', pageWidth / 2, margin + 112, { align: 'center' })
  return margin + 132
}

function drawQrCell(
  doc: jsPDF,
  item: DrawQrBoardItem,
  qrUrl: string,
  x: number,
  y: number,
  cellWidth: number,
  cellHeight: number,
) {
  const pad = Math.min(16, cellWidth * 0.06)
  const labelBlock = Math.min(92, cellHeight * 0.28)
  const qrMax = Math.min(cellWidth - pad * 2, cellHeight - labelBlock - pad * 2)
  const qrSize = Math.max(qrMax, 0)

  doc.setDrawColor(210, 216, 228)
  doc.setLineWidth(1.5)
  doc.setFillColor(252, 253, 255)
  doc.roundedRect(x, y, cellWidth, cellHeight, 10, 10, 'FD')

  doc.setTextColor(17, 32, 74)
  doc.setFont('helvetica', 'bold')
  const nameSize = Math.min(28, Math.max(11, cellWidth / 9))
  doc.setFontSize(nameSize)
  doc.text((item.label || item.event_name).toUpperCase(), x + cellWidth / 2, y + pad + nameSize, {
    align: 'center',
    maxWidth: cellWidth - pad * 2,
  })
  doc.setFontSize(Math.min(16, nameSize * 0.62))
  doc.setTextColor(55, 65, 85)
  doc.text((item.draw_type_label || '').toUpperCase(), x + cellWidth / 2, y + pad + nameSize + nameSize * 0.85, {
    align: 'center',
    maxWidth: cellWidth - pad * 2,
  })

  if (qrSize > 0) {
    const qrX = x + (cellWidth - qrSize) / 2
    const qrY = y + labelBlock + (cellHeight - labelBlock - qrSize) / 2
    doc.addImage(qrUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  }
}

export async function buildDrawQrBoardPdf(
  items: DrawQrBoardItem[],
  options: { tournamentName: string; filenameSlug: string; format?: QrBoardFormat },
): Promise<{ blob: Blob; width: number; height: number; pageCount: number; filename: string }> {
  if (items.length === 0) {
    throw new Error('No published draws are currently available for this tournament.')
  }

  const format = options.format ?? 'poster'
  const letter = format === 'letter'
  const pageWidth = letter ? QR_BOARD_LETTER_WIDTH_PT : QR_BOARD_WIDTH_PT
  const pageHeight = letter ? QR_BOARD_LETTER_HEIGHT_PT : QR_BOARD_HEIGHT_PT
  const margin = letter ? QR_BOARD_LETTER_MARGIN_PT : QR_BOARD_MARGIN_PT
  const heading = drawQrSheetHeading(options.tournamentName)
  const posterGrid = qrBoardGrid(items.length)
  const letterGrid = letterQrBoardGrid(items.length)
  const cols = letter ? letterGrid.cols : posterGrid.cols
  const perPage = letter ? letterGrid.perPage : items.length

  const doc = new jsPDF({
    orientation: letter ? 'portrait' : 'landscape',
    unit: 'pt',
    format: [pageWidth, pageHeight],
    compress: true,
  })

  const qrUrls = await Promise.all(items.map((item) => qrDataUrlForPublicUrl(item.public_url)))
  const pageCount = Math.max(1, Math.ceil(items.length / perPage))

  for (let page = 0; page < pageCount; page += 1) {
    if (page > 0) doc.addPage([pageWidth, pageHeight], letter ? 'portrait' : 'landscape')
    const headerBottom = drawSheetHeading(doc, pageWidth, pageHeight, margin, heading, letter)
    const pageItems = items.slice(page * perPage, (page + 1) * perPage)
    const usedRows = Math.max(1, Math.ceil(pageItems.length / cols))
    const layoutRows = letter ? usedRows : posterGrid.rows
    const gridWidth = pageWidth - margin * 2
    const gridHeight = pageHeight - headerBottom - margin
    const gap = letter ? 12 : 18
    const cellWidth = (gridWidth - gap * (cols - 1)) / cols
    const cellHeight = (gridHeight - gap * (layoutRows - 1)) / layoutRows
    pageItems.forEach((item, index) => {
      const col = index % cols
      const row = Math.floor(index / cols)
      const x = margin + col * (cellWidth + gap)
      const y = headerBottom + row * (cellHeight + gap)
      drawQrCell(doc, item, qrUrls[page * perPage + index], x, y, cellWidth, cellHeight)
    })
  }

  const filename = drawQrFilename(options.filenameSlug, format)
  const bytes = doc.output('arraybuffer')
  return {
    blob: new Blob([bytes], { type: 'application/pdf' }),
    width: pageWidth,
    height: pageHeight,
    pageCount: doc.getNumberOfPages(),
    filename,
  }
}

import { jsPDF } from 'jspdf'
import QRCode from 'qrcode'
import { DrawQrBoardItem } from '../../api/client'
import {
  QR_BOARD_HEIGHT_PT,
  QR_BOARD_MARGIN_PT,
  QR_BOARD_WIDTH_PT,
  drawQrFilename,
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

export async function buildDrawQrBoardPdf(
  items: DrawQrBoardItem[],
  options: { tournamentName: string; filenameSlug: string },
): Promise<{ blob: Blob; width: number; height: number; filename: string }> {
  if (items.length === 0) {
    throw new Error('No published draws are currently available for this tournament.')
  }

  const doc = new jsPDF({
    orientation: 'landscape',
    unit: 'pt',
    format: [QR_BOARD_WIDTH_PT, QR_BOARD_HEIGHT_PT],
    compress: true,
  })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = QR_BOARD_MARGIN_PT
  const headerBottom = margin + 168
  const { cols, rows } = qrBoardGrid(items.length)
  const gridWidth = pageWidth - margin * 2
  const gridHeight = pageHeight - headerBottom - margin
  const gap = 18
  const cellWidth = (gridWidth - gap * (cols - 1)) / cols
  const cellHeight = (gridHeight - gap * (rows - 1)) / rows

  doc.setFillColor(255, 255, 255)
  doc.rect(0, 0, pageWidth, pageHeight, 'F')

  doc.setTextColor(17, 32, 74)
  doc.setFont('helvetica', 'bold')
  if (options.tournamentName) {
    doc.setFontSize(22)
    doc.text(options.tournamentName.toUpperCase(), pageWidth / 2, margin + 28, { align: 'center' })
  }
  doc.setFontSize(48)
  doc.text('TOURNAMENT DRAWS', pageWidth / 2, margin + 82, { align: 'center' })
  doc.setFontSize(26)
  doc.text('SCAN TO VIEW YOUR DRAW', pageWidth / 2, margin + 120, { align: 'center' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(16)
  doc.setTextColor(80, 90, 110)
  doc.text('Select your division below', pageWidth / 2, margin + 148, { align: 'center' })

  const qrUrls = await Promise.all(items.map((item) => qrDataUrlForPublicUrl(item.public_url)))

  items.forEach((item, index) => {
    const col = index % cols
    const row = Math.floor(index / cols)
    const x = margin + col * (cellWidth + gap)
    const y = headerBottom + row * (cellHeight + gap)
    const pad = 16
    const labelBlock = Math.min(92, cellHeight * 0.28)
    const qrMax = Math.min(cellWidth - pad * 2, cellHeight - labelBlock - pad * 2)
    const qrSize = Math.max(qrMax, 0)

    doc.setDrawColor(210, 216, 228)
    doc.setLineWidth(1.5)
    doc.setFillColor(252, 253, 255)
    doc.roundedRect(x, y, cellWidth, cellHeight, 10, 10, 'FD')

    doc.setTextColor(17, 32, 74)
    doc.setFont('helvetica', 'bold')
    const nameSize = Math.min(28, cellWidth / 9)
    doc.setFontSize(nameSize)
    doc.text((item.label || item.event_name).toUpperCase(), x + cellWidth / 2, y + pad + nameSize, {
      align: 'center',
      maxWidth: cellWidth - pad * 2,
    })
    doc.setFontSize(Math.min(16, nameSize * 0.62))
    doc.setTextColor(55, 65, 85)
    doc.text((item.draw_type_label || '').toUpperCase(), x + cellWidth / 2, y + pad + nameSize + 22, {
      align: 'center',
      maxWidth: cellWidth - pad * 2,
    })

    if (qrSize > 0) {
      const qrX = x + (cellWidth - qrSize) / 2
      const qrY = y + labelBlock + (cellHeight - labelBlock - qrSize) / 2
      doc.addImage(qrUrls[index], 'PNG', qrX, qrY, qrSize, qrSize)
    }
  })

  const filename = drawQrFilename(options.filenameSlug)
  return {
    blob: doc.output('blob'),
    width: pageWidth,
    height: pageHeight,
    filename,
  }
}

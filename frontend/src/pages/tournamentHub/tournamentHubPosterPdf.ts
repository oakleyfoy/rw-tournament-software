import { jsPDF } from 'jspdf'
import { qrDataUrlForPublicUrl } from '../drawQr/drawQrBoardPdf'

const LETTER_WIDTH_PT = 8.5 * 72
const LETTER_HEIGHT_PT = 11 * 72
const MARGIN_PT = 0.5 * 72

export function tournamentHubPosterFilename(slug: string | number): string {
  const safe = String(slug || 'tournament')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `tournament-hub-qr-${safe || 'tournament'}.pdf`
}

export async function buildTournamentHubPosterPdf(options: {
  tournamentName: string
  publicUrl: string
  filenameSlug: string
}): Promise<{ blob: Blob; filename: string }> {
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'pt',
    format: [LETTER_WIDTH_PT, LETTER_HEIGHT_PT],
    compress: true,
  })

  const pageWidth = LETTER_WIDTH_PT
  const pageHeight = LETTER_HEIGHT_PT
  const centerX = pageWidth / 2

  doc.setFillColor(255, 255, 255)
  doc.rect(0, 0, pageWidth, pageHeight, 'F')

  doc.setTextColor(18, 32, 90)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(28)
  doc.text('RACQUET WAR', centerX, MARGIN_PT + 36, { align: 'center' })

  doc.setFontSize(18)
  doc.setTextColor(40, 50, 70)
  doc.text(options.tournamentName || 'Tournament', centerX, MARGIN_PT + 68, {
    align: 'center',
    maxWidth: pageWidth - MARGIN_PT * 2,
  })

  doc.setFontSize(26)
  doc.setTextColor(18, 32, 90)
  doc.text('FIND YOUR DRAW', centerX, MARGIN_PT + 118, { align: 'center' })

  const qrUrl = await qrDataUrlForPublicUrl(options.publicUrl)
  const qrSize = Math.min(340, pageWidth - MARGIN_PT * 2)
  const qrX = (pageWidth - qrSize) / 2
  const qrY = MARGIN_PT + 140
  doc.addImage(qrUrl, 'PNG', qrX, qrY, qrSize, qrSize)

  const belowQr = qrY + qrSize + 28
  doc.setFontSize(14)
  doc.setTextColor(18, 32, 90)
  doc.text('SCAN  •  SEARCH YOUR NAME  •  FIND YOUR TEAM', centerX, belowQr, {
    align: 'center',
    maxWidth: pageWidth - MARGIN_PT * 2,
  })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(12)
  doc.setTextColor(70, 80, 100)
  doc.text(
    'View your live draw, upcoming matches, court assignments, and results.',
    centerX,
    belowQr + 24,
    { align: 'center', maxWidth: pageWidth - MARGIN_PT * 2 },
  )

  doc.setFontSize(9)
  doc.setTextColor(90, 100, 120)
  doc.text(options.publicUrl, centerX, pageHeight - MARGIN_PT - 8, {
    align: 'center',
    maxWidth: pageWidth - MARGIN_PT * 2,
  })

  const filename = tournamentHubPosterFilename(options.filenameSlug)
  const bytes = doc.output('arraybuffer')
  return {
    blob: new Blob([bytes], { type: 'application/pdf' }),
    filename,
  }
}

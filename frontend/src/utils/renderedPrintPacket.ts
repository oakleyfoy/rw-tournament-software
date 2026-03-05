import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import { getPublicDrawsList, PublicEventItem } from '../api/client'

type PacketCategory = 'womens' | 'mixed'

interface CaptureJob {
  label: string
  routePath: string
  rootSelector: string
}

function buildJobsForCategory(
  tournamentId: number,
  category: PacketCategory,
  events: PublicEventItem[]
): CaptureJob[] {
  const jobs: CaptureJob[] = []
  const categoryEvents = events.filter(ev => (ev.category || '').toLowerCase() === category)

  for (const ev of categoryEvents) {
    const basePath = `/t/${tournamentId}/draws/${ev.event_id}`
    const hasRR = !!ev.has_round_robin
    const hasWF = !!ev.has_waterfall

    if (hasWF) {
      jobs.push({
        label: `${ev.name} Waterfall`,
        routePath: `${basePath}/waterfall`,
        rootSelector: '.print-root',
      })
    }

    if (hasRR) {
      jobs.push({
        label: `${ev.name} Round Robin`,
        routePath: `${basePath}/roundrobin`,
        rootSelector: '.rr-print-root',
      })
      continue
    }

    const divisions = ev.divisions || []
    for (const div of divisions) {
      if (!div?.code) continue
      jobs.push({
        label: `${ev.name} ${div.label || div.code} Bracket`,
        routePath: `${basePath}/bracket/${encodeURIComponent(div.code)}`,
        rootSelector: '.bracket-print-root',
      })
    }
  }

  return jobs
}

async function waitForRenderableRoot(
  doc: Document,
  rootSelector: string,
  timeoutMs = 30000
): Promise<HTMLElement> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const root = doc.querySelector(rootSelector) as HTMLElement | null
    if (root) {
      const text = (root.textContent || '').toLowerCase()
      const stillLoading =
        text.includes('loading waterfall') ||
        text.includes('loading round robin') ||
        text.includes('loading bracket') ||
        text.includes('loading...')
      if (!stillLoading) return root
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error(`Timed out waiting for ${rootSelector}`)
}

async function captureRouteAsCanvas(job: CaptureJob): Promise<HTMLCanvasElement> {
  const iframe = document.createElement('iframe')
  const suffix = job.routePath.includes('?') ? '&capture_packet=1' : '?capture_packet=1'
  iframe.src = `${window.location.origin}${job.routePath}${suffix}`
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.position = 'fixed'
  iframe.style.left = '-100000px'
  iframe.style.top = '0'
  iframe.style.width = '2400px'
  iframe.style.height = '1800px'
  iframe.style.border = '0'
  iframe.style.opacity = '0'
  document.body.appendChild(iframe)

  try {
    await new Promise<void>((resolve, reject) => {
      const onLoad = () => {
        iframe.removeEventListener('load', onLoad)
        resolve()
      }
      const onError = () => {
        iframe.removeEventListener('error', onError)
        reject(new Error(`Failed to load ${job.routePath}`))
      }
      iframe.addEventListener('load', onLoad)
      iframe.addEventListener('error', onError)
    })

    const doc = iframe.contentDocument
    if (!doc) throw new Error(`No document for ${job.routePath}`)

    const root = await waitForRenderableRoot(doc, job.rootSelector)
    const width = Math.max(root.scrollWidth, root.clientWidth, 1200)
    const height = Math.max(root.scrollHeight, root.clientHeight, 900)

    return await html2canvas(root, {
      backgroundColor: '#ffffff',
      scale: 2,
      useCORS: true,
      logging: false,
      width,
      height,
      windowWidth: width,
      windowHeight: height,
      scrollX: 0,
      scrollY: 0,
    })
  } finally {
    iframe.remove()
  }
}

export async function buildRenderedPrintPacketPdf(
  tournamentId: number,
  category: PacketCategory
): Promise<Blob> {
  const draws = await getPublicDrawsList(tournamentId) as any
  if (draws?.status === 'NOT_PUBLISHED') {
    throw new Error('Schedule is not published yet for this tournament.')
  }

  const jobs = buildJobsForCategory(tournamentId, category, draws?.events || [])
  if (jobs.length === 0) {
    throw new Error(`No ${category} draw pages found to export.`)
  }

  const PAGE_W = 32 * 72
  const PAGE_H = 24 * 72
  const MARGIN = 22
  const PANEL_GAP = 14
  const PAGE_HEADER_H = 18
  const PANEL_TITLE_H = 14
  const PANELS_PER_PAGE = 2
  const pdf = new jsPDF({
    orientation: 'landscape',
    unit: 'pt',
    format: [PAGE_W, PAGE_H],
    compress: true,
  })

  for (let start = 0; start < jobs.length; start += PANELS_PER_PAGE) {
    if (start > 0) pdf.addPage([PAGE_W, PAGE_H], 'landscape')

    const pageJobs = jobs.slice(start, start + PANELS_PER_PAGE)

    const title = `${category === 'womens' ? "Women's" : 'Mixed'} Draw Packet`
    pdf.setTextColor(30, 30, 30)
    pdf.setFontSize(12)
    pdf.text(title, MARGIN, MARGIN + 11)

    const slots = pageJobs.length
    const contentTop = MARGIN + PAGE_HEADER_H
    const contentBottom = PAGE_H - MARGIN
    const panelH = contentBottom - contentTop
    const panelW =
      slots > 1
        ? (PAGE_W - MARGIN * 2 - PANEL_GAP * (slots - 1)) / slots
        : PAGE_W - MARGIN * 2

    for (let i = 0; i < pageJobs.length; i++) {
      const job = pageJobs[i]
      const panelX = MARGIN + i * (panelW + PANEL_GAP)
      const panelY = contentTop

      pdf.setDrawColor(170, 170, 170)
      pdf.setLineWidth(0.8)
      pdf.rect(panelX, panelY, panelW, panelH)

      pdf.setTextColor(55, 55, 55)
      pdf.setFontSize(10)
      pdf.text(job.label, panelX + 6, panelY + 10)

      const canvas = await captureRouteAsCanvas(job)
      const imageData = canvas.toDataURL('image/png')

      const availW = panelW - 10
      const availH = panelH - PANEL_TITLE_H - 8
      const ratio = Math.min(availW / canvas.width, availH / canvas.height)
      const drawW = canvas.width * ratio
      const drawH = canvas.height * ratio
      const x = panelX + (panelW - drawW) / 2
      const y = panelY + PANEL_TITLE_H + (availH - drawH) / 2

      pdf.addImage(imageData, 'PNG', x, y, drawW, drawH, undefined, 'FAST')
    }
  }

  return pdf.output('blob')
}


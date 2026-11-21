import { cropCutsPhoto, logoPixelWidth, slugPart, watermarkBox, wordingFontSize, wordingPixelWidth, type WatermarkSettings } from './photoPrintSettings'

export const WALGREENS_PRINT_WIDTH = 1200
export const WALGREENS_PRINT_HEIGHT = 1800
/** The on-screen 4×6 frame at 100% zoom. Gaps and shadows are scaled from it. */
const PREVIEW_FRAME = 384

export interface WalgreensPhoto {
  photo_kind?: 'team' | 'group' | string | null
  team_id?: number | null
  group_photo_id?: number | null
  file_url?: string | null
  settings: WatermarkSettings
}

export function printNeedsUpscale(width: number, height: number): boolean {
  if (width <= 0 || height <= 0) return true
  return Math.max(WALGREENS_PRINT_WIDTH / width, WALGREENS_PRINT_HEIGHT / height) > 1.001
}

export function walgreensFileName(photo: Pick<WalgreensPhoto, 'photo_kind' | 'team_id' | 'group_photo_id'>): string {
  if (photo.photo_kind === 'group' && photo.group_photo_id) return `group-${photo.group_photo_id}.jpg`
  return `team-${photo.team_id ?? 'photo'}.jpg`
}

export function walgreensZipName(tournamentName: string): string {
  return `${slugPart(tournamentName) || 'team-photos'}-prints.zip`
}

export function zipStored(files: { name: string; data: Uint8Array }[]): Uint8Array {
  const locals: Uint8Array[] = []
  const centrals: Uint8Array[] = []
  let offset = 0
  for (const file of files) {
    const name = new TextEncoder().encode(file.name)
    const crc = crc32(file.data)
    const local = new Uint8Array(30 + name.length)
    const view = new DataView(local.buffer)
    view.setUint32(0, 0x04034b50, true)
    view.setUint16(4, 20, true)
    view.setUint32(14, crc, true)
    view.setUint32(18, file.data.length, true)
    view.setUint32(22, file.data.length, true)
    view.setUint16(26, name.length, true)
    local.set(name, 30)
    locals.push(local, file.data)

    const central = new Uint8Array(46 + name.length)
    const centralView = new DataView(central.buffer)
    centralView.setUint32(0, 0x02014b50, true)
    centralView.setUint16(4, 20, true)
    centralView.setUint16(6, 20, true)
    centralView.setUint32(16, crc, true)
    centralView.setUint32(20, file.data.length, true)
    centralView.setUint32(24, file.data.length, true)
    centralView.setUint16(28, name.length, true)
    centralView.setUint32(42, offset, true)
    central.set(name, 46)
    centrals.push(central)
    offset += local.length + file.data.length
  }
  const centralBytes = concat(centrals)
  const end = new Uint8Array(22)
  const endView = new DataView(end.buffer)
  endView.setUint32(0, 0x06054b50, true)
  endView.setUint16(8, files.length, true)
  endView.setUint16(10, files.length, true)
  endView.setUint32(12, centralBytes.length, true)
  endView.setUint32(16, offset, true)
  return concat([...locals, centralBytes, end])
}

function watermarkText(settings: WatermarkSettings): string {
  if (settings.content_mode === 'custom_text') return settings.custom_text
  if (settings.content_mode === 'logo_only') return ''
  return settings.event_text || ''
}

function showLogo(settings: WatermarkSettings): boolean {
  return ['logo_and_text', 'logo_only', 'custom_logo'].includes(settings.content_mode)
}

export function loadHtmlImage(url: string, crossOrigin: boolean): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    if (crossOrigin) image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('Photograph could not be loaded from storage'))
    image.src = url
  })
}

let brandLogo: Promise<HTMLImageElement> | null = null

function loadBrandLogo(): Promise<HTMLImageElement> {
  if (!brandLogo) brandLogo = loadHtmlImage('/assets/rw-watermark-logo.png', false)
  return brandLogo
}

function coloredLogo(logo: HTMLImageElement, color: string, width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(width))
  canvas.height = Math.max(1, Math.round(height))
  const context = canvas.getContext('2d')
  if (!context) return canvas
  context.drawImage(logo, 0, 0, canvas.width, canvas.height)
  context.globalCompositeOperation = 'source-in'
  context.fillStyle = color
  context.fillRect(0, 0, canvas.width, canvas.height)
  return canvas
}

export async function renderWalgreensPhoto(
  image: HTMLImageElement,
  settings: WatermarkSettings,
  logos: { brand: HTMLImageElement; custom: HTMLImageElement | null },
): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = WALGREENS_PRINT_WIDTH
  canvas.height = WALGREENS_PRINT_HEIGHT
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Print file could not be created')
  const sourceWidth = image.naturalWidth || image.width
  const sourceHeight = image.naturalHeight || image.height
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, WALGREENS_PRINT_WIDTH, WALGREENS_PRINT_HEIGHT)
  const scale = Math.max(WALGREENS_PRINT_WIDTH / sourceWidth, WALGREENS_PRINT_HEIGHT / sourceHeight)
  const drawnWidth = sourceWidth * scale
  const drawnHeight = sourceHeight * scale
  const extraX = Math.max(0, drawnWidth - WALGREENS_PRINT_WIDTH)
  const extraY = Math.max(0, drawnHeight - WALGREENS_PRINT_HEIGHT)
  const left = Math.max(0, Math.min(extraX, Math.round(extraX * settings.crop_x)))
  const top = Math.max(0, Math.min(extraY, Math.round(extraY * settings.crop_y)))
  context.drawImage(image, -left, -top, drawnWidth, drawnHeight)
  if (settings.visible) drawWatermark(context, settings, logos)
  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob((value) => resolve(value), 'image/jpeg', 0.95)
  })
  if (!blob) throw new Error('Print file could not be created')
  return blob
}

function drawWatermark(
  context: CanvasRenderingContext2D,
  settings: WatermarkSettings,
  logos: { brand: HTMLImageElement; custom: HTMLImageElement | null },
) {
  const text = watermarkText(settings)
  const logoOn = showLogo(settings)
  const logoWidth = logoOn ? logoPixelWidth(WALGREENS_PRINT_WIDTH, settings.logo_scale) : 0
  const custom = settings.content_mode === 'custom_logo' ? logos.custom : null
  const logoHeight = !logoOn
    ? 0
    : custom && custom.naturalWidth
      ? logoWidth * (custom.naturalHeight / custom.naturalWidth)
      : logoWidth * (547 / 1011)
  const textWidth = text ? wordingPixelWidth(WALGREENS_PRINT_WIDTH, settings.size_percent) : 0
  const weight = settings.font_style === 'bold' ? 700 : settings.font_style === 'medium' ? 500 : 400
  const fontStyle = settings.font_style === 'italic' ? 'italic' : 'normal'
  const family = settings.font_family.includes(' ') ? `"${settings.font_family}"` : settings.font_family
  const fontSize = text
    ? wordingFontSize(text, textWidth, `${fontStyle} ${weight} 100px ${family}`)
    : 0
  const textHeight = text ? fontSize * 1.05 : 0
  const gap = logoOn && text ? (settings.spacing / 2) * (WALGREENS_PRINT_WIDTH / PREVIEW_FRAME) : 0
  const box = watermarkBox(WALGREENS_PRINT_WIDTH, WALGREENS_PRINT_HEIGHT, settings, {
    width: Math.max(logoWidth, textWidth, 24),
    height: Math.max(logoHeight + gap + textHeight, 24),
  })
  context.save()
  context.globalAlpha = settings.opacity / 100
  if (logoOn) {
    const mark = custom
      ? custom
      : coloredLogo(logos.brand, settings.color, logoWidth, logoHeight)
    context.drawImage(mark, box.x + (box.width - logoWidth) / 2, box.y, logoWidth, logoHeight)
  }
  if (text) {
    const shadow = 2 * (WALGREENS_PRINT_WIDTH / PREVIEW_FRAME)
    context.font = `${fontStyle} ${weight} ${fontSize}px ${family}`
    context.textAlign = 'center'
    context.textBaseline = 'top'
    context.fillStyle = settings.color
    if (settings.shadow) {
      context.shadowColor = 'rgba(0, 0, 0, 0.65)'
      context.shadowOffsetX = shadow
      context.shadowOffsetY = shadow
      context.shadowBlur = shadow
    }
    context.fillText(text, box.x + box.width / 2, box.y + logoHeight + gap)
  }
  context.restore()
}

export async function buildWalgreensZip(input: {
  tournamentName: string
  photos: WalgreensPhoto[]
  customLogo?: HTMLImageElement | null
  acknowledgeLowResolution: boolean
  onProgress?: (done: number, total: number) => void
}): Promise<{ blob: Blob; filename: string }> {
  if (!input.photos.length) throw new Error('Select at least one photograph')
  if (input.photos.some((photo) => !photo.file_url)) {
    throw new Error('Photographs could not be opened from storage. Open Watermark & Print again and retry.')
  }
  if (typeof document !== 'undefined' && document.fonts?.ready) await document.fonts.ready
  const brand = await loadBrandLogo()
  const files: { name: string; data: Uint8Array }[] = []
  const used = new Set<string>()
  for (let index = 0; index < input.photos.length; index += 1) {
    const photo = input.photos[index]
    input.onProgress?.(index + 1, input.photos.length)
    const image = await loadHtmlImage(photo.file_url || '', true)
    const width = image.naturalWidth || image.width
    const height = image.naturalHeight || image.height
    if (!input.acknowledgeLowResolution && printNeedsUpscale(width, height)) {
      throw new Error(
        `A photograph is ${width}×${height}, below 1200×1800 for a 300 DPI 4×6 portrait. Confirm the resolution warning before creating the print file.`,
      )
    }
    let name = walgreensFileName(photo)
    if (used.has(name)) name = `${index + 1}-${name}`
    used.add(name)
    try {
      const blob = await renderWalgreensPhoto(image, photo.settings, { brand, custom: input.customLogo || null })
      files.push({ name, data: new Uint8Array(await blob.arrayBuffer()) })
    } catch {
      throw new Error('Photograph could not be read from storage on this computer.')
    }
  }
  const zipped = zipStored(files)
  const copy = new ArrayBuffer(zipped.byteLength)
  new Uint8Array(copy).set(zipped)
  return { blob: new Blob([copy], { type: 'application/zip' }), filename: walgreensZipName(input.tournamentName) }
}

export function photoPrintSize(width: number, height: number) {
  return {
    lowResolution: printNeedsUpscale(width, height),
    cropWarning: cropCutsPhoto(width, height, 'fill'),
  }
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let value = 0; value < 256; value += 1) {
    let crc = value
    for (let bit = 0; bit < 8; bit += 1) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1
    table[value] = crc >>> 0
  }
  return table
})()

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff
  for (let index = 0; index < data.length; index += 1) {
    crc = CRC_TABLE[(crc ^ data[index]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}

function concat(parts: Uint8Array[]): Uint8Array {
  const size = parts.reduce((sum, part) => sum + part.length, 0)
  const out = new Uint8Array(size)
  let offset = 0
  for (const part of parts) {
    out.set(part, offset)
    offset += part.length
  }
  return out
}

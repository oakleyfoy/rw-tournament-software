export const PRINT_SIZE = '4x6'
export const PRINT_WIDTH = 1200
export const PRINT_HEIGHT = 1800
export const PRINT_SIZES = [PRINT_SIZE] as const
export type PrintSize = (typeof PRINT_SIZES)[number]

export const FONT_FAMILIES = [
  'Arial',
  'Montserrat',
  'Poppins',
  'Roboto',
  'Georgia',
  'Times New Roman',
  'Lato',
  'Oswald',
  'Nunito',
  'Raleway',
  'Josefin Sans',
  'Barlow Condensed',
  'Playfair Display',
  'Lora',
  'Libre Baskerville',
  'Cinzel',
] as const
export const FONT_STYLES = ['normal', 'medium', 'bold', 'italic'] as const
export const CONTENT_MODES = [
  { id: 'logo_and_text', label: 'RW logo and event name' },
  { id: 'logo_only', label: 'RW logo only' },
  { id: 'text_only', label: 'Text only' },
  { id: 'custom_logo', label: 'Custom logo upload' },
  { id: 'custom_text', label: 'Custom text' },
] as const

export const POSITIONS = [
  'top-left',
  'top-center',
  'top-right',
  'middle-left',
  'center',
  'middle-right',
  'bottom-left',
  'bottom-center',
  'bottom-right',
] as const

export const POSITION_LABELS: Record<(typeof POSITIONS)[number], string> = {
  'top-left': 'Top left',
  'top-center': 'Top center',
  'top-right': 'Top right',
  'middle-left': 'Middle left',
  center: 'Center',
  'middle-right': 'Middle right',
  'bottom-left': 'Bottom left',
  'bottom-center': 'Bottom center',
  'bottom-right': 'Bottom right',
}

export const NAMED_COLORS = [
  { id: 'white', value: '#ffffff', label: 'White' },
  { id: 'black', value: '#111111', label: 'Black' },
  { id: 'gray', value: '#9e9e9e', label: 'Gray' },
  { id: 'red', value: '#c62828', label: 'Red' },
  { id: 'blue', value: '#1565c0', label: 'Blue' },
  { id: 'yellow', value: '#f9a825', label: 'Yellow' },
]

const ANCHORS: Record<string, [number, number]> = {
  'top-left': [0, 0],
  'top-center': [0.5, 0],
  'top-right': [1, 0],
  'middle-left': [0, 0.5],
  center: [0.5, 0.5],
  'middle-right': [1, 0.5],
  'bottom-left': [0, 1],
  'bottom-center': [0.5, 1],
  'bottom-right': [1, 1],
}

export interface WatermarkSettings {
  content_mode: string
  event_text: string
  custom_text: string
  font_family: string
  font_style: string
  color: string
  size_percent: number
  logo_scale: number
  spacing: number
  opacity: number
  position: string
  offset_x: number
  offset_y: number
  shadow: boolean
  visible: boolean
  crop_mode: 'fit' | 'fill'
  crop_x: number
  crop_y: number
  show_margins: boolean
}

export function defaultWatermarkSettings(tournamentName: string): WatermarkSettings {
  return {
    content_mode: 'logo_and_text',
    event_text: tournamentName.trim() || 'Tournament',
    custom_text: '',
    font_family: 'Arial',
    font_style: 'bold',
    color: '#ffffff',
    size_percent: 28,
    logo_scale: 1,
    spacing: 8,
    opacity: 90,
    position: 'top-center',
    offset_x: 0,
    offset_y: 0,
    shadow: true,
    visible: true,
    crop_mode: 'fill',
    crop_x: 0.5,
    crop_y: 0.5,
    show_margins: false,
  }
}

function clamp(value: number, low: number, high: number) {
  return Math.max(low, Math.min(high, value))
}

export function slugPart(value: string): string {
  return value.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

export function printFilename(tournamentName: string, playerNames: string[], printSize: string): string {
  const names = playerNames
    .filter((name) => name && name.trim() && name.trim() !== 'Partner not on file')
    .map(slugPart)
    .filter(Boolean)
  const parts = [slugPart(tournamentName), ...names, printSize].filter(Boolean)
  return `${parts.join('-') || `team-photo-${printSize}`}.jpg`
}

export function cropCutsPhoto(width: number, height: number, cropMode: string): boolean {
  if (cropMode !== 'fill' || width <= 0 || height <= 0) return false
  return Math.abs(width / height - PRINT_WIDTH / PRINT_HEIGHT) > 0.015
}

/** Logo width at 100% scale, as a fraction of the photo width. Independent of wording size. */
export const LOGO_WIDTH_FRACTION = 0.28 * 0.78

export function logoPixelWidth(frameWidth: number, logoScale: number): number {
  return Math.max(18, frameWidth * LOGO_WIDTH_FRACTION * logoScale)
}

export function wordingPixelWidth(frameWidth: number, sizePercent: number): number {
  return Math.max(24, frameWidth * (sizePercent / 100))
}

/** Font size that makes `text` about `targetWidth` pixels wide. */
export function wordingFontSize(text: string, targetWidth: number, font: string): number {
  const sample = text.trim()
  if (!sample || targetWidth <= 0) return 16
  const fallback = Math.max(12, targetWidth / (sample.length * 0.58))
  if (typeof document === 'undefined') return fallback
  let context: CanvasRenderingContext2D | null = null
  try {
    context = document.createElement('canvas').getContext('2d')
  } catch {
    context = null
  }
  if (!context || typeof context.measureText !== 'function') return fallback
  context.font = font
  const measured = context.measureText(sample).width
  if (!measured) return fallback
  const probe = Number(/(\d+(?:\.\d+)?)px/.exec(font)?.[1] || 100)
  return Math.max(12, (targetWidth * probe) / measured)
}

export function watermarkBox(
  frameWidth: number,
  frameHeight: number,
  settings: Pick<WatermarkSettings, 'size_percent' | 'position' | 'offset_x' | 'offset_y'>,
  content?: { width: number; height: number },
) {
  const margin = Math.min(frameWidth, frameHeight) * 0.04
  const markWidth = content?.width ?? frameWidth * (settings.size_percent / 100)
  const markHeight = content?.height ?? markWidth * 0.46
  const [anchorX, anchorY] = ANCHORS[settings.position] || ANCHORS['top-center']
  const rawX = margin + anchorX * (frameWidth - margin * 2 - markWidth) + settings.offset_x * frameWidth
  const rawY = margin + anchorY * (frameHeight - margin * 2 - markHeight) + settings.offset_y * frameHeight
  return {
    x: clamp(rawX, margin, Math.max(margin, frameWidth - margin - markWidth)),
    y: clamp(rawY, margin, Math.max(margin, frameHeight - margin - markHeight)),
    width: markWidth,
    height: markHeight,
    margin,
  }
}

const SERIF_FAMILIES = new Set(['Georgia', 'Times New Roman', 'Playfair Display', 'Lora', 'Libre Baskerville', 'Cinzel'])

export function fontCss(settings: Pick<WatermarkSettings, 'font_family' | 'font_style'>): string {
  const quoted = settings.font_family.includes(' ') ? `"${settings.font_family}"` : settings.font_family
  const family = SERIF_FAMILIES.has(settings.font_family) ? `${quoted}, serif` : `${quoted}, sans-serif`
  const italic = settings.font_style === 'italic' ? 'italic' : 'normal'
  const weight = settings.font_style === 'bold' ? 700 : settings.font_style === 'medium' ? 500 : 400
  return `font-family:${family};font-style:${italic};font-weight:${weight};`
}

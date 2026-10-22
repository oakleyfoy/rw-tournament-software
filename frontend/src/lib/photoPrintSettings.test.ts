import { describe, expect, it } from 'vitest'
import { cropCutsPhoto, logoPixelWidth, printFilename, watermarkBox, wordingFontSize, wordingPixelWidth } from './photoPrintSettings'

describe('print filenames and watermark placement', () => {
  it('names a print from the tournament and both players', () => {
    expect(printFilename('Scottsdale 2026', ['Haley', 'Stacey'], '4x6')).toBe('Scottsdale-2026-Haley-Stacey-4x6.jpg')
  })

  it('keeps a top-center watermark inside the safe margin', () => {
    const box = watermarkBox(600, 800, { size_percent: 28, position: 'top-center', offset_x: 0, offset_y: 0 })
    expect(box.x).toBeGreaterThanOrEqual(box.margin)
    expect(box.y).toBeGreaterThanOrEqual(box.margin)
    expect(box.x + box.width).toBeLessThanOrEqual(600 - box.margin + 0.1)
  })

  it('sizes the logo and the wording independently', () => {
    expect(logoPixelWidth(1000, 1)).toBeCloseTo(1000 * 0.28 * 0.78)
    expect(logoPixelWidth(1000, 2)).toBeCloseTo(logoPixelWidth(1000, 1) * 2)
    expect(wordingPixelWidth(1000, 80)).toBe(800)
    const small = wordingFontSize('2026 Wild Dunes', 200, '700 100px Arial')
    const large = wordingFontSize('2026 Wild Dunes', 600, '700 100px Arial')
    expect(large).toBeGreaterThan(small * 2)
  })

  it('warns when a fill crop would remove part of a landscape photo', () => {
    expect(cropCutsPhoto(3000, 2000, 'fill')).toBe(true)
    expect(cropCutsPhoto(1200, 1800, 'fill')).toBe(false)
    expect(cropCutsPhoto(3000, 2000, 'fit')).toBe(false)
  })
})

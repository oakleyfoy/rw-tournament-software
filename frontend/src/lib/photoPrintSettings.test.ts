import { describe, expect, it } from 'vitest'
import { cropCutsPhoto, printFilename, watermarkBox } from './photoPrintSettings'

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

  it('warns when a fill crop would remove part of a landscape photo', () => {
    expect(cropCutsPhoto(3000, 2000, 'fill')).toBe(true)
    expect(cropCutsPhoto(1200, 1800, 'fill')).toBe(false)
    expect(cropCutsPhoto(3000, 2000, 'fit')).toBe(false)
  })
})

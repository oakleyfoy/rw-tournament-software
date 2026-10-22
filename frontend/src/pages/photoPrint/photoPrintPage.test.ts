import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const page = readFileSync(join(here, 'PhotoPrintPage.tsx'), 'utf8')
const css = readFileSync(join(here, 'photoPrint.css'), 'utf8')
const app = readFileSync(join(here, '../../App.tsx'), 'utf8')
const desk = readFileSync(join(here, '../desk/TournamentDeskPage.tsx'), 'utf8')

describe('Watermark and print center', () => {
  it('uses the photo-print route and a three-column workspace', () => {
    expect(app).toContain('/tournaments/:tournamentId/photo-print')
    expect(css).toMatch(/grid-template-columns:\s*minmax\(220px, 260px\) minmax\(320px, 1fr\) minmax\(560px, 760px\)/)
    expect(css).toContain('photo-print-span')
    expect(css).toContain('photo-print-controls-scroll')
    expect(css).toContain('photo-print-controls-actions')
    expect(page).toContain('photo-print-controls-scroll')
    expect(page).toContain('photo-print-controls-actions')
    expect(page).toContain('Search either player')
    expect(page).toContain('Order Prints at Walgreens')
    expect(page).toContain('Apply to All Photos')
    expect(page).toContain('Save This Photo')
    expect(page).toContain('/assets/rw-watermark-logo.png')
    expect(page).toContain('logoPixelWidth(frameWidth, settings.logo_scale)')
    expect(page).toContain('wordingFontSize')
    expect(page).toContain('Wording size')
    expect(page).not.toContain('box.width * 0.78')
    expect(desk).toContain('Watermark & Print')
  })
})

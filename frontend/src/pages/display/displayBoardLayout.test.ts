import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  DISPLAY_BODY_PAD_X_PX,
  DISPLAY_GRID_GAP_PX,
  PLAYING_CARD_MIN_PX,
  UPCOMING_CARD_MIN_PX,
  WAITING_CARD_MIN_PX,
  upcomingColumnsAt,
} from './displayLayout'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'displayBoard.css'), 'utf8')

describe('display board density layout', () => {
  it('does not cap the upcoming grid around 4 columns', () => {
    expect(css).not.toMatch(/\.display-match-grid[\s\S]*?repeat\(\s*[3-6]\s*,/)
    expect(css).not.toContain('repeat(4, minmax(0, 1fr))')
    expect(css).toContain('repeat(auto-fill, minmax(var(--display-upcoming-min), 1fr))')
    expect(css).toContain('--display-upcoming-min: 220px')
  })

  it('uses a large-screen min card width that supports 7–8 columns at 1920px', () => {
    expect(UPCOMING_CARD_MIN_PX).toBeGreaterThanOrEqual(210)
    expect(UPCOMING_CARD_MIN_PX).toBeLessThanOrEqual(240)
    const cols = upcomingColumnsAt(1920)
    expect(cols).toBeGreaterThanOrEqual(7)
    expect(cols).toBeLessThanOrEqual(8)
  })

  it('scales columns at common TV widths without a hard 8-column lock', () => {
    expect(upcomingColumnsAt(1920)).toBe(8)
    expect(upcomingColumnsAt(1440)).toBeGreaterThanOrEqual(5)
    expect(upcomingColumnsAt(1440)).toBeLessThanOrEqual(6)
    expect(upcomingColumnsAt(1080)).toBeGreaterThanOrEqual(4)
    expect(upcomingColumnsAt(1080)).toBeLessThanOrEqual(5)
    expect(upcomingColumnsAt(2560)).toBeGreaterThanOrEqual(8)
    expect(css).not.toContain('grid-template-columns: repeat(8')
  })

  it('prevents horizontal overflow on the board and grids', () => {
    expect(css).toMatch(/\.display-root[\s\S]*?overflow-x:\s*hidden/)
    expect(css).toMatch(/\.display-body[\s\S]*?overflow-x:\s*hidden/)
    expect(css).toMatch(/\.display-match-grid[\s\S]*?overflow-x:\s*hidden/)
    expect(css).toMatch(/\.display-card[\s\S]*?min-width:\s*0/)
    expect(css).toMatch(/\.display-team-names[\s\S]*?overflow-wrap:\s*anywhere/)
    expect(css).not.toMatch(/overflow-x:\s*auto/)
    expect(css).not.toMatch(/overflow-x:\s*scroll/)
  })

  it('keeps waiting and playing cards wider than upcoming', () => {
    expect(WAITING_CARD_MIN_PX).toBeGreaterThan(UPCOMING_CARD_MIN_PX)
    expect(PLAYING_CARD_MIN_PX).toBeGreaterThan(WAITING_CARD_MIN_PX)
    expect(css).toContain('--display-waiting-min: 260px')
    expect(css).toContain('--display-playing-min: 340px')
    expect(DISPLAY_GRID_GAP_PX).toBe(8)
    expect(DISPLAY_BODY_PAD_X_PX).toBe(18)
  })
})

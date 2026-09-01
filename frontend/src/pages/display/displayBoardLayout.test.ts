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
  it('uses a min card width substantially below the old 220px target', () => {
    expect(UPCOMING_CARD_MIN_PX).toBeGreaterThanOrEqual(110)
    expect(UPCOMING_CARD_MIN_PX).toBeLessThanOrEqual(145)
    expect(UPCOMING_CARD_MIN_PX).toBeLessThan(220)
    expect(css).toContain('--display-upcoming-min: 130px')
    expect(css).toContain('repeat(auto-fill, minmax(var(--display-upcoming-min), 1fr))')
  })

  it('does not cap the grid to a fixed small column count', () => {
    expect(css).not.toMatch(/\.display-match-grid[\s\S]*?repeat\(\s*[3-8]\s*,/)
    expect(css).not.toContain('repeat(4, minmax(0, 1fr))')
    expect(css).not.toContain('grid-template-columns: repeat(8')
    expect(css).not.toContain('grid-template-columns: repeat(12')
  })

  it('fits about 12–14+ upcoming cards at 1920 and scales down without a hard lock', () => {
    expect(upcomingColumnsAt(1920)).toBeGreaterThanOrEqual(12)
    expect(upcomingColumnsAt(1440)).toBeGreaterThanOrEqual(9)
    expect(upcomingColumnsAt(1080)).toBeGreaterThanOrEqual(6)
    expect(upcomingColumnsAt(2560)).toBeGreaterThan(upcomingColumnsAt(1920))
  })

  it('prevents horizontal overflow and shrinks long names to fit', () => {
    expect(css).toMatch(/\.display-root[\s\S]*?overflow-x:\s*hidden/)
    expect(css).toMatch(/\.display-body[\s\S]*?overflow-x:\s*hidden/)
    expect(css).toMatch(/\.display-match-grid[\s\S]*?overflow-x:\s*hidden/)
    expect(css).toMatch(/\.display-card[\s\S]*?min-width:\s*0/)
    expect(css).toMatch(/\.display-card[\s\S]*?container-type:\s*inline-size/)
    expect(css).toMatch(/\.display-team[\s\S]*?clamp\(/)
    expect(css).toMatch(/\.display-team-names[\s\S]*?overflow-wrap:\s*anywhere/)
    expect(css).not.toMatch(/overflow-x:\s*auto/)
    expect(css).not.toMatch(/overflow-x:\s*scroll/)
  })

  it('keeps waiting slightly wider and playing larger than upcoming', () => {
    expect(WAITING_CARD_MIN_PX).toBeGreaterThanOrEqual(UPCOMING_CARD_MIN_PX)
    expect(PLAYING_CARD_MIN_PX).toBeGreaterThan(WAITING_CARD_MIN_PX)
    expect(css).toContain('--display-waiting-min: 140px')
    expect(css).toContain('--display-playing-min: 180px')
    expect(DISPLAY_GRID_GAP_PX).toBe(6)
    expect(DISPLAY_BODY_PAD_X_PX).toBe(18)
  })
})

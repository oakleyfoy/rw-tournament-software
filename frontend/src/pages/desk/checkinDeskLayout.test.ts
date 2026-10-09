import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, 'checkinDeskLayout.css'), 'utf8')
const page = readFileSync(join(here, 'TournamentDeskPage.tsx'), 'utf8')

describe('Check-In Desk layout changes', () => {
  it('uses a responsive 1/2/4 column grid for Dynamic Ready To Go', () => {
    expect(css).toContain('.checkin-dynamic-ready-grid')
    expect(css).toMatch(/grid-template-columns:\s*1fr/)
    expect(css).toMatch(/@media \(min-width:\s*700px\)[\s\S]*repeat\(2/)
    expect(css).toMatch(/@media \(min-width:\s*1100px\)[\s\S]*repeat\(4/)
    expect(page).toContain('className="checkin-dynamic-ready-grid"')
    expect(page).toMatch(/compact\b/)
  })

  it('places Dynamic Ready To Go immediately beneath Ready To Go — Assigned Court', () => {
    const assignedIdx = page.indexOf('Ready To Go — Assigned Court')
    const dynamicIdx = page.indexOf('Dynamic Ready To Go')
    const waitingIdx = page.indexOf('Waiting For Check-In')
    expect(assignedIdx).toBeGreaterThan(-1)
    expect(dynamicIdx).toBeGreaterThan(assignedIdx)
    // Dynamic Ready lives in the right-side stack with Assigned Court, not after Waiting alone.
    expect(waitingIdx).toBeGreaterThan(-1)
    expect(dynamicIdx).toBeGreaterThan(waitingIdx)
    // No second Dynamic Ready section left at the bottom of the desk.
    expect(page.match(/Dynamic Ready To Go/g)).toHaveLength(1)
  })

  it('places Release Opening Matches beside Waiting For Check-In and removes the opening banner', () => {
    expect(page).toContain('className="checkin-waiting-header"')
    expect(page).toContain('Waiting For Check-In')
    expect(page).toContain('Release Opening Matches')

    // Exactly one Release Opening Matches button markup in the page
    const releaseMatches = page.match(/Release Opening Matches/g) || []
    expect(releaseMatches).toHaveLength(1)

    // Opening round information banner fully removed
    expect(page).not.toContain('Opening WF Round 1')
    expect(page).not.toContain('Release fully checked-in preassigned matches for this opening slot')
  })

  it('does not surface obsolete REST_TOO_SHORT conflict UI icons', () => {
    expect(page).not.toContain('REST_TOO_SHORT')
  })
})

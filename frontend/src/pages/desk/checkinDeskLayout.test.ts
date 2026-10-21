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
    expect(page).toContain('onToggleCheckIn')
    expect(page).toContain('handleReadyQueueCheckToggle')
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

  it('keeps the four-column desk grids when team photos are shown', () => {
    expect(css).toMatch(/@media \(min-width:\s*1100px\)[\s\S]*repeat\(4/)
    expect(page).toContain("gridTemplateColumns: 'repeat(4, minmax(0, 1fr))'")
    expect(page).toContain("gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)'")
    expect(page).toContain("gridTemplateColumns: 'repeat(10, minmax(0, 1fr))'")
    expect(page).toContain("gridTemplateColumns: 'auto auto auto auto auto'")
    expect(page).toContain('surface="check-in-desk"')
    expect(page).toContain("'assigned-court'")
    expect(page).toContain("'on-court'")
    expect(page).toContain('surface="score-entry"')
    expect(page).toContain('photoSurface="ready-assigned"')
    expect(page).toContain('photoSurface="dynamic-ready"')
    expect(page).toContain('TeamPhotoNameRow')
    expect(page).toContain('useOfficialTeamPhotoPolling(tid)')
    expect(page).not.toContain('MatchTeamPhotos')
    expect(page).toContain('data-testid="score-entry-photos"')
    expect(page).toContain('data-team-details-photo')
    expect(page).toContain('className="checkin-dynamic-ready-grid"')
  })

  it('keeps Back To Ready To Go distinct from Back To Waiting for Check-In', () => {
    expect(page).toContain('Match Actions')
    expect(page).toContain('Back To Ready To Go')
    expect(page).toContain('Back To Waiting for Check-In')
    expect(page).toContain('both teams will need to check in again')
    const readyStart = page.indexOf('const moveBackToReady')
    const waitingStart = page.indexOf('const returnToWaitingCheckIn')
    const reopenStart = page.indexOf('const reopenToCurrentlyPlaying')
    const readyFn = page.slice(readyStart, waitingStart)
    const waitingFn = page.slice(waitingStart, reopenStart)
    expect(readyFn).toContain('deskSetMatchStatus')
    expect(readyFn).toContain("status: 'SCHEDULED'")
    expect(readyFn).not.toContain('deskReturnMatchToWaitingCheckIn')
    expect(waitingFn).toContain('deskReturnMatchToWaitingCheckIn')
    expect(waitingFn).not.toContain('deskSetMatchStatus')
    expect(page).toContain("backgroundColor: '#455a64'")
    expect(page).toContain("color: '#b71c1c'")
    expect(css).toMatch(/@media \(min-width:\s*1100px\)[\s\S]*repeat\(4/)
    expect(page).toContain('className="checkin-dynamic-ready-grid"')
  })
})

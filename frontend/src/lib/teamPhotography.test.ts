import { describe, expect, it } from 'vitest'
import { fitPhotoDimensions } from './prepareTeamPhoto'
import { initialPhotographerSession, photographerReducer, type SessionCapture } from './photographerSession'

function capture(id: string, status: SessionCapture['status'] = 'uploading'): SessionCapture {
  return {
    localId: id,
    clientUploadId: id,
    previewUrl: `blob:${id}`,
    progress: status === 'uploaded' ? 100 : 10,
    status,
    serverId: status === 'uploaded' ? 7 : undefined,
  }
}

describe('photograph preparation', () => {
  it('compresses large images down to the maximum edge', () => {
    expect(fitPhotoDimensions(4000, 2000)).toEqual({ width: 3000, height: 1500 })
    expect(fitPhotoDimensions(400, 800)).toEqual({ width: 400, height: 800 })
  })
})

describe('photographer capture session', () => {
  it('keeps the selected team while multiple photographs are captured and previewed', () => {
    let state = photographerReducer(initialPhotographerSession, { type: 'selectTournament', tournamentId: 5 })
    state = photographerReducer(state, { type: 'selectTeam', teamId: 41 })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('one') })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('two') })
    expect(state.selectedTeamId).toBe(41)
    expect(state.tournamentId).toBe(5)
    expect(state.captures.map((item) => item.localId)).toEqual(['one', 'two'])
  })

  it('ignores an accidental duplicate upload id', () => {
    let state = photographerReducer(initialPhotographerSession, { type: 'selectTeam', teamId: 41 })
    state = photographerReducer({ ...state, tournamentId: 5 }, { type: 'addCapture', capture: capture('same') })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('same') })
    expect(state.captures).toHaveLength(1)
  })

  it('selects an uploaded photograph and returns to search after confirmation', () => {
    let state = photographerReducer(initialPhotographerSession, { type: 'selectTournament', tournamentId: 5 })
    state = photographerReducer(state, { type: 'selectTeam', teamId: 41 })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('best', 'uploaded') })
    state = photographerReducer(state, { type: 'selectCapture', localId: 'best' })
    state = photographerReducer(state, { type: 'confirmStart' })
    expect(state.confirming).toBe(true)
    state = photographerReducer(state, { type: 'confirmStart' })
    expect(state.confirming).toBe(true)
    state = photographerReducer(state, { type: 'confirmSucceeded', teamLabel: 'Jane Doe / Sue Park' })
    expect(state.phase).toBe('search')
    expect(state.selectedTeamId).toBeNull()
    expect(state.tournamentId).toBe(5)
    expect(state.confirmationMessage).toContain('Jane Doe / Sue Park')
  })

  it('keeps the team and photograph when confirmation fails so it can be retried', () => {
    let state = photographerReducer(initialPhotographerSession, { type: 'selectTeam', teamId: 41 })
    state = { ...state, tournamentId: 5 }
    state = photographerReducer(state, { type: 'addCapture', capture: capture('best', 'uploaded') })
    state = photographerReducer(state, { type: 'selectCapture', localId: 'best' })
    state = photographerReducer(state, { type: 'confirmStart' })
    state = photographerReducer(state, { type: 'confirmFailed' })
    expect(state.selectedTeamId).toBe(41)
    expect(state.confirming).toBe(false)
    expect(state.captures).toHaveLength(1)
    expect(state.selectedLocalId).toBe('best')
  })

  it('returns a failed official save to ready so it can be sent again', () => {
    let state = photographerReducer(initialPhotographerSession, { type: 'selectTeam', teamId: 41 })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('retry', 'ready') })
    state = photographerReducer(state, { type: 'uploadFailed', localId: 'retry', error: 'Network error' })
    expect(state.captures[0].status).toBe('failed')
    state = photographerReducer(state, { type: 'retryUpload', localId: 'retry' })
    expect(state.selectedTeamId).toBe(41)
    expect(state.captures[0].status).toBe('ready')
    state = photographerReducer(state, { type: 'selectCapture', localId: 'retry' })
    state = photographerReducer(state, { type: 'confirmStart' })
    expect(state.confirming).toBe(true)
  })
})

describe('group photo mode resets to team photo', () => {
  it('starts on team photo and returns there after either save', () => {
    expect(initialPhotographerSession.photoMode).toBe('team')
    let state = photographerReducer(initialPhotographerSession, { type: 'selectTournament', tournamentId: 4 })
    state = photographerReducer(state, { type: 'chooseGroupPhoto' })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('group', 'ready') })
    expect(state.photoMode).toBe('group')
    expect(state.selectedTeamId).toBeNull()
    state = photographerReducer(state, { type: 'selectCapture', localId: 'group' })
    state = photographerReducer(state, { type: 'confirmSucceeded', teamLabel: 'Group Photo' })
    expect(state.photoMode).toBe('team')
    expect(state.phase).toBe('search')
    expect(state.captures).toHaveLength(0)
    expect(state.confirmationMessage).toBe('Saved group photo')

    state = photographerReducer(state, { type: 'selectTeam', teamId: 41 })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('team', 'ready') })
    state = photographerReducer(state, { type: 'selectCapture', localId: 'team' })
    state = photographerReducer(state, { type: 'confirmSucceeded', teamLabel: 'Jane / Sue' })
    expect(state.photoMode).toBe('team')
    expect(state.confirmationMessage).toBe('Saved for Jane / Sue')
  })

  it('returns to team photo on a new search or team selection and keeps a failed group photo', () => {
    let state = photographerReducer(initialPhotographerSession, { type: 'chooseGroupPhoto' })
    state = photographerReducer(state, { type: 'addCapture', capture: capture('keep', 'ready') })
    state = photographerReducer(state, { type: 'selectCapture', localId: 'keep' })
    state = photographerReducer(state, { type: 'confirmStart' })
    state = photographerReducer(state, { type: 'uploadFailed', localId: 'keep', error: 'Network error' })
    state = photographerReducer(state, { type: 'confirmFailed' })
    expect(state.photoMode).toBe('group')
    expect(state.captures).toHaveLength(1)
    expect(state.captures[0].status).toBe('failed')
    const kept = photographerReducer(state, { type: 'beginTeamSearch' })
    expect(kept.photoMode).toBe('group')
    expect(kept.captures).toHaveLength(1)

    state = photographerReducer(initialPhotographerSession, { type: 'chooseGroupPhoto' })
    state = photographerReducer(state, { type: 'beginTeamSearch' })
    expect(state.photoMode).toBe('team')
    expect(state.phase).toBe('search')

    state = photographerReducer(initialPhotographerSession, { type: 'chooseGroupPhoto' })
    state = photographerReducer(state, { type: 'selectTeam', teamId: 9 })
    expect(state.photoMode).toBe('team')
    expect(state.selectedTeamId).toBe(9)
    expect(state.captures).toHaveLength(0)

    state = photographerReducer({ ...initialPhotographerSession, tournamentId: 4, photoMode: 'group' }, { type: 'selectTournament', tournamentId: 4 })
    expect(state.photoMode).toBe('team')
  })
})

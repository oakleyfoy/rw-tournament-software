import { describe, expect, it } from 'vitest'
import { prepareTeamPhoto } from './prepareTeamPhoto'

describe('prepareTeamPhoto', () => {
  it('sends the original photograph instead of a recompressed copy', async () => {
    const file = new File([new Uint8Array([1, 2, 3, 4])], 'team.jpg', { type: 'image/jpeg' })
    const prepared = await prepareTeamPhoto(file)
    expect(prepared.blob).toBe(file)
  })
})

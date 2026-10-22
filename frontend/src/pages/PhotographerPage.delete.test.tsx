import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PhotographerPage from './PhotographerPage'

const mocks = vi.hoisted(() => ({
  listPhotographyTournaments: vi.fn(),
  searchPhotographyTeams: vi.fn(),
  listOfficialTeamPhotos: vi.fn(),
  deleteOfficialTeamPhoto: vi.fn(),
}))

vi.mock('../api/photography', () => ({
  listPhotographyTournaments: mocks.listPhotographyTournaments,
  searchPhotographyTeams: mocks.searchPhotographyTeams,
  listOfficialTeamPhotos: mocks.listOfficialTeamPhotos,
  deleteOfficialTeamPhoto: mocks.deleteOfficialTeamPhoto,
  postOfficialTeamPhoto: vi.fn(),
  officialTeamPhotoContentUrl: (teamId: number, version: string) =>
    `/api/photography/teams/${teamId}/official/content?v=${encodeURIComponent(version)}`,
  officialTeamPhotoThumbUrl: (teamId: number, version: string) =>
    `/api/photography/teams/${teamId}/official/thumb?v=${encodeURIComponent(version)}`,
}))

vi.mock('../lib/prepareTeamPhoto', () => ({
  prepareTeamPhoto: vi.fn(),
}))

const hit = {
  team_id: 41,
  event_id: 3,
  division: "Women's 3.5",
  seed: 2,
  player_names: ['Jane Doe', 'Sue Park'],
  has_official_photo: true,
}

async function openTeam() {
  render(
    <MemoryRouter>
      <PhotographerPage />
    </MemoryRouter>,
  )
  fireEvent.change(await screen.findByPlaceholderText("Either player's name"), { target: { value: 'Jane' } })
  fireEvent.click(await screen.findByRole('button', { name: /Jane Doe/ }))
  await screen.findByRole('button', { name: 'Delete Photo' })
  return screen.getByTestId('selected-team-photo')
}

describe('delete official team photo', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    mocks.listPhotographyTournaments.mockResolvedValue([
      { id: 4, name: '2026 Kiawah', location: 'Kiawah', start_date: '2026-02-20', end_date: '2026-02-22' },
    ])
    mocks.searchPhotographyTeams.mockResolvedValue([hit])
    mocks.listOfficialTeamPhotos.mockResolvedValue([
      { team_id: 41, updated_at: '2026-10-21T18:00:00', version: 'team-photos/4/41/current.jpg' },
    ])
    mocks.deleteOfficialTeamPhoto.mockResolvedValue({ team_id: 41, deleted: true })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(new Blob(['photo'], { type: 'image/jpeg' }), { status: 200 })))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:current-photo'),
      revokeObjectURL: vi.fn(),
    })
    window.localStorage.setItem('rw_auth_token', 'token')
  })

  it('asks for confirmation and leaves the photograph in place when cancelled', async () => {
    const photo = await openTeam()
    await waitFor(() => {
      expect(photo.querySelector('[data-testid="team-photo"]')).toHaveAttribute(
        'data-photo-version',
        'team-photos/4/41/current.jpg',
      )
    })
    fireEvent.click(screen.getByRole('button', { name: 'Delete Photo' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete official photo' })
    expect(dialog).toHaveTextContent(
      'Are you sure you want to permanently delete the official photograph for Jane Doe / Sue Park?',
    )
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(mocks.deleteOfficialTeamPhoto).not.toHaveBeenCalled()
    expect(photo.querySelector('[data-testid="team-photo"]')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save official photo' })).toBeInTheDocument()
  })

  it('deletes the team photograph once and shows the placeholder immediately', async () => {
    const photo = await openTeam()
    await waitFor(() => expect(photo.querySelector('[data-testid="team-photo"]')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Delete Photo' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete official photo' })
    const confirm = within(dialog).getByRole('button', { name: 'Delete Photo' })
    fireEvent.click(confirm)
    fireEvent.click(confirm)
    await waitFor(() => expect(photo.querySelector('[data-testid="team-photo-placeholder"]')).toBeInTheDocument())
    expect(photo.querySelector('[data-testid="team-photo"]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Delete Photo' })).toBeNull()
    expect(mocks.deleteOfficialTeamPhoto).toHaveBeenCalledTimes(1)
    expect(mocks.deleteOfficialTeamPhoto).toHaveBeenCalledWith(4, 41)
    expect(screen.getByRole('button', { name: 'Save official photo' })).toBeInTheDocument()
  })
})

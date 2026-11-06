import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PhotographerPage from './PhotographerPage'

const mocks = vi.hoisted(() => ({
  listPhotographyTournaments: vi.fn(),
  searchPhotographyTeams: vi.fn(),
  postOfficialTeamPhoto: vi.fn(),
  listOfficialTeamPhotos: vi.fn(),
  getTeamPhotoSms: vi.fn(),
  deleteOfficialTeamPhoto: vi.fn(),
  prepareTeamPhoto: vi.fn(),
}))

vi.mock('../api/photography', () => ({
  listPhotographyTournaments: mocks.listPhotographyTournaments,
  searchPhotographyTeams: mocks.searchPhotographyTeams,
  postOfficialTeamPhoto: mocks.postOfficialTeamPhoto,
  postGroupPhoto: vi.fn(),
  listOfficialTeamPhotos: mocks.listOfficialTeamPhotos,
  getTeamPhotoSms: mocks.getTeamPhotoSms,
  deleteOfficialTeamPhoto: mocks.deleteOfficialTeamPhoto,
  officialTeamPhotoContentUrl: (teamId: number, version: string) =>
    `/api/photography/teams/${teamId}/official/content?v=${encodeURIComponent(version)}`,
  officialTeamPhotoThumbUrl: (teamId: number, version: string) =>
    `/api/photography/teams/${teamId}/official/thumb?v=${encodeURIComponent(version)}`,
}))

vi.mock('../lib/prepareTeamPhoto', () => ({
  prepareTeamPhoto: mocks.prepareTeamPhoto,
}))

describe('photographer official photo confirmation', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    mocks.listOfficialTeamPhotos.mockResolvedValue([])
    mocks.getTeamPhotoSms.mockResolvedValue({ players: [] })
    mocks.deleteOfficialTeamPhoto.mockResolvedValue({ team_id: 41, deleted: true })
    mocks.listPhotographyTournaments.mockResolvedValue([
      { id: 4, name: '2026 Kiawah', location: 'Kiawah', start_date: '2026-02-20', end_date: '2026-02-22' },
    ])
    mocks.searchPhotographyTeams.mockResolvedValue([
      {
        team_id: 41,
        event_id: 3,
        division: "Women's 3.5",
        seed: 2,
        player_names: ['Jane Doe', 'Sue Park'],
        has_official_photo: false,
      },
    ])
    mocks.prepareTeamPhoto.mockResolvedValue({
      blob: new Blob(['jpeg'], { type: 'image/jpeg' }),
      clientUploadId: 'upload-1',
    })
    mocks.postOfficialTeamPhoto.mockImplementation(async (args: { teamId: number; tournamentId: number; clientUploadId: string }) => ({
      team_id: args.teamId,
      tournament_id: args.tournamentId,
      captured_at: '2026-10-21T18:00:00',
      updated_at: '2026-10-21T18:00:01',
      byte_size: 4,
      version: `team-photos/4/${args.teamId}/${args.clientUploadId}.jpg`,
    }))
    vi.stubGlobal('fetch', vi.fn(async () => new Response(new Blob(['photo'], { type: 'image/jpeg' }), { status: 200 })))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:saved-photo'),
      revokeObjectURL: vi.fn(),
    })
    window.localStorage.setItem('rw_auth_token', 'token')
  })

  it('shows the saved official photo for that team immediately', async () => {
    render(
      <MemoryRouter>
        <PhotographerPage />
      </MemoryRouter>,
    )
    fireEvent.change(await screen.findByPlaceholderText("Either player's name"), { target: { value: 'Jane' } })
    fireEvent.click(await screen.findByRole('button', { name: /Jane Doe/ }))
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['jpeg'], 'team.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(await screen.findByTestId('capture-preview'))
    fireEvent.click(screen.getByRole('button', { name: 'Save official photo' }))

    const saved = await screen.findByTestId('saved-official-photo')
    await waitFor(() => {
      expect(saved.querySelector('[data-testid="team-photo"]')).toHaveAttribute(
        'data-photo-version',
        'team-photos/4/41/upload-1.jpg',
      )
    })
    expect(saved.querySelector('[data-testid="team-photo"]')).toHaveAttribute('data-photo-surface', 'photographer')
    expect(screen.getByText(/Saved for Jane Doe \/ Sue Park/)).toBeInTheDocument()
    expect(saved.querySelector('[data-testid="team-photo"]')).toHaveAttribute('data-photo-frame', 'card')
    expect(mocks.postOfficialTeamPhoto).toHaveBeenCalledTimes(1)
    expect(mocks.postOfficialTeamPhoto).toHaveBeenCalledWith(expect.objectContaining({
      tournamentId: 4,
      teamId: 41,
      clientUploadId: 'upload-1',
    }))
    expect(mocks.searchPhotographyTeams).toHaveBeenCalledWith(4, 'Jane')
    const fetchMock = vi.mocked(fetch)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/official/content?'))).toBe(true)
  })

  it('shows a previously saved official photo, then the next team placeholder or photo', async () => {
    let mikeVersion = 'team-photos/4/7/original.jpg'
    mocks.listOfficialTeamPhotos.mockResolvedValue([])
    mocks.searchPhotographyTeams.mockImplementation(async (_tournamentId: number, query: string) => {
      const needle = query.toLowerCase()
      if (needle.includes('dee') || needle.includes('mike')) {
        return [{
          team_id: 7,
          event_id: 3,
          division: 'Mixed',
          seed: 1,
          player_names: ['Mike Arsenault', 'Dee Dee Worley'],
          has_official_photo: true,
          official_photo_version: mikeVersion,
        }]
      }
      if (needle.includes('lauri')) {
        return [{
          team_id: 8,
          event_id: 3,
          division: 'Mixed',
          seed: 2,
          player_names: ['Lauri Owens', 'Marc Dubler'],
          has_official_photo: false,
          official_photo_version: null,
        }]
      }
      return []
    })

    render(
      <MemoryRouter>
        <PhotographerPage />
      </MemoryRouter>,
    )

    fireEvent.change(await screen.findByPlaceholderText("Either player's name"), { target: { value: 'Dee' } })
    fireEvent.click(await screen.findByRole('button', { name: /Dee Dee Worley/ }))
    const card = await screen.findByTestId('selected-team-photo')
    await waitFor(() => {
      expect(card.querySelector('[data-testid="team-photo"]')).toHaveAttribute('data-photo-version', mikeVersion)
    })
    expect(card.querySelector('[data-testid="team-photo"]')).toHaveAttribute('data-photo-frame', 'card')
    expect(card.querySelector('[data-testid="team-photo-placeholder"]')).toBeNull()
    expect(screen.getByText(/already has an official photo/)).toBeInTheDocument()
    expect(mocks.postOfficialTeamPhoto).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'View larger team photo' }))
    expect(screen.getByRole('dialog', { name: 'Official team photo' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('dialog', { name: 'Official team photo' }))

    fireEvent.click(screen.getByRole('button', { name: 'Next team' }))
    fireEvent.change(screen.getByPlaceholderText("Either player's name"), { target: { value: 'Lauri' } })
    fireEvent.click(await screen.findByRole('button', { name: /Lauri Owens/ }))
    const lauri = await screen.findByTestId('selected-team-photo')
    expect(lauri.querySelector('[data-testid="team-photo-placeholder"]')).toBeInTheDocument()
    expect(lauri.querySelector('[data-testid="team-photo"]')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Next team' }))
    mikeVersion = 'team-photos/4/7/upload-1.jpg'
    fireEvent.change(screen.getByPlaceholderText("Either player's name"), { target: { value: 'Mike' } })
    fireEvent.click(await screen.findByRole('button', { name: /Mike Arsenault/ }))
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['jpeg'], 'team.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(await screen.findByTestId('capture-preview'))
    fireEvent.click(screen.getByRole('button', { name: 'Save official photo' }))

    const saved = await screen.findByTestId('saved-official-photo')
    await waitFor(() => {
      expect(saved.querySelector('[data-testid="team-photo"]')).toHaveAttribute('data-photo-version', mikeVersion)
    })
    expect(mocks.postOfficialTeamPhoto).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByPlaceholderText("Either player's name"), { target: { value: 'Dee' } })
    fireEvent.click(await screen.findByRole('button', { name: /Dee Dee Worley/ }))
    const returned = await screen.findByTestId('selected-team-photo')
    await waitFor(() => {
      expect(returned.querySelector('[data-testid="team-photo"]')).toHaveAttribute('data-photo-version', mikeVersion)
    })
    expect(mocks.postOfficialTeamPhoto).toHaveBeenCalledTimes(1)
  })
})

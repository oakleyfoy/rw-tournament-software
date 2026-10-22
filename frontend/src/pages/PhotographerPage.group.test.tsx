import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PhotographerPage from './PhotographerPage'

const mocks = vi.hoisted(() => ({
  listPhotographyTournaments: vi.fn(),
  searchPhotographyTeams: vi.fn(),
  postOfficialTeamPhoto: vi.fn(),
  postGroupPhoto: vi.fn(),
  listOfficialTeamPhotos: vi.fn(),
  getTeamPhotoSms: vi.fn(),
  prepareTeamPhoto: vi.fn(),
}))

vi.mock('../api/photography', () => ({
  listPhotographyTournaments: mocks.listPhotographyTournaments,
  searchPhotographyTeams: mocks.searchPhotographyTeams,
  postOfficialTeamPhoto: mocks.postOfficialTeamPhoto,
  postGroupPhoto: mocks.postGroupPhoto,
  listOfficialTeamPhotos: mocks.listOfficialTeamPhotos,
  getTeamPhotoSms: mocks.getTeamPhotoSms,
  deleteOfficialTeamPhoto: vi.fn(),
  officialTeamPhotoContentUrl: () => '/team-photo',
  officialTeamPhotoThumbUrl: () => '/team-thumb',
  groupPhotoContentUrl: () => '/group-photo',
}))

vi.mock('../lib/prepareTeamPhoto', () => ({
  prepareTeamPhoto: mocks.prepareTeamPhoto,
}))

describe('photographer group photo mode', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    mocks.listOfficialTeamPhotos.mockResolvedValue([])
    mocks.getTeamPhotoSms.mockResolvedValue({ players: [] })
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
      clientUploadId: 'group-upload-1',
    })
    mocks.postGroupPhoto.mockResolvedValue({
      id: 3,
      tournament_id: 4,
      captured_at: '2026-10-22T18:00:00',
      byte_size: 4,
      version: 'team-photos/4/groups/group-upload-1.jpg',
      label: 'Group Photo 1',
    })
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:group-photo'),
      revokeObjectURL: vi.fn(),
    })
  })

  it('opens on Team Photo, saves a group photo without a team, and returns to Team Photo', async () => {
    render(
      <MemoryRouter>
        <PhotographerPage />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('button', { name: 'Team Photo' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Group Photo' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByPlaceholderText("Either player's name")).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Group Photo' }))
    expect(screen.queryByPlaceholderText("Either player's name")).toBeNull()
    expect(screen.getByText('Saved for printing only. It is not linked to a team and no text is sent.')).toBeTruthy()

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['jpeg'], 'group.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(await screen.findByTestId('capture-preview'))
    fireEvent.click(screen.getByRole('button', { name: 'Save group photo' }))

    expect(await screen.findByText(/Saved group photo/)).toBeTruthy()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Team Photo' })).toHaveAttribute('aria-pressed', 'true')
    })
    expect(screen.getByPlaceholderText("Either player's name")).toBeTruthy()
    expect(mocks.postGroupPhoto).toHaveBeenCalledWith(expect.objectContaining({ tournamentId: 4, clientUploadId: 'group-upload-1' }))
    expect(mocks.postOfficialTeamPhoto).not.toHaveBeenCalled()
    expect(mocks.getTeamPhotoSms).not.toHaveBeenCalled()
  })

  it('keeps Group Photo and the picture when saving fails', async () => {
    mocks.postGroupPhoto.mockRejectedValue(new Error('Network error'))
    render(
      <MemoryRouter>
        <PhotographerPage />
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Group Photo' }))
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['jpeg'], 'group.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(await screen.findByTestId('capture-preview'))
    fireEvent.click(screen.getByRole('button', { name: 'Save group photo' }))
    expect((await screen.findAllByText(/Network error/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Group Photo' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('capture-preview')).toBeTruthy()
    expect(screen.queryByPlaceholderText("Either player's name")).toBeNull()
  })
})

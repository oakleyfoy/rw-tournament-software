import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MatchTeamPhotos, TeamPhotoProvider } from './TeamPhotoThumb'
import { TeamSearchResultButton } from './TeamSearchResultButton'

describe('team photo operational rendering', () => {
  it('shows a neutral placeholder when no photograph exists', () => {
    render(
      <TeamPhotoProvider value={{ photos: {}, refresh: async () => undefined, tournamentId: 1 }}>
        <MatchTeamPhotos teamIds={[11, 12]} surface="assigned-court" />
      </TeamPhotoProvider>,
    )
    const placeholders = screen.getAllByTestId('team-photo-placeholder')
    expect(placeholders).toHaveLength(2)
    expect(placeholders[0]).toHaveAttribute('aria-label', 'No team photo')
    expect(screen.getByTestId('match-team-photos')).toHaveAttribute('data-photo-surface', 'assigned-court')
  })

  it('renders only the official photo for the matching team', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/teams/11/')) {
        return new Response(new Blob(['photo'], { type: 'image/jpeg' }), { status: 200 })
      }
      return new Response('', { status: 404 })
    }))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:team-photo'),
      revokeObjectURL: vi.fn(),
    })
    window.localStorage.setItem('rw_auth_token', 'token')
    render(
      <TeamPhotoProvider value={{ photos: { 11: '2026-10-21T12:00:00' }, refresh: async () => undefined, tournamentId: 1 }}>
        <MatchTeamPhotos teamIds={[11, 12]} surface="score-entry" />
      </TeamPhotoProvider>,
    )
    const photo = await screen.findByTestId('team-photo')
    expect(photo).toHaveAttribute('data-photo-surface', 'score-entry')
    expect(screen.getAllByTestId('team-photo-placeholder')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'View larger team photo' }))
    expect(screen.getByRole('dialog', { name: 'Official team photo' })).toBeInTheDocument()
  })
})

describe('team search result', () => {
  it('shows both player names, division, and distinguishing team information', () => {
    render(
      <TeamSearchResultButton
        hit={{
          team_id: 41,
          event_id: 3,
          division: "Women's 3.5",
          seed: 2,
          player_names: ['Jane Doe', 'Sue Park'],
          avoid_group: 'B',
          has_official_photo: false,
        }}
        onSelect={() => undefined}
      />,
    )
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
    expect(screen.getByText('Sue Park')).toBeInTheDocument()
    expect(screen.getByText(/Women's 3.5/)).toBeInTheDocument()
    expect(screen.getByText(/Team 41/)).toBeInTheDocument()
    expect(screen.getByText(/Seed 2/)).toBeInTheDocument()
    expect(screen.getByText(/Avoid B/)).toBeInTheDocument()
  })
})

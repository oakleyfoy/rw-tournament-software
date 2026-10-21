import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MatchTeamPhotos, TeamPhotoNameRow, TeamPhotoProvider } from './TeamPhotoThumb'
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

describe('team photo name rows', () => {
  const teams = [
    { teamId: 11, name: 'Haley / Stacey' },
    { teamId: 12, name: 'Trisha / Heather' },
  ]

  function renderRows(order: typeof teams) {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/teams/12/')) {
        return new Response(new Blob(['photo'], { type: 'image/jpeg' }), { status: 200 })
      }
      return new Response('', { status: 404 })
    }))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:team-12'),
      revokeObjectURL: vi.fn(),
    })
    window.localStorage.setItem('rw_auth_token', 'token')
    render(
      <TeamPhotoProvider value={{ photos: { 12: '2026-10-21T12:00:00' }, refresh: async () => undefined, tournamentId: 4 }}>
        <div>
          {order.map((team) => (
            <TeamPhotoNameRow key={team.teamId} teamId={team.teamId} name={team.name} size={18} surface="on-court" />
          ))}
        </div>
      </TeamPhotoProvider>,
    )
  }

  async function expectPhotoBeside(teamId: string, name: string) {
    const row = screen.getAllByTestId('team-photo-name-row').find((item) => item.getAttribute('data-team-id') === teamId)
    expect(row).toBeTruthy()
    expect(within(row!).getByTestId('team-photo-name')).toHaveTextContent(name)
    expect(await within(row!).findByTestId('team-photo')).toHaveAttribute('data-photo-surface', 'on-court')
    const other = screen.getAllByTestId('team-photo-name-row').find((item) => item.getAttribute('data-team-id') !== teamId)
    expect(within(other!).queryByTestId('team-photo')).toBeNull()
    expect(within(other!).getByTestId('team-photo-placeholder')).toBeInTheDocument()
  }

  it('keeps each photograph beside its own team when the match order changes', async () => {
    renderRows(teams)
    await expectPhotoBeside('12', 'Trisha / Heather')
    expect(screen.getAllByTestId('team-photo-name-row')[0]).toHaveAttribute('data-team-id', '11')

    cleanup()
    renderRows([...teams].reverse())
    const rows = screen.getAllByTestId('team-photo-name-row')
    expect(rows[0]).toHaveAttribute('data-team-id', '12')
    expect(within(rows[0]).getByTestId('team-photo-name')).toHaveTextContent('Trisha / Heather')
    expect(within(rows[0]).getByTestId('team-photo')).toBeInTheDocument()
    expect(rows[1]).toHaveAttribute('data-team-id', '11')
    expect(within(rows[1]).getByTestId('team-photo-name')).toHaveTextContent('Haley / Stacey')
  })
})

describe('team search result', () => {
  it('shows only the two player names and still selects the team by id', () => {
    const onSelect = vi.fn()
    render(
      <TeamSearchResultButton
        hit={{
          team_id: 41,
          event_id: 3,
          division: "Women's 3.5",
          seed: 2,
          player_names: ['Jane Doe', 'Sue Park'],
          avoid_group: 'B',
          source_team_key: '8801/8802',
          has_official_photo: false,
        }}
        onSelect={onSelect}
      />,
    )
    const button = screen.getByRole('button', { name: /Jane Doe/ })
    expect(button).toHaveTextContent('Jane Doe')
    expect(button).toHaveTextContent('Sue Park')
    expect(button).not.toHaveTextContent('Team 41')
    expect(button).not.toHaveTextContent("Women's 3.5")
    expect(button).not.toHaveTextContent('Seed 2')
    expect(button).not.toHaveTextContent('8801/8802')
    expect(button).not.toHaveTextContent('Avoid B')
    fireEvent.click(button)
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ team_id: 41, event_id: 3 }))
  })
})

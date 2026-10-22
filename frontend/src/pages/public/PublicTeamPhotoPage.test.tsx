import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PublicTeamPhotoPage from './PublicTeamPhotoPage'

describe('public team photo page', () => {
  it('shows the team photo and a download link for a valid token', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      tournament_name: '2026 Wild Dunes',
      players: ['Mike Arsenault', 'Dee Dee Worley'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    render(
      <MemoryRouter initialEntries={['/p/photo/abc']}>
        <Routes>
          <Route path="/p/photo/:token" element={<PublicTeamPhotoPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: '2026 Wild Dunes' })).toBeInTheDocument()
    expect(screen.getByText('Mike Arsenault / Dee Dee Worley')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download Photo' })).toHaveAttribute('href', '/api/public/team-photo/abc/image?download=1')
    expect(screen.getByRole('img', { name: 'Official team photograph' })).toHaveAttribute('src', '/api/public/team-photo/abc/image')
  })
})

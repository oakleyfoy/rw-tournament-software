import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PhotoPrintPage from './PhotoPrintPage'
import { defaultWatermarkSettings } from '../../lib/photoPrintSettings'

const mocks = vi.hoisted(() => ({
  loadPhotoPrintWorkspace: vi.fn(),
}))

vi.mock('../../api/photoPrint', () => ({
  loadPhotoPrintWorkspace: mocks.loadPhotoPrintWorkspace,
  savePhotoPrintDefault: vi.fn(),
  applyPhotoPrintToAll: vi.fn(),
  savePhotoPrintOverride: vi.fn(),
  resetPhotoPrintOverride: vi.fn(),
  reviewPhotoPrint: vi.fn(),
  uploadPhotoPrintLogo: vi.fn(),
  exportPhotoPrints: vi.fn(),
  downloadPhotoPrintPackage: vi.fn(),
  downloadPhotoPrintFile: vi.fn(),
  photoPrintLogoUrl: () => '/logo',
  saveBlob: vi.fn(),
}))

vi.mock('../../api/photography', () => ({
  officialTeamPhotoContentUrl: () => '/photo.jpg',
}))

describe('photo print workspace', () => {
  beforeEach(() => {
    const settings = defaultWatermarkSettings('Scottsdale 2026')
    mocks.loadPhotoPrintWorkspace.mockResolvedValue({
      tournament_id: 5,
      tournament_name: 'Scottsdale 2026',
      default_settings: settings,
      has_custom_logo: false,
      totals: { teams: 4, with_photos: 1, reviewed: 0, ready: 0, needs_attention: 1 },
      walgreens: {
        ordering_url: 'https://photo.walgreens.com/store/prints',
        direct_ordering_available: false,
        note: 'Walgreens has not confirmed an order.',
      },
      photos: [{
        team_id: 9,
        player_names: ['Haley', 'Stacey'],
        version: 'v1',
        reviewed: false,
        has_override: false,
        settings,
        source_width: 400,
        source_height: 600,
        low_resolution_sizes: ['4x6'],
        needs_attention: true,
      }],
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      blob: async () => new Blob(['img'], { type: 'image/jpeg' }),
    })))
  })

  it('shows the gallery, live preview, and print actions', async () => {
    render(
      <MemoryRouter initialEntries={['/tournaments/5/photo-print']}>
        <Routes>
          <Route path="/tournaments/:tournamentId/photo-print" element={<PhotoPrintPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('Haley / Stacey')).toBeTruthy()
    expect(screen.getByText('Photo 1 of 1')).toBeTruthy()
    expect(screen.getByLabelText('Top center')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Apply to All Photos' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Order Prints at Walgreens' })).toBeTruthy()
    expect(screen.queryByText('9')).toBeNull()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Resize watermark' })).toBeTruthy())
  })
})

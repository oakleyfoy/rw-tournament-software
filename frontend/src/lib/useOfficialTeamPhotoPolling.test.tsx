import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OfficialPhotoSummary } from '../api/photography'
import { TeamPhotoNameRow, TeamPhotoProvider } from '../components/TeamPhotoThumb'
import { TEAM_PHOTO_POLL_MS, photoVersionsFromSummaries, useOfficialTeamPhotoPolling } from './useOfficialTeamPhotoPolling'

const hookSource = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'useOfficialTeamPhotoPolling.ts'), 'utf8')

function summary(teamId: number, version: string): OfficialPhotoSummary {
  return { team_id: teamId, updated_at: version, version }
}

function OperationalScreen({
  label,
  listPhotos,
}: {
  label: string
  listPhotos: (tournamentId: number) => Promise<OfficialPhotoSummary[]>
}) {
  const live = useOfficialTeamPhotoPolling(4, { listPhotos, intervalMs: TEAM_PHOTO_POLL_MS })
  const [score, setScore] = useState('6-4, 7-5')
  const [winnerId, setWinnerId] = useState<number | null>(null)
  return (
    <div data-testid={label}>
      <input aria-label={`${label} score`} value={score} onChange={(event) => setScore(event.target.value)} />
      <TeamPhotoProvider value={{ photos: live.versions, refresh: live.refresh, showSaved: live.showSaved, tournamentId: 4 }}>
        <label>
          <input
            type="radio"
            name={`${label}-winner`}
            aria-label={`${label} Haley`}
            checked={winnerId === 11}
            onChange={() => setWinnerId(11)}
          />
          <TeamPhotoNameRow teamId={11} name="Haley / Stacey" surface="score-entry" />
        </label>
        <label>
          <input
            type="radio"
            name={`${label}-winner`}
            aria-label={`${label} Trisha`}
            checked={winnerId === 12}
            onChange={() => setWinnerId(12)}
          />
          <TeamPhotoNameRow teamId={12} name="Trisha / Heather" surface="score-entry" />
        </label>
      </TeamPhotoProvider>
    </div>
  )
}

describe('official team photo polling', () => {
  it('uses the stored object version, and the timestamp when a version is absent', () => {
    expect(photoVersionsFromSummaries([
      summary(11, 'team-photos/4/11/first.jpg'),
      { team_id: 12, updated_at: '2026-10-21T18:00:01' },
    ])).toEqual({
      11: 'team-photos/4/11/first.jpg',
      12: '2026-10-21T18:00:01',
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('updates each open screen from photo metadata without reloading the desk or the score', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const contentUrls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      contentUrls.push(String(url))
      return new Response(new Blob(['photo'], { type: 'image/jpeg' }), { status: 200 })
    }))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => `blob:photo-${contentUrls.length}`),
      revokeObjectURL: vi.fn(),
    })
    window.localStorage.setItem('rw_auth_token', 'token')

    let catalog: OfficialPhotoSummary[] = []
    const listPhotos = vi.fn(async () => catalog)
    const loadSnapshot = vi.fn()

    render(
      <>
        <OperationalScreen label="desk-a" listPhotos={listPhotos} />
        <OperationalScreen label="desk-b" listPhotos={listPhotos} />
      </>,
    )

    expect(hookSource).not.toContain('getDeskSnapshot')
    expect(hookSource).not.toContain('loadSnapshot')
    expect(TEAM_PHOTO_POLL_MS).toBe(5000)
    expect(loadSnapshot).not.toHaveBeenCalled()

    catalog = [summary(11, 'team-photos/4/11/first.jpg')]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    for (const label of ['desk-a', 'desk-b']) {
      const rows = within(screen.getByTestId(label)).getAllByTestId('team-photo-name-row')
      const haley = rows.find((row) => row.getAttribute('data-team-id') === '11')
      const trisha = rows.find((row) => row.getAttribute('data-team-id') === '12')
      expect(within(haley!).getByTestId('team-photo-name')).toHaveTextContent('Haley / Stacey')
      expect(within(haley!).getByTestId('team-photo')).toHaveAttribute('data-photo-version', 'team-photos/4/11/first.jpg')
      expect(within(trisha!).getByTestId('team-photo-name')).toHaveTextContent('Trisha / Heather')
      expect(within(trisha!).getByTestId('team-photo-placeholder')).toBeInTheDocument()
    }
    const firstFetches = contentUrls.filter((url) => url.includes(encodeURIComponent('team-photos/4/11/first.jpg')))
    expect(firstFetches).toHaveLength(2)

    fireEvent.change(screen.getByRole('textbox', { name: 'desk-a score' }), { target: { value: '3-6' } })
    fireEvent.click(screen.getByRole('radio', { name: 'desk-a Trisha' }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(contentUrls.filter((url) => url.includes(encodeURIComponent('team-photos/4/11/first.jpg')))).toHaveLength(2)
    expect(loadSnapshot).not.toHaveBeenCalled()

    catalog = [summary(11, 'team-photos/4/11/second.jpg'), summary(12, 'team-photos/4/12/heather.jpg')]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    for (const label of ['desk-a', 'desk-b']) {
      const rows = within(screen.getByTestId(label)).getAllByTestId('team-photo-name-row')
      const haley = rows.find((row) => row.getAttribute('data-team-id') === '11')
      const trisha = rows.find((row) => row.getAttribute('data-team-id') === '12')
      expect(within(haley!).getByTestId('team-photo')).toHaveAttribute('data-photo-version', 'team-photos/4/11/second.jpg')
      expect(within(haley!).queryByTestId('team-photo-placeholder')).toBeNull()
      expect(within(trisha!).getByTestId('team-photo')).toHaveAttribute('data-photo-version', 'team-photos/4/12/heather.jpg')
      expect(within(trisha!).getByTestId('team-photo-name')).toHaveTextContent('Trisha / Heather')
    }
    expect(contentUrls.filter((url) => url.includes(encodeURIComponent('team-photos/4/11/first.jpg')))).toHaveLength(2)
    expect(contentUrls.filter((url) => url.includes(encodeURIComponent('team-photos/4/11/second.jpg')))).toHaveLength(2)
    expect(contentUrls.filter((url) => url.includes(encodeURIComponent('team-photos/4/12/heather.jpg')))).toHaveLength(2)
    expect(screen.getByRole('textbox', { name: 'desk-a score' })).toHaveValue('3-6')
    expect(screen.getByRole('radio', { name: 'desk-a Trisha' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'desk-a Haley' })).not.toBeChecked()
    expect(loadSnapshot).not.toHaveBeenCalled()
  })

  it('does not start a second metadata request while one is still running', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let release: (() => void) | undefined
    const listPhotos = vi.fn(() => new Promise<OfficialPhotoSummary[]>((resolve) => {
      release = () => resolve([])
    }))
    render(<OperationalScreen label="desk-a" listPhotos={listPhotos} />)
    expect(listPhotos).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(listPhotos).toHaveBeenCalledTimes(1)
    await act(async () => {
      release?.()
    })
  })
})

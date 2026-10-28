import { describe, expect, it } from 'vitest'
import { buildTournamentHubPosterPdf, tournamentHubPosterFilename } from './tournamentHubPosterPdf'

describe('tournament hub poster pdf', () => {
  it('builds a letter poster for the stable hub URL', async () => {
    const pdf = await buildTournamentHubPosterPdf({
      tournamentName: 'Destin September 2026',
      publicUrl: 'https://rw-tournament-software.onrender.com/t/9/hub',
      filenameSlug: 'destin-september-2026',
    })
    expect(pdf.filename).toBe('tournament-hub-qr-destin-september-2026.pdf')
    expect(pdf.blob.type).toBe('application/pdf')
    expect(pdf.blob.size).toBeGreaterThan(1000)
  })

  it('slugifies poster filenames', () => {
    expect(tournamentHubPosterFilename('Destin September 2026')).toBe(
      'tournament-hub-qr-destin-september-2026.pdf',
    )
  })
})

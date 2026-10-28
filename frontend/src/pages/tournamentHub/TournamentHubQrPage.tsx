import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getTournamentHubQr, type TournamentHubQrResponse } from '../../api/client'
import { qrDataUrlForPublicUrl } from '../drawQr/drawQrBoardPdf'
import { buildTournamentHubPosterPdf } from './tournamentHubPosterPdf'

export default function TournamentHubQrPage() {
  const { id } = useParams<{ id: string }>()
  const tournamentId = Number(id)
  const navigate = useNavigate()
  const [data, setData] = useState<TournamentHubQrResponse | null>(null)
  const [qrPreview, setQrPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!Number.isFinite(tournamentId) || tournamentId <= 0) return
    let cancelled = false
    setLoading(true)
    setError(null)
    getTournamentHubQr(tournamentId)
      .then(async (resp) => {
        if (cancelled) return
        setData(resp)
        const preview = await qrDataUrlForPublicUrl(resp.public_url)
        if (!cancelled) setQrPreview(preview)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load tournament QR code')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tournamentId])

  const copyLink = async () => {
    if (!data) return
    try {
      await navigator.clipboard.writeText(data.public_url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Could not copy the link')
    }
  }

  const downloadPng = () => {
    if (!qrPreview || !data) return
    const link = document.createElement('a')
    link.href = qrPreview
    link.download = `tournament-hub-qr-${data.filename_slug}.png`
    link.click()
  }

  const printPoster = async () => {
    if (!data) return
    setBusy(true)
    setError(null)
    try {
      const pdf = await buildTournamentHubPosterPdf({
        tournamentName: data.tournament_name,
        publicUrl: data.public_url,
        filenameSlug: data.filename_slug,
      })
      const url = URL.createObjectURL(pdf.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = pdf.filename
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate poster')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <div className="container"><div className="loading">Loading tournament QR code…</div></div>
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1>Tournament QR Code</h1>
        <button className="btn btn-secondary" type="button" onClick={() => navigate(-1)}>
          Back
        </button>
      </div>

      {error ? <div className="error-message" data-testid="tournament-hub-qr-error">{error}</div> : null}

      {data && (
        <div className="card" data-testid="tournament-hub-qr-preview" style={{ maxWidth: 560 }}>
          <p style={{ marginTop: 0, fontWeight: 700, fontSize: 18 }}>{data.tournament_name}</p>
          <p style={{ color: '#555', marginTop: 0 }}>
            One QR code for the whole tournament. Players scan, search their name, and find their team.
          </p>
          {!data.published && (
            <p style={{ color: '#e65100', fontWeight: 600 }}>
              Schedule is not published yet. The QR link is stable and will work once the schedule is published.
            </p>
          )}
          {qrPreview && (
            <img
              src={qrPreview}
              alt={`QR code for ${data.tournament_name}`}
              width={280}
              height={280}
              style={{ display: 'block', margin: '12px auto', background: '#fff' }}
            />
          )}
          <p
            data-testid="tournament-hub-qr-url"
            style={{
              fontSize: 13,
              wordBreak: 'break-all',
              textAlign: 'center',
              color: '#333',
            }}
          >
            {data.public_url}
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center' }}>
            <button type="button" className="btn btn-secondary" data-testid="tournament-hub-copy-link" onClick={() => void copyLink()}>
              {copied ? 'Copied' : 'Copy Link'}
            </button>
            <button type="button" className="btn btn-secondary" data-testid="tournament-hub-download-qr" onClick={downloadPng} disabled={!qrPreview}>
              Download QR Code
            </button>
            <button
              type="button"
              className="btn btn-primary"
              data-testid="tournament-hub-print-poster"
              onClick={() => void printPoster()}
              disabled={busy}
            >
              {busy ? 'Generating…' : 'Print Tournament Poster'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

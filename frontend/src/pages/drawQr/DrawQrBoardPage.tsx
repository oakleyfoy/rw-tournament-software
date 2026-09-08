import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { DrawQrBoardResponse, getDrawQrBoard } from '../../api/client'
import { buildDrawQrBoardPdf } from './drawQrBoardPdf'

export default function DrawQrBoardPage() {
  const { id } = useParams<{ id: string }>()
  const tournamentId = Number(id)
  const navigate = useNavigate()
  const [data, setData] = useState<DrawQrBoardResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    if (!Number.isFinite(tournamentId) || tournamentId <= 0) return
    let cancelled = false
    setLoading(true)
    setError(null)
    getDrawQrBoard(tournamentId)
      .then((resp) => {
        if (!cancelled) setData(resp)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load draw QR board')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tournamentId])

  const handleGenerate = async () => {
    if (!data || data.items.length === 0) return
    setGenerating(true)
    setError(null)
    try {
      const pdf = await buildDrawQrBoardPdf(data.items, {
        tournamentName: data.tournament_name,
        filenameSlug: data.filename_slug,
      })
      const url = URL.createObjectURL(pdf.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = pdf.filename
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate PDF')
    } finally {
      setGenerating(false)
    }
  }

  if (loading) {
    return <div className="container"><div className="loading">Loading draw QR board…</div></div>
  }

  const items = data?.items ?? []

  return (
    <div className="container">
      <div className="page-header">
        <h1>Draw QR Board</h1>
        <button className="btn btn-secondary" onClick={() => navigate(-1)}>
          Back
        </button>
      </div>

      {error ? <div className="error-message" data-testid="draw-qr-error">{error}</div> : null}

      {items.length === 0 ? (
        <div className="card" data-testid="draw-qr-empty">
          No published draws are currently available for this tournament.
        </div>
      ) : (
        <div className="card" data-testid="draw-qr-preview">
          <p data-testid="draw-qr-count" style={{ fontWeight: 700, marginTop: 0 }}>
            {items.length} draw{items.length === 1 ? '' : 's'} will be included
          </p>
          <ul data-testid="draw-qr-item-list" style={{ margin: '0 0 20px', paddingLeft: 20 }}>
            {items.map((item) => (
              <li key={`${item.event_id}-${item.draw_type}-${item.division_code || 'none'}`}>
                {item.label} — {item.draw_type_label}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="btn btn-primary"
            data-testid="draw-qr-generate"
            onClick={() => void handleGenerate()}
            disabled={generating}
          >
            {generating ? 'Generating…' : 'Generate 32 × 24 PDF'}
          </button>
        </div>
      )}
    </div>
  )
}

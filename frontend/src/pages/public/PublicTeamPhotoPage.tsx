import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

type PhotoPage = {
  tournament_name: string
  players: string[]
}

export default function PublicTeamPhotoPage() {
  const { token } = useParams()
  const [page, setPage] = useState<PhotoPage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) {
      setError('This photo link is no longer available.')
      return
    }
    let cancelled = false
    fetch(`${API_BASE_URL}/public/team-photo/${encodeURIComponent(token)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error('unavailable')
        return response.json() as Promise<PhotoPage>
      })
      .then((body) => {
        if (!cancelled) setPage(body)
      })
      .catch(() => {
        if (!cancelled) setError('This photo link is no longer available.')
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const imageUrl = token ? `${API_BASE_URL}/public/team-photo/${encodeURIComponent(token)}/image` : ''

  return (
    <main style={{ maxWidth: 480, margin: '0 auto', padding: 16, fontFamily: 'sans-serif', color: '#1a1a1a' }}>
      {error && <p>{error}</p>}
      {page && (
        <>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>{page.tournament_name}</h1>
          <p style={{ marginTop: 0 }}>{page.players.filter(Boolean).join(' / ')}</p>
          <img
            src={imageUrl}
            alt="Official team photograph"
            style={{ width: '100%', height: 'auto', borderRadius: 12, background: '#111' }}
          />
          <a
            href={`${imageUrl}?download=1`}
            download="racquet-war-team-photo.jpg"
            style={{
              display: 'block',
              marginTop: 16,
              padding: '14px 16px',
              borderRadius: 10,
              background: '#1a237e',
              color: '#fff',
              textAlign: 'center',
              fontWeight: 800,
              textDecoration: 'none',
            }}
          >
            Download Photo
          </a>
        </>
      )}
    </main>
  )
}

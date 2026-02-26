import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getPublicDrawsList, PublicDrawsListResponse } from '../../api/client'

export default function PublicDrawsPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : null

  const [data, setData] = useState<PublicDrawsListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)

  useEffect(() => {
    if (!tid) return
    setLoading(true)
    setNotPublished(false)
    getPublicDrawsList(tid)
      .then((resp: any) => {
        if (resp.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
        } else {
          setData(resp)
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [tid])

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#666' }}>
        Loading draws...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#c62828' }}>
        {error}
      </div>
    )
  }

  if (notPublished) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#555', marginBottom: 8 }}>
          Schedule Not Published
        </div>
        <div style={{ fontSize: 14, color: '#888' }}>
          The tournament schedule has not been published yet. Check back later.
        </div>
      </div>
    )
  }

  if (!data) return null

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '32px 16px' }}>
      <h1 style={{
        fontSize: 22,
        fontWeight: 700,
        color: '#1a237e',
        marginBottom: 24,
        textAlign: 'center',
        textTransform: 'uppercase',
        letterSpacing: 1,
      }}>
        {data.tournament_name}
      </h1>
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        gap: 20,
        marginTop: 10,
        marginBottom: 20,
        fontSize: 14,
        fontWeight: 600,
      }}>
        <span style={{
          color: '#1a237e',
          borderBottom: '2px solid #1a237e',
          paddingBottom: 2,
        }}>
          Draws
        </span>
        <Link
          to={`/t/${tid}/schedule`}
          style={{ color: '#666', textDecoration: 'none' }}
        >
          Schedule
        </Link>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {data.events.map(ev => (
          <div
            key={ev.event_id}
            style={{
              padding: '14px 18px',
              border: '1px solid #e0e0e0',
              borderRadius: 6,
              backgroundColor: '#fff',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: 15, color: '#333' }}>
                {ev.name}
              </div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                {ev.category} &middot; {ev.team_count} teams
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {ev.has_waterfall && (
                <Link
                  to={`/t/${tid}/draws/${ev.event_id}/waterfall`}
                  style={{
                    fontSize: 13,
                    padding: '6px 14px',
                    borderRadius: 4,
                    backgroundColor: '#1a237e',
                    color: '#fff',
                    textDecoration: 'none',
                    fontWeight: 500,
                  }}
                >
                  Waterfall
                </Link>
              )}
              {ev.has_round_robin && (
                <Link
                  to={`/t/${tid}/draws/${ev.event_id}/roundrobin`}
                  style={{
                    fontSize: 13,
                    padding: '6px 14px',
                    borderRadius: 4,
                    backgroundColor: '#2e7d32',
                    color: '#fff',
                    textDecoration: 'none',
                    fontWeight: 500,
                  }}
                >
                  Round Robin
                </Link>
              )}
              {ev.divisions.map(div => (
                <Link
                  key={div.code}
                  to={`/t/${tid}/draws/${ev.event_id}/bracket/${div.code}`}
                  style={{
                    fontSize: 13,
                    padding: '6px 14px',
                    borderRadius: 4,
                    backgroundColor: '#5c6bc0',
                    color: '#fff',
                    textDecoration: 'none',
                    fontWeight: 500,
                  }}
                >
                  {div.label}
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>

      {data.events.length === 0 && (
        <div style={{ textAlign: 'center', color: '#888', padding: 40 }}>
          No events found.
        </div>
      )}
    </div>
  )
}

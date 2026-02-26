import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getPublicRoundRobin, RoundRobinResponse, RRMatchBox, RRPool, RRPoolStandings } from '../../api/client'

// ── Print styles ────────────────────────────────────────────────────────

const PRINT_STYLE_ID = 'rr-print-css'

function injectPrintStyles() {
  if (document.getElementById(PRINT_STYLE_ID)) return
  const style = document.createElement('style')
  style.id = PRINT_STYLE_ID
  style.textContent = `
    @media print {
      @page { size: portrait; margin: 6mm; }
      html, body {
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
      .no-print { display: none !important; }
      .rr-print-root {
        background: #fff !important;
        min-height: auto !important;
      }
      .rr-print-root * {
        background-color: #fff !important;
        color: #000 !important;
        border-color: #888 !important;
        box-shadow: none !important;
      }
      .rr-print-root [data-rr-header] {
        background-color: #000 !important;
        color: #fff !important;
        padding: 3px 8px !important;
        font-size: 10px !important;
      }
      .rr-print-root [data-rr-canvas] {
        padding: 4px !important;
      }
      .rr-print-root [data-rr-inner] {
        zoom: 0.72 !important;
      }
      .rr-print-root [data-pool-title] {
        background-color: #000 !important;
        color: #fff !important;
      }
    }
  `
  document.head.appendChild(style)
}

// ── Match card ──────────────────────────────────────────────────────────

function RRMatchCard({ match }: { match: RRMatchBox }) {
  const isFinal = match.status === 'FINAL'

  const infoParts: string[] = [`Match #${match.match_id}`]
  if (match.court_label) infoParts.push(match.court_label)

  const schedParts: string[] = []
  if (match.day_display) schedParts.push(match.day_display)
  if (match.time_display) schedParts.push(match.time_display)

  return (
    <div style={{
      border: '1px solid #ccc',
      borderRadius: 3,
      padding: '6px 10px',
      backgroundColor: '#fff',
      width: 280,
      fontSize: 12,
      lineHeight: 1.4,
    }}>
      {/* Team A */}
      <div style={{
        fontWeight: 600,
        fontSize: 12,
        borderBottom: '1px solid #eee',
        paddingBottom: 3,
        marginBottom: 3,
      }}>
        {match.line1}
      </div>

      {/* Match info line */}
      <div style={{
        fontSize: 10,
        color: '#555',
        fontWeight: 600,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span>{infoParts.join(' - ')}</span>
        {isFinal && match.winner_name && (
          <span style={{ color: '#2e7d32', fontWeight: 700 }}>{match.winner_name}</span>
        )}
      </div>

      {/* Score or schedule */}
      {isFinal && match.score_display ? (
        <div style={{
          fontSize: 13,
          fontWeight: 700,
          color: '#1a237e',
          textAlign: 'center',
          padding: '2px 0',
        }}>
          {match.score_display}
        </div>
      ) : schedParts.length > 0 ? (
        <div style={{ fontSize: 10, color: '#888', padding: '2px 0' }}>
          {schedParts.join(' - ')}
        </div>
      ) : (
        <div style={{ fontSize: 10, color: '#aaa', fontStyle: 'italic', padding: '2px 0' }}>
          Not yet scheduled
        </div>
      )}

      {/* Team B */}
      <div style={{
        fontWeight: 600,
        fontSize: 12,
        borderTop: '1px solid #eee',
        paddingTop: 3,
        marginTop: 3,
      }}>
        {match.line2}
      </div>
    </div>
  )
}

// ── Pool section ────────────────────────────────────────────────────────

function PoolSection({ pool, eventName }: { pool: RRPool; eventName: string }) {
  const title = `${eventName} Round Robin ${pool.pool_label}`.toUpperCase()

  const rows: RRMatchBox[][] = []
  for (let i = 0; i < pool.matches.length; i += 2) {
    rows.push(pool.matches.slice(i, i + 2))
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <div data-pool-title style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '8px 14px',
        fontSize: 13,
        fontWeight: 700,
        letterSpacing: 1,
        textTransform: 'uppercase',
        borderRadius: '3px 3px 0 0',
      }}>
        {title}
      </div>

      <div style={{
        border: '1px solid #ddd',
        borderTop: 'none',
        borderRadius: '0 0 3px 3px',
        padding: '12px',
        backgroundColor: '#fafafa',
      }}>
        {rows.map((row, ri) => (
          <div key={ri} style={{
            display: 'flex',
            gap: 16,
            marginBottom: ri < rows.length - 1 ? 10 : 0,
            alignItems: 'center',
            flexWrap: 'wrap',
          }}>
            <div style={{
              width: 64,
              fontSize: 11,
              fontWeight: 700,
              color: '#1a237e',
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              flexShrink: 0,
              textAlign: 'center',
            }}>
              Round {ri + 1}
            </div>
            {row.map(m => (
              <RRMatchCard key={m.match_id} match={m} />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Standings table ──────────────────────────────────────────────────────

function PoolStandingsTable({ standings }: { standings: RRPoolStandings }) {
  if (standings.rows.length === 0) return null

  const th: React.CSSProperties = { padding: '3px 6px', fontWeight: 700, fontSize: 10, textAlign: 'center', whiteSpace: 'nowrap' }
  const td: React.CSSProperties = { padding: '2px 6px', fontSize: 10, textAlign: 'center', whiteSpace: 'nowrap' }

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#1a237e', marginBottom: 2 }}>{standings.pool_label}</div>
      <table style={{ borderCollapse: 'collapse', fontSize: 10, width: '100%' }}>
        <thead>
          <tr style={{ backgroundColor: '#e8eaf6', borderBottom: '1px solid #c5cae9' }}>
            <th style={th}>#</th>
            <th style={{ ...th, textAlign: 'left' }}>Team</th>
            <th style={th}>W</th>
            <th style={th}>L</th>
            <th style={th}>Sets</th>
            <th style={th}>Games</th>
            <th style={th}>P</th>
          </tr>
        </thead>
        <tbody>
          {standings.rows.map((row, idx) => (
            <tr key={row.team_id} style={{ borderBottom: '1px solid #f0f0f0', backgroundColor: idx < 2 ? '#f1f8e9' : '#fff' }}>
              <td style={td}>{idx + 1}</td>
              <td style={{ ...td, textAlign: 'left', fontWeight: 600 }}>{row.team_display}</td>
              <td style={{ ...td, fontWeight: 700, color: '#2e7d32' }}>{row.wins}</td>
              <td style={{ ...td, color: '#c62828' }}>{row.losses}</td>
              <td style={td}>{row.sets_won}-{row.sets_lost}</td>
              <td style={td}>{row.games_won}-{row.games_lost}</td>
              <td style={td}>{row.played}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StandingsSection({ standings }: { standings: RRPoolStandings[] }) {
  if (!standings || standings.length === 0) return null
  const hasData = standings.some(s => s.rows.some(r => r.played > 0))
  if (!hasData) return null

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: 16,
      marginBottom: 20,
    }}>
      {standings.map(s => (
        <PoolStandingsTable key={s.pool_code} standings={s} />
      ))}
    </div>
  )
}


// ── Main page ───────────────────────────────────────────────────────────

export default function PublicRoundRobinPage() {
  const { tournamentId, eventId } = useParams<{
    tournamentId: string
    eventId: string
  }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : null
  const eid = eventId ? parseInt(eventId, 10) : null

  const [data, setData] = useState<RoundRobinResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)

  useEffect(() => {
    if (!tid || !eid) return
    setLoading(true)
    setNotPublished(false)
    getPublicRoundRobin(tid, eid)
      .then((resp: any) => {
        if (resp.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
        } else {
          setData(resp)
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [tid, eid])

  const handlePrint = useCallback(() => {
    injectPrintStyles()
    setTimeout(() => window.print(), 100)
  }, [])

  if (loading) {
    return (
      <div style={{ padding: 60, textAlign: 'center', color: '#666', fontSize: 16 }}>
        Loading round robin...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 60, textAlign: 'center', color: '#c62828', fontSize: 16 }}>
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

  const headerText = `${data.event_name} Round Robin`.toUpperCase()

  // Display pools in a 2-column grid (Div I + Div II side by side, Div III + Div IV side by side)
  const poolPairs: RRPool[][] = []
  for (let i = 0; i < data.pools.length; i += 2) {
    poolPairs.push(data.pools.slice(i, i + 2))
  }

  return (
    <div className="rr-print-root" style={{ backgroundColor: '#f8f9fa', minHeight: '100vh' }}>
      {/* Nav */}
      <div className="no-print" style={{
        padding: '8px 20px',
        backgroundColor: '#fff',
        borderBottom: '1px solid #e0e0e0',
        fontSize: 13,
        color: '#555',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <Link
            to={`/t/${tid}/draws`}
            style={{ color: '#1a237e', textDecoration: 'none', fontWeight: 500 }}
          >
            &larr; Draws
          </Link>
          <Link
            to={`/t/${tid}/draws/${eid}/waterfall`}
            style={{ color: '#1a237e', textDecoration: 'none', fontWeight: 500 }}
          >
            Waterfall
          </Link>
          <Link
            to={`/t/${tid}/schedule`}
            style={{ color: '#1a237e', textDecoration: 'none', fontWeight: 500 }}
          >
            Schedule
          </Link>
        </div>
        <button
          onClick={handlePrint}
          style={{
            padding: '4px 14px',
            fontSize: 12,
            fontWeight: 600,
            backgroundColor: '#1a237e',
            color: '#fff',
            border: 'none',
            borderRadius: 3,
            cursor: 'pointer',
          }}
        >
          Print / PDF
        </button>
      </div>

      {/* Header */}
      <div data-rr-header style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '14px 24px',
        fontSize: 16,
        fontWeight: 700,
        letterSpacing: 1.5,
        textTransform: 'uppercase',
        textAlign: 'center',
      }}>
        {headerText}
      </div>

      {/* Standings */}
      {data.standings && data.standings.length > 0 && (
        <div style={{ padding: '16px 24px 0' }}>
          <StandingsSection standings={data.standings} />
        </div>
      )}

      {/* Content */}
      <div data-rr-canvas style={{ padding: '20px 24px' }}>
        <div data-rr-inner>
          {poolPairs.map((pair, pi) => (
            <div key={pi} style={{
              display: 'flex',
              gap: 24,
              marginBottom: 20,
              flexWrap: 'wrap',
            }}>
              {pair.map(pool => (
                <div key={pool.pool_code} style={{ flex: '1 1 48%', minWidth: 320 }}>
                  <PoolSection pool={pool} eventName={data.event_name} />
                </div>
              ))}
            </div>
          ))}

          {/* Tiebreaker note */}
          <div style={{
            fontSize: 11,
            color: '#666',
            fontStyle: 'italic',
            textAlign: 'center',
            marginTop: 12,
          }}>
            {data.tiebreaker_note}
          </div>
        </div>
      </div>
    </div>
  )
}

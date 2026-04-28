import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { getPublicRoundRobin, RoundRobinResponse, RRMatchBox, RRPool, RRPoolStandings } from '../../api/client'

const REFRESH_MS = 15000

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

function RRMatchCard({ match, showCourtInfo }: { match: RRMatchBox; showCourtInfo: boolean }) {
  const isFinal = match.status === 'FINAL'

  const infoParts: string[] = [`Match #${match.match_id}`]
  if (showCourtInfo && match.court_label) infoParts.push(match.court_label)

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

function getDivisionNumberFromLabel(label: string): number {
  const match = label.match(/Division\s+([IVX]+)/i)
  if (!match) return Number.MAX_SAFE_INTEGER
  const roman = match[1].toUpperCase()
  const values: Record<string, number> = {
    I: 1,
    II: 2,
    III: 3,
    IV: 4,
    V: 5,
    VI: 6,
    VII: 7,
    VIII: 8,
  }
  return values[roman] ?? Number.MAX_SAFE_INTEGER
}

// ── Pool section ────────────────────────────────────────────────────────

function PoolSection({ pool, eventName, showCourtInfo }: { pool: RRPool; eventName: string; showCourtInfo: boolean }) {
  const title = `${eventName} Round Robin ${pool.pool_label}`.toUpperCase()

  const rounds = Array.from(
    pool.matches.reduce((acc, match) => {
      const roundIndex = match.round_index || 0
      const existing = acc.get(roundIndex) || []
      existing.push(match)
      acc.set(roundIndex, existing)
      return acc
    }, new Map<number, RRMatchBox[]>()).entries()
  )
    .sort((a, b) => a[0] - b[0])
    .map(([roundIndex, matches]) => ({ roundIndex, matches }))

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
        {rounds.map(({ roundIndex, matches }, ri) => (
          <div key={`${pool.pool_code}-${roundIndex}-${ri}`} style={{
            display: 'flex',
            gap: 16,
            marginBottom: ri < rounds.length - 1 ? 10 : 0,
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
              Round {roundIndex || ri + 1}
            </div>
            {matches.map(m => (
              <RRMatchCard key={m.match_id} match={m} showCourtInfo={showCourtInfo} />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function RRMatchCardTv({ match, showCourtInfo }: { match: RRMatchBox; showCourtInfo: boolean }) {
  const isFinal = match.status === 'FINAL'
  const infoParts: string[] = []
  if (showCourtInfo && match.court_label) infoParts.push(match.court_label)
  if (match.time_display) infoParts.push(match.time_display)

  return (
    <div style={{
      border: '1px solid #d7deef',
      borderRadius: 6,
      padding: '7px 9px',
      backgroundColor: '#fff',
      fontSize: 12,
      lineHeight: 1.35,
    }}>
      <div style={{ fontWeight: 800, fontSize: 12, color: '#1f2937', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {match.line1}
      </div>
      <div style={{ fontSize: 10, color: '#6b7280', textAlign: 'center', padding: '2px 0', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        vs
      </div>
      <div style={{ fontWeight: 800, fontSize: 12, color: '#1f2937', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {match.line2}
      </div>
      <div style={{
        marginTop: 5,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8,
        fontSize: 10,
        color: '#667085',
      }}>
        <span>{infoParts.join(' • ') || (isFinal ? 'Completed' : 'Pending')}</span>
        {isFinal && match.score_display && (
          <span style={{ color: '#1a237e', fontWeight: 800 }}>{match.score_display}</span>
        )}
      </div>
      {isFinal && match.winner_name && (
        <div style={{ marginTop: 4, fontSize: 10, fontWeight: 800, color: '#2e7d32' }}>
          Winner: {match.winner_name}
        </div>
      )}
    </div>
  )
}

function PoolMatchesTv({
  pool,
  showCourtInfo,
}: {
  pool: RRPool
  showCourtInfo: boolean
}) {
  const title = pool.pool_label.toUpperCase()
  const rounds = Array.from(
    pool.matches.reduce((acc, match) => {
      const roundIndex = match.round_index || 0
      const existing = acc.get(roundIndex) || []
      existing.push(match)
      acc.set(roundIndex, existing)
      return acc
    }, new Map<number, RRMatchBox[]>()).entries()
  )
    .sort((a, b) => a[0] - b[0])
    .map(([roundIndex, matches]) => ({ roundIndex, matches }))

  return (
    <div style={{ border: '1px solid #d9deeb', borderRadius: 8, backgroundColor: '#fcfdff', overflow: 'hidden' }}>
      <div style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '8px 10px',
        fontSize: 12,
        fontWeight: 800,
        letterSpacing: 0.7,
        textTransform: 'uppercase',
        textAlign: 'center',
      }}>
        {title}
      </div>
      <div style={{ padding: '10px', display: 'grid', gap: 8 }}>
        {rounds.map(({ roundIndex, matches }, ri) => (
          <div key={`${pool.pool_code}-${roundIndex}-${ri}`} style={{ display: 'grid', gap: 6 }}>
            <div style={{
              fontSize: 10,
              fontWeight: 800,
              color: '#1a237e',
              textTransform: 'uppercase',
              letterSpacing: 0.6,
              textAlign: 'center',
            }}>
              Round {roundIndex || ri + 1}
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              {matches.map((match) => (
                <RRMatchCardTv key={match.match_id} match={match} showCourtInfo={showCourtInfo} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function PoolStandingsTableTv({ standings }: { standings: RRPoolStandings }) {
  return (
    <div style={{
      border: '1px solid #d9deeb',
      borderRadius: 8,
      backgroundColor: '#fcfdff',
      overflow: 'hidden',
    }}>
      <div style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '8px 10px',
        fontSize: 12,
        fontWeight: 800,
        letterSpacing: 0.7,
        textTransform: 'uppercase',
        textAlign: 'center',
      }}>
        {`${standings.pool_label} Standings`.toUpperCase()}
      </div>
      <div style={{ padding: '8px 10px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead>
            <tr style={{ backgroundColor: '#eef2ff', borderBottom: '1px solid #c7d2fe' }}>
              <th style={{ padding: '4px 6px', textAlign: 'left' }}>#</th>
              <th style={{ padding: '4px 6px', textAlign: 'left' }}>Team</th>
              <th style={{ padding: '4px 6px', textAlign: 'center' }}>W</th>
              <th style={{ padding: '4px 6px', textAlign: 'center' }}>L</th>
              <th style={{ padding: '4px 6px', textAlign: 'center' }}>SD</th>
              <th style={{ padding: '4px 6px', textAlign: 'center' }}>GD</th>
            </tr>
          </thead>
          <tbody>
            {standings.rows.map((row, idx) => {
              const setDiff = row.sets_won - row.sets_lost
              const gameDiff = row.games_won - row.games_lost
              return (
                <tr key={row.team_id} style={{ borderBottom: '1px solid #eef2f7', backgroundColor: idx < 2 ? '#f1f8e9' : '#fff' }}>
                  <td style={{ padding: '4px 6px', fontWeight: 700 }}>{idx + 1}</td>
                  <td style={{ padding: '4px 6px', fontWeight: 700, color: '#1f2937' }}>{row.team_display}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'center', fontWeight: 700, color: '#2e7d32' }}>{row.wins}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'center', color: '#c62828' }}>{row.losses}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'center', fontWeight: 700, color: setDiff >= 0 ? '#2e7d32' : '#c62828' }}>
                    {setDiff >= 0 ? '+' : ''}{setDiff}
                  </td>
                  <td style={{ padding: '4px 6px', textAlign: 'center', fontWeight: 700, color: gameDiff >= 0 ? '#1565c0' : '#c62828' }}>
                    {gameDiff >= 0 ? '+' : ''}{gameDiff}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Standings table ──────────────────────────────────────────────────────

function PoolStandingsTable({ standings }: { standings: RRPoolStandings }) {
  if (standings.rows.length === 0) return null

  const th: React.CSSProperties = {
    padding: '5px 8px',
    fontWeight: 700,
    fontSize: 10,
    textAlign: 'center',
    whiteSpace: 'nowrap',
  }
  const td: React.CSSProperties = {
    padding: '4px 8px',
    fontSize: 10,
    textAlign: 'center',
    whiteSpace: 'nowrap',
  }

  return (
    <div style={{ marginBottom: 4, border: '1px solid #dfe4ef', borderRadius: 6, backgroundColor: '#fff', padding: '8px 10px' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#1a237e', marginBottom: 6 }}>{standings.pool_label}</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 10, width: '100%' }}>
          <thead>
            <tr style={{ backgroundColor: '#e8eaf6', borderBottom: '1px solid #c5cae9' }}>
              <th style={th}>#</th>
              <th style={{ ...th, textAlign: 'left' }}>Team</th>
              <th style={th}>Wins</th>
              <th style={th}>Losses</th>
              <th style={th}>Sets Won</th>
              <th style={th}>Sets Lost</th>
              <th style={{ ...th, fontWeight: 800, color: '#2e7d32' }}>Set Diff</th>
              <th style={th}>Games Won</th>
              <th style={th}>Games Lost</th>
              <th style={{ ...th, fontWeight: 800, color: '#1565c0' }}>Game Diff</th>
              <th style={th}>Played</th>
            </tr>
          </thead>
          <tbody>
            {standings.rows.map((row, idx) => {
              const setDiff = row.sets_won - row.sets_lost
              const gameDiff = row.games_won - row.games_lost
              return (
                <tr key={row.team_id} style={{ borderBottom: '1px solid #f0f0f0', backgroundColor: idx < 2 ? '#f1f8e9' : '#fff' }}>
                  <td style={td}>{idx + 1}</td>
                  <td style={{ ...td, textAlign: 'left', fontWeight: 600 }}>{row.team_display}</td>
                  <td style={{ ...td, fontWeight: 700, color: '#2e7d32' }}>{row.wins}</td>
                  <td style={{ ...td, color: '#c62828' }}>{row.losses}</td>
                  <td style={td}>{row.sets_won}</td>
                  <td style={td}>{row.sets_lost}</td>
                  <td style={{ ...td, fontWeight: 800, color: setDiff >= 0 ? '#2e7d32' : '#c62828' }}>
                    {setDiff >= 0 ? '+' : ''}{setDiff}
                  </td>
                  <td style={td}>{row.games_won}</td>
                  <td style={td}>{row.games_lost}</td>
                  <td style={{ ...td, fontWeight: 800, color: gameDiff >= 0 ? '#1565c0' : '#c62828' }}>
                    {gameDiff >= 0 ? '+' : ''}{gameDiff}
                  </td>
                  <td style={td}>{row.played}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StandingsSection({ standings }: { standings: RRPoolStandings[] }) {
  if (!standings || standings.length === 0) return null
  const hasData = standings.some(s => s.rows.some(r => r.played > 0))
  if (!hasData) return null

  const columnCount = standings.length <= 1 ? 1 : 2

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
      gap: 18,
      marginBottom: 20,
      width: '100%',
    }}>
      {standings.map(s => (
        <PoolStandingsTable key={s.pool_code} standings={s} />
      ))}
    </div>
  )
}

function StandingsHelpPanel({ tiebreakerNote }: { tiebreakerNote: string }) {
  const cardStyle: React.CSSProperties = {
    border: '1px solid #dde2f0',
    borderRadius: 6,
    padding: '10px 12px',
    backgroundColor: '#fff',
    marginBottom: 10,
  }
  const headingStyle: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 700,
    color: '#1a237e',
    marginBottom: 6,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  }

  return (
    <div style={{ flex: '0 0 260px', maxWidth: 300, minWidth: 240 }}>
      <div style={cardStyle}>
        <div style={headingStyle}>Standings Abbreviations</div>
        <div style={{ fontSize: 11, color: '#455a64', lineHeight: 1.55 }}>
          <div><strong>W</strong> = Match Wins</div>
          <div><strong>L</strong> = Match Losses</div>
          <div><strong>Sets</strong> = Sets Won - Sets Lost</div>
          <div><strong>Games</strong> = Games Won - Games Lost</div>
          <div><strong>P</strong> = Matches Played</div>
        </div>
      </div>

      <div style={cardStyle}>
        <div style={headingStyle}>Tiebreak Order</div>
        <ol style={{ margin: '0 0 6px 18px', padding: 0, fontSize: 11, color: '#455a64', lineHeight: 1.55 }}>
          <li>Most match wins (W)</li>
          <li>Best set differential</li>
          <li>Best game differential</li>
          <li>Head-to-head (for exact two-team ties)</li>
        </ol>
        <div style={{ fontSize: 10, color: '#78909c', fontStyle: 'italic' }}>
          {tiebreakerNote}
        </div>
      </div>
    </div>
  )
}

function StandingsHelpRow({ tiebreakerNote }: { tiebreakerNote: string }) {
  const cardStyle: React.CSSProperties = {
    border: '1px solid #dde2f0',
    borderRadius: 6,
    padding: '10px 12px',
    backgroundColor: '#fff',
    flex: '1 1 320px',
    minWidth: 280,
  }
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10 }}>
      <div style={cardStyle}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#1a237e', marginBottom: 6, textTransform: 'uppercase' }}>
          Standings Abbreviations
        </div>
        <div style={{ fontSize: 11, color: '#455a64', lineHeight: 1.5 }}>
          <div><strong>W</strong> = Match Wins</div>
          <div><strong>L</strong> = Match Losses</div>
          <div><strong>Sets</strong> = Sets Won - Sets Lost</div>
          <div><strong>Games</strong> = Games Won - Games Lost</div>
          <div><strong>P</strong> = Matches Played</div>
        </div>
      </div>
      <div style={cardStyle}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#1a237e', marginBottom: 6, textTransform: 'uppercase' }}>
          Tiebreak Order
        </div>
        <ol style={{ margin: '0 0 6px 18px', padding: 0, fontSize: 11, color: '#455a64', lineHeight: 1.5 }}>
          <li>Most match wins (W)</li>
          <li>Best set differential</li>
          <li>Best game differential</li>
          <li>Head-to-head (for exact two-team ties)</li>
        </ol>
        <div style={{ fontSize: 10, color: '#78909c', fontStyle: 'italic' }}>{tiebreakerNote}</div>
      </div>
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
  const [searchParams] = useSearchParams()
  const captureMode = searchParams.get('capture_packet') === '1'
  const tvMode = searchParams.get('tv') === '1'

  const [data, setData] = useState<RoundRobinResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)

  useEffect(() => {
    if (!tid || !eid) return
    let cancelled = false

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true)
      setNotPublished(false)
      setError(null)
      try {
        const resp: any = await getPublicRoundRobin(tid, eid)
        if (cancelled) return
        if (resp.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
          setData(null)
        } else {
          setData(resp)
          setNotPublished(false)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load')
      } finally {
        if (!cancelled && showSpinner) setLoading(false)
      }
    }

    void load(true)
    const timer = window.setInterval(() => {
      void load(false)
    }, REFRESH_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [tid, eid])

  const handlePrint = useCallback(() => {
    injectPrintStyles()
    setTimeout(() => window.print(), 100)
  }, [])

  const showCourtInfo = data?.show_court_info !== false
  const poolsSorted = useMemo(
    () => [...(data?.pools || [])].sort((a, b) => getDivisionNumberFromLabel(a.pool_label) - getDivisionNumberFromLabel(b.pool_label)),
    [data?.pools]
  )
  const standingsByCode = useMemo(
    () => new Map((data?.standings || []).map((standing) => [standing.pool_code, standing])),
    [data?.standings]
  )
  const poolPairs: RRPool[][] = []
  for (let i = 0; i < poolsSorted.length; i += 2) {
    poolPairs.push(poolsSorted.slice(i, i + 2))
  }
  const tvPageParam = searchParams.get('tv_page')
  const tvRotationParam = searchParams.get('tv_rotation')
  const tvRequestedPage = tvPageParam ? Math.max(parseInt(tvPageParam, 10) || 0, 0) : null
  const tvRotation = tvRotationParam ? Math.max(parseInt(tvRotationParam, 10) || 0, 0) : 0
  const tvPageCount = Math.max(poolPairs.length, 1)
  const tvPageIndex = tvRequestedPage != null
    ? Math.min(tvRequestedPage, tvPageCount - 1)
    : tvRotation % tvPageCount
  const tvActivePair = poolPairs[tvPageIndex] || []
  const tvLeftPool = tvActivePair[0] || null
  const tvRightPool = tvActivePair[1] || null
  const tvLeftStandings = tvLeftPool ? standingsByCode.get(tvLeftPool.pool_code) || null : null
  const tvRightStandings = tvRightPool ? standingsByCode.get(tvRightPool.pool_code) || null : null

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

  return (
    <div className="rr-print-root" style={{
      backgroundColor: captureMode || tvMode ? '#fff' : '#f8f9fa',
      minHeight: captureMode ? 'auto' : '100vh',
      height: tvMode ? '100vh' : undefined,
      overflow: tvMode ? 'hidden' : undefined,
      display: tvMode ? 'flex' : undefined,
      flexDirection: tvMode ? 'column' : undefined,
    }}>
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
        ...(captureMode || tvMode ? { display: 'none' } : {}),
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
        padding: tvMode ? '10px 18px' : '14px 24px',
        fontSize: tvMode ? 14 : 16,
        fontWeight: 700,
        letterSpacing: 1.5,
        textTransform: 'uppercase',
        textAlign: 'center',
        flexShrink: tvMode ? 0 : undefined,
      }}>
        {headerText}
      </div>

      {/* Standings */}
      {!captureMode && !tvMode && data.standings && data.standings.length > 0 && (
        <div style={{ padding: '16px 24px 0' }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 720px', minWidth: 300 }}>
              <StandingsSection standings={data.standings} />
            </div>
            <StandingsHelpPanel tiebreakerNote={data.tiebreaker_note} />
          </div>
        </div>
      )}

      {/* Content */}
      <div data-rr-canvas style={{
        padding: captureMode ? '12px 14px' : tvMode ? '10px 12px' : '20px 24px',
        flex: tvMode ? 1 : undefined,
        minHeight: tvMode ? 0 : undefined,
        overflow: tvMode ? 'hidden' : undefined,
      }}>
        <div data-rr-inner>
          {tvMode ? (
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1.2fr 0.9fr 1.2fr',
              gap: 12,
              height: '100%',
              alignItems: 'start',
            }}>
              <div style={{ minWidth: 0, minHeight: 0 }}>
                {tvLeftPool ? (
                  <PoolMatchesTv pool={tvLeftPool} showCourtInfo={showCourtInfo} />
                ) : (
                  <div style={{
                    border: '1px solid #d9deeb',
                    borderRadius: 8,
                    backgroundColor: '#fcfdff',
                    minHeight: 120,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#90a4ae',
                    fontSize: 12,
                    textTransform: 'uppercase',
                    letterSpacing: 0.6,
                  }}>
                    No Division
                  </div>
                )}
              </div>
              <div style={{ minWidth: 0, minHeight: 0, display: 'grid', gap: 12, alignContent: 'start' }}>
                {tvLeftStandings ? (
                  <PoolStandingsTableTv standings={tvLeftStandings} />
                ) : (
                  <div style={{
                    border: '1px solid #d9deeb',
                    borderRadius: 8,
                    backgroundColor: '#fcfdff',
                    minHeight: 120,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#90a4ae',
                    fontSize: 12,
                    textTransform: 'uppercase',
                    letterSpacing: 0.6,
                  }}>
                    No Standings
                  </div>
                )}
                {tvRightStandings ? (
                  <PoolStandingsTableTv standings={tvRightStandings} />
                ) : (
                  <div style={{
                    border: '1px solid #d9deeb',
                    borderRadius: 8,
                    backgroundColor: '#fcfdff',
                    minHeight: 120,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#90a4ae',
                    fontSize: 12,
                    textTransform: 'uppercase',
                    letterSpacing: 0.6,
                  }}>
                    No Standings
                  </div>
                )}
              </div>
              <div style={{ minWidth: 0, minHeight: 0 }}>
                {tvRightPool ? (
                  <PoolMatchesTv pool={tvRightPool} showCourtInfo={showCourtInfo} />
                ) : (
                  <div style={{
                    border: '1px solid #d9deeb',
                    borderRadius: 8,
                    backgroundColor: '#fcfdff',
                    minHeight: 120,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#90a4ae',
                    fontSize: 12,
                    textTransform: 'uppercase',
                    letterSpacing: 0.6,
                  }}>
                    No Division
                  </div>
                )}
              </div>
            </div>
          ) : (
            <>
              {poolPairs.map((pair, pi) => (
                <div key={pi} style={{
                  display: 'flex',
                  gap: 24,
                  marginBottom: 20,
                  flexWrap: 'wrap',
                }}>
                  {pair.map(pool => (
                    <div key={pool.pool_code} style={{ flex: '1 1 48%', minWidth: 320 }}>
                      <PoolSection pool={pool} eventName={data.event_name} showCourtInfo={showCourtInfo} />
                    </div>
                  ))}
                </div>
              ))}

              {captureMode && <StandingsHelpRow tiebreakerNote={data.tiebreaker_note} />}
            </>
          )}

        </div>
      </div>
    </div>
  )
}

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { getPublicWaterfall, PublicWaterfallResponse, PublicMatchBox } from '../../api/client'

// ── Print styles ────────────────────────────────────────────────────────

const PRINT_STYLE_ID = 'waterfall-print-css'

function injectPrintStyles() {
  if (document.getElementById(PRINT_STYLE_ID)) return
  const style = document.createElement('style')
  style.id = PRINT_STYLE_ID
  style.textContent = `
    @media print {
      @page { size: landscape; margin: 5mm; }
      html, body {
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
      .no-print { display: none !important; }
      .print-root {
        background: #fff !important;
        min-height: auto !important;
        overflow: visible !important;
      }
      .print-root * {
        background-color: #fff !important;
        color: #000 !important;
        border-color: #888 !important;
        box-shadow: none !important;
      }
      .print-root [data-header] {
        background-color: #000 !important;
        color: #fff !important;
        padding: 3px 8px !important;
        font-size: 10px !important;
      }
      .print-root [data-bracket-canvas] {
        padding: 4px 0 !important;
        overflow: visible !important;
      }
      .print-root [data-bracket-inner] {
        zoom: 0.58 !important;
        min-width: 0 !important;
        max-width: none !important;
        margin: 0 !important;
      }
      .print-root [data-match-box] {
        padding: 1px 3px !important;
        line-height: 1.15 !important;
      }
      .print-root [data-row-pair] {
        margin-bottom: 8px !important;
        min-height: auto !important;
      }
      .print-root [data-dest-box] {
        padding: 1px 3px !important;
        line-height: 1.15 !important;
        border: 1px solid #aaa !important;
      }
      .print-root [data-dest-box] > div { gap: 1px !important; }
      .print-root [data-connector] {
        width: 12px !important;
      }
      .print-root [data-vs] { display: none !important; }
      .print-root [data-col-headers] {
        margin-bottom: 2px !important;
      }
    }
  `
  document.head.appendChild(style)
}

// ── Color system ────────────────────────────────────────────────────────

const COLORS = {
  header: { bg: '#1a237e', text: '#fff' },
  center: { bg: '#e3f2fd', border: '#90caf9', bgFinal: '#bbdefb' },
  winner: { bg: '#e8f5e9', border: '#81c784', bgFinal: '#c8e6c9' },
  loser:  { bg: '#fff3e0', border: '#ffb74d', bgFinal: '#ffe0b2' },
}

// ── Match box component ─────────────────────────────────────────────────

const CENTER_BOX_WIDTH = 480
const SIDE_BOX_WIDTH = 340

function MatchBoxCard({ box, variant }: {
  box: PublicMatchBox
  variant: 'center' | 'winner' | 'loser'
}) {
  const palette = COLORS[variant]
  const isFinal = box.status === 'FINAL'
  const isCenter = variant === 'center'
  const winnerId = box.winner_team_id
  const line1IsWinner = isFinal && winnerId != null && box.team_a_id === winnerId
  const line2IsWinner = isFinal && winnerId != null && box.team_b_id === winnerId

  return (
    <div style={{
      backgroundColor: isFinal ? palette.bgFinal : palette.bg,
      border: `1px solid ${palette.border}`,
      borderRadius: 3,
      padding: '6px 10px',
      width: isCenter ? CENTER_BOX_WIDTH : SIDE_BOX_WIDTH,
      boxSizing: 'border-box',
      fontSize: 12,
      lineHeight: 1.4,
      position: 'relative',
      textAlign: 'center',
    }} data-match-box>
      {/* Top line: match number + court/time or score */}
      <div style={{
        fontWeight: 700,
        fontSize: 11,
        color: '#333',
        marginBottom: 3,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: 6,
      }}>
        <span>{box.top_line}</span>
        {isFinal && (
          <span style={{
            fontSize: 9,
            fontWeight: 700,
            color: '#2e7d32',
            backgroundColor: '#c8e6c9',
            padding: '1px 5px',
            borderRadius: 2,
            textTransform: 'uppercase',
          }}>
            Completed
          </span>
        )}
      </div>

      {/* Team lines with "vs" — winner highlighted */}
      <div style={{
        color: line1IsWinner ? '#1b5e20' : '#222',
        fontSize: 11,
        fontWeight: line1IsWinner ? 700 : 400,
      }}>
        {line1IsWinner && <span style={{ fontSize: 9, marginRight: 4 }}>&#9654;</span>}
        {box.line1}
      </div>
      <div data-vs style={{ fontSize: 10, color: '#999', fontWeight: 600, fontStyle: 'italic', margin: '1px 0' }}>
        vs
      </div>
      <div style={{
        color: line2IsWinner ? '#1b5e20' : '#222',
        fontSize: 11,
        fontWeight: line2IsWinner ? 700 : 400,
      }}>
        {line2IsWinner && <span style={{ fontSize: 9, marginRight: 4 }}>&#9654;</span>}
        {box.line2}
      </div>

      {/* Notes */}
      {box.notes && (
        <div style={{ fontSize: 9, color: '#888', marginTop: 2, fontStyle: 'italic' }}>
          {box.notes}
        </div>
      )}
    </div>
  )
}

// ── Arrow connector ─────────────────────────────────────────────────────

function ArrowConnector({ direction }: { direction: 'left' | 'right' }) {
  const isLeft = direction === 'left'
  return (
    <div data-connector style={{
      width: 32,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      position: 'relative',
    }}>
      <div style={{ width: '100%', height: 1, backgroundColor: '#999' }} />
      <div style={{
        position: 'absolute',
        [isLeft ? 'left' : 'right']: 0,
        width: 0,
        height: 0,
        borderTop: '5px solid transparent',
        borderBottom: '5px solid transparent',
        ...(isLeft
          ? { borderRight: '8px solid #999' }
          : { borderLeft: '8px solid #999' }),
      }} />
    </div>
  )
}

// ── Destination label box ───────────────────────────────────────────────

const DEST_BOX_WIDTH = 200

const DIV_CODE_MAP: Record<string, string> = {
  'Division I': 'BWW',
  'Division II': 'BWL',
  'Division III': 'BLW',
  'Division IV': 'BLL',
}

function DestinationBox({ label, teamName, tournamentId, eventId, divisionType }: {
  label: string
  teamName: string | null
  tournamentId: number | null
  eventId: number | null
  divisionType: 'bracket' | 'roundrobin'
}) {
  const navigate = useNavigate()
  const lines = label.split('\n')

  const handleClick = (line: string) => {
    if (!tournamentId || !eventId) return
    if (divisionType === 'roundrobin') {
      navigate(`/t/${tournamentId}/draws/${eventId}/roundrobin`)
      return
    }
    const divMatch = line.match(/Division\s+(I{1,3}V?|IV)/)
    if (divMatch) {
      const divName = `Division ${divMatch[1]}`
      const code = DIV_CODE_MAP[divName]
      if (code) {
        navigate(`/t/${tournamentId}/draws/${eventId}/bracket/${code}`)
      }
    }
  }

  return (
    <div style={{
      width: DEST_BOX_WIDTH,
      padding: '8px 10px',
      fontSize: 10,
      fontWeight: 600,
      backgroundColor: '#f5f5f5',
      border: '1px dashed #ccc',
      borderRadius: 3,
      textAlign: 'center',
      boxSizing: 'border-box',
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    }} data-dest-box>
      {teamName && (
        <div style={{
          color: '#1b5e20',
          fontWeight: 700,
          fontSize: 11,
          lineHeight: 1.3,
          paddingBottom: 4,
          borderBottom: '1px solid #e0e0e0',
        }}>
          {teamName}
        </div>
      )}
      {lines.map((line, i) => (
        <div
          key={i}
          onClick={() => handleClick(line)}
          style={{
            color: '#1a237e',
            cursor: 'pointer',
            textDecoration: 'underline',
            textDecorationColor: '#ccc',
            lineHeight: 1.4,
          }}
        >
          {line}
        </div>
      ))}
    </div>
  )
}

// ── Waterfall row (pair of R1 matches with shared R2 boxes) ─────────

interface RowPair {
  r1_a: PublicMatchBox
  r1_b: PublicMatchBox | null
  winner: PublicMatchBox | null
  loser: PublicMatchBox | null
  winner_dest: string | null
  loser_dest: string | null
  r2_winner_team_name: string | null
  r2_loser_team_name: string | null
}

function WaterfallRowPair({ pair, tournamentId, eventId, divisionType }: {
  pair: RowPair
  tournamentId: number | null
  eventId: number | null
  divisionType: 'bracket' | 'roundrobin'
}) {
  return (
    <div data-row-pair style={{
      display: 'flex',
      alignItems: 'stretch',
      justifyContent: 'center',
      marginBottom: 18,
      minHeight: 90,
    }}>
      {/* Loser destination (far left) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        width: DEST_BOX_WIDTH,
        flexShrink: 0,
      }}>
        {pair.loser_dest && <DestinationBox label={pair.loser_dest} teamName={pair.r2_loser_team_name} tournamentId={tournamentId} eventId={eventId} divisionType={divisionType} />}
      </div>

      {/* Arrow: destination ← loser box */}
      {pair.loser_dest && <ArrowConnector direction="left" />}
      {!pair.loser_dest && <div style={{ width: 32, flexShrink: 0 }} />}

      {/* Loser box (left) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        width: SIDE_BOX_WIDTH,
        flexShrink: 0,
      }}>
        {pair.loser ? <MatchBoxCard box={pair.loser} variant="loser" /> : <div style={{ width: SIDE_BOX_WIDTH }} />}
      </div>

      {/* Arrow: loser ← center */}
      <ArrowConnector direction="left" />

      {/* Center column: two R1 boxes stacked */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        justifyContent: 'center',
        flexShrink: 0,
        width: CENTER_BOX_WIDTH,
      }}>
        <MatchBoxCard box={pair.r1_a} variant="center" />
        {pair.r1_b && <MatchBoxCard box={pair.r1_b} variant="center" />}
      </div>

      {/* Arrow: center → winner */}
      <ArrowConnector direction="right" />

      {/* Winner box (right) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        width: SIDE_BOX_WIDTH,
        flexShrink: 0,
      }}>
        {pair.winner ? <MatchBoxCard box={pair.winner} variant="winner" /> : <div style={{ width: SIDE_BOX_WIDTH }} />}
      </div>

      {/* Arrow: winner → destination */}
      {pair.winner_dest && <ArrowConnector direction="right" />}
      {!pair.winner_dest && <div style={{ width: 32, flexShrink: 0 }} />}

      {/* Winner destination (far right) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        width: DEST_BOX_WIDTH,
        flexShrink: 0,
      }}>
        {pair.winner_dest && <DestinationBox label={pair.winner_dest} teamName={pair.r2_winner_team_name} tournamentId={tournamentId} eventId={eventId} divisionType={divisionType} />}
      </div>
    </div>
  )
}

// ── Main page ───────────────────────────────────────────────────────────

export default function PublicWaterfallPage() {
  const { tournamentId, eventId } = useParams<{ tournamentId: string; eventId: string }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : null
  const eid = eventId ? parseInt(eventId, 10) : null
  const [searchParams] = useSearchParams()
  const versionIdParam = searchParams.get('version_id')
  const versionId = versionIdParam ? parseInt(versionIdParam, 10) : undefined

  const [data, setData] = useState<PublicWaterfallResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)

  useEffect(() => {
    if (!tid || !eid) return
    setLoading(true)
    setNotPublished(false)
    getPublicWaterfall(tid, eid, versionId)
      .then((resp: any) => {
        if (resp.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
        } else {
          setData(resp)
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [tid, eid, versionId])

  // Group rows into pairs: each pair shares R2 winner/loser boxes
  const rowPairs = useMemo((): RowPair[] => {
    if (!data?.rows) return []
    const pairs: RowPair[] = []

    for (let i = 0; i < data.rows.length; i += 2) {
      const rowA = data.rows[i]
      const rowB = i + 1 < data.rows.length ? data.rows[i + 1] : null

      pairs.push({
        r1_a: rowA.center_box,
        r1_b: rowB?.center_box ?? null,
        winner: rowA.winner_box,
        loser: rowA.loser_box,
        winner_dest: rowA.winner_dest ?? null,
        loser_dest: rowA.loser_dest ?? null,
        r2_winner_team_name: rowA.r2_winner_team_name ?? null,
        r2_loser_team_name: rowA.r2_loser_team_name ?? null,
      })
    }

    return pairs
  }, [data])

  const handlePrint = useCallback(() => {
    injectPrintStyles()
    setTimeout(() => window.print(), 100)
  }, [])

  if (loading) {
    return (
      <div style={{ padding: 60, textAlign: 'center', color: '#666', fontSize: 16 }}>
        Loading waterfall bracket...
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

  const headerText = `${data.event_name} Waterfall Bracket`.toUpperCase()

  return (
    <div className="print-root" style={{ backgroundColor: '#f8f9fa', minHeight: '100vh' }}>
      {versionId && (
        <div className="no-print" style={{
          padding: '8px 20px',
          backgroundColor: '#fff3e0',
          color: '#e65100',
          fontSize: 13,
          fontWeight: 600,
          textAlign: 'center',
          borderBottom: '1px solid #ffe0b2',
        }}>
          Viewing Desk Draft — not the published version
        </div>
      )}
      {/* Nav bar */}
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
      <div data-header style={{
        backgroundColor: COLORS.header.bg,
        color: COLORS.header.text,
        padding: '14px 24px',
        fontSize: 16,
        fontWeight: 700,
        letterSpacing: 1.5,
        textTransform: 'uppercase',
        textAlign: 'center',
      }}>
        {headerText}
      </div>

      {/* Bracket canvas: fixed width, horizontal scroll on mobile */}
      <div data-bracket-canvas style={{ overflowX: 'auto', padding: '20px 16px' }}>
        <div data-bracket-inner style={{
          minWidth: 1500,
          maxWidth: 1900,
          margin: '0 auto',
        }}>
          {/* Column headers */}
          <div data-col-headers style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 10,
            fontSize: 11,
            fontWeight: 700,
            color: '#666',
            textTransform: 'uppercase',
            letterSpacing: 1,
          }}>
            <div style={{ width: DEST_BOX_WIDTH, flexShrink: 0 }} />
            <div style={{ width: 32, flexShrink: 0 }} />
            <div style={{ width: SIDE_BOX_WIDTH, textAlign: 'center', flexShrink: 0 }}>
              Round 1 Loser
            </div>
            <div style={{ width: 32, flexShrink: 0 }} />
            <div style={{ width: CENTER_BOX_WIDTH, textAlign: 'center', flexShrink: 0 }}>
              WF Round 1
            </div>
            <div style={{ width: 32, flexShrink: 0 }} />
            <div style={{ width: SIDE_BOX_WIDTH, textAlign: 'center', flexShrink: 0 }}>
              Round 1 Winner
            </div>
            <div style={{ width: 32, flexShrink: 0 }} />
            <div style={{ width: DEST_BOX_WIDTH, flexShrink: 0 }} />
          </div>

          {/* Row pairs */}
          {rowPairs.map((pair, idx) => (
            <WaterfallRowPair key={idx} pair={pair} tournamentId={tid} eventId={eid} divisionType={data.division_type || 'bracket'} />
          ))}

          {rowPairs.length === 0 && (
            <div style={{
              textAlign: 'center',
              color: '#888',
              padding: 60,
              fontSize: 15,
            }}>
              No waterfall matches found for this event.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

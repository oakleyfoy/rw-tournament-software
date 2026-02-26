import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { getPublicBracket, BracketResponse, BracketMatchBox } from '../../api/client'

// ── Print styles ────────────────────────────────────────────────────────

const PRINT_STYLE_ID = 'bracket-print-css'

function injectBracketPrintStyles() {
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
      .bracket-print-root {
        background: #fff !important;
        min-height: auto !important;
        overflow: visible !important;
      }
      .bracket-print-root * {
        background-color: #fff !important;
        color: #000 !important;
        border-color: #888 !important;
        box-shadow: none !important;
      }
      .bracket-print-root [data-bracket-header] {
        background-color: #000 !important;
        color: #fff !important;
        padding: 3px 8px !important;
        font-size: 10px !important;
      }
      .bracket-print-root [data-bracket-canvas] {
        padding: 4px 0 !important;
        overflow: visible !important;
      }
      .bracket-print-root [data-bracket-inner] {
        zoom: 0.7 !important;
        min-width: 0 !important;
      }
      .bracket-print-root [data-bracket-card] {
        padding: 2px 4px !important;
        font-size: 8px !important;
        line-height: 1.2 !important;
        border: 1px solid #999 !important;
      }
      .bracket-print-root [data-bracket-card] [data-score-badge] {
        background-color: #eee !important;
        color: #000 !important;
      }
      .bracket-print-root svg line { stroke: #000 !important; }
    }
  `
  document.head.appendChild(style)
}

// ── Layout constants ────────────────────────────────────────────────────

const MATCH_W = 280
const MATCH_H = 82
const GAP_V = 8
const CONNECTOR_W = 28

const COLORS = {
  header: { bg: '#1a237e', text: '#fff' },
  main: { bg: '#e3f2fd', border: '#90caf9', bgFinal: '#bbdefb' },
  consolation: { bg: '#fff3e0', border: '#ffb74d', bgFinal: '#ffe0b2' },
}

function MatchCard({ match, variant }: {
  match: BracketMatchBox
  variant: 'main' | 'consolation'
}) {
  const palette = COLORS[variant]
  const isFinal = match.status === 'FINAL'

  const schedParts: string[] = []
  if (match.court_label) schedParts.push(match.court_label)
  if (match.day_display) schedParts.push(match.day_display)
  if (match.time_display) schedParts.push(match.time_display)
  const schedLine = schedParts.length > 0 ? schedParts.join(' • ') : null

  return (
    <div style={{
      width: MATCH_W,
      height: MATCH_H,
      backgroundColor: isFinal ? palette.bgFinal : palette.bg,
      border: `1px solid ${palette.border}`,
      borderRadius: 3,
      padding: '4px 8px',
      boxSizing: 'border-box',
      fontSize: 11,
      lineHeight: 1.3,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      position: 'relative',
    }} data-bracket-card>
      {/* Match number + score/final badge */}
      <div style={{
        fontWeight: 700,
        fontSize: 10,
        color: '#555',
        marginBottom: 1,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span>Match #{match.match_id}</span>
        {isFinal && match.score_display && (
          <span data-score-badge style={{
            fontSize: 9,
            fontWeight: 700,
            color: '#2e7d32',
            backgroundColor: '#c8e6c9',
            padding: '1px 4px',
            borderRadius: 2,
          }}>
            {match.score_display}
          </span>
        )}
      </div>

      {/* Court / Date / Time */}
      {schedLine && (
        <div style={{ fontSize: 9, color: '#888', marginBottom: 2 }}>
          {schedLine}
        </div>
      )}
      {!schedLine && match.status === 'UNSCHEDULED' && (
        <div style={{ fontSize: 9, color: '#aaa', fontStyle: 'italic', marginBottom: 2 }}>
          Not yet scheduled
        </div>
      )}

      {/* Team lines */}
      <div style={{
        color: '#222',
        fontSize: 11,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        borderBottom: '1px solid rgba(0,0,0,0.08)',
        paddingBottom: 1,
        marginBottom: 1,
      }}>
        {match.line1}
      </div>
      <div style={{
        color: '#222',
        fontSize: 11,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}>
        {match.line2}
      </div>
    </div>
  )
}

interface RoundColumn {
  roundIndex: number
  label: string
  matches: BracketMatchBox[]
}

function BracketTree({ matches, variant, roundLabels }: {
  matches: BracketMatchBox[]
  variant: 'main' | 'consolation'
  roundLabels?: Record<number, string>
}) {
  const rounds: RoundColumn[] = useMemo(() => {
    const roundMap = new Map<number, BracketMatchBox[]>()
    for (const m of matches) {
      const ri = m.round_index
      if (!roundMap.has(ri)) roundMap.set(ri, [])
      roundMap.get(ri)!.push(m)
    }
    const defaultLabels: Record<number, string> = { 1: 'Quarterfinals', 2: 'Semifinals', 3: 'Final' }
    const labels = roundLabels || defaultLabels
    return Array.from(roundMap.entries())
      .sort(([a], [b]) => a - b)
      .map(([ri, mList]) => ({
        roundIndex: ri,
        label: labels[ri] || `Round ${ri}`,
        matches: mList.sort((a, b) => a.sequence_in_round - b.sequence_in_round),
      }))
  }, [matches, roundLabels])

  if (rounds.length === 0) return null

  const maxMatches = Math.max(...rounds.map(r => r.matches.length))
  const bracketHeight = maxMatches * (MATCH_H + GAP_V) - GAP_V

  return (
    <div style={{ display: 'flex', alignItems: 'flex-start' }}>
      {rounds.map((round, colIdx) => {
        const matchCount = round.matches.length
        const totalSlotH = bracketHeight / matchCount

        return (
          <div key={round.roundIndex} style={{ display: 'flex' }}>
            {colIdx > 0 && (
              <svg
                width={CONNECTOR_W}
                height={bracketHeight}
                style={{ flexShrink: 0 }}
              >
                {round.matches.map((_, mi) => {
                  const prevRound = rounds[colIdx - 1]
                  const prevSlotH = bracketHeight / prevRound.matches.length
                  const srcIdx1 = mi * 2
                  const srcIdx2 = mi * 2 + 1

                  const srcY1 = srcIdx1 * prevSlotH + prevSlotH / 2
                  const srcY2 = srcIdx2 < prevRound.matches.length
                    ? srcIdx2 * prevSlotH + prevSlotH / 2
                    : srcY1

                  const dstY = mi * totalSlotH + totalSlotH / 2

                  return (
                    <g key={mi}>
                      <line x1={0} y1={srcY1} x2={CONNECTOR_W / 2} y2={srcY1} stroke="#999" strokeWidth={1} />
                      <line x1={0} y1={srcY2} x2={CONNECTOR_W / 2} y2={srcY2} stroke="#999" strokeWidth={1} />
                      <line x1={CONNECTOR_W / 2} y1={srcY1} x2={CONNECTOR_W / 2} y2={srcY2} stroke="#999" strokeWidth={1} />
                      <line x1={CONNECTOR_W / 2} y1={dstY} x2={CONNECTOR_W} y2={dstY} stroke="#999" strokeWidth={1} />
                    </g>
                  )
                })}
              </svg>
            )}

            <div style={{ flexShrink: 0 }}>
              <div style={{
                textAlign: 'center',
                fontSize: 11,
                fontWeight: 700,
                color: '#666',
                textTransform: 'uppercase',
                letterSpacing: 1,
                marginBottom: 8,
                width: MATCH_W,
              }}>
                {round.label}
              </div>

              <div style={{ height: bracketHeight, position: 'relative' }}>
                {round.matches.map((m, mi) => (
                  <div
                    key={m.match_id}
                    style={{
                      position: 'absolute',
                      top: mi * totalSlotH + (totalSlotH - MATCH_H) / 2,
                      left: 0,
                    }}
                  >
                    <MatchCard match={m} variant={variant} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ConsolationSection({ matches }: { matches: BracketMatchBox[] }) {
  if (matches.length === 0) return null

  const { bracketMatches, standaloneMatches } = useMemo(() => {
    const matchIds = new Set(matches.map(m => m.match_id))

    // Find matches whose sources are OTHER consolation matches (bracket chain)
    const sourcedFromConsol = matches.filter(m =>
      (m.source_match_a_id && matchIds.has(m.source_match_a_id)) ||
      (m.source_match_b_id && matchIds.has(m.source_match_b_id))
    )
    const bracketChainIds = new Set<number>()

    // Add the final(s) and trace back to their sources
    for (const m of sourcedFromConsol) {
      bracketChainIds.add(m.match_id)
      if (m.source_match_a_id && matchIds.has(m.source_match_a_id))
        bracketChainIds.add(m.source_match_a_id)
      if (m.source_match_b_id && matchIds.has(m.source_match_b_id))
        bracketChainIds.add(m.source_match_b_id)
    }

    const bm = matches
      .filter(m => bracketChainIds.has(m.match_id))
      .sort((a, b) => (a.round_index - b.round_index) || (a.sequence_in_round - b.sequence_in_round))

    const sm = matches
      .filter(m => !bracketChainIds.has(m.match_id))
      .sort((a, b) => (a.round_index - b.round_index) || (a.sequence_in_round - b.sequence_in_round))

    // Re-index bracket matches for the tree: the feeder matches become round 1,
    // the match they feed into becomes round 2
    if (bm.length > 0) {
      const feeders = bm.filter(m => !bracketChainIds.has(m.source_match_a_id!) || !matchIds.has(m.source_match_a_id!))
        .filter(m => sourcedFromConsol.every(s => s.match_id !== m.match_id))
      const finals = bm.filter(m => sourcedFromConsol.some(s => s.match_id === m.match_id))

      for (const f of feeders) f.round_index = 1
      let ri = 2
      for (const f of finals) f.round_index = ri++
    }

    return { bracketMatches: bm, standaloneMatches: sm }
  }, [matches])

  return (
    <div style={{ marginTop: 40 }}>
      <div style={{
        fontSize: 13,
        fontWeight: 700,
        color: '#666',
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginBottom: 16,
      }}>
        Consolation Bracket
      </div>

      {bracketMatches.length > 0 && (
        <BracketTree
          matches={bracketMatches}
          variant="consolation"
          roundLabels={{ 1: 'Consolation Semis', 2: 'Consolation Final' }}
        />
      )}

      {standaloneMatches.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{
            fontSize: 11,
            fontWeight: 700,
            color: '#888',
            textTransform: 'uppercase',
            letterSpacing: 1,
            marginBottom: 8,
          }}>
            Drop-In Matches
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {standaloneMatches.map(m => (
              <MatchCard key={m.match_id} match={m} variant="consolation" />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function PublicBracketPage() {
  const { tournamentId, eventId, divisionCode } = useParams<{
    tournamentId: string
    eventId: string
    divisionCode: string
  }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : null
  const eid = eventId ? parseInt(eventId, 10) : null
  const dc = divisionCode?.toUpperCase() || 'BWW'
  const [searchParams] = useSearchParams()
  const versionIdParam = searchParams.get('version_id')
  const versionId = versionIdParam ? parseInt(versionIdParam, 10) : undefined

  const [data, setData] = useState<BracketResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)

  useEffect(() => {
    if (!tid || !eid) return
    setLoading(true)
    setNotPublished(false)
    getPublicBracket(tid, eid, dc, versionId)
      .then((resp: any) => {
        if (resp.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
        } else {
          setData(resp)
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [tid, eid, dc, versionId])

  const handlePrint = useCallback(() => {
    injectBracketPrintStyles()
    setTimeout(() => window.print(), 100)
  }, [])

  if (loading) {
    return (
      <div style={{ padding: 60, textAlign: 'center', color: '#666', fontSize: 16 }}>
        Loading bracket...
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

  const headerText = `${data.event_name} — ${data.division_label}`.toUpperCase()

  return (
    <div className="bracket-print-root" style={{ backgroundColor: '#f8f9fa', minHeight: '100vh' }}>
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
      {/* Nav */}
      <div className="no-print" style={{
        padding: '8px 20px',
        backgroundColor: '#fff',
        borderBottom: '1px solid #e0e0e0',
        fontSize: 13,
        color: '#555',
        display: 'flex',
        gap: 16,
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
      <div data-bracket-header style={{
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

      {/* Bracket canvas */}
      <div data-bracket-canvas style={{ overflowX: 'auto', padding: '20px 24px' }}>
        <div data-bracket-inner style={{ display: 'inline-block', minWidth: 800 }}>
          <BracketTree matches={data.main_matches} variant="main" />
          <ConsolationSection matches={data.consolation_matches} />
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { getPublicBracket, BracketResponse, BracketMatchBox } from '../../api/client'

const REFRESH_MS = 15000

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

function partitionConsolationMatches(matches: BracketMatchBox[]) {
  const matchIds = new Set(matches.map(m => m.match_id))
  const bracketChainIds = new Set<number>()
  const winnerChainMatches = matches.filter(m => {
    const fromConsol =
      (m.source_match_a_id && matchIds.has(m.source_match_a_id)) ||
      (m.source_match_b_id && matchIds.has(m.source_match_b_id))
    if (!fromConsol) return false
    const line1 = (m.line1 || '').toLowerCase()
    const line2 = (m.line2 || '').toLowerCase()
    return line1.startsWith('winner of match') || line2.startsWith('winner of match')
  })

  for (const m of winnerChainMatches) {
    bracketChainIds.add(m.match_id)
    if (m.source_match_a_id && matchIds.has(m.source_match_a_id)) {
      bracketChainIds.add(m.source_match_a_id)
    }
    if (m.source_match_b_id && matchIds.has(m.source_match_b_id)) {
      bracketChainIds.add(m.source_match_b_id)
    }
  }

  const bracketMatches = matches
    .filter(m => bracketChainIds.has(m.match_id))
    .map(m => ({ ...m }))
    .sort((a, b) => (a.round_index - b.round_index) || (a.sequence_in_round - b.sequence_in_round))

  const standaloneMatches = matches
    .filter(m => !bracketChainIds.has(m.match_id))
    .map(m => ({ ...m }))
    .sort((a, b) => (b.round_index - a.round_index) || (a.sequence_in_round - b.sequence_in_round))

  if (bracketMatches.length > 0) {
    const finals = bracketMatches.filter(m => winnerChainMatches.some(s => s.match_id === m.match_id))
    const feederIds = new Set<number>()
    for (const finalMatch of finals) {
      if (finalMatch.source_match_a_id && bracketChainIds.has(finalMatch.source_match_a_id)) {
        feederIds.add(finalMatch.source_match_a_id)
      }
      if (finalMatch.source_match_b_id && bracketChainIds.has(finalMatch.source_match_b_id)) {
        feederIds.add(finalMatch.source_match_b_id)
      }
    }
    const feeders = bracketMatches.filter(m => feederIds.has(m.match_id))

    for (const feeder of feeders) feeder.round_index = 1
    let ri = 2
    for (const finalMatch of finals) finalMatch.round_index = ri++
  }

  return { bracketMatches, standaloneMatches }
}

function MatchCard({ match, variant, showCourtInfo }: {
  match: BracketMatchBox
  variant: 'main' | 'consolation'
  showCourtInfo: boolean
}) {
  const palette = COLORS[variant]
  const isFinal = match.status === 'FINAL'

  const schedParts: string[] = []
  if (showCourtInfo && match.court_label) schedParts.push(match.court_label)
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
        <span>{`Match #${match.match_id}`}</span>
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

function MatchCardTv({ match, variant, showCourtInfo }: {
  match: BracketMatchBox
  variant: 'main' | 'consolation'
  showCourtInfo: boolean
}) {
  const palette = COLORS[variant]
  const isFinal = match.status === 'FINAL'
  const metaParts: string[] = []
  if (showCourtInfo && match.court_label) metaParts.push(match.court_label)
  if (match.time_display) metaParts.push(match.time_display)

  return (
    <div style={{
      backgroundColor: isFinal ? palette.bgFinal : palette.bg,
      border: `1px solid ${palette.border}`,
      borderRadius: 6,
      padding: '8px 10px',
      boxSizing: 'border-box',
      display: 'grid',
      gap: 4,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 10, fontWeight: 800, color: '#475467' }}>{`Match #${match.match_id}`}</span>
        {isFinal && match.score_display && (
          <span style={{ fontSize: 10, fontWeight: 800, color: '#1a237e' }}>{match.score_display}</span>
        )}
      </div>
      <div style={{ fontSize: 12, fontWeight: 800, color: '#1f2937', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {match.line1}
      </div>
      <div style={{ fontSize: 12, fontWeight: 800, color: '#1f2937', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {match.line2}
      </div>
      <div style={{ fontSize: 10, color: '#667085' }}>
        {metaParts.join(' • ') || (match.status === 'UNSCHEDULED' ? 'Pending' : 'Completed')}
      </div>
    </div>
  )
}

interface RoundColumn {
  roundIndex: number
  label: string
  matches: BracketMatchBox[]
}

function BracketTree({ matches, variant, roundLabels, showCourtInfo }: {
  matches: BracketMatchBox[]
  variant: 'main' | 'consolation'
  roundLabels?: Record<number, string>
  showCourtInfo: boolean
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
                    <MatchCard match={m} variant={variant} showCourtInfo={showCourtInfo} />
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

function ConsolationSection({ matches, showCourtInfo }: { matches: BracketMatchBox[]; showCourtInfo: boolean }) {
  if (matches.length === 0) return null

  const { bracketMatches, standaloneMatches } = useMemo(() => partitionConsolationMatches(matches), [matches])

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
          showCourtInfo={showCourtInfo}
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
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            {standaloneMatches.map(m => (
              <MatchCard key={m.match_id} match={m} variant="consolation" showCourtInfo={showCourtInfo} />
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
  const captureMode = searchParams.get('capture_packet') === '1'
  const tvMode = searchParams.get('tv') === '1'

  const [data, setData] = useState<BracketResponse | null>(null)
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
        const resp: any = await getPublicBracket(tid, eid, dc, versionId)
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
  }, [tid, eid, dc, versionId])

  const handlePrint = useCallback(() => {
    injectBracketPrintStyles()
    setTimeout(() => window.print(), 100)
  }, [])

  const showCourtInfo = data?.show_court_info !== false
  const tvMainRounds = useMemo(() => {
    const labels: Record<number, string> = { 1: 'Quarterfinals', 2: 'Semifinals', 3: 'Final' }
    if (!data) return []
    const roundMap = new Map<number, BracketMatchBox[]>()
    for (const match of data.main_matches) {
      const existing = roundMap.get(match.round_index) || []
      existing.push(match)
      roundMap.set(match.round_index, existing)
    }
    return Array.from(roundMap.entries())
      .sort(([a], [b]) => a - b)
      .map(([roundIndex, matches]) => ({
        title: labels[roundIndex] || `Round ${roundIndex}`,
        matches: matches.slice().sort((a, b) => a.sequence_in_round - b.sequence_in_round),
      }))
  }, [data])
  const tvConsolation = useMemo(
    () => partitionConsolationMatches(data?.consolation_matches || []),
    [data?.consolation_matches]
  )

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
    <div className="bracket-print-root" style={{
      backgroundColor: captureMode || tvMode ? '#fff' : '#f8f9fa',
      minHeight: captureMode ? 'auto' : '100vh',
      height: tvMode ? '100vh' : undefined,
      overflow: tvMode ? 'hidden' : undefined,
      display: tvMode ? 'flex' : undefined,
      flexDirection: tvMode ? 'column' : undefined,
    }}>
      {versionId && !captureMode && !tvMode && (
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
      <div data-bracket-header style={{
        backgroundColor: COLORS.header.bg,
        color: COLORS.header.text,
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

      {/* Bracket canvas */}
      <div data-bracket-canvas style={{
        overflowX: tvMode ? 'hidden' : 'auto',
        overflowY: tvMode ? 'hidden' : 'visible',
        padding: captureMode ? '10px 14px' : tvMode ? '10px 12px' : '20px 24px',
        flex: tvMode ? 1 : undefined,
        minHeight: tvMode ? 0 : undefined,
      }}>
        <div data-bracket-inner style={{ display: tvMode ? 'block' : 'inline-block', minWidth: captureMode ? 640 : tvMode ? 0 : 800, height: tvMode ? '100%' : undefined }}>
          {tvMode ? (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
              gridTemplateRows: 'repeat(2, minmax(0, 1fr))',
              gap: 12,
              height: '100%',
            }}>
              {[
                { title: tvMainRounds[0]?.title || 'Round 1', matches: tvMainRounds[0]?.matches || [], variant: 'main' as const },
                { title: tvMainRounds[1]?.title || 'Round 2', matches: tvMainRounds[1]?.matches || [], variant: 'main' as const },
                {
                  title: tvMainRounds.length > 2
                    ? tvMainRounds.slice(2).map((round) => round.title).join(' / ')
                    : 'Final Rounds',
                  matches: tvMainRounds.slice(2).flatMap((round) => round.matches),
                  variant: 'main' as const,
                },
                {
                  title: tvConsolation.standaloneMatches.length > 0 ? 'Drop-In Matches' : 'Consolation',
                  matches: [...tvConsolation.bracketMatches, ...tvConsolation.standaloneMatches],
                  variant: 'consolation' as const,
                },
              ].map((section, idx) => (
                <div
                  key={idx}
                  style={{
                    border: '1px solid #d9deeb',
                    borderRadius: 8,
                    backgroundColor: '#fcfdff',
                    padding: '10px',
                    minWidth: 0,
                    minHeight: 0,
                    display: 'grid',
                    alignContent: 'start',
                    gap: 8,
                    overflow: 'hidden',
                  }}
                >
                  <div style={{
                    fontSize: 12,
                    fontWeight: 800,
                    color: '#1a237e',
                    textTransform: 'uppercase',
                    letterSpacing: 0.7,
                    textAlign: 'center',
                  }}>
                    {section.title}
                  </div>
                  {section.matches.length > 0 ? (
                    <div style={{ display: 'grid', gap: 8 }}>
                      {section.matches.map((match) => (
                        <MatchCardTv
                          key={match.match_id}
                          match={match}
                          variant={section.variant}
                          showCourtInfo={showCourtInfo}
                        />
                      ))}
                    </div>
                  ) : (
                    <div style={{
                      minHeight: 80,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#90a4ae',
                      fontSize: 12,
                      textTransform: 'uppercase',
                      letterSpacing: 0.6,
                    }}>
                      No Matches
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <>
              <BracketTree matches={data.main_matches} variant="main" showCourtInfo={showCourtInfo} />
              <ConsolationSection matches={data.consolation_matches} showCourtInfo={showCourtInfo} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

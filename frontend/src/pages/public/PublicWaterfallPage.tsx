import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { getPublicWaterfall, PublicWaterfallResponse, PublicMatchBox } from '../../api/client'

const REFRESH_MS = 15000

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
const DEST_BOX_WIDTH = 200
const CONNECTOR_WIDTH = 32
const WATERFALL_BASE_WIDTH =
  (DEST_BOX_WIDTH * 2) +
  (SIDE_BOX_WIDTH * 2) +
  CENTER_BOX_WIDTH +
  (CONNECTOR_WIDTH * 4)

type WaterfallLayout = {
  scale: number
  centerBoxWidth: number
  sideBoxWidth: number
  destBoxWidth: number
  connectorWidth: number
  matchFontSize: number
  teamFontSize: number
  topLineFontSize: number
  badgeFontSize: number
  vsFontSize: number
  notesFontSize: number
  cardPaddingY: number
  cardPaddingX: number
  rowGap: number
  rowMarginBottom: number
  rowMinHeight: number
  destPaddingY: number
  destPaddingX: number
  destFontSize: number
  destTeamFontSize: number
  headerFontSize: number
  headerGap: number
}

function stripTvLocationSuffix(text: string | null | undefined): string {
  if (!text) return ''
  return text.replace(/,\s*[^,]+,\s*[A-Z]{2}\s*$/, '').trim()
}

function shortenTvPersonName(text: string): string {
  const trimmed = text.trim()
  if (!trimmed) return ''
  if (
    /^(winner|loser)\s+of\b/i.test(trimmed) ||
    /^seed\b/i.test(trimmed) ||
    /^(tbd|bye)\b/i.test(trimmed)
  ) {
    return trimmed
  }
  const [firstWord] = trimmed.split(/\s+/)
  return firstWord || trimmed
}

function shortenTvTeamLine(text: string | null | undefined): string {
  if (!text) return ''
  return text
    .split(/\s*\/\s*/)
    .map((segment) => shortenTvPersonName(stripTvLocationSuffix(segment)))
    .join(' / ')
}

function buildWaterfallLayout(scale: number, canvasWidth: number): WaterfallLayout {
  const isPhone = canvasWidth <= 520
  const isCompact = canvasWidth <= 900
  const minScale = isPhone ? 0.19 : isCompact ? 0.34 : 0.58
  const s = Math.min(Math.max(scale, minScale), 1)
  const px = (value: number, min: number) => Math.max(min, Math.round(value * s))
  const fp = (value: number, min: number) => Math.max(min, Number((value * s).toFixed(1)))
  return {
    scale: s,
    centerBoxWidth: px(CENTER_BOX_WIDTH, isPhone ? 88 : isCompact ? 140 : 250),
    sideBoxWidth: px(SIDE_BOX_WIDTH, isPhone ? 62 : isCompact ? 98 : 180),
    destBoxWidth: px(DEST_BOX_WIDTH, isPhone ? 36 : isCompact ? 58 : 110),
    connectorWidth: px(CONNECTOR_WIDTH, isPhone ? 6 : isCompact ? 10 : 16),
    matchFontSize: fp(12, isPhone ? 5.6 : isCompact ? 7.2 : 9),
    teamFontSize: fp(11, isPhone ? 5.2 : isCompact ? 6.8 : 8.5),
    topLineFontSize: fp(11, isPhone ? 5.2 : isCompact ? 6.8 : 8.5),
    badgeFontSize: fp(9, isPhone ? 4.8 : isCompact ? 5.8 : 7),
    vsFontSize: fp(10, isPhone ? 4.8 : isCompact ? 6 : 7.5),
    notesFontSize: fp(9, isPhone ? 4.8 : isCompact ? 5.8 : 7),
    cardPaddingY: px(6, isPhone ? 2 : 3),
    cardPaddingX: px(10, isPhone ? 3 : 5),
    rowGap: px(2, 1),
    rowMarginBottom: px(18, isPhone ? 5 : 8),
    rowMinHeight: px(90, isPhone ? 30 : isCompact ? 40 : 52),
    destPaddingY: px(8, isPhone ? 2 : 4),
    destPaddingX: px(10, isPhone ? 3 : 5),
    destFontSize: fp(10, isPhone ? 5 : isCompact ? 6.2 : 7.5),
    destTeamFontSize: fp(11, isPhone ? 5.2 : isCompact ? 6.5 : 8.5),
    headerFontSize: fp(11, isPhone ? 5.8 : isCompact ? 7.2 : 8.5),
    headerGap: px(6, isPhone ? 2 : 4),
  }
}

function MatchBoxCard({ box, variant, layout, widthOverride, heightOverride, tvMode = false }: {
  box: PublicMatchBox
  variant: 'center' | 'winner' | 'loser'
  layout: WaterfallLayout
  widthOverride?: number | string
  heightOverride?: number | string
  tvMode?: boolean
}) {
  const palette = COLORS[variant]
  const isFinal = box.status === 'FINAL'
  const isCenter = variant === 'center'
  const winnerId = box.winner_team_id
  const line1IsWinner = isFinal && winnerId != null && box.team_a_id === winnerId
  const line2IsWinner = isFinal && winnerId != null && box.team_b_id === winnerId
  const topLineFontSize = tvMode
    ? Math.max(layout.topLineFontSize * 1.6, layout.topLineFontSize + 3.5)
    : layout.topLineFontSize
  const badgeFontSize = tvMode
    ? Math.max(layout.badgeFontSize * 1.2, layout.badgeFontSize + 1)
    : layout.badgeFontSize
  const teamFontSize = tvMode
    ? Math.max(layout.teamFontSize * 1.85, layout.teamFontSize + 5)
    : layout.teamFontSize
  const vsFontSize = tvMode
    ? Math.max(layout.vsFontSize * 1.2, layout.vsFontSize + 1.2)
    : layout.vsFontSize
  const notesFontSize = tvMode
    ? Math.max(layout.notesFontSize * 1.5, layout.notesFontSize + 2)
    : layout.notesFontSize
  const line1 = tvMode ? shortenTvTeamLine(box.line1) : box.line1
  const line2 = tvMode ? shortenTvTeamLine(box.line2) : box.line2
  const notes = tvMode ? stripTvLocationSuffix(box.notes) : box.notes

  return (
    <div style={{
      backgroundColor: isFinal ? palette.bgFinal : palette.bg,
      border: `1px solid ${palette.border}`,
      borderRadius: 3,
      padding: `${layout.cardPaddingY}px ${layout.cardPaddingX}px`,
      width: widthOverride ?? (isCenter ? layout.centerBoxWidth : layout.sideBoxWidth),
      height: heightOverride,
      boxSizing: 'border-box',
      fontSize: layout.matchFontSize,
      lineHeight: tvMode ? 1.25 : 1.4,
      position: 'relative',
      textAlign: 'center',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
    }} data-match-box>
      {/* Top line: match number + court/time or score */}
      <div style={{
        fontWeight: 700,
        fontSize: topLineFontSize,
        color: '#333',
        marginBottom: tvMode ? 5 : 3,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: layout.headerGap,
        flexWrap: tvMode ? 'nowrap' : 'wrap',
        whiteSpace: tvMode ? 'nowrap' : undefined,
        overflow: tvMode ? 'hidden' : undefined,
        textOverflow: tvMode ? 'ellipsis' : undefined,
      }}>
        {box.top_line && <span>{box.top_line}</span>}
        {isFinal && (
          <span style={{
            fontSize: badgeFontSize,
            fontWeight: 700,
            color: '#2e7d32',
            backgroundColor: '#c8e6c9',
            padding: `${Math.max(1, Math.round(layout.cardPaddingY / 3))}px ${Math.max(3, Math.round(layout.cardPaddingX / 2))}px`,
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
        fontSize: teamFontSize,
        fontWeight: line1IsWinner ? 800 : 600,
        whiteSpace: tvMode ? 'nowrap' : undefined,
        overflow: tvMode ? 'hidden' : undefined,
        textOverflow: tvMode ? 'ellipsis' : undefined,
      }}>
        {line1IsWinner && <span style={{ fontSize: badgeFontSize, marginRight: 4 }}>&#9654;</span>}
        {line1}
      </div>
      <div data-vs style={{ fontSize: vsFontSize, color: '#999', fontWeight: 600, fontStyle: 'italic', margin: tvMode ? '3px 0' : '1px 0' }}>
        vs
      </div>
      <div style={{
        color: line2IsWinner ? '#1b5e20' : '#222',
        fontSize: teamFontSize,
        fontWeight: line2IsWinner ? 800 : 600,
        whiteSpace: tvMode ? 'nowrap' : undefined,
        overflow: tvMode ? 'hidden' : undefined,
        textOverflow: tvMode ? 'ellipsis' : undefined,
      }}>
        {line2IsWinner && <span style={{ fontSize: badgeFontSize, marginRight: 4 }}>&#9654;</span>}
        {line2}
      </div>

      {/* Notes */}
      {notes && (
        <div style={{
          fontSize: notesFontSize,
          color: '#888',
          marginTop: tvMode ? 5 : 2,
          fontStyle: 'italic',
          whiteSpace: tvMode ? 'nowrap' : undefined,
          overflow: tvMode ? 'hidden' : undefined,
          textOverflow: tvMode ? 'ellipsis' : undefined,
        }}>
          {notes}
        </div>
      )}
    </div>
  )
}

// ── Arrow connector ─────────────────────────────────────────────────────

function ArrowConnector({ direction, layout }: { direction: 'left' | 'right'; layout: WaterfallLayout }) {
  const isLeft = direction === 'left'
  return (
    <div data-connector style={{
      width: layout.connectorWidth,
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
        borderTop: `${Math.max(3, Math.round(layout.connectorWidth * 0.16))}px solid transparent`,
        borderBottom: `${Math.max(3, Math.round(layout.connectorWidth * 0.16))}px solid transparent`,
        ...(isLeft
          ? { borderRight: `${Math.max(5, Math.round(layout.connectorWidth * 0.25))}px solid #999` }
          : { borderLeft: `${Math.max(5, Math.round(layout.connectorWidth * 0.25))}px solid #999` }),
      }} />
    </div>
  )
}

function isByeBox(box: PublicMatchBox | null): boolean {
  if (!box) return false
  return /^\s*bye\s*$/i.test(box.line2 || '') || /^\s*bye\s*$/i.test(box.line1 || '')
}

// A left-pointing line (with arrowhead) representing a loser exiting a match.
function LoserExitLine({ layout }: { layout: WaterfallLayout }) {
  return (
    <div style={{ position: 'relative', width: '100%', display: 'flex', alignItems: 'center' }}>
      <div style={{ width: '100%', height: 1, backgroundColor: '#c0392b' }} />
      <div style={{
        position: 'absolute',
        left: 0,
        width: 0,
        height: 0,
        borderTop: `${Math.max(3, Math.round(layout.connectorWidth * 0.16))}px solid transparent`,
        borderBottom: `${Math.max(3, Math.round(layout.connectorWidth * 0.16))}px solid transparent`,
        borderRight: `${Math.max(5, Math.round(layout.connectorWidth * 0.25))}px solid #c0392b`,
      }} />
    </div>
  )
}

// Full-width left column of loser-exit lines, one per real (non-bye) R1 box.
function LoserExitLines({ boxes, width, layout }: {
  boxes: (PublicMatchBox | null)[]
  width: number
  layout: WaterfallLayout
}) {
  const lanes = boxes.filter((b): b is PublicMatchBox => Boolean(b))
  return (
    <div style={{ width, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: layout.rowGap }}>
      {lanes.map((box, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
          {!isByeBox(box) && <LoserExitLine layout={layout} />}
        </div>
      ))}
    </div>
  )
}

const DIV_CODE_MAP: Record<string, string> = {
  'Division I': 'BWW',
  'Division II': 'BWL',
  'Division III': 'BLW',
  'Division IV': 'BLL',
}

// ── Destination label box ───────────────────────────────────────────────

function DestinationBox({
  label,
  teamName,
  winnerPathTeamName,
  loserPathTeamName,
  tournamentId,
  eventId,
  divisionType,
  layout,
  widthOverride,
}: {
  label: string
  /** Round-robin pool dest, or legacy single name when path names omitted */
  /** Round-robin / legacy: single name above destination lines. */
  teamName: string | null
  /** Bracket: team for the "Winner to Division …" line (under that line). */
  winnerPathTeamName?: string | null
  /** Bracket: team for the "Loser to Division …" line (under that line). */
  loserPathTeamName?: string | null
  tournamentId: number | null
  eventId: number | null
  divisionType: 'bracket' | 'roundrobin'
  layout: WaterfallLayout
  widthOverride?: number | string
}) {
  const navigate = useNavigate()
  const lines = label.split('\n')
  const useBracketPaths =
    divisionType === 'bracket' &&
    (Boolean(winnerPathTeamName?.trim()) || Boolean(loserPathTeamName?.trim()))

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
      width: widthOverride ?? layout.destBoxWidth,
      padding: `${layout.destPaddingY}px ${layout.destPaddingX}px`,
      fontSize: layout.destFontSize,
      fontWeight: 600,
      backgroundColor: '#f5f5f5',
      border: '1px dashed #ccc',
      borderRadius: 3,
      textAlign: 'center',
      boxSizing: 'border-box',
      display: 'flex',
      flexDirection: 'column',
      gap: layout.headerGap,
    }} data-dest-box>
      {!useBracketPaths && teamName && (
        <div style={{
          color: '#1b5e20',
          fontWeight: 700,
          fontSize: layout.destTeamFontSize,
          lineHeight: 1.3,
          paddingBottom: Math.max(2, Math.round(layout.destPaddingY / 2)),
          borderBottom: '1px solid #e0e0e0',
        }}>
          {teamName}
        </div>
      )}
      {lines.map((line, i) => (
        <div key={i}>
          <div
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
          {useBracketPaths && i === 0 && winnerPathTeamName?.trim() && (
            <div style={{
              color: '#1b5e20',
              fontWeight: 700,
              fontSize: layout.destTeamFontSize,
              lineHeight: 1.3,
              marginTop: 2,
              marginBottom: Math.max(4, Math.round(layout.destPaddingY / 2)),
            }}>
              {winnerPathTeamName}
            </div>
          )}
          {useBracketPaths && i === 1 && loserPathTeamName?.trim() && (
            <div style={{
              color: '#1b5e20',
              fontWeight: 700,
              fontSize: layout.destTeamFontSize,
              lineHeight: 1.3,
              marginTop: 2,
            }}>
              {loserPathTeamName}
            </div>
          )}
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
  r2_winner_bracket_winner_name: string | null
  r2_winner_bracket_loser_name: string | null
  r2_loser_bracket_winner_name: string | null
  r2_loser_bracket_loser_name: string | null
}

function splitIntoBalancedColumns<T>(items: T[], columnCount: number): T[][] {
  if (columnCount <= 1 || items.length === 0) return [items]

  const columns: T[][] = []
  let start = 0
  for (let idx = 0; idx < columnCount; idx += 1) {
    const remainingItems = items.length - start
    const remainingColumns = columnCount - idx
    const size = Math.ceil(remainingItems / remainingColumns)
    columns.push(items.slice(start, start + size))
    start += size
  }
  return columns.filter((column) => column.length > 0)
}

function WaterfallRowPair({ pair, tournamentId, eventId, divisionType, layout }: {
  pair: RowPair
  tournamentId: number | null
  eventId: number | null
  divisionType: 'bracket' | 'roundrobin'
  layout: WaterfallLayout
}) {
  const hasLoserBracket = Boolean(pair.loser) || Boolean(pair.loser_dest)

  return (
    <div data-row-pair style={{
      display: 'flex',
      alignItems: 'stretch',
      justifyContent: 'center',
      marginBottom: layout.rowMarginBottom,
      minHeight: layout.rowMinHeight,
    }}>
      {hasLoserBracket ? (
        <>
          {/* Loser destination (far left) */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            width: layout.destBoxWidth,
            flexShrink: 0,
          }}>
            {pair.loser_dest && (
              <DestinationBox
                label={pair.loser_dest}
                teamName={pair.r2_loser_team_name}
                winnerPathTeamName={pair.r2_loser_bracket_winner_name}
                loserPathTeamName={pair.r2_loser_bracket_loser_name}
                tournamentId={tournamentId}
                eventId={eventId}
                divisionType={divisionType}
                layout={layout}
              />
            )}
          </div>

          {/* Arrow: destination ← loser box */}
          {pair.loser_dest && <ArrowConnector direction="left" layout={layout} />}
          {!pair.loser_dest && <div style={{ width: layout.connectorWidth, flexShrink: 0 }} />}

          {/* Loser box (left) */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            width: layout.sideBoxWidth,
            flexShrink: 0,
          }}>
            {pair.loser ? <MatchBoxCard box={pair.loser} variant="loser" layout={layout} /> : <div style={{ width: layout.sideBoxWidth }} />}
          </div>

          {/* Arrow: loser ← center */}
          <ArrowConnector direction="left" layout={layout} />
        </>
      ) : (
        /* No loser bracket: draw a loser-exit line out of each real R1 match. */
        <LoserExitLines
          boxes={[pair.r1_a, pair.r1_b]}
          width={layout.destBoxWidth + layout.sideBoxWidth + layout.connectorWidth * 2}
          layout={layout}
        />
      )}

      {/* Center column: two R1 boxes stacked */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: layout.rowGap,
        justifyContent: 'center',
        flexShrink: 0,
        width: layout.centerBoxWidth,
      }}>
        <MatchBoxCard box={pair.r1_a} variant="center" layout={layout} />
        {pair.r1_b && <MatchBoxCard box={pair.r1_b} variant="center" layout={layout} />}
      </div>

      {/* Arrow: center → winner */}
      <ArrowConnector direction="right" layout={layout} />

      {/* Winner box (right) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        width: layout.sideBoxWidth,
        flexShrink: 0,
      }}>
        {pair.winner ? <MatchBoxCard box={pair.winner} variant="winner" layout={layout} /> : <div style={{ width: layout.sideBoxWidth }} />}
      </div>

      {/* Arrow: winner → destination */}
      {pair.winner_dest && <ArrowConnector direction="right" layout={layout} />}
      {!pair.winner_dest && <div style={{ width: layout.connectorWidth, flexShrink: 0 }} />}

      {/* Winner destination (far right) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        width: layout.destBoxWidth,
        flexShrink: 0,
      }}>
        {pair.winner_dest && (
          <DestinationBox
            label={pair.winner_dest}
            teamName={pair.r2_winner_team_name}
            winnerPathTeamName={pair.r2_winner_bracket_winner_name}
            loserPathTeamName={pair.r2_winner_bracket_loser_name}
            tournamentId={tournamentId}
            eventId={eventId}
            divisionType={divisionType}
            layout={layout}
          />
        )}
      </div>
    </div>
  )
}

function WaterfallRowPairCompact({
  pair,
  tournamentId,
  eventId,
  divisionType,
  layout,
  availableWidth,
  tvMode = false,
}: {
  pair: RowPair
  tournamentId: number | null
  eventId: number | null
  divisionType: 'bracket' | 'roundrobin'
  layout: WaterfallLayout
  availableWidth: number
  tvMode?: boolean
}) {
  const laneWidth = tvMode
    ? Math.max(Math.min(availableWidth - 16, 360), 220)
    : Math.max(Math.min(availableWidth - 20, 420), 260)
  const sectionLabelStyle = {
    fontSize: Math.max(layout.destFontSize, tvMode ? 10 : 9),
    fontWeight: 700,
    color: '#666',
    textTransform: 'uppercase' as const,
    letterSpacing: 0.6,
    marginBottom: tvMode ? 2 : 4,
  }

  return (
    <div
      data-row-pair
      style={{
        display: 'grid',
        gap: tvMode ? Math.max(layout.headerGap, 4) : Math.max(layout.rowMarginBottom, 10),
        justifyItems: 'center',
        marginBottom: tvMode ? Math.max(layout.headerGap + 4, 8) : Math.max(layout.rowMarginBottom + 6, 14),
      }}
    >
      <div style={{ display: 'grid', gap: layout.rowGap, justifyItems: 'center', width: '100%' }}>
        <div style={sectionLabelStyle}>WF Round 1</div>
        <MatchBoxCard box={pair.r1_a} variant="center" layout={layout} widthOverride={laneWidth} />
        {pair.r1_b && <MatchBoxCard box={pair.r1_b} variant="center" layout={layout} widthOverride={laneWidth} />}
      </div>

      {pair.loser && (
        <div style={{ display: 'grid', gap: Math.max(layout.headerGap, 6), justifyItems: 'center', width: '100%' }}>
          <div style={sectionLabelStyle}>Loser Path</div>
          <MatchBoxCard box={pair.loser} variant="loser" layout={layout} widthOverride={laneWidth} />
          {pair.loser_dest && (
            <DestinationBox
              label={pair.loser_dest}
              teamName={pair.r2_loser_team_name}
              winnerPathTeamName={pair.r2_loser_bracket_winner_name}
              loserPathTeamName={pair.r2_loser_bracket_loser_name}
              tournamentId={tournamentId}
              eventId={eventId}
              divisionType={divisionType}
              layout={layout}
              widthOverride={laneWidth}
            />
          )}
        </div>
      )}

      {pair.winner && (
        <div style={{ display: 'grid', gap: Math.max(layout.headerGap, 6), justifyItems: 'center', width: '100%' }}>
          <div style={sectionLabelStyle}>Winner Path</div>
          <MatchBoxCard box={pair.winner} variant="winner" layout={layout} widthOverride={laneWidth} />
          {pair.winner_dest && (
            <DestinationBox
              label={pair.winner_dest}
              teamName={pair.r2_winner_team_name}
              winnerPathTeamName={pair.r2_winner_bracket_winner_name}
              loserPathTeamName={pair.r2_winner_bracket_loser_name}
              tournamentId={tournamentId}
              eventId={eventId}
              divisionType={divisionType}
              layout={layout}
              widthOverride={laneWidth}
            />
          )}
        </div>
      )}
    </div>
  )
}

type TvWaterfallEntry = {
  box: PublicMatchBox
  variant: 'center' | 'winner' | 'loser'
}

function WaterfallTvColumn({
  title,
  entries,
  layout,
  cardWidth,
}: {
  title: string
  entries: TvWaterfallEntry[]
  layout: WaterfallLayout
  cardWidth: number
}) {
  return (
    <div
      style={{
        minWidth: 0,
        minHeight: 0,
        height: '100%',
        border: '1px solid #d9deeb',
        borderRadius: 8,
        backgroundColor: '#fcfdff',
        padding: '6px 8px',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{
        fontSize: Math.max(layout.headerFontSize, 13),
        fontWeight: 700,
        color: '#1a237e',
        textTransform: 'uppercase',
        letterSpacing: 0.8,
        textAlign: 'center',
      }}>
        {title}
      </div>
      {entries.length > 0 ? (
        <div
          style={{
            display: 'grid',
            gridTemplateRows: `repeat(${entries.length}, minmax(0, 1fr))`,
            gap: 6,
            justifyItems: 'center',
            alignItems: 'stretch',
            flex: 1,
            minHeight: 0,
          }}
        >
          {entries.map((entry, idx) => (
            <div key={`${entry.box.match_id}-${idx}`} style={{ width: '100%', display: 'flex', justifyContent: 'center', minHeight: 0 }}>
              <MatchBoxCard
                box={entry.box}
                variant={entry.variant}
                layout={layout}
                widthOverride={cardWidth}
                heightOverride="100%"
                tvMode
              />
            </div>
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
  const captureMode = searchParams.get('capture_packet') === '1'
  const displayFitMode = searchParams.get('display_fit') === '1'
  const tvMode = searchParams.get('tv') === '1'

  const [data, setData] = useState<PublicWaterfallResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const [canvasWidth, setCanvasWidth] = useState<number>(WATERFALL_BASE_WIDTH)

  useEffect(() => {
    if (!tid || !eid) return
    let cancelled = false

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true)
      setNotPublished(false)
      setError(null)
      try {
        const resp: any = await getPublicWaterfall(tid, eid, versionId)
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
        r2_winner_bracket_winner_name: rowA.r2_winner_bracket_winner_name ?? null,
        r2_winner_bracket_loser_name: rowA.r2_winner_bracket_loser_name ?? null,
        r2_loser_bracket_winner_name: rowA.r2_loser_bracket_winner_name ?? null,
        r2_loser_bracket_loser_name: rowA.r2_loser_bracket_loser_name ?? null,
      })
    }

    return pairs
  }, [data])
  const tvRoundOneEntries = useMemo<TvWaterfallEntry[]>(
    () => rowPairs.flatMap((pair) => {
      const entries: TvWaterfallEntry[] = [{ box: pair.r1_a, variant: 'center' }]
      if (pair.r1_b) entries.push({ box: pair.r1_b, variant: 'center' })
      return entries
    }),
    [rowPairs]
  )
  const tvWinnerEntries = useMemo<TvWaterfallEntry[]>(
    () => rowPairs.flatMap((pair) => pair.winner ? [{ box: pair.winner, variant: 'winner' }] : []),
    [rowPairs]
  )
  const tvLoserEntries = useMemo<TvWaterfallEntry[]>(
    () => rowPairs.flatMap((pair) => pair.loser ? [{ box: pair.loser, variant: 'loser' }] : []),
    [rowPairs]
  )
  const tvSecondRoundEntries = useMemo<TvWaterfallEntry[]>(
    () => rowPairs.flatMap((pair) => {
      const entries: TvWaterfallEntry[] = []
      if (pair.winner) entries.push({ box: pair.winner, variant: 'winner' })
      if (pair.loser) entries.push({ box: pair.loser, variant: 'loser' })
      return entries
    }),
    [rowPairs]
  )
  const tvUseFourColumns = tvMode

  const handlePrint = useCallback(() => {
    injectPrintStyles()
    setTimeout(() => window.print(), 100)
  }, [])

  useEffect(() => {
    const node = canvasRef.current
    if (!node) return
    const recompute = () => {
      setCanvasWidth(Math.max(node.clientWidth, 320))
    }
    recompute()
    const observer = new ResizeObserver(recompute)
    observer.observe(node)
    window.addEventListener('resize', recompute)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', recompute)
    }
  }, [])

  useEffect(() => {
    if (!displayFitMode) return
    const html = document.documentElement
    const body = document.body
    const prevHtmlOverflowX = html.style.overflowX
    const prevBodyOverflowX = body.style.overflowX
    html.style.overflowX = 'hidden'
    body.style.overflowX = 'hidden'
    return () => {
      html.style.overflowX = prevHtmlOverflowX
      body.style.overflowX = prevBodyOverflowX
    }
  }, [displayFitMode])

  const useCompactWaterfallLayout = displayFitMode || (!captureMode && canvasWidth <= 520)
  const layout = captureMode
    ? buildWaterfallLayout(1, WATERFALL_BASE_WIDTH)
    : tvMode
      ? buildWaterfallLayout(tvUseFourColumns ? 0.58 : 0.68, Math.max(canvasWidth / (tvUseFourColumns ? 4 : 2), 260))
    : buildWaterfallLayout((canvasWidth - 8) / WATERFALL_BASE_WIDTH, canvasWidth)
  const compactColumnCount = useMemo(() => {
    if (!displayFitMode) return 1
    if (rowPairs.length >= 10 && canvasWidth >= 1080) return 3
    if (rowPairs.length >= 5) return 2
    return 1
  }, [displayFitMode, rowPairs.length, canvasWidth])
  const compactColumns = useMemo(
    () => splitIntoBalancedColumns(rowPairs, compactColumnCount),
    [rowPairs, compactColumnCount]
  )
  const compactGridGap = Math.max(layout.rowMarginBottom, 14)
  const compactColumnWidth = compactColumnCount > 0
      ? Math.max((canvasWidth - (compactGridGap * (compactColumnCount - 1))) / compactColumnCount, 280)
      : canvasWidth
  const tvColumnCount = tvUseFourColumns ? 4 : 2
  const tvColumnGap = 8
  const tvColumnWidth = Math.max((canvasWidth - (tvColumnGap * (tvColumnCount - 1))) / tvColumnCount, 220)
  const tvCardWidth = Math.max(
    Math.min(tvColumnWidth - 2, tvUseFourColumns ? 315 : 520),
    tvUseFourColumns ? 250 : 360
  )
  const tvRoundOneColumns = useMemo(
    () => splitIntoBalancedColumns(tvRoundOneEntries, tvUseFourColumns ? 2 : 1),
    [tvRoundOneEntries, tvUseFourColumns]
  )
  const tvColumns = useMemo(() => {
    if (!tvMode) return []
    if (tvUseFourColumns) {
      return [
        { title: 'WF Round 1', entries: tvRoundOneColumns[0] || [] },
        { title: 'WF Round 1', entries: tvRoundOneColumns[1] || [] },
        { title: 'Round 2 Winners', entries: tvWinnerEntries },
        { title: 'Round 2 Losers', entries: tvLoserEntries },
      ]
    }
    return [
      { title: 'WF Round 1', entries: tvRoundOneEntries },
      { title: 'WF Round 2', entries: tvSecondRoundEntries },
    ]
  }, [tvMode, tvUseFourColumns, tvRoundOneColumns, tvWinnerEntries, tvLoserEntries, tvRoundOneEntries, tvSecondRoundEntries])

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
    <div className="print-root" style={{
      backgroundColor: captureMode || displayFitMode || tvMode ? '#fff' : '#f8f9fa',
      minHeight: captureMode || displayFitMode ? 'auto' : '100vh',
      height: tvMode ? '100vh' : undefined,
      overflow: tvMode ? 'hidden' : undefined,
      display: tvMode ? 'flex' : undefined,
      flexDirection: tvMode ? 'column' : undefined,
    }}>
      {versionId && !captureMode && !displayFitMode && !tvMode && (
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
        ...((captureMode || displayFitMode || tvMode) ? { display: 'none' } : {}),
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

      {/* Bracket canvas: fixed width, horizontal scroll on mobile */}
      <div
        ref={canvasRef}
        data-bracket-canvas
        style={{
          overflowX: captureMode ? 'visible' : 'hidden',
          overflowY: tvMode ? 'hidden' : 'visible',
          padding: captureMode
            ? '10px 8px'
            : tvMode
              ? '10px 12px'
            : canvasWidth <= 520
              ? '12px 6px'
              : canvasWidth <= 900
                ? '16px 10px'
                : '20px 16px',
          flex: tvMode ? 1 : undefined,
          minHeight: tvMode ? 0 : undefined,
        }}
      >
        <div data-bracket-inner style={{
          width: '100%',
          minWidth: 0,
          maxWidth: captureMode ? 1900 : tvMode ? 'none' : WATERFALL_BASE_WIDTH,
          margin: '0 auto',
          height: tvMode ? '100%' : undefined,
          display: tvMode ? 'flex' : undefined,
          flexDirection: tvMode ? 'column' : undefined,
        }}>
          {!tvMode && (
            <div style={{
            marginBottom: 12,
            padding: '10px 12px',
            border: '1px solid #dce775',
            borderRadius: 6,
            backgroundColor: '#f9fbe7',
            color: '#455a64',
            fontSize: 11,
          }}>
            <div style={{ fontWeight: 700, color: '#33691e', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.3 }}>
              WF Pool Tiebreaker Rules
            </div>
            <ol style={{ margin: '0 0 0 18px', padding: 0, lineHeight: 1.5 }}>
              <li>WF wins</li>
              <li>WF Match #2 game difference</li>
              <li>WF Match #1 &amp; #2 combined game difference</li>
              <li>Combined Ratings</li>
            </ol>
            </div>
          )}

          {!tvMode && !useCompactWaterfallLayout && (
            <div data-col-headers style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 10,
              fontSize: layout.headerFontSize,
              fontWeight: 700,
              color: '#666',
              textTransform: 'uppercase',
              letterSpacing: 1,
            }}>
              <div style={{ width: layout.destBoxWidth, flexShrink: 0 }} />
              <div style={{ width: layout.connectorWidth, flexShrink: 0 }} />
              <div style={{ width: layout.sideBoxWidth, textAlign: 'center', flexShrink: 0 }}>
                Round 1 Loser
              </div>
              <div style={{ width: layout.connectorWidth, flexShrink: 0 }} />
              <div style={{ width: layout.centerBoxWidth, textAlign: 'center', flexShrink: 0 }}>
                WF Round 1
              </div>
              <div style={{ width: layout.connectorWidth, flexShrink: 0 }} />
              <div style={{ width: layout.sideBoxWidth, textAlign: 'center', flexShrink: 0 }}>
                Round 1 Winner
              </div>
              <div style={{ width: layout.connectorWidth, flexShrink: 0 }} />
              <div style={{ width: layout.destBoxWidth, flexShrink: 0 }} />
            </div>
          )}

          {/* Row pairs */}
          {tvMode ? (
            <div style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${tvColumnCount}, minmax(0, 1fr))`,
              gap: tvColumnGap,
              alignItems: 'stretch',
              flex: 1,
              minHeight: 0,
            }}>
              {tvColumns.map((column, idx) => (
                <WaterfallTvColumn
                  key={`${column.title}-${idx}`}
                  title={column.title}
                  entries={column.entries}
                  layout={layout}
                  cardWidth={tvCardWidth}
                />
              ))}
            </div>
          ) : useCompactWaterfallLayout ? (
            compactColumnCount > 1 ? (
              <div style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${compactColumnCount}, minmax(0, 1fr))`,
                gap: compactGridGap,
                alignItems: 'start',
              }}>
                {compactColumns.map((column, columnIdx) => (
                  <div
                    key={columnIdx}
                    style={{
                      minWidth: 0,
                    }}
                  >
                    <div style={{
                      fontSize: Math.max(layout.headerFontSize, 10),
                      fontWeight: 700,
                      color: '#666',
                      textTransform: 'uppercase',
                      letterSpacing: 0.8,
                      textAlign: 'center',
                      marginBottom: Math.max(layout.headerGap + 4, 8),
                    }}>
                      Section {columnIdx + 1}
                    </div>
                    {column.map((pair, pairIdx) => (
                      <WaterfallRowPairCompact
                        key={`${columnIdx}-${pairIdx}`}
                        pair={pair}
                        tournamentId={tid}
                        eventId={eid}
                        divisionType={data.division_type || 'bracket'}
                        layout={layout}
                        availableWidth={compactColumnWidth}
                      />
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              rowPairs.map((pair, idx) => (
                <WaterfallRowPairCompact
                  key={idx}
                  pair={pair}
                  tournamentId={tid}
                  eventId={eid}
                  divisionType={data.division_type || 'bracket'}
                  layout={layout}
                  availableWidth={canvasWidth}
                />
              ))
            )
          ) : (
            rowPairs.map((pair, idx) => (
              <WaterfallRowPair
                key={idx}
                pair={pair}
                tournamentId={tid}
                eventId={eid}
                divisionType={data.division_type || 'bracket'}
                layout={layout}
              />
            ))
          )}

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

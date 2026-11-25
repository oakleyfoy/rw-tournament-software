import type { DeskMatchItem } from '../../api/client'
import { isOpeningMatch, type CourtColumn } from './courtSheet'

type DesignatedCourtSheetProps = {
  columns: CourtColumn[]
  isDraft: boolean
  busyMatchId: number | null
  onOpenMatch: (match: DeskMatchItem) => void
  onStart: (matchId: number) => void
  onMove: (matchId: number, courtName: string) => void
}

function MatchLines({ match }: { match: DeskMatchItem }) {
  return (
    <>
      <div style={{ fontSize: 12, fontWeight: 800 }}>
        #{match.match_number}{match.scheduled_time ? ` · ${match.scheduled_time}` : ''}
      </div>
      <div style={{ fontSize: 12, marginTop: 4 }}>{match.team1_display || 'TBD'}</div>
      <div style={{ fontSize: 10, opacity: 0.7 }}>vs</div>
      <div style={{ fontSize: 12 }}>{match.team2_display || 'TBD'}</div>
    </>
  )
}

export default function DesignatedCourtSheet({
  columns,
  isDraft,
  busyMatchId,
  onOpenMatch,
  onStart,
  onMove,
}: DesignatedCourtSheetProps) {
  if (columns.length === 0) {
    return <div style={{ fontSize: 13, color: '#90a4ae' }}>No courts are on this day yet.</div>
  }

  return (
    <div
      data-testid="court-sheet"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
        gap: 10,
        alignItems: 'start',
      }}
    >
      {columns.map((column) => {
        const dark = column.blackedOut
        const ink = dark ? '#eceff1' : '#263238'
        const muted = dark ? '#b0bec5' : '#607d8b'
        return (
          <div
            key={column.courtName}
            data-court-column={column.courtName}
            onDragOver={(event) => {
              event.preventDefault()
            }}
            onDrop={(event) => {
              event.preventDefault()
              const matchId = Number(event.dataTransfer.getData('text/match-id'))
              if (!matchId) return
              onMove(matchId, column.courtName)
            }}
            style={{
              borderRadius: 8,
              overflow: 'hidden',
              border: dark ? '1px solid #263238' : '1px solid #cfd8dc',
              background: dark ? '#263238' : '#fff',
              color: ink,
              minHeight: 120,
            }}
          >
            <div style={{
              padding: '8px 10px',
              fontWeight: 800,
              fontSize: 14,
              display: 'flex',
              justifyContent: 'space-between',
              gap: 8,
              background: dark ? '#1c262b' : '#f4f7f8',
            }}>
              <span>{column.courtName.replace(/^Court\s+/i, 'Court ')}</span>
              <span style={{ fontSize: 11, color: muted, fontWeight: 700 }}>
                {column.closed ? 'Closed' : column.current && dark ? 'On court' : 'Open'}
              </span>
            </div>
            <div style={{ padding: 10, display: 'grid', gap: 8 }}>
              {!column.current && (
                <div style={{ fontSize: 12, color: muted }}>No match on this court.</div>
              )}
              {column.current && (
                <div
                  onClick={() => onOpenMatch(column.current as DeskMatchItem)}
                  style={{
                    textAlign: 'left',
                    border: dark ? '1px solid #455a64' : '1px solid #cfd8dc',
                    borderRadius: 8,
                    padding: 8,
                    background: dark ? '#37474f' : '#fff',
                    color: ink,
                    cursor: 'pointer',
                  }}
                >
                  <MatchLines match={column.current} />
                  {!dark && column.startableMatchId !== column.current.match_id && (
                    <div style={{ marginTop: 8, fontSize: 11, fontWeight: 700, color: muted }}>
                      {isOpeningMatch(column.current)
                        ? 'Check in first'
                        : (!column.current.team1_id || !column.current.team2_id ? 'Waiting for teams' : 'Not ready')}
                    </div>
                  )}
                  {column.startableMatchId === column.current.match_id && (
                    <button
                      type="button"
                      disabled={!isDraft || busyMatchId != null}
                      onClick={(event) => {
                        event.stopPropagation()
                        onStart(column.current!.match_id)
                      }}
                      style={{
                        marginTop: 8,
                        padding: '6px 10px',
                        borderRadius: 6,
                        border: 'none',
                        background: !isDraft || busyMatchId != null ? '#90a4ae' : '#2e7d32',
                        color: '#fff',
                        fontSize: 12,
                        fontWeight: 800,
                        cursor: !isDraft || busyMatchId != null ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {busyMatchId === column.current.match_id ? 'Starting…' : 'Start'}
                    </button>
                  )}
                </div>
              )}
              {column.stack.map((match) => (
                <div
                  key={match.match_id}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData('text/match-id', String(match.match_id))
                    event.dataTransfer.effectAllowed = 'move'
                  }}
                  onClick={() => onOpenMatch(match)}
                  style={{
                    border: dark ? '1px dashed #78909c' : '1px dashed #b0bec5',
                    borderRadius: 8,
                    padding: 8,
                    cursor: 'grab',
                    background: dark ? '#2c3a42' : '#f8fafc',
                  }}
                >
                  <MatchLines match={match} />
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

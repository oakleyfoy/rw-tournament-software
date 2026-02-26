import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getDeskSnapshot,
  getDeskImpact,
  getPoolProjection,
  confirmPoolPlacement,
  checkDeskConflicts,
  createWorkingDraft,
  deskFinalizeMatch,
  deskCorrectMatch,
  deskSetMatchStatus,
  deskMoveMatch,
  deskSwapMatches,
  deskAddSlots,
  deskAddCourt,
  bulkPauseInProgress,
  bulkDelayAfter,
  bulkResumePaused,
  bulkUndelay,
  getCourtStates,
  patchCourtState,
  reschedulePreview,
  rescheduleApply,
  DeskSnapshotResponse,
  DeskMatchItem,
  SnapshotSlot,
  MatchImpactItem,
  ImpactTarget,
  ConflictItem,
  CourtStateItem,
  FinalizeResponse,
  PoolProjectionResponse,
  EventProjection,
  ReschedulePreviewResponse,
  rebuildPreview,
  rebuildApply,
  RebuildPreviewResponse,
  RebuildMatchItem,
  getDeskTeams,
  defaultTeamWeekend,
  updateTeam,
  DeskTeamItem,
} from '../../api/client'
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  useDraggable,
} from '@dnd-kit/core'

const STAGE_COLORS: Record<string, string> = {
  WF: '#1a237e',
  RR: '#2e7d32',
  BRACKET: '#3949ab',
  CONS: '#e65100',
  PLACEMENT: '#6a1b9a',
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  SCHEDULED: { bg: '#e0e0e0', text: '#555' },
  IN_PROGRESS: { bg: '#fff3e0', text: '#e65100' },
  FINAL: { bg: '#c8e6c9', text: '#2e7d32' },
  PAUSED: { bg: '#fce4ec', text: '#c62828' },
  DELAYED: { bg: '#fff8e1', text: '#f57f17' },
  CANCELLED: { bg: '#efebe9', text: '#795548' },
}

const STATUS_LABEL: Record<string, string> = {
  SCHEDULED: 'Scheduled',
  IN_PROGRESS: 'In Progress',
  FINAL: 'Completed',
  PAUSED: 'Paused',
  DELAYED: 'Delayed',
  CANCELLED: 'Cancelled',
}

function Badge({ label, bg, color }: { label: string; bg: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '1px 5px',
      borderRadius: 2,
      fontSize: 9,
      fontWeight: 700,
      color,
      backgroundColor: bg,
      textTransform: 'uppercase',
      letterSpacing: 0.3,
      lineHeight: '14px',
    }}>
      {label}
    </span>
  )
}

function eventAbbrev(name: string): string {
  if (!name) return ''
  const n = name.trim()
  const lower = n.toLowerCase()
  const letter = lower.includes("women") ? 'W'
    : lower.includes("men") || lower.includes("man") ? 'M'
    : lower.includes("mixed") || lower.includes("mix") ? 'MX'
    : n.charAt(0).toUpperCase()
  const tier = n.match(/\b([A-D])\b/i)?.[1]?.toUpperCase() || ''
  return `${letter}${tier}`
}

const EVENT_COLORS: Record<string, string> = {
  W: '#9c27b0', M: '#1565c0', MX: '#00796b',
}

function EventBadge({ name }: { name: string }) {
  const abbr = eventAbbrev(name)
  if (!abbr) return null
  const prefix = abbr.replace(/[A-D]$/, '')
  const bg = EVENT_COLORS[prefix] || '#616161'
  return <Badge label={abbr} bg={bg} color="#fff" />
}

const CONFLICT_ICONS: Record<string, string> = {
  TEAM_ALREADY_PLAYING: '🔴',
  DAY_CAP_EXCEEDED: '🟡',
  REST_TOO_SHORT: '🟠',
}

function ConflictWarningsModal({
  actionLabel,
  conflicts,
  onProceed,
  onCancel,
}: {
  actionLabel: string
  conflicts: ConflictItem[]
  onProceed: () => void
  onCancel: () => void
}) {
  return (
    <>
      <div
        onClick={onCancel}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          backgroundColor: 'rgba(0,0,0,0.45)',
          zIndex: 2000,
        }}
      />
      <div style={{
        position: 'fixed',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 440,
        maxHeight: '80vh',
        backgroundColor: '#fff',
        borderRadius: 10,
        boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
        zIndex: 2001,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid #e0e0e0',
          backgroundColor: '#fff3e0',
        }}>
          <div style={{ fontWeight: 700, fontSize: 16, color: '#e65100' }}>
            Potential Conflicts
          </div>
          <div style={{ fontSize: 12, color: '#bf360c', marginTop: 2 }}>
            Review before: {actionLabel}
          </div>
        </div>
        <div style={{ padding: '14px 20px', overflow: 'auto', flex: 1 }}>
          {conflicts.map((c, i) => (
            <div key={i} style={{
              padding: '10px 12px',
              backgroundColor: '#fffde7',
              border: '1px solid #fff9c4',
              borderRadius: 6,
              marginBottom: 8,
              fontSize: 13,
              display: 'flex',
              gap: 8,
              alignItems: 'flex-start',
            }}>
              <span style={{ fontSize: 16, flexShrink: 0 }}>{CONFLICT_ICONS[c.code] || '⚠️'}</span>
              <div>
                <div style={{ fontWeight: 600, color: '#333' }}>{c.message}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{
          padding: '12px 20px',
          borderTop: '1px solid #e0e0e0',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 10,
        }}>
          <button
            onClick={onCancel}
            style={{
              padding: '8px 18px',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: '#f5f5f5',
              color: '#555',
              border: '1px solid #ddd',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={onProceed}
            style={{
              padding: '8px 18px',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: '#e65100',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Proceed Anyway
          </button>
        </div>
      </div>
    </>
  )
}

function CourtCard({
  courtName,
  nowPlaying,
  upNext,
  onDeck,
  isDraft,
  onAction,
  courtState,
  onCourtStateChange,
  courtMatches,
  allMatches,
  onMatchClick,
}: {
  courtName: string
  nowPlaying?: DeskMatchItem
  upNext?: DeskMatchItem
  onDeck?: DeskMatchItem
  isDraft: boolean
  onAction: (match: DeskMatchItem, action: string) => void
  courtState?: CourtStateItem
  onCourtStateChange?: (courtLabel: string, patch: { is_closed?: boolean; note?: string }) => void
  courtMatches: DeskMatchItem[]
  allMatches: DeskMatchItem[]
  onMatchClick?: (m: DeskMatchItem) => void
}) {
  const [editingNote, setEditingNote] = useState(false)
  const [noteText, setNoteText] = useState(courtState?.note || '')
  const [showHistory, setShowHistory] = useState(false)
  const isClosed = courtState?.is_closed || false

  useEffect(() => {
    setNoteText(courtState?.note || '')
  }, [courtState?.note])

  const courtLabel = courtName.replace(/^Court\s+/i, '')

  return (
    <div style={{
      border: isClosed ? '2px solid #c62828' : '1px solid #e0e0e0',
      borderRadius: 6,
      backgroundColor: '#fff',
      overflow: 'hidden',
      minWidth: 200,
    }}>
      <div style={{
        backgroundColor: isClosed ? '#c62828' : '#1a237e',
        color: '#fff',
        padding: '4px 10px',
        fontSize: 12,
        fontWeight: 700,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span>{courtName}</span>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {isClosed && (
            <span style={{
              fontSize: 9,
              fontWeight: 700,
              backgroundColor: 'rgba(255,255,255,0.3)',
              padding: '1px 5px',
              borderRadius: 2,
            }}>
              CLOSED
            </span>
          )}
          <button
            onClick={() => setShowHistory(h => !h)}
            style={{
              fontSize: 9,
              fontWeight: 600,
              padding: '1px 5px',
              borderRadius: 2,
              border: '1px solid rgba(255,255,255,0.5)',
              backgroundColor: showHistory ? 'rgba(255,255,255,0.3)' : 'transparent',
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            History
          </button>
          {isDraft && onCourtStateChange && (
            <button
              onClick={() => onCourtStateChange(courtLabel, { is_closed: !isClosed })}
              style={{
                fontSize: 9,
                fontWeight: 600,
                padding: '1px 5px',
                borderRadius: 2,
                border: '1px solid rgba(255,255,255,0.5)',
                backgroundColor: 'transparent',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              {isClosed ? 'Open' : 'Close'}
            </button>
          )}
        </div>
      </div>
      {(courtState?.note || (isDraft && onCourtStateChange)) && (
        <div style={{
          padding: '2px 10px',
          backgroundColor: isClosed ? '#ffebee' : '#f5f5f5',
          borderBottom: '1px solid #e0e0e0',
          fontSize: 10,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          minHeight: 18,
        }}>
          {editingNote ? (
            <>
              <input
                type="text"
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                maxLength={280}
                placeholder="Court note..."
                style={{
                  flex: 1,
                  fontSize: 10,
                  padding: '1px 4px',
                  border: '1px solid #ccc',
                  borderRadius: 2,
                }}
                autoFocus
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    onCourtStateChange?.(courtLabel, { note: noteText })
                    setEditingNote(false)
                  }
                  if (e.key === 'Escape') {
                    setNoteText(courtState?.note || '')
                    setEditingNote(false)
                  }
                }}
              />
              <button
                onClick={() => {
                  onCourtStateChange?.(courtLabel, { note: noteText })
                  setEditingNote(false)
                }}
                style={{
                  fontSize: 9,
                  fontWeight: 600,
                  padding: '1px 5px',
                  border: 'none',
                  borderRadius: 2,
                  backgroundColor: '#1a237e',
                  color: '#fff',
                  cursor: 'pointer',
                }}
              >
                Save
              </button>
            </>
          ) : (
            <>
              <span style={{ flex: 1, color: '#666', fontStyle: courtState?.note ? 'normal' : 'italic', fontSize: 10 }}>
                {courtState?.note || 'No note'}
              </span>
              {isDraft && onCourtStateChange && (
                <button
                  onClick={() => setEditingNote(true)}
                  style={{
                    fontSize: 9,
                    fontWeight: 600,
                    padding: '0px 4px',
                    border: '1px solid #ccc',
                    borderRadius: 2,
                    backgroundColor: '#fff',
                    color: '#555',
                    cursor: 'pointer',
                  }}
                >
                  Edit
                </button>
              )}
            </>
          )}
        </div>
      )}
      <div style={{ padding: '6px 10px' }}>
        {nowPlaying ? (
          <div style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: nowPlaying.status === 'PAUSED' ? '#c62828' : '#e65100', textTransform: 'uppercase', marginBottom: 2 }}>
              {nowPlaying.status === 'PAUSED' ? 'Paused' : 'Now Playing'}
            </div>
            <MiniMatchCard match={nowPlaying} isDraft={isDraft} onAction={onAction} showActions allMatches={allMatches} onMatchClick={onMatchClick} />
          </div>
        ) : (
          <div style={{ fontSize: 10, color: '#bbb', marginBottom: 6, fontStyle: 'italic' }}>
            No match in progress
          </div>
        )}
        {upNext ? (
          <div style={{ marginBottom: onDeck ? 6 : 0 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: '#555', textTransform: 'uppercase', marginBottom: 2 }}>
              Up Next
            </div>
            <MiniMatchCard match={upNext} isDraft={isDraft} onAction={onAction} showActions allMatches={allMatches} onMatchClick={onMatchClick} />
          </div>
        ) : (
          <div style={{ fontSize: 10, color: '#bbb', fontStyle: 'italic', marginBottom: onDeck ? 6 : 0 }}>
            No upcoming match
          </div>
        )}
        {onDeck && (
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, color: '#999', textTransform: 'uppercase', marginBottom: 2 }}>
              On Deck
            </div>
            {(() => {
              const deckDefault = onDeck.team1_defaulted || onDeck.team2_defaulted
              return (
                <div
                  onClick={onMatchClick ? () => onMatchClick(onDeck) : undefined}
                  style={{
                    border: '1px solid #eee',
                    borderRadius: 4,
                    padding: '3px 8px',
                    backgroundColor: deckDefault ? '#fce4ec' : '#fafafa',
                    fontSize: 10,
                    opacity: 0.85,
                    borderLeft: deckDefault ? '3px solid #c62828' : undefined,
                    cursor: onMatchClick ? 'pointer' : undefined,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, fontSize: 10 }}>#{onDeck.match_number}</span>
                    <div style={{ display: 'flex', gap: 2 }}>
                      {deckDefault && <Badge label="DEFAULT" bg="#c62828" color="#fff" />}
                      <EventBadge name={onDeck.event_name} />
                      <Badge label={onDeck.stage} bg={STAGE_COLORS[onDeck.stage] || '#757575'} color="#fff" />
                    </div>
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 10 }}>
                    <span style={{ color: onDeck.team1_defaulted ? '#c62828' : '#555', textDecoration: onDeck.team1_defaulted ? 'line-through' : 'none' }}>
                      {onDeck.team1_display}
                    </span>
                    <span style={{ color: '#999' }}> vs </span>
                    <span style={{ color: onDeck.team2_defaulted ? '#c62828' : '#555', textDecoration: onDeck.team2_defaulted ? 'line-through' : 'none' }}>
                      {onDeck.team2_display}
                    </span>
                  </div>
                  {onDeck.scheduled_time && (
                    <div style={{ color: '#999', fontSize: 9 }}>{onDeck.scheduled_time}</div>
                  )}
                </div>
              )
            })()}
          </div>
        )}
      </div>
      {showHistory && (
        <div style={{
          borderTop: '1px solid #e0e0e0',
          backgroundColor: '#fafafa',
          padding: '6px 10px',
          maxHeight: 300,
          overflowY: 'auto',
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#555', textTransform: 'uppercase', marginBottom: 4 }}>
            Completed ({courtMatches.length} match{courtMatches.length !== 1 ? 'es' : ''})
          </div>
          {courtMatches.length === 0 ? (
            <div style={{ fontSize: 10, color: '#999', fontStyle: 'italic' }}>No matches on this court</div>
          ) : (
            courtMatches.map(m => {
              const sc = STATUS_COLORS[m.status] || STATUS_COLORS.SCHEDULED
              return (
                <div key={m.match_id} onClick={() => onMatchClick?.(m)} style={{
                  border: '1px solid #e8e8e8',
                  borderRadius: 4,
                  padding: '3px 8px',
                  marginBottom: 3,
                  backgroundColor: '#fff',
                  fontSize: 10,
                  cursor: onMatchClick ? 'pointer' : 'default',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 1 }}>
                    <span style={{ fontWeight: 700 }}>#{m.match_number}</span>
                    <div style={{ display: 'flex', gap: 2 }}>
                      <EventBadge name={m.event_name} />
                      <Badge label={m.stage} bg={STAGE_COLORS[m.stage] || '#757575'} color="#fff" />
                      <Badge label={STATUS_LABEL[m.status] || m.status} bg={sc.bg} color={sc.text} />
                    </div>
                  </div>
                  <div style={{ fontWeight: 600, color: '#333' }}>{m.team1_display} vs {m.team2_display}</div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: '#888', fontSize: 9 }}>
                    {m.scheduled_time && <span>{m.day_label} {m.scheduled_time}</span>}
                    {m.score_display && <span style={{ fontWeight: 600, color: '#1a237e' }}>{m.score_display}</span>}
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}

function FeederMatchInfo({ sourceMatchId, allMatches }: { sourceMatchId: number; allMatches: DeskMatchItem[] }) {
  const feeder = allMatches.find(m => m.match_id === sourceMatchId)
  if (!feeder) return null
  const fsc = STATUS_COLORS[feeder.status] || STATUS_COLORS.SCHEDULED
  const parts: string[] = []
  if (feeder.scheduled_time) parts.push(feeder.scheduled_time)
  if (feeder.court_name) parts.push(feeder.court_name)
  return (
    <div style={{ fontSize: 9, color: '#888', marginTop: 1, paddingLeft: 6, borderLeft: '2px solid #e0e0e0' }}>
      <span style={{ fontWeight: 600 }}>← #{feeder.match_number}</span>
      {parts.length > 0 && <span> {parts.join(' · ')}</span>}
      <span style={{
        marginLeft: 4,
        fontSize: 8,
        fontWeight: 700,
        color: fsc.text,
        backgroundColor: fsc.bg,
        padding: '0 4px',
        borderRadius: 2,
      }}>
        {STATUS_LABEL[feeder.status] || feeder.status}
      </span>
    </div>
  )
}

function NoteIcon({ note }: { note: string }) {
  return (
    <span
      title={note}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 14,
        height: 14,
        backgroundColor: '#fff3e0',
        border: '1px solid #ffb74d',
        borderRadius: 2,
        fontSize: 9,
        lineHeight: 1,
        cursor: 'default',
        flexShrink: 0,
      }}
    >
      &#9998;
    </span>
  )
}

function MiniMatchCard({
  match,
  isDraft,
  onAction,
  showActions,
  allMatches,
  onMatchClick,
}: {
  match: DeskMatchItem
  isDraft: boolean
  onAction: (match: DeskMatchItem, action: string) => void
  showActions?: boolean
  allMatches?: DeskMatchItem[]
  onMatchClick?: (m: DeskMatchItem) => void
}) {
  const sc = STATUS_COLORS[match.status] || STATUS_COLORS.SCHEDULED
  const team1TBD = !match.team1_id && match.source_match_a_id
  const team2TBD = !match.team2_id && match.source_match_b_id
  const hasDefault = match.team1_defaulted || match.team2_defaulted
  return (
    <div
      onClick={onMatchClick ? () => onMatchClick(match) : undefined}
      style={{
        border: '1px solid #e8e8e8',
        borderRadius: 4,
        padding: '4px 8px',
        backgroundColor: hasDefault ? '#fce4ec' : '#fafafa',
        fontSize: 11,
        borderLeft: hasDefault ? '3px solid #c62828' : undefined,
        cursor: onMatchClick ? 'pointer' : undefined,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
        <span style={{ fontWeight: 700, fontSize: 11 }}>#{match.match_number}</span>
        <div style={{ display: 'flex', gap: 3 }}>
          {hasDefault && <Badge label="DEFAULT" bg="#c62828" color="#fff" />}
          <EventBadge name={match.event_name} />
          <Badge label={match.stage} bg={STAGE_COLORS[match.stage] || '#757575'} color="#fff" />
          <Badge label={STATUS_LABEL[match.status] || match.status} bg={sc.bg} color={sc.text} />
        </div>
      </div>
      <div style={{
        fontWeight: 600,
        color: match.team1_defaulted ? '#c62828' : team1TBD ? '#999' : '#333',
        fontSize: 11,
        fontStyle: team1TBD ? 'italic' : 'normal',
        textDecoration: match.team1_defaulted ? 'line-through' : 'none',
        display: 'flex', alignItems: 'center', gap: 3,
      }}>
        {match.team1_display}
        {match.team1_notes && <NoteIcon note={match.team1_notes} />}
      </div>
      {team1TBD && allMatches && (
        <FeederMatchInfo sourceMatchId={match.source_match_a_id!} allMatches={allMatches} />
      )}
      <div style={{ color: '#999', fontSize: 9, lineHeight: '12px' }}>vs</div>
      <div style={{
        fontWeight: 600,
        color: match.team2_defaulted ? '#c62828' : team2TBD ? '#999' : '#333',
        fontSize: 11,
        fontStyle: team2TBD ? 'italic' : 'normal',
        textDecoration: match.team2_defaulted ? 'line-through' : 'none',
        display: 'flex', alignItems: 'center', gap: 3,
      }}>
        {match.team2_display}
        {match.team2_notes && <NoteIcon note={match.team2_notes} />}
      </div>
      {team2TBD && allMatches && (
        <FeederMatchInfo sourceMatchId={match.source_match_b_id!} allMatches={allMatches} />
      )}
      {match.status === 'FINAL' && match.score_display && (
        <div style={{ marginTop: 2, fontWeight: 700, color: '#2e7d32', fontSize: 11 }}>
          Score: {match.score_display}
        </div>
      )}
      {match.scheduled_time && match.status !== 'FINAL' && (
        <div style={{ marginTop: 2, color: '#888', fontSize: 10 }}>
          {match.court_name} &middot; {match.scheduled_time}
        </div>
      )}
      {showActions && isDraft && match.status !== 'FINAL' && (
        <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
          {(match.status === 'SCHEDULED' || match.status === 'DELAYED') && (
            <button
              onClick={() => onAction(match, 'IN_PROGRESS')}
              style={{
                padding: '2px 8px',
                fontSize: 10,
                fontWeight: 600,
                backgroundColor: '#e65100',
                color: '#fff',
                border: 'none',
                borderRadius: 3,
                cursor: 'pointer',
              }}
            >
              Start
            </button>
          )}
          {match.status === 'PAUSED' && (
            <button
              onClick={() => onAction(match, 'IN_PROGRESS')}
              style={{
                padding: '2px 8px',
                fontSize: 10,
                fontWeight: 600,
                backgroundColor: '#e65100',
                color: '#fff',
                border: 'none',
                borderRadius: 3,
                cursor: 'pointer',
              }}
            >
              Resume
            </button>
          )}
          {(match.status === 'IN_PROGRESS' || match.status === 'PAUSED') && (
            <button
              onClick={() => onAction(match, 'FINALIZE')}
              style={{
                padding: '2px 8px',
                fontSize: 10,
                fontWeight: 600,
                backgroundColor: '#2e7d32',
                color: '#fff',
                border: 'none',
                borderRadius: 3,
                cursor: 'pointer',
              }}
            >
              Score
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Match Drawer (right slideout) ──────────────────────────────────────

function MatchDrawer({
  match,
  isDraft,
  versionId,
  tournamentId,
  onClose,
  onRefreshKeepOpen,
  onRefreshAndClose,
  allMatches,
}: {
  match: DeskMatchItem
  isDraft: boolean
  versionId: number
  tournamentId: number
  onClose: () => void
  onRefreshKeepOpen: () => void
  onRefreshAndClose: () => void
  allMatches: DeskMatchItem[]
}) {
  const [score, setScore] = useState('')
  const [winnerId, setWinnerId] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<FinalizeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [finalized, setFinalized] = useState(match.status === 'FINAL')
  const [pendingConflicts, setPendingConflicts] = useState<ConflictItem[] | null>(null)
  const [pendingAction, setPendingAction] = useState<{ label: string; fn: () => void } | null>(null)

  const [correcting, setCorrecting] = useState(false)
  const [corrScore, setCorrScore] = useState('')
  const [corrWinnerId, setCorrWinnerId] = useState<number | null>(null)
  const [corrSubmitting, setCorrSubmitting] = useState(false)
  const [corrResult, setCorrResult] = useState<FinalizeResponse | null>(null)
  const [corrError, setCorrError] = useState<string | null>(null)

  const [noteTeamId, setNoteTeamId] = useState<number | null>(null)
  const [noteEventId, setNoteEventId] = useState<number | null>(null)
  const [noteText, setNoteText] = useState('')
  const [noteSaving, setNoteSaving] = useState(false)

  const openNote = useCallback((teamId: number, currentNote: string | null) => {
    setNoteTeamId(teamId)
    setNoteEventId(match.event_id)
    setNoteText(currentNote || '')
  }, [match.event_id])

  const saveNote = useCallback(async () => {
    if (noteTeamId == null || noteEventId == null) return
    setNoteSaving(true)
    try {
      await updateTeam(noteEventId, noteTeamId, { notes: noteText })
      setNoteTeamId(null)
      onRefreshKeepOpen()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save note')
    } finally {
      setNoteSaving(false)
    }
  }, [noteTeamId, noteEventId, noteText, onRefreshKeepOpen])

  const runWithConflictCheck = useCallback(async (
    actionType: string,
    actionLabel: string,
    actionFn: () => void
  ) => {
    try {
      const resp = await checkDeskConflicts(tournamentId, {
        version_id: versionId,
        action_type: actionType,
        match_id: match.match_id,
      })
      if (resp.conflicts.length > 0) {
        setPendingConflicts(resp.conflicts)
        setPendingAction({ label: actionLabel, fn: actionFn })
        return
      }
    } catch {
      // If conflict check fails, proceed anyway (warn-only)
    }
    actionFn()
  }, [tournamentId, versionId, match.match_id])

  const doFinalize = useCallback(async () => {
    if (!winnerId) return
    if (!score.trim()) return
    setSubmitting(true)
    setError(null)
    setResult(null)
    try {
      const resp = await deskFinalizeMatch(tournamentId, match.match_id, {
        version_id: versionId,
        score: score || undefined,
        winner_team_id: winnerId,
      })
      setResult(resp)
      setFinalized(true)
      onRefreshKeepOpen()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to finalize')
    } finally {
      setSubmitting(false)
    }
  }, [tournamentId, match.match_id, versionId, score, winnerId, onRefreshKeepOpen])

  const handleFinalize = useCallback(() => {
    if (!winnerId) return
    runWithConflictCheck('FINALIZE', 'Finalize Match', doFinalize)
  }, [winnerId, runWithConflictCheck, doFinalize])

  const doDefault = useCallback(async () => {
    if (!winnerId) return
    setSubmitting(true)
    setError(null)
    setResult(null)
    try {
      const resp = await deskFinalizeMatch(tournamentId, match.match_id, {
        version_id: versionId,
        winner_team_id: winnerId,
        is_default: true,
      })
      setResult(resp)
      setFinalized(true)
      onRefreshKeepOpen()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to default')
    } finally {
      setSubmitting(false)
    }
  }, [tournamentId, match.match_id, versionId, winnerId, onRefreshKeepOpen])

  const handleDefault = useCallback(() => {
    if (!winnerId) return
    runWithConflictCheck('FINALIZE', 'Default Match', doDefault)
  }, [winnerId, runWithConflictCheck, doDefault])

  const doRetired = useCallback(async () => {
    if (!winnerId) return
    if (!score.trim()) return
    setSubmitting(true)
    setError(null)
    setResult(null)
    try {
      const resp = await deskFinalizeMatch(tournamentId, match.match_id, {
        version_id: versionId,
        score: score,
        winner_team_id: winnerId,
        is_retired: true,
      })
      setResult(resp)
      setFinalized(true)
      onRefreshKeepOpen()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to finalize (retired)')
    } finally {
      setSubmitting(false)
    }
  }, [tournamentId, match.match_id, versionId, score, winnerId, onRefreshKeepOpen])

  const handleRetired = useCallback(() => {
    if (!winnerId || !score.trim()) return
    runWithConflictCheck('FINALIZE', 'Retired Match', doRetired)
  }, [winnerId, score, runWithConflictCheck, doRetired])

  const openCorrection = useCallback(() => {
    setCorrScore(result?.match.score_display || match.score_display || '')
    setCorrWinnerId(result?.match.winner_team_id ?? match.winner_team_id ?? null)
    setCorrError(null)
    setCorrResult(null)
    setCorrecting(true)
  }, [match, result])

  const submitCorrection = useCallback(async () => {
    if (!corrWinnerId || !corrScore.trim()) return
    setCorrSubmitting(true)
    setCorrError(null)
    try {
      const resp = await deskCorrectMatch(tournamentId, match.match_id, {
        version_id: versionId,
        score: corrScore,
        winner_team_id: corrWinnerId,
      })
      setCorrResult(resp)
      setCorrecting(false)
      onRefreshKeepOpen()
    } catch (e) {
      setCorrError(e instanceof Error ? e.message : 'Failed to correct match')
    } finally {
      setCorrSubmitting(false)
    }
  }, [tournamentId, match.match_id, versionId, corrScore, corrWinnerId, onRefreshKeepOpen])

  const doSetStatus = useCallback(async (status: string) => {
    setError(null)
    setStatusMsg(null)
    try {
      await deskSetMatchStatus(tournamentId, match.match_id, {
        version_id: versionId,
        status,
      })
      setStatusMsg(`Status set to ${status}`)
      onRefreshAndClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to set status')
    }
  }, [tournamentId, match.match_id, versionId, onRefreshAndClose])

  const handleSetStatus = useCallback((status: string) => {
    if (status === 'IN_PROGRESS') {
      runWithConflictCheck('SET_IN_PROGRESS', 'Set In Progress', () => doSetStatus(status))
    } else {
      doSetStatus(status)
    }
  }, [runWithConflictCheck, doSetStatus])

  const sc = STATUS_COLORS[match.status] || STATUS_COLORS.SCHEDULED

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      right: 0,
      width: 380,
      height: '100vh',
      backgroundColor: '#fff',
      boxShadow: '-4px 0 20px rgba(0,0,0,0.15)',
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '16px 20px',
        borderBottom: '1px solid #e0e0e0',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span style={{ fontWeight: 700, fontSize: 16 }}>Match #{match.match_number}</span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            fontSize: 20,
            cursor: 'pointer',
            color: '#888',
            padding: '4px 8px',
          }}
        >
          &times;
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          <Badge label={match.stage} bg={STAGE_COLORS[match.stage] || '#757575'} color="#fff" />
          <Badge label={STATUS_LABEL[match.status] || match.status} bg={sc.bg} color={sc.text} />
        </div>

        <div style={{ marginBottom: 12, fontSize: 13, color: '#888' }}>
          {match.event_name}
          {match.division_name ? ` — ${match.division_name}` : ''}
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 15, color: '#222', marginBottom: 2, display: 'flex', alignItems: 'center', gap: 6 }}>
            {match.team1_display}
            {match.team1_notes && <NoteIcon note={match.team1_notes} />}
            {match.team1_id && isDraft && (
              <button onClick={() => openNote(match.team1_id!, match.team1_notes ?? null)} title="Add/edit note" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 13, color: match.team1_notes ? '#ef6c00' : '#bbb' }}>
                &#9998;
              </button>
            )}
          </div>
          <div style={{ color: '#999', fontSize: 12 }}>vs</div>
          <div style={{ fontWeight: 600, fontSize: 15, color: '#222', marginTop: 2, display: 'flex', alignItems: 'center', gap: 6 }}>
            {match.team2_display}
            {match.team2_notes && <NoteIcon note={match.team2_notes} />}
            {match.team2_id && isDraft && (
              <button onClick={() => openNote(match.team2_id!, match.team2_notes ?? null)} title="Add/edit note" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 13, color: match.team2_notes ? '#ef6c00' : '#bbb' }}>
                &#9998;
              </button>
            )}
          </div>
        </div>

        {noteTeamId != null && (
          <div style={{
            padding: '10px 14px',
            backgroundColor: '#fff8e1',
            border: '1px solid #ffe082',
            borderRadius: 6,
            marginBottom: 16,
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#e65100', marginBottom: 6 }}>
              Note for {noteTeamId === match.team1_id ? match.team1_display : match.team2_display}
            </div>
            <textarea
              value={noteText}
              onChange={e => setNoteText(e.target.value)}
              rows={2}
              style={{ width: '100%', boxSizing: 'border-box', fontSize: 13, padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, resize: 'vertical' }}
              placeholder="e.g. Leaving early Sunday, need to play by 11 AM..."
            />
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <button
                onClick={saveNote}
                disabled={noteSaving}
                style={{ padding: '4px 12px', fontSize: 12, fontWeight: 600, backgroundColor: '#e65100', color: '#fff', border: 'none', borderRadius: 3, cursor: 'pointer' }}
              >
                {noteSaving ? 'Saving...' : 'Save Note'}
              </button>
              <button
                onClick={() => setNoteTeamId(null)}
                style={{ padding: '4px 12px', fontSize: 12, fontWeight: 600, backgroundColor: '#fff', color: '#555', border: '1px solid #ccc', borderRadius: 3, cursor: 'pointer' }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {match.court_name && (
          <div style={{ fontSize: 13, color: '#555', marginBottom: 4 }}>
            {match.court_name} &middot; {match.scheduled_time}
          </div>
        )}

        {(match.status === 'FINAL' || finalized) && (
          <div style={{
            padding: '12px 16px',
            backgroundColor: '#e8f5e9',
            borderRadius: 6,
            border: '1px solid #c8e6c9',
            marginBottom: 16,
          }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#2e7d32', marginBottom: 4 }}>
              Completed
            </div>
            {(corrResult?.match.score_display || result?.match.score_display || match.score_display) && (
              <div style={{ fontSize: 14, fontWeight: 600, color: '#333' }}>
                Score: {corrResult?.match.score_display || result?.match.score_display || match.score_display}
              </div>
            )}
            {(corrResult?.match || result?.match || match.winner_team_id || match.winner_display) && (
              <div style={{ fontSize: 13, color: '#555', marginTop: 4 }}>
                Winner: {(() => {
                  const wid = corrResult?.match.winner_team_id ?? result?.match.winner_team_id ?? match.winner_team_id ?? winnerId
                  if (wid) return wid === match.team1_id ? match.team1_display : match.team2_display
                  return match.winner_display || 'Unknown'
                })()}
              </div>
            )}

            {isDraft && !correcting && (
              <button
                onClick={openCorrection}
                style={{
                  marginTop: 10,
                  padding: '5px 12px',
                  fontSize: 12,
                  fontWeight: 600,
                  backgroundColor: '#fff',
                  color: '#d84315',
                  border: '1px solid #d84315',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                Correct Score / Winner
              </button>
            )}

            {correcting && (
              <div style={{ marginTop: 12, padding: '10px 12px', backgroundColor: '#fff8e1', borderRadius: 6, border: '1px solid #ffe082' }}>
                <div style={{ fontWeight: 700, fontSize: 13, color: '#e65100', marginBottom: 8 }}>
                  Correct Match
                </div>
                <div style={{ marginBottom: 8 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#555', marginBottom: 4 }}>Score</label>
                  <input
                    type="text"
                    value={corrScore}
                    onChange={e => setCorrScore(e.target.value)}
                    placeholder="e.g. 6-4, 7-5"
                    style={{ width: '100%', padding: '6px 10px', fontSize: 14, border: '1px solid #ccc', borderRadius: 4, boxSizing: 'border-box' }}
                  />
                </div>
                <div style={{ marginBottom: 8 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#555', marginBottom: 4 }}>Winner</label>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {match.team1_id && (
                      <button
                        onClick={() => setCorrWinnerId(match.team1_id!)}
                        style={{
                          flex: 1,
                          padding: '6px 8px',
                          fontSize: 12,
                          fontWeight: 600,
                          backgroundColor: corrWinnerId === match.team1_id ? '#1b5e20' : '#e0e0e0',
                          color: corrWinnerId === match.team1_id ? '#fff' : '#333',
                          border: 'none',
                          borderRadius: 4,
                          cursor: 'pointer',
                        }}
                      >
                        {match.team1_display}
                      </button>
                    )}
                    {match.team2_id && (
                      <button
                        onClick={() => setCorrWinnerId(match.team2_id!)}
                        style={{
                          flex: 1,
                          padding: '6px 8px',
                          fontSize: 12,
                          fontWeight: 600,
                          backgroundColor: corrWinnerId === match.team2_id ? '#1b5e20' : '#e0e0e0',
                          color: corrWinnerId === match.team2_id ? '#fff' : '#333',
                          border: 'none',
                          borderRadius: 4,
                          cursor: 'pointer',
                        }}
                      >
                        {match.team2_display}
                      </button>
                    )}
                  </div>
                </div>
                {corrError && (
                  <div style={{ color: '#c62828', fontSize: 12, marginBottom: 6 }}>{corrError}</div>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={submitCorrection}
                    disabled={!corrWinnerId || !corrScore.trim() || corrSubmitting}
                    style={{
                      flex: 1,
                      padding: '7px 12px',
                      fontSize: 13,
                      fontWeight: 700,
                      backgroundColor: corrWinnerId && corrScore.trim() ? '#d84315' : '#ccc',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 4,
                      cursor: corrWinnerId && corrScore.trim() ? 'pointer' : 'default',
                    }}
                  >
                    {corrSubmitting ? 'Saving...' : 'Save Correction'}
                  </button>
                  <button
                    onClick={() => setCorrecting(false)}
                    style={{
                      padding: '7px 12px',
                      fontSize: 13,
                      fontWeight: 600,
                      backgroundColor: '#e0e0e0',
                      color: '#333',
                      border: 'none',
                      borderRadius: 4,
                      cursor: 'pointer',
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {corrResult && corrResult.warnings && corrResult.warnings.length > 0 && (
              <div style={{ marginTop: 8, padding: '8px 10px', backgroundColor: '#fff3e0', borderRadius: 4, border: '1px solid #ffe0b2' }}>
                <div style={{ fontWeight: 700, fontSize: 12, color: '#e65100', marginBottom: 4 }}>Warnings</div>
                {corrResult.warnings.map((w, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#bf360c', marginBottom: 2 }}>
                    {w.detail || w.reason}
                  </div>
                ))}
              </div>
            )}

            {corrResult && corrResult.downstream_updates && corrResult.downstream_updates.length > 0 && (
              <div style={{ marginTop: 8, padding: '8px 10px', backgroundColor: '#e3f2fd', borderRadius: 4, border: '1px solid #bbdefb' }}>
                <div style={{ fontWeight: 700, fontSize: 12, color: '#1565c0', marginBottom: 4 }}>Advancement Updated</div>
                {corrResult.downstream_updates.map((u, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#333', marginBottom: 2 }}>
                    {u.team_name} → Match #{u.match_id} (slot {u.slot_filled})
                    {u.next_court && <span> — {u.next_court}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Downstream Impact */}
        <DrawerImpact
          tournamentId={tournamentId}
          versionId={versionId}
          matchId={match.match_id}
          matchStatus={match.status}
          onSwitchToImpact={undefined}
        />

        {/* Match History Timeline */}
        <MatchTimeline match={match} />

        {!isDraft && (
          <div style={{
            padding: '12px 16px',
            backgroundColor: '#fff3e0',
            borderRadius: 6,
            fontSize: 13,
            color: '#e65100',
            marginTop: 16,
          }}>
            Viewing published schedule (read-only). Open Desk Draft to make updates.
          </div>
        )}

        {isDraft && !finalized && match.status !== 'FINAL' && (
          <div style={{ marginTop: 16, borderTop: '1px solid #e0e0e0', paddingTop: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, color: '#333' }}>
              Actions
            </div>

            {(match.status === 'SCHEDULED' || match.status === 'DELAYED') && (
              <button
                onClick={() => handleSetStatus('IN_PROGRESS')}
                style={{
                  width: '100%',
                  padding: '8px 16px',
                  fontSize: 13,
                  fontWeight: 600,
                  backgroundColor: '#e65100',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  marginBottom: 12,
                }}
              >
                Set In Progress
              </button>
            )}
            {match.status === 'PAUSED' && (
              <button
                onClick={() => handleSetStatus('IN_PROGRESS')}
                style={{
                  width: '100%',
                  padding: '8px 16px',
                  fontSize: 13,
                  fontWeight: 600,
                  backgroundColor: '#e65100',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  marginBottom: 12,
                }}
              >
                Resume Match
              </button>
            )}

            <div style={{
              border: '1px solid #e0e0e0',
              borderRadius: 6,
              padding: 14,
              backgroundColor: '#fafafa',
            }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: '#333' }}>
                Finalize Match
              </div>
              <div style={{ marginBottom: 8 }}>
                <label style={{ fontSize: 12, fontWeight: 500, color: '#555' }}>Score</label>
                <input
                  type="text"
                  placeholder="e.g. 8-4"
                  value={score}
                  onChange={e => setScore(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '6px 10px',
                    fontSize: 13,
                    border: '1px solid #ccc',
                    borderRadius: 4,
                    marginTop: 4,
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div style={{ marginBottom: 10 }}>
                <label style={{ fontSize: 12, fontWeight: 500, color: '#555' }}>Winner</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                  {match.team1_id && (
                    <label style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      fontSize: 13,
                      cursor: 'pointer',
                      padding: '6px 10px',
                      borderRadius: 4,
                      border: winnerId === match.team1_id ? '2px solid #1a237e' : '1px solid #ddd',
                      backgroundColor: winnerId === match.team1_id ? '#e8eaf6' : '#fff',
                    }}>
                      <input
                        type="radio"
                        name="winner"
                        checked={winnerId === match.team1_id}
                        onChange={() => setWinnerId(match.team1_id)}
                      />
                      {match.team1_display}
                    </label>
                  )}
                  {match.team2_id && (
                    <label style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      fontSize: 13,
                      cursor: 'pointer',
                      padding: '6px 10px',
                      borderRadius: 4,
                      border: winnerId === match.team2_id ? '2px solid #1a237e' : '1px solid #ddd',
                      backgroundColor: winnerId === match.team2_id ? '#e8eaf6' : '#fff',
                    }}>
                      <input
                        type="radio"
                        name="winner"
                        checked={winnerId === match.team2_id}
                        onChange={() => setWinnerId(match.team2_id)}
                      />
                      {match.team2_display}
                    </label>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={handleFinalize}
                  disabled={!winnerId || !score.trim() || submitting}
                  style={{
                    flex: 1,
                    padding: '8px 16px',
                    fontSize: 13,
                    fontWeight: 600,
                    backgroundColor: winnerId && score.trim() ? '#2e7d32' : '#ccc',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 4,
                    cursor: winnerId && score.trim() ? 'pointer' : 'default',
                  }}
                >
                  {submitting ? 'Submitting...' : 'Finalize Match'}
                </button>
                {match.team1_id && match.team2_id && (
                  <button
                    onClick={handleDefault}
                    disabled={!winnerId || submitting}
                    style={{
                      flex: 1,
                      padding: '8px 16px',
                      fontSize: 13,
                      fontWeight: 600,
                      backgroundColor: winnerId ? '#e65100' : '#ccc',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 4,
                      cursor: winnerId ? 'pointer' : 'default',
                    }}
                  >
                    {submitting ? 'Submitting...' : match.stage === 'WF' ? 'Default (WF)' : 'Default Win'}
                  </button>
                )}
                {match.team1_id && match.team2_id && (
                  <button
                    onClick={handleRetired}
                    disabled={!winnerId || !score.trim() || submitting}
                    title="Enter the score at point of retirement, select the winning team, then click Retired"
                    style={{
                      flex: 1,
                      padding: '8px 16px',
                      fontSize: 13,
                      fontWeight: 600,
                      backgroundColor: winnerId && score.trim() ? '#6a1b9a' : '#ccc',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 4,
                      cursor: winnerId && score.trim() ? 'pointer' : 'default',
                    }}
                  >
                    {submitting ? 'Submitting...' : 'Retired'}
                  </button>
                )}
                {match.stage === 'WF' && match.team1_id && match.team2_id && (
                  <div style={{ fontSize: 11, color: '#e65100', fontStyle: 'italic', marginTop: 4 }}>
                    Waterfall: select which team gets the win or loss, then click Default (WF)
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {error && (
          <div style={{ marginTop: 12, padding: '10px 14px', backgroundColor: '#ffebee', borderRadius: 6, color: '#c62828', fontSize: 13 }}>
            {error}
          </div>
        )}
        {statusMsg && (
          <div style={{ marginTop: 12, padding: '10px 14px', backgroundColor: '#e8f5e9', borderRadius: 6, color: '#2e7d32', fontSize: 13 }}>
            {statusMsg}
          </div>
        )}
        {result && (
          <div style={{ marginTop: 16 }}>
            {result.downstream_updates.length > 0 && (
              <div style={{
                padding: '12px 16px',
                backgroundColor: '#e8f5e9',
                borderRadius: 6,
                border: '1px solid #c8e6c9',
                fontSize: 13,
                marginBottom: 10,
              }}>
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8, color: '#2e7d32' }}>
                  Next Matches
                </div>
                {result.downstream_updates.map((u, i) => (
                  <div key={i} style={{ padding: '8px 0', borderTop: i > 0 ? '1px solid #c8e6c9' : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <span style={{
                        fontSize: 10,
                        fontWeight: 700,
                        color: '#fff',
                        backgroundColor: u.role === 'WINNER' ? '#2e7d32' : '#e65100',
                        padding: '1px 6px',
                        borderRadius: 3,
                        textTransform: 'uppercase',
                      }}>
                        {u.role}
                      </span>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{u.team_name}</span>
                    </div>
                    <div style={{ fontSize: 13, color: '#333', marginLeft: 2 }}>
                      {u.next_day && <div>{u.next_day}</div>}
                      {u.next_time && u.next_court && (
                        <div style={{ fontWeight: 600 }}>{u.next_time} &middot; {u.next_court}</div>
                      )}
                      {u.opponent ? (
                        <div style={{ marginTop: 2 }}>vs <strong>{u.opponent}</strong></div>
                      ) : (() => {
                        const nextMatch = allMatches.find(m => m.match_id === u.match_id)
                        const otherSourceId = nextMatch
                          ? (nextMatch.source_match_a_id === match.match_id
                              ? nextMatch.source_match_b_id
                              : nextMatch.source_match_a_id)
                          : null
                        const feeder = otherSourceId ? allMatches.find(m => m.match_id === otherSourceId) : null
                        return (
                          <div style={{ marginTop: 2 }}>
                            <div style={{ color: '#999', fontStyle: 'italic' }}>Opponent TBD</div>
                            {feeder && (
                              <FeederMatchInfo sourceMatchId={feeder.match_id} allMatches={allMatches} />
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {result.downstream_updates.length === 0 && result.warnings.length === 0 && (
              <div style={{
                padding: '12px 16px',
                backgroundColor: '#f5f5f5',
                borderRadius: 6,
                fontSize: 13,
                color: '#888',
              }}>
                No downstream matches to advance into.
              </div>
            )}
            {result.warnings.length > 0 && (
              <div style={{
                padding: '12px 16px',
                backgroundColor: '#fff3e0',
                borderRadius: 6,
                border: '1px solid #ffe0b2',
                fontSize: 13,
              }}>
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8, color: '#e65100' }}>
                  Warnings
                </div>
                {result.warnings.map((w, i) => (
                  <div key={i} style={{ padding: '4px 0', borderTop: i > 0 ? '1px solid #ffe0b2' : 'none' }}>
                    <strong>{w.reason}</strong>: {w.detail}
                  </div>
                ))}
              </div>
            )}
            <button
              onClick={() => window.open(
                `/t/${tournamentId}/draws/${match.event_id}/waterfall?version_id=${versionId}`,
                '_blank'
              )}
              style={{
                width: '100%',
                marginTop: 12,
                padding: '8px 16px',
                fontSize: 13,
                fontWeight: 600,
                backgroundColor: '#1a237e',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer',
              }}
            >
              View Waterfall Bracket
            </button>
            {result.auto_started && (
              <div style={{
                marginTop: 12,
                padding: '10px 14px',
                backgroundColor: '#fff3e0',
                borderRadius: 6,
                border: '1px solid #ffe0b2',
                fontSize: 13,
              }}>
                <div style={{ fontWeight: 700, color: '#e65100', marginBottom: 4 }}>
                  Now Playing on {result.auto_started.court_name}
                </div>
                <div style={{ fontWeight: 600 }}>
                  Match #{result.auto_started.match_number}: {result.auto_started.team1_display} vs {result.auto_started.team2_display}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Conflict warnings modal */}
      {pendingConflicts && pendingAction && (
        <ConflictWarningsModal
          actionLabel={pendingAction.label}
          conflicts={pendingConflicts}
          onProceed={() => {
            const fn = pendingAction.fn
            setPendingConflicts(null)
            setPendingAction(null)
            fn()
          }}
          onCancel={() => {
            setPendingConflicts(null)
            setPendingAction(null)
          }}
        />
      )}
    </div>
  )
}


// ── Impact helpers ────────────────────────────────────────────────────

function ImpactArrow({
  label,
  target,
  isFinal,
}: {
  label: string
  target: ImpactTarget | null
  isFinal: boolean
}) {
  if (!target) {
    return (
      <div style={{ fontSize: 12, color: '#bbb', marginBottom: 2 }}>
        {label} → <span style={{ fontStyle: 'italic' }}>no downstream</span>
      </div>
    )
  }

  let icon = '→'
  let color = '#555'
  let detail = `Match #${target.target_match_number} (${target.target_slot === 'team_a' ? 'Team 1' : 'Team 2'})`

  if (target.blocked_reason) {
    icon = '⚠'
    color = '#e65100'
    const reason = target.blocked_reason === 'SLOT_LOCKED' ? 'slot locked' : 'slot already set'
    detail += ` — ${reason}`
  }

  if (isFinal && target.advanced === true) {
    icon = '✓'
    color = '#2e7d32'
    detail += ' — advanced'
  } else if (isFinal && target.advanced === false && !target.blocked_reason) {
    icon = '…'
    color = '#888'
    detail += ' — pending'
  }

  return (
    <div style={{ fontSize: 12, color, marginBottom: 2, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
      <span style={{ fontWeight: 700, flexShrink: 0 }}>{label}</span>
      <span>{icon}</span>
      <span>{detail}</span>
      {target.target_current_team_display && (
        <span style={{ color: '#999', marginLeft: 4 }}>
          ({target.target_current_team_display})
        </span>
      )}
    </div>
  )
}

function MatchTimeline({ match }: { match: DeskMatchItem }) {
  const [expanded, setExpanded] = useState(false)

  const formatTs = (iso: string | null) => {
    if (!iso) return null
    try {
      const d = new Date(iso)
      return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
        hour12: true,
      })
    } catch { return iso }
  }

  interface TimelineEvent {
    ts: string
    sortKey: string
    icon: string
    color: string
    label: string
  }

  const events: TimelineEvent[] = []

  if (match.created_at) {
    events.push({
      ts: formatTs(match.created_at) || '',
      sortKey: match.created_at,
      icon: '●',
      color: '#bbb',
      label: 'Match created',
    })
  }

  if (match.started_at) {
    events.push({
      ts: formatTs(match.started_at) || '',
      sortKey: match.started_at,
      icon: '●',
      color: '#1a237e',
      label: 'Status changed to IN PROGRESS',
    })
  }

  if (match.completed_at) {
    events.push({
      ts: formatTs(match.completed_at) || '',
      sortKey: match.completed_at,
      icon: '●',
      color: '#2e7d32',
      label: 'Completed',
    })
  }

  if (match.winner_display && match.completed_at) {
    events.push({
      ts: formatTs(match.completed_at) || '',
      sortKey: match.completed_at + 'z1',
      icon: '★',
      color: '#2e7d32',
      label: `Winner: ${match.winner_display}`,
    })
  }

  events.sort((a, b) => a.sortKey.localeCompare(b.sortKey))

  return (
    <div style={{
      marginTop: 12,
      border: '1px solid #e0e0e0',
      borderRadius: 6,
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          width: '100%',
          padding: '8px 14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#fafafa',
          border: 'none',
          cursor: 'pointer',
          fontSize: 13,
          fontWeight: 600,
          color: '#555',
        }}
      >
        <span>Match History</span>
        <span style={{ fontSize: 10, color: '#999' }}>{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div style={{ padding: '10px 14px', borderTop: '1px solid #e8e8e8' }}>
          {events.length === 0 ? (
            <div style={{ fontSize: 12, color: '#bbb', fontStyle: 'italic' }}>No history yet</div>
          ) : (
            <div style={{ position: 'relative', paddingLeft: 18 }}>
              <div style={{
                position: 'absolute',
                left: 5,
                top: 6,
                bottom: 6,
                width: 2,
                backgroundColor: '#e0e0e0',
              }} />
              {events.map((ev, i) => (
                <div key={i} style={{
                  position: 'relative',
                  paddingBottom: i < events.length - 1 ? 10 : 0,
                }}>
                  <span style={{
                    position: 'absolute',
                    left: -18,
                    top: 1,
                    fontSize: ev.icon === '★' ? 11 : 10,
                    color: ev.color,
                    lineHeight: 1,
                    zIndex: 1,
                  }}>
                    {ev.icon}
                  </span>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#333' }}>
                    {ev.label}
                  </div>
                  <div style={{ fontSize: 10, color: '#999', marginTop: 1 }}>
                    {ev.ts}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function DrawerImpact({
  tournamentId,
  versionId,
  matchId,
  matchStatus,
  onSwitchToImpact,
}: {
  tournamentId: number
  versionId: number
  matchId: number
  matchStatus: string
  onSwitchToImpact: (() => void) | undefined
}) {
  const [impact, setImpact] = useState<MatchImpactItem | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getDeskImpact(tournamentId, versionId, matchId)
      .then(resp => {
        setImpact(resp.impacts.length > 0 ? resp.impacts[0] : null)
      })
      .catch(() => setImpact(null))
      .finally(() => setLoading(false))
  }, [tournamentId, versionId, matchId])

  if (loading) return null

  const isFinal = matchStatus === 'FINAL'
  const hasDownstream = impact?.winner_target || impact?.loser_target

  if (!hasDownstream) {
    return (
      <div style={{
        marginTop: 12,
        padding: '10px 14px',
        backgroundColor: '#f5f5f5',
        borderRadius: 6,
        fontSize: 12,
        color: '#999',
      }}>
        No downstream advancement paths.
      </div>
    )
  }

  return (
    <div style={{
      marginTop: 12,
      padding: '10px 14px',
      backgroundColor: '#f8f9ff',
      borderRadius: 6,
      border: '1px solid #e0e4f0',
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: '#1a237e', marginBottom: 6 }}>
        Downstream Impact
      </div>
      <ImpactArrow label="Winner" target={impact!.winner_target} isFinal={isFinal} />
      <ImpactArrow label="Loser" target={impact!.loser_target} isFinal={isFinal} />
      {onSwitchToImpact && (
        <button
          onClick={onSwitchToImpact}
          style={{
            marginTop: 6,
            fontSize: 11,
            color: '#1a237e',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            textDecoration: 'underline',
            padding: 0,
          }}
        >
          View in Impact tab
        </button>
      )}
    </div>
  )
}


// ── Impact Tab ────────────────────────────────────────────────────────

function ImpactTab({
  tournamentId,
  versionId,
  onMatchClick,
}: {
  tournamentId: number
  versionId: number
  onMatchClick: (m: DeskMatchItem) => void
}) {
  const [impacts, setImpacts] = useState<MatchImpactItem[]>([])
  const [loading, setLoading] = useState(true)
  const [searchNum, setSearchNum] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchImpacts = useCallback(() => {
    getDeskImpact(tournamentId, versionId)
      .then(resp => setImpacts(resp.impacts))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tournamentId, versionId])

  useEffect(() => {
    setLoading(true)
    fetchImpacts()
    intervalRef.current = setInterval(fetchImpacts, 25_000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [fetchImpacts])

  const filtered = useMemo(() => {
    let list = impacts
    if (searchNum) {
      const num = parseInt(searchNum, 10)
      if (!isNaN(num)) list = list.filter(i => i.match_number === num)
      else list = list.filter(i => i.match_code.toLowerCase().includes(searchNum.toLowerCase()))
    }
    if (stageFilter) list = list.filter(i => i.stage === stageFilter)
    // Only show matches with downstream paths
    list = list.filter(i => i.winner_target || i.loser_target)
    return list
  }, [impacts, searchNum, stageFilter])

  if (loading) {
    return <div style={{ color: '#888', fontSize: 13, padding: 20 }}>Loading impact data...</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          type="text"
          placeholder="Match # or code"
          value={searchNum}
          onChange={e => setSearchNum(e.target.value)}
          style={{
            padding: '6px 10px',
            fontSize: 13,
            border: '1px solid #ccc',
            borderRadius: 4,
            width: 160,
          }}
        />
        <select
          value={stageFilter}
          onChange={e => setStageFilter(e.target.value)}
          style={{ padding: '6px 10px', fontSize: 13, border: '1px solid #ccc', borderRadius: 4 }}
        >
          <option value="">All Stages</option>
          <option value="WF">WF</option>
          <option value="RR">RR</option>
          <option value="BRACKET">Bracket</option>
          <option value="CONS">Consolation</option>
          <option value="PLACEMENT">Placement</option>
        </select>
        <span style={{ fontSize: 11, color: '#aaa' }}>
          {filtered.length} match{filtered.length !== 1 ? 'es' : ''} with downstream paths
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {filtered.map(imp => {
          const isFinal = imp.status === 'FINAL'
          const sc = STATUS_COLORS[imp.status] || STATUS_COLORS.SCHEDULED
          return (
            <div
              key={imp.match_id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 14,
                padding: '10px 14px',
                backgroundColor: '#fff',
                border: '1px solid #e8e8e8',
                borderRadius: 6,
                cursor: 'pointer',
              }}
              onClick={() => {
                const fakeItem: DeskMatchItem = {
                  match_id: imp.match_id,
                  match_number: imp.match_number,
                  match_code: imp.match_code,
                  stage: imp.stage,
                  event_id: 0,
                  event_name: '',
                  division_name: null,
                  day_index: 0,
                  day_label: '',
                  scheduled_time: null,
                  sort_time: null,
                  court_name: null,
                  status: imp.status,
                  team1_id: imp.team1_id,
                  team1_display: imp.team1_display,
                  team2_id: imp.team2_id,
                  team2_display: imp.team2_display,
                  score_display: null,
                  source_match_a_id: null,
                  source_match_b_id: null,
                  created_at: null,
                  started_at: null,
                  completed_at: null,
                  winner_display: null,
                  slot_id: null,
                  assignment_id: null,
                  court_number: null,
                  day_date: null,
                }
                onMatchClick(fakeItem)
              }}
            >
              {/* Left: match info */}
              <div style={{ flex: '0 0 auto', minWidth: 180 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>#{imp.match_number}</span>
                  <Badge label={imp.stage} bg={STAGE_COLORS[imp.stage] || '#757575'} color="#fff" />
                  <Badge label={STATUS_LABEL[imp.status] || imp.status} bg={sc.bg} color={sc.text} />
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#333' }}>{imp.team1_display}</div>
                <div style={{ fontSize: 11, color: '#999' }}>vs</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#333' }}>{imp.team2_display}</div>
              </div>

              {/* Right: advancement paths */}
              <div style={{ flex: 1, borderLeft: '1px solid #eee', paddingLeft: 14 }}>
                <ImpactArrow label="Winner" target={imp.winner_target} isFinal={isFinal} />
                <ImpactArrow label="Loser" target={imp.loser_target} isFinal={isFinal} />
              </div>
            </div>
          )
        })}
        {filtered.length === 0 && (
          <div style={{ color: '#999', fontSize: 13, fontStyle: 'italic', padding: 10 }}>
            No matches with downstream advancement paths found.
          </div>
        )}
      </div>
    </div>
  )
}


// ── Schedule Tab ───────────────────────────────────────────────────────

function ScheduleTab({
  matches,
  isDraft: _isDraft,
  onMatchClick,
}: {
  matches: DeskMatchItem[]
  isDraft: boolean
  onMatchClick: (m: DeskMatchItem) => void
}) {
  const [filterEvent, setFilterEvent] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  const events = useMemo(() => {
    const set = new Set<string>()
    matches.forEach(m => set.add(m.event_name))
    return Array.from(set).sort()
  }, [matches])

  const grouped = useMemo(() => {
    let filtered = matches
    if (filterEvent) filtered = filtered.filter(m => m.event_name === filterEvent)
    if (filterStatus) filtered = filtered.filter(m => m.status === filterStatus)

    const days: Record<string, Record<string, DeskMatchItem[]>> = {}
    for (const m of filtered) {
      const dk = m.day_label || 'Unscheduled'
      const tk = m.sort_time || m.scheduled_time || 'Unscheduled'
      if (!days[dk]) days[dk] = {}
      if (!days[dk][tk]) days[dk][tk] = []
      days[dk][tk].push(m)
    }
    return days
  }, [matches, filterEvent, filterStatus])

  const sc = (status: string) => STATUS_COLORS[status] || STATUS_COLORS.SCHEDULED

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <select
          value={filterEvent}
          onChange={e => setFilterEvent(e.target.value)}
          style={{ padding: '6px 10px', fontSize: 13, borderRadius: 4, border: '1px solid #ccc' }}
        >
          <option value="">All Events</option>
          {events.map(e => <option key={e} value={e}>{e}</option>)}
        </select>
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          style={{ padding: '6px 10px', fontSize: 13, borderRadius: 4, border: '1px solid #ccc' }}
        >
          <option value="">All Statuses</option>
          <option value="SCHEDULED">Scheduled</option>
          <option value="IN_PROGRESS">In Progress</option>
          <option value="FINAL">Completed</option>
        </select>
      </div>
      {Object.entries(grouped).map(([day, times]) => (
        <div key={day} style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#1a237e', margin: '0 0 10px 0' }}>{day}</h3>
          {Object.entries(times).sort(([a], [b]) => a.localeCompare(b)).map(([time, ms]) => (
            <div key={time} style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#555', marginBottom: 6 }}>
                {ms[0]?.scheduled_time || time}
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                gap: 8,
              }}>
                {ms.map(m => (
                  <div
                    key={m.match_id}
                    onClick={() => onMatchClick(m)}
                    style={{
                      border: '1px solid #e0e0e0',
                      borderRadius: 6,
                      padding: '8px 10px',
                      backgroundColor: '#fff',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                      <span style={{ fontWeight: 700 }}>#{m.match_number}</span>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <EventBadge name={m.event_name} />
                        <Badge label={m.stage} bg={STAGE_COLORS[m.stage] || '#757575'} color="#fff" />
                        <Badge label={STATUS_LABEL[m.status] || m.status} bg={sc(m.status).bg} color={sc(m.status).text} />
                      </div>
                    </div>
                    <div style={{ fontWeight: 600, color: '#333' }}>{m.team1_display} vs {m.team2_display}</div>
                    <div style={{ color: '#888', fontSize: 11, marginTop: 2 }}>
                      {m.court_name}
                      {m.status === 'FINAL' && m.score_display ? ` — ${m.score_display}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}


// ── Draws Tab ──────────────────────────────────────────────────────────

function DrawsTab({
  tournamentId,
  versionId,
  matches,
}: {
  tournamentId: number
  versionId: number
  matches: DeskMatchItem[]
}) {
  const eventGroups = useMemo(() => {
    const map: Record<number, { name: string; hasWF: boolean; hasBracket: boolean; hasRR: boolean }> = {}
    for (const m of matches) {
      if (!map[m.event_id]) {
        map[m.event_id] = { name: m.event_name, hasWF: false, hasBracket: false, hasRR: false }
      }
      if (m.stage === 'WF') map[m.event_id].hasWF = true
      if (m.stage === 'BRACKET' || m.stage === 'CONS') map[m.event_id].hasBracket = true
      if (m.stage === 'RR') map[m.event_id].hasRR = true
    }
    return Object.entries(map).sort(([, a], [, b]) => a.name.localeCompare(b.name))
  }, [matches])

  const divisionCodes = ['BWW', 'BWL', 'BLW', 'BLL']
  const divisionLabels: Record<string, string> = {
    BWW: 'Division I',
    BWL: 'Division II',
    BLW: 'Division III',
    BLL: 'Division IV',
  }

  return (
    <div>
      <h2 style={{ fontSize: 16, fontWeight: 700, color: '#333', margin: '0 0 16px 0' }}>
        Event Draws
      </h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {eventGroups.map(([eid, ev]) => (
          <div
            key={eid}
            style={{
              border: '1px solid #e0e0e0',
              borderRadius: 8,
              backgroundColor: '#fff',
              padding: '14px 18px',
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 700, color: '#1a237e', marginBottom: 10 }}>
              {ev.name}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {ev.hasWF && (
                <a
                  href={`/t/${tournamentId}/draws/${eid}/waterfall?version_id=${versionId}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: '6px 14px',
                    fontSize: 12,
                    fontWeight: 600,
                    backgroundColor: '#1a237e',
                    color: '#fff',
                    borderRadius: 4,
                    textDecoration: 'none',
                  }}
                >
                  Waterfall
                </a>
              )}
              {ev.hasBracket && divisionCodes.map(dc => (
                <a
                  key={dc}
                  href={`/t/${tournamentId}/draws/${eid}/bracket/${dc}?version_id=${versionId}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: '6px 14px',
                    fontSize: 12,
                    fontWeight: 600,
                    backgroundColor: '#3949ab',
                    color: '#fff',
                    borderRadius: 4,
                    textDecoration: 'none',
                  }}
                >
                  {divisionLabels[dc]}
                </a>
              ))}
              {ev.hasRR && (
                <a
                  href={`/t/${tournamentId}/draws/${eid}/roundrobin?version_id=${versionId}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: '6px 14px',
                    fontSize: 12,
                    fontWeight: 600,
                    backgroundColor: '#2e7d32',
                    color: '#fff',
                    borderRadius: 4,
                    textDecoration: 'none',
                  }}
                >
                  Round Robin
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}


// ── Pool Projection Panel ─────────────────────────────────────────────

const BUCKET_COLORS: Record<string, string> = {
  WW: '#2e7d32', WL: '#558b2f', LW: '#e65100', LL: '#c62828',
  W: '#2e7d32', L: '#c62828',
}
const STATUS_BG: Record<string, string> = {
  confirmed: '#e8f5e9',
  projected: '#fff8e1',
  pending: '#f5f5f5',
}

function PoolProjectionPanel({
  tournamentId,
  versionId,
  isDraft,
  onPlacementComplete,
}: {
  tournamentId: number
  versionId: number
  isDraft: boolean
  onPlacementComplete?: () => void
}) {
  const [data, setData] = useState<PoolProjectionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [eventFilter, setEventFilter] = useState<number | ''>('')
  const [placing, setPlacing] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [confirmEvt, setConfirmEvt] = useState<EventProjection | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchProjection = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await getPoolProjection(
        tournamentId, versionId,
        eventFilter !== '' ? eventFilter : undefined
      )
      setData(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [tournamentId, versionId, eventFilter])

  useEffect(() => { fetchProjection() }, [fetchProjection])

  useEffect(() => {
    intervalRef.current = setInterval(fetchProjection, 30000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [fetchProjection])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(t)
  }, [toast])

  const handleConfirmPlacement = async (evt: EventProjection) => {
    setPlacing(true)
    try {
      const pools = evt.pools.map(p => ({
        pool_label: p.pool_label,
        team_ids: p.teams.map(t => t.team_id),
      }))
      await confirmPoolPlacement(tournamentId, {
        version_id: versionId,
        event_id: evt.event_id,
        pools,
      })
      setToast(`Pools placed for ${evt.event_name}`)
      setConfirmEvt(null)
      fetchProjection()
      onPlacementComplete?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Placement failed')
    } finally {
      setPlacing(false)
    }
  }

  if (loading && !data) return <div style={{ padding: 8, color: '#888', fontSize: 11 }}>Loading projections...</div>
  if (error) return <div style={{ padding: 8, color: '#c62828', fontSize: 11 }}>{error}</div>
  if (!data || data.events.length === 0) return <div style={{ padding: 8, color: '#888', fontSize: 11 }}>No WF events found.</div>

  const allEvents = data.events
  const uniqueEvents = Array.from(new Map(allEvents.map(e => [e.event_id, { id: e.event_id, name: e.event_name }])).values())

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 13, fontWeight: 700, color: '#333', margin: 0 }}>Pool Projection</h2>
        {uniqueEvents.length > 1 && (
          <select
            value={eventFilter}
            onChange={e => setEventFilter(e.target.value ? Number(e.target.value) : '')}
            style={{ padding: '2px 6px', fontSize: 10, borderRadius: 3, border: '1px solid #ccc' }}
          >
            <option value="">All</option>
            {uniqueEvents.map(ev => <option key={ev.id} value={ev.id}>{ev.name}</option>)}
          </select>
        )}
      </div>

      {allEvents.map(evt => {
        const pct = evt.total_wf_matches > 0 ? Math.round((evt.finalized_wf_matches / evt.total_wf_matches) * 100) : 0
        return (
          <div key={evt.event_id} style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#1a237e' }}>{evt.event_name}</span>
              {evt.wf_complete ? (
                <span style={{ fontSize: 9, fontWeight: 700, color: '#2e7d32', backgroundColor: '#e8f5e9', padding: '1px 6px', borderRadius: 3 }}>
                  ALL WF COMPLETE
                </span>
              ) : (
                <span style={{ fontSize: 9, color: '#888' }}>
                  {evt.finalized_wf_matches}/{evt.total_wf_matches} WF
                </span>
              )}
            </div>

            {/* Progress bar */}
            <div style={{ height: 4, backgroundColor: '#e0e0e0', borderRadius: 2, marginBottom: 6, maxWidth: 200 }}>
              <div style={{ height: '100%', width: `${pct}%`, backgroundColor: evt.wf_complete ? '#2e7d32' : '#1a237e', borderRadius: 2, transition: 'width 0.3s' }} />
            </div>

            {/* Pool cards */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {evt.pools.map(pool => (
                <div key={pool.pool_label} style={{
                  border: '1px solid #ddd', borderRadius: 4, padding: '4px 8px',
                  minWidth: 130, maxWidth: 180, flex: '1 1 130px',
                  backgroundColor: '#fafafa',
                }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#1a237e', marginBottom: 3, borderBottom: '1px solid #eee', paddingBottom: 2 }}>
                    {pool.pool_display}
                  </div>
                  {pool.teams.map((team, idx) => (
                    <div key={team.team_id} style={{
                      display: 'flex', alignItems: 'center', gap: 4,
                      padding: '1px 0', fontSize: 10,
                      backgroundColor: STATUS_BG[team.status] || '#fff',
                      borderRadius: 2, marginBottom: 1,
                      opacity: team.status === 'pending' ? 0.5 : 1,
                    }}>
                      <span style={{ width: 14, textAlign: 'center', fontSize: 9, color: '#999' }}>{idx + 1}</span>
                      <span style={{
                        fontSize: 8, fontWeight: 700, padding: '0 3px', borderRadius: 2,
                        color: '#fff', backgroundColor: BUCKET_COLORS[team.bucket] || '#999',
                        minWidth: 18, textAlign: 'center',
                      }}>
                        {team.bucket}
                      </span>
                      <span style={{ fontWeight: 600, color: '#333', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {team.status === 'pending' ? '—' : team.team_display}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            {/* Confirm placement button */}
            {evt.wf_complete && isDraft && (
              <button
                onClick={() => setConfirmEvt(evt)}
                disabled={placing}
                style={{
                  marginTop: 6, padding: '4px 12px', fontSize: 10, fontWeight: 700,
                  backgroundColor: '#1a237e', color: '#fff', border: 'none', borderRadius: 3,
                  cursor: placing ? 'not-allowed' : 'pointer', opacity: placing ? 0.6 : 1,
                }}
              >
                {placing ? 'Placing...' : 'Confirm Pool Placement'}
              </button>
            )}
          </div>
        )
      })}

      {/* Confirm modal */}
      {confirmEvt && (
        <>
          <div onClick={() => setConfirmEvt(null)} style={{
            position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
            backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 1999,
          }} />
          <div style={{
            position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
            backgroundColor: '#fff', borderRadius: 8, padding: 20, zIndex: 2000,
            boxShadow: '0 8px 32px rgba(0,0,0,0.25)', minWidth: 300, maxWidth: 400,
          }}>
            <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#1a237e' }}>Confirm Pool Placement</h3>
            <p style={{ fontSize: 11, color: '#555', margin: '0 0 12px' }}>
              Place teams into RR pools for <strong>{confirmEvt.event_name}</strong>?
              This will assign teams to all RR match slots.
            </p>
            <div style={{ fontSize: 10, marginBottom: 12 }}>
              {confirmEvt.pools.map(p => (
                <div key={p.pool_label} style={{ marginBottom: 4 }}>
                  <strong>{p.pool_display}:</strong>{' '}
                  {p.teams.map(t => t.team_display).join(', ')}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirmEvt(null)} style={{
                padding: '5px 14px', fontSize: 11, border: '1px solid #ccc', borderRadius: 4,
                backgroundColor: '#fff', cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={() => handleConfirmPlacement(confirmEvt)} disabled={placing} style={{
                padding: '5px 14px', fontSize: 11, border: 'none', borderRadius: 4,
                backgroundColor: '#1a237e', color: '#fff', fontWeight: 700,
                cursor: placing ? 'not-allowed' : 'pointer',
              }}>{placing ? 'Placing...' : 'Confirm'}</button>
            </div>
          </div>
        </>
      )}

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          padding: '8px 20px', backgroundColor: '#2e7d32', color: '#fff',
          borderRadius: 6, fontSize: 12, fontWeight: 600, zIndex: 2000,
          boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
        }}>{toast}</div>
      )}
    </div>
  )
}


// ── Bulk Controls Panel ────────────────────────────────────────────────

function BulkControlsPanel({
  isDraft,
  data,
  onBulkPause,
  onBulkResume,
  onBulkDelay,
  onBulkUndelay,
}: {
  isDraft: boolean
  data: DeskSnapshotResponse
  onBulkPause: () => void
  onBulkResume: () => void
  onBulkDelay: (afterTime: string, dayIndex?: number) => void
  onBulkUndelay: () => void
}) {
  const [delayTime, setDelayTime] = useState('12:00')
  const [delayDay, setDelayDay] = useState<number | undefined>(undefined)

  const inProgressCount = data.matches.filter(m => m.status === 'IN_PROGRESS').length
  const scheduledCount = data.matches.filter(m => m.status === 'SCHEDULED').length
  const pausedCount = data.matches.filter(m => m.status === 'PAUSED').length
  const delayedCount = data.matches.filter(m => m.status === 'DELAYED').length

  const dayOptions = useMemo(() => {
    const days = new Set<number>()
    data.matches.forEach(m => { if (m.day_index > 0) days.add(m.day_index) })
    return Array.from(days).sort()
  }, [data.matches])

  if (!isDraft) {
    return (
      <div style={{
        padding: '20px 0',
        color: '#888',
        fontSize: 13,
        fontStyle: 'italic',
        textAlign: 'center',
      }}>
        Open Desk Draft to use bulk controls
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 600 }}>
      {/* Status summary */}
      <div style={{
        display: 'flex',
        gap: 12,
        marginBottom: 24,
        flexWrap: 'wrap',
      }}>
        {[
          { label: 'In Progress', count: inProgressCount, color: '#e65100' },
          { label: 'Scheduled', count: scheduledCount, color: '#555' },
          { label: 'Paused', count: pausedCount, color: '#c62828' },
          { label: 'Delayed', count: delayedCount, color: '#f57f17' },
        ].map(s => (
          <div key={s.label} style={{
            padding: '8px 16px',
            borderRadius: 6,
            border: '1px solid #e0e0e0',
            backgroundColor: '#fff',
            textAlign: 'center',
            minWidth: 90,
          }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.count}</div>
            <div style={{ fontSize: 11, color: '#888', fontWeight: 600 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Pause / Resume */}
      <div style={{
        padding: 16,
        border: '1px solid #e0e0e0',
        borderRadius: 8,
        backgroundColor: '#fff',
        marginBottom: 16,
      }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 700, color: '#333' }}>
          Pause / Resume
        </h3>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
          Pause all in-progress matches or resume all paused matches at once.
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            onClick={onBulkPause}
            disabled={inProgressCount === 0}
            style={{
              padding: '8px 20px',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: inProgressCount > 0 ? '#c62828' : '#ccc',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: inProgressCount > 0 ? 'pointer' : 'default',
            }}
          >
            Pause All In-Progress ({inProgressCount})
          </button>
          <button
            onClick={onBulkResume}
            disabled={pausedCount === 0}
            style={{
              padding: '8px 20px',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: pausedCount > 0 ? '#2e7d32' : '#ccc',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: pausedCount > 0 ? 'pointer' : 'default',
            }}
          >
            Resume All Paused ({pausedCount})
          </button>
        </div>
      </div>

      {/* Delay / Un-delay */}
      <div style={{
        padding: 16,
        border: '1px solid #e0e0e0',
        borderRadius: 8,
        backgroundColor: '#fff',
      }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 700, color: '#333' }}>
          Delay / Un-delay
        </h3>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
          Delay scheduled matches after a time, or restore all delayed matches back to scheduled.
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
          <div>
            <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 2 }}>Time</label>
            <input
              type="time"
              value={delayTime}
              onChange={e => setDelayTime(e.target.value)}
              style={{
                padding: '6px 10px',
                fontSize: 13,
                border: '1px solid #ccc',
                borderRadius: 4,
              }}
            />
          </div>
          <div>
            <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 2 }}>Day (optional)</label>
            <select
              value={delayDay ?? ''}
              onChange={e => setDelayDay(e.target.value ? parseInt(e.target.value) : undefined)}
              style={{
                padding: '6px 10px',
                fontSize: 13,
                border: '1px solid #ccc',
                borderRadius: 4,
              }}
            >
              <option value="">All Days</option>
              {dayOptions.map(d => (
                <option key={d} value={d}>Day {d}</option>
              ))}
            </select>
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <button
              onClick={() => onBulkDelay(delayTime, delayDay)}
              disabled={scheduledCount === 0}
              style={{
                padding: '8px 20px',
                fontSize: 13,
                fontWeight: 600,
                backgroundColor: scheduledCount > 0 ? '#f57f17' : '#ccc',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: scheduledCount > 0 ? 'pointer' : 'default',
              }}
            >
              Set to Delayed
            </button>
          </div>
        </div>
        {delayedCount > 0 && (
          <button
            onClick={onBulkUndelay}
            style={{
              padding: '8px 20px',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: '#1565c0',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Restore All Delayed to Scheduled ({delayedCount})
          </button>
        )}
      </div>
    </div>
  )
}


// ── Weather / Reschedule Tab ──────────────────────────────────────────

type WizardStep = 'setup' | 'preview' | 'done' | 'rebuild_preview' | 'rebuild_done'

interface RebuildDayRow {
  date: string
  enabled: boolean
  start_time: string
  end_time: string
  courts: number
  format: string
}

const FORMAT_OPTIONS = [
  { value: 'REGULAR', label: 'Full Match 3rd Set TB (1:45)', minutes: 105 },
  { value: 'PRO_SET_8', label: '8-Game Pro Set (1:00)', minutes: 60 },
  { value: 'PRO_SET_4', label: '4-Game Pro Set (0:35)', minutes: 35 },
]

function WeatherTab({
  tournamentId,
  data,
  isDraft,
  onBulkPause,
  onBulkResume,
  onBulkDelay,
  onBulkUndelay,
  onRefresh,
  onSwitchToGrid,
  onRescheduled,
}: {
  tournamentId: number
  data: DeskSnapshotResponse
  isDraft: boolean
  onBulkPause: () => void
  onBulkResume: () => void
  onBulkDelay: (afterTime: string, dayIndex?: number) => void
  onBulkUndelay: () => void
  onRefresh: () => void
  onSwitchToGrid: () => void
  onRescheduled: (ids: number[]) => void
}) {
  const [mode, setMode] = useState<'PARTIAL_DAY' | 'REBUILD' | 'COURT_LOSS'>('PARTIAL_DAY')
  const [affectedDay, setAffectedDay] = useState('')
  const [unavailableFrom, setUnavailableFrom] = useState('11:00')
  const [availableFrom, setAvailableFrom] = useState('14:00')
  const [unavailableCourts, setUnavailableCourts] = useState<number[]>([])
  const [extendEnd, setExtendEnd] = useState('')
  const [addSlots, setAddSlots] = useState(true)
  const [step, setStep] = useState<WizardStep>('setup')
  const [preview, setPreview] = useState<ReschedulePreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [applyLoading, setApplyLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [selectedFormat] = useState<string | null>(null)

  // Rebuild state
  const [rebuildDays, setRebuildDays] = useState<RebuildDayRow[]>([])
  const [rbPreview, setRbPreview] = useState<RebuildPreviewResponse | null>(null)
  const [rbLoading, setRbLoading] = useState(false)
  const [rbApplyLoading, setRbApplyLoading] = useState(false)
  const [dropConsolation, setDropConsolation] = useState<'none' | 'finals' | 'all'>('none')

  const inProgressCount = data.matches.filter(m => m.status === 'IN_PROGRESS').length
  const pausedCount = data.matches.filter(m => m.status === 'PAUSED').length
  const delayedCount = data.matches.filter(m => m.status === 'DELAYED').length
  const remainingCount = data.matches.filter(m => m.status !== 'FINAL').length

  const scheduleDays = useMemo(() => {
    const days = new Set<string>()
    data.slots.forEach(s => days.add(s.day_date))
    data.matches.forEach(m => { if (m.day_date) days.add(m.day_date) })
    return Array.from(days).sort()
  }, [data.slots, data.matches])

  const allCourts = useMemo(() => {
    const courts = new Set<number>()
    data.slots.forEach(s => courts.add(s.court_number))
    return Array.from(courts).sort((a, b) => a - b)
  }, [data.slots])

  const defaultCourtCount = allCourts.length || 1

  useEffect(() => {
    if (!affectedDay && scheduleDays.length > 0) setAffectedDay(scheduleDays[0])
  }, [scheduleDays, affectedDay])

  // Initialize rebuild days from schedule days when switching to REBUILD mode
  useEffect(() => {
    if (mode === 'REBUILD' && rebuildDays.length === 0 && scheduleDays.length > 0) {
      const dayStartTimes: Record<string, string> = {}
      const dayEndTimes: Record<string, string> = {}
      data.slots.forEach(s => {
        const st = s.start_time.slice(0, 5)
        const et = s.end_time?.slice(0, 5) || st
        if (!dayStartTimes[s.day_date] || st < dayStartTimes[s.day_date]) dayStartTimes[s.day_date] = st
        if (!dayEndTimes[s.day_date] || et > dayEndTimes[s.day_date]) dayEndTimes[s.day_date] = et
      })
      setRebuildDays(scheduleDays.map(d => ({
        date: d,
        enabled: true,
        start_time: dayStartTimes[d] || '08:00',
        end_time: dayEndTimes[d] || '18:00',
        courts: defaultCourtCount,
        format: 'REGULAR',
      })))
    }
  }, [mode, scheduleDays, rebuildDays.length, data.slots, defaultCourtCount])

  const updateRebuildDay = (idx: number, patch: Partial<RebuildDayRow>) => {
    setRebuildDays(prev => prev.map((d, i) => i === idx ? { ...d, ...patch } : d))
  }

  const rebuildSlotCount = useMemo(() => {
    let total = 0
    for (const d of rebuildDays) {
      if (!d.enabled) continue
      const fmt = FORMAT_OPTIONS.find(f => f.value === d.format)
      const blockMin = fmt?.minutes || 105
      const [sh, sm] = d.start_time.split(':').map(Number)
      const [eh, em] = d.end_time.split(':').map(Number)
      const startMin = sh * 60 + sm
      const endMin = eh * 60 + em
      const slotsPerCourt = Math.max(0, Math.floor((endMin - startMin) / blockMin))
      total += slotsPerCourt * d.courts
    }
    return total
  }, [rebuildDays])

  const handleNextFromSetup = async () => {
    handlePreview()
  }

  const handlePreview = async (format?: string) => {
    setPreviewLoading(true)
    setError(null)
    try {
      const resp = await reschedulePreview(tournamentId, {
        version_id: data.version_id,
        mode: mode === 'REBUILD' ? 'PARTIAL_DAY' : mode,
        affected_day: affectedDay,
        unavailable_from: mode === 'PARTIAL_DAY' ? unavailableFrom : undefined,
        available_from: mode === 'PARTIAL_DAY' ? availableFrom : undefined,
        unavailable_courts: mode === 'COURT_LOSS' ? unavailableCourts : undefined,
        extend_day_end: extendEnd || undefined,
        add_time_slots: addSlots,
        scoring_format: format || selectedFormat || undefined,
      })
      setPreview(resp)
      setStep('preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleApply = async () => {
    if (!preview) return
    setApplyLoading(true)
    setError(null)
    try {
      const moves = preview.proposed_moves.map(m => ({ match_id: m.match_id, new_slot_id: m.new_slot_id }))
      await rescheduleApply(tournamentId, {
        version_id: data.version_id,
        moves,
        duration_updates: preview.duration_updates || undefined,
      })
      setStep('done')
      setToast(`Rescheduled ${preview.proposed_moves.length} matches`)
      setTimeout(() => setToast(null), 5000)
      onRescheduled(preview.proposed_moves.map(m => m.match_id))
      onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Apply failed')
    } finally {
      setApplyLoading(false)
    }
  }

  const handleRebuildPreview = async () => {
    setRbLoading(true)
    setError(null)
    try {
      const enabledDays = rebuildDays.filter(d => d.enabled)
      const resp = await rebuildPreview(tournamentId, {
        version_id: data.version_id,
        days: enabledDays.map(d => ({
          date: d.date,
          start_time: d.start_time,
          end_time: d.end_time,
          courts: d.courts,
          format: d.format,
        })),
        drop_consolation: dropConsolation,
      })
      setRbPreview(resp)
      setStep('rebuild_preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed')
    } finally {
      setRbLoading(false)
    }
  }

  const handleRebuildApply = async () => {
    setRbApplyLoading(true)
    setError(null)
    try {
      const enabledDays = rebuildDays.filter(d => d.enabled)
      const resp = await rebuildApply(tournamentId, {
        version_id: data.version_id,
        days: enabledDays.map(d => ({
          date: d.date,
          start_time: d.start_time,
          end_time: d.end_time,
          courts: d.courts,
          format: d.format,
        })),
        drop_consolation: dropConsolation,
      })
      setStep('rebuild_done')
      const parts = [`${resp.assigned} assigned`, `${resp.slots_created} slots created`]
      if (resp.dropped_count > 0) parts.push(`${resp.dropped_count} consolation matches dropped`)
      setToast(`Rebuilt schedule: ${parts.join(', ')}`)
      setTimeout(() => setToast(null), 5000)
      onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rebuild failed')
    } finally {
      setRbApplyLoading(false)
    }
  }

  const btnStyle = (active: boolean, color: string = '#1a237e'): React.CSSProperties => ({
    padding: '8px 20px',
    fontSize: 13,
    fontWeight: 600,
    backgroundColor: active ? color : '#ccc',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    cursor: active ? 'pointer' : 'default',
  })

  const inputStyle: React.CSSProperties = {
    padding: '6px 10px', fontSize: 15, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, width: 150,
  }

  if (!isDraft) {
    return (
      <div style={{ padding: '20px 0', color: '#888', fontSize: 13, fontStyle: 'italic', textAlign: 'center' }}>
        Open Desk Draft to use weather / reschedule controls
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 900 }}>
      {error && (
        <div style={{ padding: 12, backgroundColor: '#ffebee', color: '#c62828', borderRadius: 6, marginBottom: 16, fontSize: 13 }}>
          {error}
        </div>
      )}
      {toast && (
        <div style={{ padding: 12, backgroundColor: '#e8f5e9', color: '#2e7d32', borderRadius: 6, marginBottom: 16, fontSize: 13, fontWeight: 600 }}>
          {toast}
        </div>
      )}

      {/* Quick Actions */}
      <div style={{ padding: 16, border: '1px solid #e0e0e0', borderRadius: 8, backgroundColor: '#fff', marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 700, color: '#333' }}>Quick Actions</h3>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
          Short rain delay? Pause all matches and resume when ready.
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button onClick={onBulkPause} disabled={inProgressCount === 0} style={btnStyle(inProgressCount > 0, '#c62828')}>
            Pause All ({inProgressCount})
          </button>
          <button onClick={onBulkResume} disabled={pausedCount === 0} style={btnStyle(pausedCount > 0, '#2e7d32')}>
            Resume All ({pausedCount})
          </button>
          <button onClick={() => onBulkDelay('00:00')} disabled={delayedCount > 0} style={btnStyle(delayedCount === 0, '#f57f17')}>
            Delay All Upcoming
          </button>
          {delayedCount > 0 && (
            <button onClick={onBulkUndelay} style={btnStyle(true, '#1565c0')}>
              Un-delay All ({delayedCount})
            </button>
          )}
        </div>
      </div>

      {/* Reschedule Wizard */}
      <div style={{ padding: 16, border: '1px solid #e0e0e0', borderRadius: 8, backgroundColor: '#fff' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: '#1a237e' }}>
          Reschedule Wizard
        </h3>

        {step === 'setup' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#333', marginBottom: 8 }}>What happened?</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                {([
                  { value: 'PARTIAL_DAY' as const, label: 'Partial Day Loss' },
                  { value: 'REBUILD' as const, label: 'Rebuild Remaining Schedule' },
                  { value: 'COURT_LOSS' as const, label: 'Court Loss' },
                ]).map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => setMode(opt.value)}
                    style={{
                      padding: '8px 18px',
                      fontSize: 13,
                      fontWeight: 600,
                      border: mode === opt.value ? '2px solid #1a237e' : '2px solid #ccc',
                      borderRadius: 6,
                      backgroundColor: mode === opt.value ? '#e8eaf6' : '#fff',
                      color: mode === opt.value ? '#1a237e' : '#555',
                      cursor: 'pointer',
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* REBUILD: Day configuration table */}
            {mode === 'REBUILD' && (
              <>
                <div style={{ fontSize: 12, color: '#666', marginBottom: 10 }}>
                  Configure remaining days. Uncheck days no longer available. Adjust times, courts, and match format per day.
                </div>
                <div style={{ overflowX: 'auto', marginBottom: 12 }}>
                  <table style={{ borderCollapse: 'collapse', fontSize: 14, width: '100%' }}>
                    <thead>
                      <tr style={{ backgroundColor: '#f5f5f5' }}>
                        <th style={{ padding: '8px 10px', textAlign: 'center', borderBottom: '1px solid #ddd', width: 36 }}></th>
                        <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Date</th>
                        <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Start</th>
                        <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>End</th>
                        <th style={{ padding: '8px 10px', textAlign: 'center', borderBottom: '1px solid #ddd' }}>Courts</th>
                        <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Format</th>
                        <th style={{ padding: '8px 10px', textAlign: 'center', borderBottom: '1px solid #ddd' }}>Slots</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rebuildDays.map((day, i) => {
                        const fmt = FORMAT_OPTIONS.find(f => f.value === day.format)
                        const blockMin = fmt?.minutes || 105
                        const [sh, sm] = day.start_time.split(':').map(Number)
                        const [eh, em] = day.end_time.split(':').map(Number)
                        const slotsPerCourt = Math.max(0, Math.floor(((eh * 60 + em) - (sh * 60 + sm)) / blockMin))
                        const daySlots = day.enabled ? slotsPerCourt * day.courts : 0
                        return (
                          <tr key={day.date} style={{
                            borderBottom: '1px solid #f0f0f0',
                            opacity: day.enabled ? 1 : 0.4,
                          }}>
                            <td style={{ padding: '4px 8px', textAlign: 'center' }}>
                              <input
                                type="checkbox"
                                checked={day.enabled}
                                onChange={e => updateRebuildDay(i, { enabled: e.target.checked })}
                              />
                            </td>
                            <td style={{ padding: '6px 10px', fontWeight: 700, fontSize: 14 }}>{day.date}</td>
                            <td style={{ padding: '6px 10px' }}>
                              <input
                                type="time"
                                value={day.start_time}
                                onChange={e => updateRebuildDay(i, { start_time: e.target.value })}
                                disabled={!day.enabled}
                                style={inputStyle}
                              />
                            </td>
                            <td style={{ padding: '6px 10px' }}>
                              <input
                                type="time"
                                value={day.end_time}
                                onChange={e => updateRebuildDay(i, { end_time: e.target.value })}
                                disabled={!day.enabled}
                                style={inputStyle}
                              />
                            </td>
                            <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                              <input
                                type="number"
                                min={1}
                                max={20}
                                value={day.courts}
                                onChange={e => updateRebuildDay(i, { courts: parseInt(e.target.value) || 1 })}
                                disabled={!day.enabled}
                                style={{ ...inputStyle, width: 70, textAlign: 'center' }}
                              />
                            </td>
                            <td style={{ padding: '6px 10px' }}>
                              <select
                                value={day.format}
                                onChange={e => updateRebuildDay(i, { format: e.target.value })}
                                disabled={!day.enabled}
                                style={{ ...inputStyle, width: 250 }}
                              >
                                {FORMAT_OPTIONS.map(f => (
                                  <option key={f.value} value={f.value}>{f.label}</option>
                                ))}
                              </select>
                            </td>
                            <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: '#1a237e' }}>
                              {daySlots}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div style={{
                  padding: '10px 14px',
                  backgroundColor: rebuildSlotCount >= remainingCount ? '#e8f5e9' : '#fff3e0',
                  borderRadius: 6,
                  border: `1px solid ${rebuildSlotCount >= remainingCount ? '#c8e6c9' : '#ffe0b2'}`,
                  marginBottom: 16,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: 13,
                  fontWeight: 600,
                }}>
                  <span>
                    {remainingCount} remaining match{remainingCount !== 1 ? 'es' : ''}
                    {' '}/{' '}
                    {rebuildSlotCount} slots available
                  </span>
                  <span style={{
                    color: rebuildSlotCount >= remainingCount ? '#2e7d32' : '#e65100',
                    fontWeight: 700,
                  }}>
                    {rebuildSlotCount >= remainingCount
                      ? 'Fits'
                      : `${remainingCount - rebuildSlotCount} over capacity`}
                  </span>
                </div>

                {/* Drop consolation matches to reduce match count */}
                {(rebuildSlotCount < remainingCount || dropConsolation !== 'none') && (
                  <div style={{
                    padding: '12px 14px',
                    backgroundColor: '#fff8e1',
                    borderRadius: 6,
                    border: '1px solid #ffe082',
                    marginBottom: 16,
                  }}>
                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8, color: '#e65100' }}>
                      Not enough slots — trim consolation matches?
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                        <input
                          type="radio"
                          name="dropConsolation"
                          checked={dropConsolation === 'none'}
                          onChange={() => setDropConsolation('none')}
                          style={{ width: 16, height: 16 }}
                        />
                        <span>Keep all matches</span>
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                        <input
                          type="radio"
                          name="dropConsolation"
                          checked={dropConsolation === 'finals'}
                          onChange={() => setDropConsolation('finals')}
                          style={{ width: 16, height: 16 }}
                        />
                        <span>Drop consolation finals only (keeps consolation semis)</span>
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                        <input
                          type="radio"
                          name="dropConsolation"
                          checked={dropConsolation === 'all'}
                          onChange={() => setDropConsolation('all')}
                          style={{ width: 16, height: 16 }}
                        />
                        <span>Drop all consolation matches (semis + finals)</span>
                      </label>
                    </div>
                  </div>
                )}

                <button
                  onClick={handleRebuildPreview}
                  disabled={rbLoading || rebuildDays.filter(d => d.enabled).length === 0}
                  style={btnStyle(!rbLoading && rebuildDays.filter(d => d.enabled).length > 0)}
                >
                  {rbLoading ? 'Computing...' : 'Preview Rebuild'}
                </button>
              </>
            )}

            {/* PARTIAL_DAY / COURT_LOSS: existing fields */}
            {mode !== 'REBUILD' && (
              <>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
                  <div>
                    <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 2 }}>Affected Day</label>
                    <select
                      value={affectedDay}
                      onChange={e => setAffectedDay(e.target.value)}
                      style={{ padding: '6px 10px', fontSize: 13, border: '1px solid #ccc', borderRadius: 4 }}
                    >
                      {scheduleDays.map(d => (
                        <option key={d} value={d}>{d}</option>
                      ))}
                    </select>
                  </div>

                  {mode === 'PARTIAL_DAY' && (
                    <>
                      <div>
                        <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 2 }}>Unavailable From</label>
                        <input
                          type="time"
                          value={unavailableFrom}
                          onChange={e => setUnavailableFrom(e.target.value)}
                          style={{ padding: '6px 10px', fontSize: 13, border: '1px solid #ccc', borderRadius: 4 }}
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 2 }}>Available From</label>
                        <input
                          type="time"
                          value={availableFrom}
                          onChange={e => setAvailableFrom(e.target.value)}
                          style={{ padding: '6px 10px', fontSize: 13, border: '1px solid #ccc', borderRadius: 4 }}
                        />
                      </div>
                    </>
                  )}
                </div>

                {mode === 'COURT_LOSS' && (
                  <div style={{ marginBottom: 16 }}>
                    <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 4 }}>Unavailable Courts</label>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {allCourts.map(cn => (
                        <label key={cn} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={unavailableCourts.includes(cn)}
                            onChange={e => {
                              if (e.target.checked) setUnavailableCourts([...unavailableCourts, cn])
                              else setUnavailableCourts(unavailableCourts.filter(c => c !== cn))
                            }}
                          />
                          Court {cn}
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 20, alignItems: 'flex-end' }}>
                  <div>
                    <label style={{ fontSize: 11, color: '#888', fontWeight: 600, display: 'block', marginBottom: 2 }}>Extend Day End Time (optional)</label>
                    <input
                      type="time"
                      value={extendEnd}
                      onChange={e => setExtendEnd(e.target.value)}
                      style={{ padding: '6px 10px', fontSize: 13, border: '1px solid #ccc', borderRadius: 4 }}
                    />
                  </div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={addSlots} onChange={e => setAddSlots(e.target.checked)} />
                    Auto-create overflow time slots
                  </label>
                </div>

                <button
                  onClick={handleNextFromSetup}
                  disabled={previewLoading || !affectedDay}
                  style={btnStyle(!previewLoading && !!affectedDay)}
                >
                  {previewLoading ? 'Computing...' : 'Preview Reschedule'}
                </button>
              </>
            )}
          </>
        )}

        {step === 'preview' && preview && (
          <>
            {preview.format_applied && (
              <div style={{
                padding: '6px 12px', marginBottom: 12, borderRadius: 6,
                backgroundColor: '#e8eaf6', border: '1px solid #c5cae9',
                fontSize: 12, fontWeight: 600, color: '#1a237e',
              }}>
                Format: {preview.format_applied === 'PRO_SET_8' ? '8-Game Pro Set (60 min)' : preview.format_applied === 'PRO_SET_4' ? '4-Game Pro Set (35 min)' : 'Regular (105 min)'}
                {preview.duration_updates && ` — ${Object.keys(preview.duration_updates).length} match durations updated`}
              </div>
            )}
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
              {[
                { label: 'Affected', value: preview.stats.total_affected, color: '#e65100' },
                { label: 'Rescheduled', value: preview.stats.total_moved, color: '#2e7d32' },
                { label: 'Unplaceable', value: preview.stats.total_unplaceable, color: '#c62828' },
                { label: 'Kept', value: preview.stats.total_kept, color: '#555' },
              ].map(s => (
                <div key={s.label} style={{
                  padding: '8px 16px', borderRadius: 6, border: '1px solid #e0e0e0',
                  backgroundColor: '#fff', textAlign: 'center', minWidth: 80,
                }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: '#888', fontWeight: 600 }}>{s.label}</div>
                </div>
              ))}
              {preview.new_slots_created > 0 && (
                <div style={{
                  padding: '8px 16px', borderRadius: 6, border: '1px solid #e0e0e0',
                  backgroundColor: '#fff', textAlign: 'center', minWidth: 80,
                }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#1565c0' }}>{preview.new_slots_created}</div>
                  <div style={{ fontSize: 11, color: '#888', fontWeight: 600 }}>New Slots</div>
                </div>
              )}
            </div>

            {preview.proposed_moves.length > 0 && (
              <div style={{ marginBottom: 16, maxHeight: 400, overflowY: 'auto', border: '1px solid #e0e0e0', borderRadius: 6 }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#f5f5f5', position: 'sticky', top: 0 }}>
                      <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Match</th>
                      <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Event</th>
                      <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>From</th>
                      <th style={{ padding: '6px 8px', textAlign: 'center', borderBottom: '1px solid #ddd' }}></th>
                      <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>To</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.proposed_moves.map(m => (
                      <tr key={m.match_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                        <td style={{ padding: '5px 8px', fontWeight: 600 }}>{m.match_code}</td>
                        <td style={{ padding: '5px 8px', color: '#555' }}>{m.event_name} ({m.stage})</td>
                        <td style={{ padding: '5px 8px', color: '#888' }}>
                          {m.old_court ? `${m.old_court} @ ${m.old_time}` : 'Unassigned'}
                        </td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', color: '#1a237e', fontWeight: 700 }}>→</td>
                        <td style={{ padding: '5px 8px', color: '#2e7d32', fontWeight: 600 }}>
                          {m.new_court} @ {m.new_time}
                          {m.new_day !== m.old_day && <span style={{ color: '#888', marginLeft: 4 }}>({m.new_day})</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {preview.unplaceable.length > 0 && (
              <div style={{
                padding: 12, backgroundColor: '#ffebee', borderRadius: 6, marginBottom: 16,
                border: '1px solid #ef9a9a',
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#c62828', marginBottom: 6 }}>
                  Could Not Place ({preview.unplaceable.length})
                </div>
                {preview.unplaceable.map(u => (
                  <div key={u.match_id} style={{ fontSize: 12, color: '#c62828', padding: '2px 0' }}>
                    {u.match_code} — {u.event_name} ({u.stage}): {u.reason}
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
              <button onClick={handleApply} disabled={applyLoading || preview.proposed_moves.length === 0} style={btnStyle(!applyLoading && preview.proposed_moves.length > 0, '#2e7d32')}>
                {applyLoading ? 'Applying...' : `Apply Reschedule (${preview.proposed_moves.length})`}
              </button>
              <button
                onClick={() => { setStep('setup'); setPreview(null) }}
                style={{ padding: '8px 20px', fontSize: 13, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', color: '#555', cursor: 'pointer' }}
              >
                ← Back
              </button>
            </div>
          </>
        )}

        {/* Rebuild Preview */}
        {step === 'rebuild_preview' && rbPreview && (
          <>
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
              {[
                { label: 'Remaining', value: rbPreview.remaining_matches, color: '#e65100' },
                { label: 'In Progress', value: rbPreview.in_progress_matches, color: '#1565c0' },
                { label: 'Slots', value: rbPreview.total_slots, color: '#2e7d32' },
                ...(rbPreview.dropped_count > 0
                  ? [{ label: 'Dropped', value: rbPreview.dropped_count, color: '#c62828' }]
                  : []),
              ].map(s => (
                <div key={s.label} style={{
                  padding: '8px 16px', borderRadius: 6, border: '1px solid #e0e0e0',
                  backgroundColor: '#fff', textAlign: 'center', minWidth: 80,
                }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: '#888', fontWeight: 600 }}>{s.label}</div>
                </div>
              ))}
            </div>

            {rbPreview.dropped_count > 0 && (
              <div style={{
                padding: 12, backgroundColor: '#fce4ec', borderRadius: 6, marginBottom: 16,
                border: '1px solid #ef9a9a', fontSize: 13, fontWeight: 600, color: '#c62828',
              }}>
                {rbPreview.dropped_count} consolation match{rbPreview.dropped_count !== 1 ? 'es' : ''} will be cancelled
                ({dropConsolation === 'finals' ? 'consolation finals only' : 'all consolation matches'}).
              </div>
            )}

            {rbPreview.overflow > 0 && (
              <div style={{
                padding: 12, backgroundColor: '#fff3e0', borderRadius: 6, marginBottom: 16,
                border: '1px solid #ffe0b2', fontSize: 13, fontWeight: 600, color: '#e65100',
              }}>
                {rbPreview.overflow} match{rbPreview.overflow !== 1 ? 'es' : ''} won't fit. Consider adding time, courts, or using a shorter format.
              </div>
            )}

            {rbPreview.fits && (
              <div style={{
                padding: 12, backgroundColor: '#e8f5e9', borderRadius: 6, marginBottom: 16,
                border: '1px solid #c8e6c9', fontSize: 13, fontWeight: 600, color: '#2e7d32',
              }}>
                All {rbPreview.remaining_matches} matches fit in {rbPreview.total_slots} available slots.
              </div>
            )}

            {/* Per-day breakdown */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#333', marginBottom: 6 }}>Per-Day Breakdown</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {rbPreview.per_day.map(d => {
                  const fmt = FORMAT_OPTIONS.find(f => f.value === d.format)
                  return (
                    <div key={d.date} style={{
                      padding: '8px 12px', borderRadius: 6, border: '1px solid #e0e0e0',
                      backgroundColor: '#fafafa', fontSize: 12, minWidth: 120,
                    }}>
                      <div style={{ fontWeight: 700, marginBottom: 2 }}>{d.date}</div>
                      <div style={{ color: '#666' }}>{d.courts} courts, {d.slots} slots</div>
                      <div style={{ color: '#888', fontSize: 11 }}>{fmt?.label || d.format}</div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Match list */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#333', marginBottom: 6 }}>
                Match Order ({rbPreview.matches.length})
              </div>
              <div style={{ maxHeight: 350, overflowY: 'auto', border: '1px solid #e0e0e0', borderRadius: 6 }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#f5f5f5', position: 'sticky', top: 0 }}>
                      <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #ddd', width: 30 }}>#</th>
                      <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Match</th>
                      <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Event</th>
                      <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #ddd' }}>Teams</th>
                      <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #ddd' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rbPreview.matches.map((m: RebuildMatchItem) => (
                      <tr key={m.match_id} style={{
                        borderBottom: '1px solid #f0f0f0',
                        backgroundColor: m.status === 'IN_PROGRESS' ? '#fff3e0' : undefined,
                      }}>
                        <td style={{ padding: '4px 8px', textAlign: 'center', color: '#888' }}>{m.rank}</td>
                        <td style={{ padding: '4px 8px', fontWeight: 600 }}>{m.match_code}</td>
                        <td style={{ padding: '4px 8px', color: '#555' }}>{m.event_name} ({m.stage})</td>
                        <td style={{ padding: '4px 8px' }}>{m.team1} vs {m.team2}</td>
                        <td style={{ padding: '4px 8px', textAlign: 'center' }}>
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 3,
                            backgroundColor: m.status === 'IN_PROGRESS' ? '#fff3e0' : '#f5f5f5',
                            color: m.status === 'IN_PROGRESS' ? '#e65100' : '#888',
                          }}>
                            {m.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={handleRebuildApply}
                disabled={rbApplyLoading || rbPreview.remaining_matches === 0}
                style={btnStyle(!rbApplyLoading && rbPreview.remaining_matches > 0, '#2e7d32')}
              >
                {rbApplyLoading ? 'Rebuilding...' : `Remake Schedule (${rbPreview.remaining_matches})`}
              </button>
              <button
                onClick={() => { setStep('setup'); setRbPreview(null) }}
                style={{ padding: '8px 20px', fontSize: 13, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', color: '#555', cursor: 'pointer' }}
              >
                ← Back
              </button>
            </div>
          </>
        )}

        {(step === 'done' || step === 'rebuild_done') && (
          <div style={{ textAlign: 'center', padding: '32px 0' }}>
            <div style={{ fontSize: 36, marginBottom: 8 }}>✓</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#2e7d32', marginBottom: 16 }}>
              {step === 'rebuild_done' ? 'Schedule Rebuilt' : 'Reschedule Applied'}
            </div>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 20 }}>
              {step === 'rebuild_done'
                ? 'Remaining matches have been reassigned to new slots. Review in the Grid tab.'
                : 'Matches have been moved. Review and fine-tune in the Grid tab.'}
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
              <button
                onClick={onSwitchToGrid}
                style={btnStyle(true)}
              >
                Open Grid
              </button>
              <button
                onClick={() => { setStep('setup'); setPreview(null); setRbPreview(null) }}
                style={{ padding: '8px 20px', fontSize: 13, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', color: '#555', cursor: 'pointer' }}
              >
                New Reschedule
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}


// ── Grid Tab (Drag-and-Drop) ────────────────────────────────────────────

function timeTo12Hour(t: string) {
  const [hh, mm] = t.split(':').map(Number)
  const ampm = hh < 12 ? 'AM' : 'PM'
  const h12 = hh % 12 || 12
  return `${h12}:${mm.toString().padStart(2, '0')} ${ampm}`
}

function DroppableCell({ slotId, children }: { slotId: number; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${slotId}` })
  return (
    <td
      ref={setNodeRef}
      style={{
        padding: 3,
        borderBottom: '1px solid #eee',
        borderRight: '1px solid #f0f0f0',
        backgroundColor: isOver ? '#e8f5e9' : '#fff',
        verticalAlign: 'top',
        minWidth: 130,
        transition: 'background-color 0.15s',
      }}
    >
      {children}
    </td>
  )
}

function DraggableMatch({
  match,
  isDraft,
  onMatchClick,
  highlighted,
  allMatches,
}: {
  match: DeskMatchItem
  isDraft: boolean
  onMatchClick: (m: DeskMatchItem) => void
  highlighted?: boolean
  allMatches?: DeskMatchItem[]
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `match-${match.match_id}`,
    data: { match },
    disabled: !isDraft || match.status === 'FINAL',
  })
  const sc = STATUS_COLORS[match.status] || STATUS_COLORS.SCHEDULED
  const hasDefault = match.team1_defaulted || match.team2_defaulted
  return (
    <div
      ref={setNodeRef}
      {...(isDraft && match.status !== 'FINAL' ? listeners : {})}
      {...(isDraft && match.status !== 'FINAL' ? attributes : {})}
      onClick={e => { e.stopPropagation(); onMatchClick(match) }}
      style={{
        border: highlighted ? '2px solid #f9a825' : '1px solid #c5cae9',
        borderRadius: 4,
        padding: '3px 6px',
        backgroundColor: hasDefault ? '#fce4ec' : isDragging ? '#bbdefb' : highlighted ? '#fff8e1' : '#e8eaf6',
        fontSize: 10,
        cursor: isDraft && match.status !== 'FINAL' ? 'grab' : 'pointer',
        opacity: isDragging ? 0.5 : 1,
        minHeight: 36,
        userSelect: 'none',
        borderLeft: hasDefault ? '3px solid #c62828' : undefined,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 1 }}>
        <span style={{ fontWeight: 700, fontSize: 10 }}>#{match.match_number}</span>
        <div style={{ display: 'flex', gap: 2 }}>
          {hasDefault && <Badge label="DEFAULT" bg="#c62828" color="#fff" />}
          <EventBadge name={match.event_name} />
          <Badge label={match.stage} bg={STAGE_COLORS[match.stage] || '#757575'} color="#fff" />
          <Badge label={STATUS_LABEL[match.status] || match.status} bg={sc.bg} color={sc.text} />
        </div>
      </div>
      <div style={{
        fontWeight: 600,
        color: match.team1_defaulted ? '#c62828' : !match.team1_id && match.source_match_a_id ? '#999' : '#333',
        fontSize: 10,
        fontStyle: !match.team1_id && match.source_match_a_id ? 'italic' : 'normal',
        textDecoration: match.team1_defaulted ? 'line-through' : 'none',
        display: 'flex', alignItems: 'center', gap: 2,
      }}>
        {match.team1_display}
        {match.team1_notes && <NoteIcon note={match.team1_notes} />}
      </div>
      {!match.team1_id && match.source_match_a_id && allMatches && (
        <FeederMatchInfo sourceMatchId={match.source_match_a_id} allMatches={allMatches} />
      )}
      <div style={{ color: '#999', fontSize: 8 }}>vs</div>
      <div style={{
        fontWeight: 600,
        color: match.team2_defaulted ? '#c62828' : !match.team2_id && match.source_match_b_id ? '#999' : '#333',
        fontSize: 10,
        fontStyle: !match.team2_id && match.source_match_b_id ? 'italic' : 'normal',
        textDecoration: match.team2_defaulted ? 'line-through' : 'none',
        display: 'flex', alignItems: 'center', gap: 2,
      }}>
        {match.team2_display}
        {match.team2_notes && <NoteIcon note={match.team2_notes} />}
      </div>
      {!match.team2_id && match.source_match_b_id && allMatches && (
        <FeederMatchInfo sourceMatchId={match.source_match_b_id} allMatches={allMatches} />
      )}
      {match.status === 'FINAL' && match.score_display && (
        <div style={{ fontWeight: 700, color: '#2e7d32', fontSize: 10 }}>{match.score_display}</div>
      )}
    </div>
  )
}

function DeskGridTab({
  tournamentId,
  data,
  isDraft,
  onRefresh,
  onMatchClick,
  highlightedMatchIds,
}: {
  tournamentId: string
  data: DeskSnapshotResponse
  isDraft: boolean
  onRefresh: () => void
  highlightedMatchIds?: Set<number>
  onMatchClick: (m: DeskMatchItem) => void
}) {
  const tid = parseInt(tournamentId, 10)
  const [selectedDay, setSelectedDay] = useState<string>('')
  const [draggedMatch, setDraggedMatch] = useState<DeskMatchItem | null>(null)
  const [conflictModal, setConflictModal] = useState<{
    conflicts: ConflictItem[]
    matchId: number
    targetSlotId: number
  } | null>(null)
  const [swapModal, setSwapModal] = useState<{
    draggedMatch: DeskMatchItem
    occupantMatch: DeskMatchItem
    targetSlotId: number
  } | null>(null)
  const [addSlotOpen, setAddSlotOpen] = useState(false)
  const [addCourtOpen, setAddCourtOpen] = useState(false)
  const [gridToast, setGridToast] = useState<string | null>(null)

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // Build grid data from slots and matches
  const { days, courtNumbers, courtLabels, timeRows, matchBySlot } = useMemo(() => {
    const slots = data.slots || []
    const matchMap = new Map<number, DeskMatchItem>()
    for (const m of data.matches) {
      if (m.slot_id != null) matchMap.set(m.slot_id, m)
    }

    const daySet = new Set<string>()
    const courtNumSet = new Set<number>()
    const courtLabelMap = new Map<number, string>()

    for (const s of slots) {
      daySet.add(s.day_date)
      courtNumSet.add(s.court_number)
      if (!courtLabelMap.has(s.court_number)) {
        courtLabelMap.set(s.court_number, s.court_label)
      }
    }

    const sortedDays = [...daySet].sort()
    const sortedCourts = [...courtNumSet].sort((a, b) => a - b)
    const labels: Record<number, string> = {}
    for (const [cn, lbl] of courtLabelMap) labels[cn] = lbl

    const timeRowMap = new Map<string, Map<number, SnapshotSlot>>()
    for (const s of slots) {
      if (s.day_date !== (selectedDay || sortedDays[0])) continue
      if (!timeRowMap.has(s.start_time)) timeRowMap.set(s.start_time, new Map())
      timeRowMap.get(s.start_time)!.set(s.court_number, s)
    }

    const sortedTimes = [...timeRowMap.keys()].sort()
    const rows = sortedTimes.map(t => ({
      time: t,
      slotsByCourt: timeRowMap.get(t)!,
    }))

    return {
      days: sortedDays,
      courtNumbers: sortedCourts,
      courtLabels: labels,
      timeRows: rows,
      matchBySlot: matchMap,
    }
  }, [data.slots, data.matches, selectedDay])

  useEffect(() => {
    if (days.length > 0 && !selectedDay) {
      setSelectedDay(days[0])
    }
  }, [days, selectedDay])

  const showToast = (msg: string) => {
    setGridToast(msg)
    setTimeout(() => setGridToast(null), 3000)
  }

  const handleDragStart = (event: DragStartEvent) => {
    const m = (event.active.data.current as any)?.match as DeskMatchItem | undefined
    setDraggedMatch(m || null)
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    setDraggedMatch(null)
    const { active, over } = event
    if (!over) return

    const match = (active.data.current as any)?.match as DeskMatchItem
    if (!match) return

    const overId = String(over.id)
    if (!overId.startsWith('slot-')) return
    const targetSlotId = parseInt(overId.replace('slot-', ''), 10)

    if (match.slot_id === targetSlotId) return

    const occupant = matchBySlot.get(targetSlotId)
    if (occupant) {
      setSwapModal({ draggedMatch: match, occupantMatch: occupant, targetSlotId })
      return
    }

    try {
      const conflicts = await checkDeskConflicts(tid, {
        version_id: data.version_id,
        action_type: 'MOVE',
        match_id: match.match_id,
        target_slot_id: targetSlotId,
      })
      if (conflicts.conflicts.length > 0) {
        setConflictModal({ conflicts: conflicts.conflicts, matchId: match.match_id, targetSlotId })
        return
      }
      await deskMoveMatch(tid, match.match_id, {
        version_id: data.version_id,
        target_slot_id: targetSlotId,
      })
      showToast(`Match #${match.match_number} moved`)
      onRefresh()
    } catch (err: any) {
      const detail = err?.detail || err?.message || 'Move failed'
      if (typeof detail === 'object' && detail.occupant_match_id) {
        const occ = data.matches.find(m => m.match_id === detail.occupant_match_id)
        if (occ) {
          setSwapModal({ draggedMatch: match, occupantMatch: occ, targetSlotId })
          return
        }
      }
      showToast(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
  }

  const doMove = async (matchId: number, targetSlotId: number) => {
    try {
      await deskMoveMatch(tid, matchId, {
        version_id: data.version_id,
        target_slot_id: targetSlotId,
      })
      showToast('Match moved')
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err?.message || 'Move failed')
    }
  }

  const doSwap = async (matchAId: number, matchBId: number) => {
    try {
      await deskSwapMatches(tid, {
        version_id: data.version_id,
        match_a_id: matchAId,
        match_b_id: matchBId,
      })
      showToast('Matches swapped')
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err?.message || 'Swap failed')
    }
  }

  const handleAddSlot = async (dayDate: string, startTime: string, endTime: string, courtNums: number[]) => {
    try {
      await deskAddSlots(tid, {
        version_id: data.version_id,
        day_date: dayDate,
        start_time: startTime,
        end_time: endTime,
        court_numbers: courtNums,
      })
      showToast('Time slot(s) added')
      setAddSlotOpen(false)
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err?.message || 'Failed to add slot')
    }
  }

  const handleAddCourt = async (courtLabel: string, createSlots: boolean) => {
    try {
      await deskAddCourt(tid, {
        version_id: data.version_id,
        court_label: courtLabel,
        create_matching_slots: createSlots,
      })
      showToast(`Court "${courtLabel}" added`)
      setAddCourtOpen(false)
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err?.message || 'Failed to add court')
    }
  }

  const dayLabel = (d: string) => {
    try {
      const dt = new Date(d + 'T00:00:00')
      return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
    } catch {
      return d
    }
  }

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {days.map(d => (
            <button
              key={d}
              onClick={() => setSelectedDay(d)}
              style={{
                padding: '5px 14px',
                fontSize: 12,
                fontWeight: 600,
                border: '1px solid #c5cae9',
                borderRadius: 4,
                backgroundColor: (selectedDay || days[0]) === d ? '#1a237e' : '#fff',
                color: (selectedDay || days[0]) === d ? '#fff' : '#333',
                cursor: 'pointer',
              }}
            >
              {dayLabel(d)}
            </button>
          ))}
        </div>
        {isDraft && (
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={() => setAddSlotOpen(true)}
              style={{
                padding: '5px 12px',
                fontSize: 11,
                fontWeight: 600,
                border: '1px solid #4caf50',
                borderRadius: 4,
                backgroundColor: '#e8f5e9',
                color: '#2e7d32',
                cursor: 'pointer',
              }}
            >
              + Time Slot
            </button>
            <button
              onClick={() => setAddCourtOpen(true)}
              style={{
                padding: '5px 12px',
                fontSize: 11,
                fontWeight: 600,
                border: '1px solid #1565c0',
                borderRadius: 4,
                backgroundColor: '#e3f2fd',
                color: '#1565c0',
                cursor: 'pointer',
              }}
            >
              + Court
            </button>
          </div>
        )}
      </div>

      {/* Grid */}
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 11, width: '100%' }}>
            <thead>
              <tr>
                <th style={{
                  position: 'sticky',
                  left: 0,
                  top: 0,
                  background: '#1a237e',
                  color: '#fff',
                  padding: '6px 8px',
                  textAlign: 'left',
                  borderBottom: '2px solid #1a237e',
                  minWidth: 70,
                  zIndex: 3,
                  fontSize: 12,
                  fontWeight: 700,
                }}>
                  Time
                </th>
                {courtNumbers.map(cn => (
                  <th key={cn} style={{
                    padding: '6px 8px',
                    textAlign: 'center',
                    borderBottom: '2px solid #1a237e',
                    background: '#1a237e',
                    color: '#fff',
                    minWidth: 130,
                    fontSize: 12,
                    fontWeight: 700,
                    letterSpacing: 0.5,
                    position: 'sticky',
                    top: 0,
                    zIndex: 2,
                  }}>
                    Court {courtLabels[cn] || cn}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {timeRows.map(row => (
                <tr key={row.time}>
                  <td style={{
                    position: 'sticky',
                    left: 0,
                    background: '#fff',
                    padding: '6px',
                    borderBottom: '1px solid #eee',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    zIndex: 1,
                    fontSize: 11,
                  }}>
                    {timeTo12Hour(row.time)}
                  </td>
                  {courtNumbers.map(cn => {
                    const slot = row.slotsByCourt.get(cn)
                    if (!slot) {
                      return (
                        <td key={cn} style={{
                          padding: 3,
                          borderBottom: '1px solid #eee',
                          borderRight: '1px solid #f0f0f0',
                          textAlign: 'center',
                          color: '#ccc',
                          fontSize: 10,
                        }}>
                          —
                        </td>
                      )
                    }

                    const match = matchBySlot.get(slot.slot_id)
                    if (!slot.is_active) {
                      return (
                        <td key={cn} style={{
                          padding: 3,
                          borderBottom: '1px solid #eee',
                          borderRight: '1px solid #f0f0f0',
                          textAlign: 'center',
                          backgroundColor: '#fce4e4',
                          color: '#c62828',
                          fontSize: 9,
                          fontWeight: 600,
                        }}>
                          BLOCKED
                        </td>
                      )
                    }

                    return (
                      <DroppableCell key={cn} slotId={slot.slot_id}>
                        {match ? (
                          <DraggableMatch match={match} isDraft={isDraft} onMatchClick={onMatchClick} highlighted={highlightedMatchIds?.has(match.match_id)} allMatches={data.matches} />
                        ) : (
                          <div style={{
                            minHeight: 36,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#bbb',
                            fontSize: 10,
                            fontStyle: 'italic',
                          }}>
                            Open
                          </div>
                        )}
                      </DroppableCell>
                    )
                  })}
                </tr>
              ))}
              {timeRows.length === 0 && (
                <tr>
                  <td colSpan={courtNumbers.length + 1} style={{ padding: 20, textAlign: 'center', color: '#999', fontSize: 12 }}>
                    No time slots for this day
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <DragOverlay>
          {draggedMatch && (
            <div style={{
              border: '2px solid #1a237e',
              borderRadius: 4,
              padding: '3px 6px',
              backgroundColor: '#e8eaf6',
              fontSize: 10,
              boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
              width: 140,
            }}>
              <div style={{ fontWeight: 700 }}>#{draggedMatch.match_number}</div>
              <div style={{ fontWeight: 600, color: '#333' }}>{draggedMatch.team1_display}</div>
              <div style={{ color: '#999', fontSize: 8 }}>vs</div>
              <div style={{ fontWeight: 600, color: '#333' }}>{draggedMatch.team2_display}</div>
            </div>
          )}
        </DragOverlay>
      </DndContext>

      {/* Conflict warning modal */}
      {conflictModal && (
        <>
          <div onClick={() => setConflictModal(null)} style={{
            position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
            backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 1999,
          }} />
          <div style={{
            position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
            width: 420, backgroundColor: '#fff', borderRadius: 10,
            boxShadow: '0 8px 30px rgba(0,0,0,0.3)', zIndex: 2000, overflow: 'hidden',
          }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0' }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>Potential Conflicts</div>
            </div>
            <div style={{ padding: '12px 20px', maxHeight: 300, overflowY: 'auto' }}>
              {conflictModal.conflicts.map((c, i) => (
                <div key={i} style={{
                  padding: '8px 0',
                  borderBottom: i < conflictModal.conflicts.length - 1 ? '1px solid #f0f0f0' : 'none',
                  fontSize: 12,
                  display: 'flex',
                  gap: 8,
                  alignItems: 'flex-start',
                }}>
                  <span style={{ color: '#f57f17', fontSize: 16 }}>&#9888;</span>
                  <span>{c.message}</span>
                </div>
              ))}
            </div>
            <div style={{
              padding: '12px 20px', borderTop: '1px solid #e0e0e0',
              display: 'flex', justifyContent: 'flex-end', gap: 8,
            }}>
              <button
                onClick={() => setConflictModal(null)}
                style={{
                  padding: '6px 16px', fontSize: 12, fontWeight: 600,
                  border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  const { matchId, targetSlotId } = conflictModal
                  setConflictModal(null)
                  await doMove(matchId, targetSlotId)
                }}
                style={{
                  padding: '6px 16px', fontSize: 12, fontWeight: 600,
                  border: 'none', borderRadius: 4, backgroundColor: '#e65100',
                  color: '#fff', cursor: 'pointer',
                }}
              >
                Proceed Anyway
              </button>
            </div>
          </div>
        </>
      )}

      {/* Swap confirmation modal */}
      {swapModal && (
        <>
          <div onClick={() => setSwapModal(null)} style={{
            position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
            backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 1999,
          }} />
          <div style={{
            position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
            width: 420, backgroundColor: '#fff', borderRadius: 10,
            boxShadow: '0 8px 30px rgba(0,0,0,0.3)', zIndex: 2000, overflow: 'hidden',
          }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0' }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>Swap Matches?</div>
            </div>
            <div style={{ padding: '12px 20px', fontSize: 12, color: '#555' }}>
              <p style={{ margin: '0 0 8px' }}>
                That slot is occupied. Do you want to swap these two matches?
              </p>
              <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
                <div style={{
                  flex: 1, padding: 8, border: '1px solid #c5cae9',
                  borderRadius: 4, backgroundColor: '#e8eaf6',
                }}>
                  <div style={{ fontWeight: 700, fontSize: 11 }}>#{swapModal.draggedMatch.match_number}</div>
                  <div style={{ fontSize: 10, color: '#333' }}>{swapModal.draggedMatch.team1_display} vs {swapModal.draggedMatch.team2_display}</div>
                  <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>{swapModal.draggedMatch.court_name} {swapModal.draggedMatch.scheduled_time}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', fontWeight: 700, color: '#1a237e' }}>&#8596;</div>
                <div style={{
                  flex: 1, padding: 8, border: '1px solid #c5cae9',
                  borderRadius: 4, backgroundColor: '#e8eaf6',
                }}>
                  <div style={{ fontWeight: 700, fontSize: 11 }}>#{swapModal.occupantMatch.match_number}</div>
                  <div style={{ fontSize: 10, color: '#333' }}>{swapModal.occupantMatch.team1_display} vs {swapModal.occupantMatch.team2_display}</div>
                  <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>{swapModal.occupantMatch.court_name} {swapModal.occupantMatch.scheduled_time}</div>
                </div>
              </div>
            </div>
            <div style={{
              padding: '12px 20px', borderTop: '1px solid #e0e0e0',
              display: 'flex', justifyContent: 'flex-end', gap: 8,
            }}>
              <button
                onClick={() => setSwapModal(null)}
                style={{
                  padding: '6px 16px', fontSize: 12, fontWeight: 600,
                  border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  const { draggedMatch: dm, occupantMatch: om } = swapModal
                  setSwapModal(null)
                  await doSwap(dm.match_id, om.match_id)
                }}
                style={{
                  padding: '6px 16px', fontSize: 12, fontWeight: 600,
                  border: 'none', borderRadius: 4, backgroundColor: '#1a237e',
                  color: '#fff', cursor: 'pointer',
                }}
              >
                Swap
              </button>
            </div>
          </div>
        </>
      )}

      {/* Add Time Slot Modal */}
      {addSlotOpen && (
        <AddTimeSlotModal
          days={days}
          courtNumbers={courtNumbers}
          courtLabels={courtLabels}
          onClose={() => setAddSlotOpen(false)}
          onSubmit={handleAddSlot}
        />
      )}

      {/* Add Court Modal */}
      {addCourtOpen && (
        <AddCourtModal
          onClose={() => setAddCourtOpen(false)}
          onSubmit={handleAddCourt}
        />
      )}

      {/* Toast */}
      {gridToast && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          padding: '10px 24px', backgroundColor: '#2e7d32', color: '#fff',
          borderRadius: 6, fontSize: 13, fontWeight: 600, zIndex: 2000,
          boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
        }}>
          {gridToast}
        </div>
      )}
    </div>
  )
}


// ── Add Time Slot Modal ─────────────────────────────────────────────────

function AddTimeSlotModal({
  days,
  courtNumbers,
  courtLabels,
  onClose,
  onSubmit,
}: {
  days: string[]
  courtNumbers: number[]
  courtLabels: Record<number, string>
  onClose: () => void
  onSubmit: (dayDate: string, startTime: string, endTime: string, courtNums: number[]) => void
}) {
  const [day, setDay] = useState(days[0] || '')
  const [startTime, setStartTime] = useState('09:00')
  const [endTime, setEndTime] = useState('10:30')
  const [selectedCourts, setSelectedCourts] = useState<number[]>([...courtNumbers])

  const toggleCourt = (cn: number) => {
    setSelectedCourts(prev =>
      prev.includes(cn) ? prev.filter(c => c !== cn) : [...prev, cn]
    )
  }

  return (
    <>
      <div onClick={onClose} style={{
        position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
        backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 1999,
      }} />
      <div style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
        width: 400, backgroundColor: '#fff', borderRadius: 10,
        boxShadow: '0 8px 30px rgba(0,0,0,0.3)', zIndex: 2000, overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0' }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Add Time Slot</div>
        </div>
        <div style={{ padding: '16px 20px' }}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Day</label>
            <select
              value={day}
              onChange={e => setDay(e.target.value)}
              style={{ width: '100%', padding: '6px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4 }}
            >
              {days.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Start Time</label>
              <input
                type="time"
                value={startTime}
                onChange={e => setStartTime(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4, boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>End Time</label>
              <input
                type="time"
                value={endTime}
                onChange={e => setEndTime(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4, boxSizing: 'border-box' }}
              />
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <label style={{ fontSize: 11, fontWeight: 600 }}>Courts</label>
              <button
                onClick={() => setSelectedCourts([...courtNumbers])}
                style={{ fontSize: 10, color: '#1a237e', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
              >
                Select All
              </button>
              <button
                onClick={() => setSelectedCourts([])}
                style={{ fontSize: 10, color: '#c62828', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
              >
                Unselect All
              </button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {courtNumbers.map(cn => (
                <label key={cn} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={selectedCourts.includes(cn)}
                    onChange={() => toggleCourt(cn)}
                  />
                  Court {courtLabels[cn] || cn}
                </label>
              ))}
            </div>
          </div>
        </div>
        <div style={{
          padding: '12px 20px', borderTop: '1px solid #e0e0e0',
          display: 'flex', justifyContent: 'flex-end', gap: 8,
        }}>
          <button
            onClick={onClose}
            style={{ padding: '6px 16px', fontSize: 12, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', cursor: 'pointer' }}
          >
            Cancel
          </button>
          <button
            onClick={() => {
              if (selectedCourts.length === 0) return
              onSubmit(day, startTime, endTime, selectedCourts)
            }}
            style={{ padding: '6px 16px', fontSize: 12, fontWeight: 600, border: 'none', borderRadius: 4, backgroundColor: '#2e7d32', color: '#fff', cursor: 'pointer' }}
          >
            Add Slot
          </button>
        </div>
      </div>
    </>
  )
}


// ── Add Court Modal ─────────────────────────────────────────────────────

function AddCourtModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void
  onSubmit: (courtLabel: string, createSlots: boolean) => void
}) {
  const [label, setLabel] = useState('')
  const [createSlots, setCreateSlots] = useState(true)

  return (
    <>
      <div onClick={onClose} style={{
        position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
        backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 1999,
      }} />
      <div style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
        width: 380, backgroundColor: '#fff', borderRadius: 10,
        boxShadow: '0 8px 30px rgba(0,0,0,0.3)', zIndex: 2000, overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0' }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Add Court</div>
        </div>
        <div style={{ padding: '16px 20px' }}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Court Label</label>
            <input
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="e.g. 7 or Stadium"
              style={{ width: '100%', padding: '6px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4, boxSizing: 'border-box' }}
              autoFocus
            />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={createSlots}
              onChange={e => setCreateSlots(e.target.checked)}
            />
            Create slots for all existing time windows
          </label>
        </div>
        <div style={{
          padding: '12px 20px', borderTop: '1px solid #e0e0e0',
          display: 'flex', justifyContent: 'flex-end', gap: 8,
        }}>
          <button
            onClick={onClose}
            style={{ padding: '6px 16px', fontSize: 12, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', cursor: 'pointer' }}
          >
            Cancel
          </button>
          <button
            onClick={() => {
              if (!label.trim()) return
              onSubmit(label.trim(), createSlots)
            }}
            style={{ padding: '6px 16px', fontSize: 12, fontWeight: 600, border: 'none', borderRadius: 4, backgroundColor: '#1a237e', color: '#fff', cursor: 'pointer' }}
          >
            Add Court
          </button>
        </div>
      </div>
    </>
  )
}


// ── Main Page ──────────────────────────────────────────────────────────

// ── Teams Tab ─────────────────────────────────────────────────────────

function TeamsTab({
  tournamentId,
  versionId,
  onRefresh,
}: {
  tournamentId: number
  versionId: number
  onRefresh: () => void
}) {
  const [teams, setTeams] = useState<DeskTeamItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editFields, setEditFields] = useState<{ name: string; display_name: string; player1_cellphone: string; player1_email: string; player2_cellphone: string; player2_email: string; notes: string }>({ name: '', display_name: '', player1_cellphone: '', player1_email: '', player2_cellphone: '', player2_email: '', notes: '' })
  const [saving, setSaving] = useState(false)
  const [defaultConfirm, setDefaultConfirm] = useState<DeskTeamItem | null>(null)
  const [defaulting, setDefaulting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadTeams = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getDeskTeams(tournamentId)
      setTeams(data)
    } catch (e: any) {
      console.error('Failed to load teams:', e)
      setError('Failed to load teams. The server may need to be restarted.')
    } finally {
      setLoading(false)
    }
  }, [tournamentId])

  useEffect(() => { loadTeams() }, [loadTeams])

  const filtered = useMemo(() => {
    if (!search.trim()) return teams
    const q = search.toLowerCase()
    return teams.filter(t =>
      (t.name || '').toLowerCase().includes(q) ||
      (t.display_name || '').toLowerCase().includes(q) ||
      (t.event_name || '').toLowerCase().includes(q) ||
      (t.player1_cellphone || '').includes(q) ||
      (t.player2_cellphone || '').includes(q) ||
      (t.player1_email || '').toLowerCase().includes(q) ||
      (t.player2_email || '').toLowerCase().includes(q) ||
      String(t.seed).includes(q) ||
      (t.notes || '').toLowerCase().includes(q)
    )
  }, [teams, search])

  const startEdit = (t: DeskTeamItem) => {
    setEditingId(t.team_id)
    setEditFields({
      name: t.name || '',
      display_name: t.display_name || '',
      player1_cellphone: t.player1_cellphone || '',
      player1_email: t.player1_email || '',
      player2_cellphone: t.player2_cellphone || '',
      player2_email: t.player2_email || '',
      notes: t.notes || '',
    })
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const saveEdit = async (t: DeskTeamItem) => {
    setSaving(true)
    try {
      await updateTeam(t.event_id, t.team_id, {
        name: editFields.name || undefined,
        display_name: editFields.display_name || undefined,
        player1_cellphone: editFields.player1_cellphone || undefined,
        player1_email: editFields.player1_email || undefined,
        player2_cellphone: editFields.player2_cellphone || undefined,
        player2_email: editFields.player2_email || undefined,
        notes: editFields.notes,
      })
      setEditingId(null)
      await loadTeams()
      setToast('Team updated')
      setTimeout(() => setToast(null), 3000)
    } catch (e: any) {
      console.error('Failed to save team:', e)
      setToast('Failed to save team')
      setTimeout(() => setToast(null), 4000)
    } finally {
      setSaving(false)
    }
  }

  const handleDefaultWeekend = async () => {
    if (!defaultConfirm) return
    setDefaulting(true)
    try {
      const resp = await defaultTeamWeekend(tournamentId, defaultConfirm.team_id, versionId)
      setDefaultConfirm(null)
      await loadTeams()
      onRefresh()
      setToast(`${resp.team_name} defaulted — ${resp.matches_defaulted} match${resp.matches_defaulted !== 1 ? 'es' : ''} auto-defaulted`)
      setTimeout(() => setToast(null), 5000)
    } catch (e: any) {
      console.error('Failed to default team:', e)
      setToast('Failed to default team')
      setTimeout(() => setToast(null), 4000)
    } finally {
      setDefaulting(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    padding: '4px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 3, width: '100%', boxSizing: 'border-box',
  }

  if (loading) return <div style={{ padding: 20, color: '#888' }}>Loading teams...</div>
  if (error) return <div style={{ padding: 20, color: '#c62828', backgroundColor: '#fce4ec', borderRadius: 6, fontSize: 14 }}>{error}</div>

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search teams..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, maxWidth: 400, padding: '8px 12px', fontSize: 14, border: '1px solid #ccc', borderRadius: 6 }}
        />
        <span style={{ fontSize: 12, color: '#888' }}>{filtered.length} of {teams.length} teams</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ backgroundColor: '#f5f5f5', borderBottom: '2px solid #ccc' }}>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>Seed</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>Display Name</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>Full Name</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>Event</th>
              <th style={{ padding: '8px 10px', textAlign: 'center' }}>Rating</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>P1 Cell</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>P1 Email</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>P2 Cell</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>P2 Email</th>
              <th style={{ padding: '8px 10px', textAlign: 'left' }}>Notes</th>
              <th style={{ padding: '8px 10px', textAlign: 'center' }}>Status</th>
              <th style={{ padding: '8px 10px', textAlign: 'center' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(t => {
              const isEditing = editingId === t.team_id
              return (
                <tr key={t.team_id} style={{
                  borderBottom: '1px solid #eee',
                  backgroundColor: t.is_defaulted ? '#fce4ec' : undefined,
                  opacity: t.is_defaulted ? 0.7 : 1,
                }}>
                  <td style={{ padding: '6px 10px', fontWeight: 700 }}>{t.seed ?? '—'}</td>
                  <td style={{ padding: '6px 10px' }}>
                    {isEditing ? (
                      <input value={editFields.display_name} onChange={e => setEditFields(f => ({ ...f, display_name: e.target.value }))} style={inputStyle} />
                    ) : (
                      <span style={{ textDecoration: t.is_defaulted ? 'line-through' : 'none' }}>{t.display_name || '—'}</span>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    {isEditing ? (
                      <input value={editFields.name} onChange={e => setEditFields(f => ({ ...f, name: e.target.value }))} style={inputStyle} />
                    ) : (
                      <span style={{ textDecoration: t.is_defaulted ? 'line-through' : 'none' }}>{t.name}</span>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 11, color: '#666' }}>{t.event_name}</td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>{t.rating ?? '—'}</td>
                  <td style={{ padding: '6px 10px' }}>
                    {isEditing ? (
                      <input value={editFields.player1_cellphone} onChange={e => setEditFields(f => ({ ...f, player1_cellphone: e.target.value }))} style={inputStyle} placeholder="P1 phone" />
                    ) : (
                      t.player1_cellphone || '—'
                    )}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    {isEditing ? (
                      <input value={editFields.player1_email} onChange={e => setEditFields(f => ({ ...f, player1_email: e.target.value }))} style={inputStyle} placeholder="P1 email" />
                    ) : (
                      t.player1_email || '—'
                    )}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    {isEditing ? (
                      <input value={editFields.player2_cellphone} onChange={e => setEditFields(f => ({ ...f, player2_cellphone: e.target.value }))} style={inputStyle} placeholder="P2 phone" />
                    ) : (
                      t.player2_cellphone || '—'
                    )}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    {isEditing ? (
                      <input value={editFields.player2_email} onChange={e => setEditFields(f => ({ ...f, player2_email: e.target.value }))} style={inputStyle} placeholder="P2 email" />
                    ) : (
                      t.player2_email || '—'
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', maxWidth: 200 }}>
                    {isEditing ? (
                      <input value={editFields.notes} onChange={e => setEditFields(f => ({ ...f, notes: e.target.value }))} style={inputStyle} placeholder="Notes..." />
                    ) : (
                      <span style={{ fontSize: 11, color: t.notes ? '#333' : '#bbb', fontStyle: t.notes ? 'normal' : 'italic' }}>
                        {t.notes || '—'}
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    {t.is_defaulted ? (
                      <span style={{ fontSize: 10, fontWeight: 700, color: '#c62828', backgroundColor: '#ffcdd2', padding: '2px 6px', borderRadius: 3 }}>
                        DEFAULTED
                      </span>
                    ) : (
                      <span style={{ fontSize: 10, fontWeight: 600, color: '#2e7d32' }}>Active</span>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                      {isEditing ? (
                        <>
                          <button
                            onClick={() => saveEdit(t)}
                            disabled={saving}
                            style={{ padding: '3px 10px', fontSize: 11, fontWeight: 600, backgroundColor: '#2e7d32', color: '#fff', border: 'none', borderRadius: 3, cursor: 'pointer' }}
                          >
                            {saving ? '...' : 'Save'}
                          </button>
                          <button
                            onClick={cancelEdit}
                            style={{ padding: '3px 10px', fontSize: 11, fontWeight: 600, backgroundColor: '#fff', color: '#555', border: '1px solid #ccc', borderRadius: 3, cursor: 'pointer' }}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => startEdit(t)}
                            style={{ padding: '3px 10px', fontSize: 11, fontWeight: 600, backgroundColor: '#1a237e', color: '#fff', border: 'none', borderRadius: 3, cursor: 'pointer' }}
                          >
                            Edit
                          </button>
                          {!t.is_defaulted && (
                            <button
                              onClick={() => setDefaultConfirm(t)}
                              style={{ padding: '3px 10px', fontSize: 11, fontWeight: 600, backgroundColor: '#e65100', color: '#fff', border: 'none', borderRadius: 3, cursor: 'pointer' }}
                            >
                              Default
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Default confirmation modal */}
      {defaultConfirm && (
        <div style={{
          position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
          backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            backgroundColor: '#fff', borderRadius: 8, padding: 24, maxWidth: 440, width: '90%',
            boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
          }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: 16, color: '#c62828' }}>
              Default Team for Rest of Weekend?
            </h3>
            <p style={{ fontSize: 14, color: '#333', marginBottom: 12, lineHeight: 1.5 }}>
              <strong>{defaultConfirm.display_name || defaultConfirm.name}</strong> ({defaultConfirm.event_name})
              will be defaulted from all remaining matches. Their opponents will automatically advance.
              This cannot be undone easily.
            </p>
            <p style={{ fontSize: 12, color: '#e65100', marginBottom: 16, lineHeight: 1.4, fontStyle: 'italic' }}>
              Note: Waterfall matches will NOT be auto-defaulted. You will need to manually resolve each
              waterfall match so the opponent can choose to take the win or the loss.
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setDefaultConfirm(null)}
                disabled={defaulting}
                style={{ padding: '8px 16px', fontSize: 13, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', color: '#555', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleDefaultWeekend}
                disabled={defaulting}
                style={{ padding: '8px 16px', fontSize: 13, fontWeight: 600, backgroundColor: '#c62828', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
              >
                {defaulting ? 'Defaulting...' : 'Confirm Default'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          padding: '10px 24px', backgroundColor: '#2e7d32', color: '#fff',
          borderRadius: 6, fontSize: 13, fontWeight: 600, zIndex: 1001,
          boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
        }}>
          {toast}
        </div>
      )}
    </div>
  )
}


export default function TournamentDeskPage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const navigate = useNavigate()
  const tid = tournamentId ? parseInt(tournamentId, 10) : null

  const [data, setData] = useState<DeskSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [draftVersionId, setDraftVersionId] = useState<number | null>(null)
  const [creatingDraft, setCreatingDraft] = useState(false)

  const [searchText, setSearchText] = useState('')
  const [drawerMatch, setDrawerMatch] = useState<DeskMatchItem | null>(null)
  const [activeTab, setActiveTab] = useState<'courts' | 'schedule' | 'draws' | 'impact' | 'pools' | 'bulk' | 'grid' | 'weather' | 'teams'>('courts')
  const [rescheduledMatchIds, setRescheduledMatchIds] = useState<Set<number>>(new Set())
  const [courtStates, setCourtStates] = useState<Record<string, CourtStateItem>>({})
  const [bulkToast, setBulkToast] = useState<string | null>(null)
  const [bulkConfirm, setBulkConfirm] = useState<{ label: string; fn: () => Promise<void> } | null>(null)

  const loadSnapshot = useCallback(async (versionId?: number) => {
    if (!tid) return
    setLoading(true)
    setError(null)
    try {
      const resp = await getDeskSnapshot(tid, versionId)
      setData(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [tid])

  const loadCourtStates = useCallback(async () => {
    if (!tid) return
    try {
      const states = await getCourtStates(tid)
      const map: Record<string, CourtStateItem> = {}
      for (const s of states) map[s.court_label] = s
      setCourtStates(map)
    } catch { /* ignore */ }
  }, [tid])

  useEffect(() => {
    loadSnapshot()
    loadCourtStates()
  }, [loadSnapshot, loadCourtStates])

  const handleCreateDraft = useCallback(async () => {
    if (!tid) return
    setCreatingDraft(true)
    try {
      const resp = await createWorkingDraft(tid)
      setDraftVersionId(resp.version_id)
      await loadSnapshot(resp.version_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create draft')
    } finally {
      setCreatingDraft(false)
    }
  }, [tid, loadSnapshot])

  useEffect(() => {
    if (data && data.version_status !== 'draft' && !creatingDraft) {
      handleCreateDraft()
    }
  }, [data?.version_status])

  const handleRefresh = useCallback(() => {
    if (draftVersionId) {
      loadSnapshot(draftVersionId)
    } else {
      loadSnapshot()
    }
  }, [draftVersionId, loadSnapshot])

  const handleAction = useCallback((match: DeskMatchItem, action: string) => {
    if (action === 'FINALIZE') {
      setDrawerMatch(match)
    } else if (action === 'IN_PROGRESS' && data && tid) {
      deskSetMatchStatus(tid, match.match_id, {
        version_id: data.version_id,
        status: 'IN_PROGRESS',
      }).then(() => handleRefresh())
        .catch(e => setError(e instanceof Error ? e.message : 'Failed'))
    }
  }, [data, tid, handleRefresh])

  const handleCourtStateChange = useCallback(async (courtLabel: string, patch: { is_closed?: boolean; note?: string }) => {
    if (!tid) return
    try {
      const updated = await patchCourtState(tid, courtLabel, patch)
      setCourtStates(prev => ({ ...prev, [courtLabel]: updated }))
    } catch { /* ignore */ }
  }, [tid])

  const handleBulkPause = useCallback(async () => {
    if (!tid || !data) return
    try {
      const resp = await bulkPauseInProgress(tid, data.version_id)
      setBulkToast(`Paused ${resp.updated_count} match${resp.updated_count !== 1 ? 'es' : ''}`)
      setTimeout(() => setBulkToast(null), 4000)
      handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bulk pause failed')
    }
  }, [tid, data, handleRefresh])

  const handleBulkDelay = useCallback(async (afterTime: string, dayIndex?: number) => {
    if (!tid || !data) return
    try {
      const resp = await bulkDelayAfter(tid, {
        version_id: data.version_id,
        after_time: afterTime,
        ...(dayIndex != null ? { day_index: dayIndex } : {}),
      })
      setBulkToast(`Delayed ${resp.updated_count} match${resp.updated_count !== 1 ? 'es' : ''}`)
      setTimeout(() => setBulkToast(null), 4000)
      handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bulk delay failed')
    }
  }, [tid, data, handleRefresh])

  const handleBulkResume = useCallback(async () => {
    if (!tid || !data) return
    try {
      const resp = await bulkResumePaused(tid, data.version_id)
      setBulkToast(`Resumed ${resp.updated_count} match${resp.updated_count !== 1 ? 'es' : ''}`)
      setTimeout(() => setBulkToast(null), 4000)
      handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bulk resume failed')
    }
  }, [tid, data, handleRefresh])

  const handleBulkUndelay = useCallback(async () => {
    if (!tid || !data) return
    try {
      const resp = await bulkUndelay(tid, data.version_id)
      setBulkToast(`Un-delayed ${resp.updated_count} match${resp.updated_count !== 1 ? 'es' : ''}`)
      setTimeout(() => setBulkToast(null), 4000)
      handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bulk un-delay failed')
    }
  }, [tid, data, handleRefresh])

  const isDraft = data?.version_status === 'draft'

  const [startAllOpen, setStartAllOpen] = useState(false)
  const [startAllExcluded, setStartAllExcluded] = useState<Set<string>>(new Set())
  const [startingAll, setStartingAll] = useState(false)

  const startableCourts = useMemo(() => {
    if (!data) return []
    return data.courts
      .map(court => {
        const nowPlaying = data.now_playing_by_court[court]
        if (nowPlaying) return null
        const upNext = data.up_next_by_court[court]
        if (upNext && upNext.status === 'SCHEDULED') return { court, match: upNext }
        return null
      })
      .filter((x): x is { court: string; match: DeskMatchItem } => x !== null)
  }, [data])

  const handleStartAllOpen = useCallback(() => {
    setStartAllExcluded(new Set())
    setStartAllOpen(true)
  }, [])

  const handleStartAllConfirm = useCallback(async () => {
    if (!tid || !data) return
    setStartingAll(true)
    try {
      const toStart = startableCourts.filter(c => !startAllExcluded.has(c.court))
      await Promise.all(
        toStart.map(({ match }) =>
          deskSetMatchStatus(tid, match!.match_id, {
            version_id: data.version_id,
            status: 'IN_PROGRESS',
          })
        )
      )
      setStartAllOpen(false)
      handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start matches')
    } finally {
      setStartingAll(false)
    }
  }, [tid, data, startableCourts, startAllExcluded, handleRefresh])

  const searchResults = useMemo(() => {
    if (!data || !searchText.trim()) return null
    const q = searchText.trim().toLowerCase()
    const numQ = parseInt(q, 10)
    return data.matches.filter(m => {
      if (!isNaN(numQ) && m.match_number === numQ) return true
      if (m.team1_display.toLowerCase().includes(q)) return true
      if (m.team2_display.toLowerCase().includes(q)) return true
      return false
    })
  }, [data, searchText])

  if (loading && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#666' }}>Loading desk...</div>
    )
  }

  if (error && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#c62828' }}>{error}</div>
    )
  }

  if (!data) return null

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f5f5f5' }}>
      {/* Header */}
      <div style={{
        backgroundColor: '#1a237e',
        color: '#fff',
        padding: '12px 24px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => navigate('/')}
            title="Back to tournaments"
            style={{
              background: 'rgba(255,255,255,0.15)',
              border: 'none',
              color: '#fff',
              fontSize: 18,
              fontWeight: 700,
              cursor: 'pointer',
              borderRadius: 4,
              padding: '4px 10px',
              lineHeight: 1,
            }}
          >
            ←
          </button>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{data.tournament_name}</div>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Tournament Desk</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={handleRefresh}
            style={{
              padding: '6px 14px',
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: 'rgba(255,255,255,0.2)',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Refresh
          </button>
          <button
            onClick={() => window.open(`/desk/t/${tid}/board`, '_blank')}
            style={{
              padding: '6px 14px',
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: '#0d47a1',
              color: '#fff',
              border: '1px solid rgba(255,255,255,0.3)',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Board View
          </button>
        </div>
      </div>

      {/* Mode banner */}
      <div style={{
        padding: '8px 24px',
        backgroundColor: '#e8f5e9',
        color: '#2e7d32',
        fontSize: 13,
        fontWeight: 600,
        borderBottom: '1px solid #c8e6c9',
      }}>
        Live Desk — scores update for players immediately
      </div>

      {/* Tab bar */}
      <div style={{
        display: 'flex',
        gap: 0,
        backgroundColor: '#fff',
        borderBottom: '2px solid #e0e0e0',
        paddingLeft: 24,
      }}>
        {(['courts', 'schedule', 'draws', 'impact', 'pools', 'bulk', 'grid', 'weather', 'teams'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '10px 20px',
              fontSize: 13,
              fontWeight: 600,
              border: 'none',
              borderBottom: activeTab === tab ? '3px solid #1a237e' : '3px solid transparent',
              backgroundColor: 'transparent',
              color: activeTab === tab ? '#1a237e' : '#888',
              cursor: 'pointer',
              textTransform: 'capitalize',
              marginBottom: -2,
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      <div style={{ padding: '16px 24px' }}>
        {/* Courts Tab */}
        {activeTab === 'courts' && (
          <>
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, position: 'relative' }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: '#333', margin: 0 }}>
                  Courts
                </h2>
                {isDraft && startableCourts.length > 0 && (
                  <button
                    onClick={handleStartAllOpen}
                    style={{
                      padding: '4px 12px',
                      fontSize: 12,
                      fontWeight: 600,
                      backgroundColor: '#e65100',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 4,
                      cursor: 'pointer',
                    }}
                  >
                    Start All
                  </button>
                )}
                {startAllOpen && (
                  <>
                    <div
                      onClick={() => setStartAllOpen(false)}
                      style={{
                        position: 'fixed',
                        top: 0, left: 0, right: 0, bottom: 0,
                        backgroundColor: 'rgba(0,0,0,0.3)',
                        zIndex: 999,
                      }}
                    />
                    <div style={{
                      position: 'absolute',
                      top: '100%',
                      left: 0,
                      marginTop: 4,
                      backgroundColor: '#fff',
                      border: '1px solid #ccc',
                      borderRadius: 6,
                      boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
                      padding: 16,
                      zIndex: 1000,
                      minWidth: 280,
                    }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: '#333', marginBottom: 8 }}>
                        Start Matches
                      </div>
                      <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
                        Uncheck courts to exclude:
                      </div>
                      {startableCourts.map(({ court, match }) => (
                        <label
                          key={court}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            padding: '4px 0',
                            fontSize: 13,
                            cursor: 'pointer',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={!startAllExcluded.has(court)}
                            onChange={() => {
                              setStartAllExcluded(prev => {
                                const next = new Set(prev)
                                if (next.has(court)) next.delete(court)
                                else next.add(court)
                                return next
                              })
                            }}
                          />
                          <span style={{ fontWeight: 600 }}>{court}</span>
                          <span style={{ color: '#888', fontSize: 11 }}>
                            — #{match!.match_number} {match!.team1_display} vs {match!.team2_display}
                          </span>
                        </label>
                      ))}
                      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                        <button
                          onClick={handleStartAllConfirm}
                          disabled={startingAll || startAllExcluded.size === startableCourts.length}
                          style={{
                            flex: 1,
                            padding: '6px 14px',
                            fontSize: 13,
                            fontWeight: 600,
                            backgroundColor: startAllExcluded.size === startableCourts.length ? '#ccc' : '#e65100',
                            color: '#fff',
                            border: 'none',
                            borderRadius: 4,
                            cursor: startAllExcluded.size === startableCourts.length ? 'not-allowed' : 'pointer',
                          }}
                        >
                          {startingAll ? 'Starting...' : `Start ${startableCourts.length - startAllExcluded.size} Match${startableCourts.length - startAllExcluded.size !== 1 ? 'es' : ''}`}
                        </button>
                        <button
                          onClick={() => setStartAllOpen(false)}
                          style={{
                            padding: '6px 14px',
                            fontSize: 13,
                            fontWeight: 600,
                            backgroundColor: '#f5f5f5',
                            color: '#555',
                            border: '1px solid #ccc',
                            borderRadius: 4,
                            cursor: 'pointer',
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                gap: 8,
                marginTop: 8,
              }}>
                {data.courts.map(court => {
                  const courtLabel = court.replace(/^Court\s+/i, '')
                  const courtMatches = data.matches
                    .filter(m => m.court_name === court && m.status === 'FINAL')
                    .sort((a, b) => (a.day_index - b.day_index) || (a.sort_time || '').localeCompare(b.sort_time || ''))
                  return (
                    <CourtCard
                      key={court}
                      courtName={court}
                      nowPlaying={data.now_playing_by_court[court]}
                      upNext={data.up_next_by_court[court]}
                      onDeck={data.on_deck_by_court[court]}
                      isDraft={isDraft}
                      onAction={handleAction}
                      courtState={courtStates[courtLabel]}
                      onCourtStateChange={handleCourtStateChange}
                      courtMatches={courtMatches}
                      allMatches={data.matches}
                      onMatchClick={m => setDrawerMatch(m)}
                    />
                  )
                })}
              </div>
              {data.courts.length === 0 && (
                <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>No courts found</div>
              )}
            </div>

            <div style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, color: '#333', margin: '0 0 12px 0' }}>
                Quick Search
              </h2>
              <input
                type="text"
                placeholder="Search by Match # or team name..."
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
                style={{
                  width: '100%',
                  maxWidth: 400,
                  padding: '8px 12px',
                  fontSize: 14,
                  border: '1px solid #ccc',
                  borderRadius: 6,
                  boxSizing: 'border-box',
                }}
              />
              {searchResults && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 13, color: '#888', marginBottom: 8 }}>
                    {searchResults.length} result{searchResults.length !== 1 ? 's' : ''}
                  </div>
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                    gap: 8,
                  }}>
                    {searchResults.map(m => (
                      <div
                        key={m.match_id}
                        onClick={() => setDrawerMatch(m)}
                        style={{ cursor: 'pointer' }}
                      >
                        <MiniMatchCard match={m} isDraft={isDraft} onAction={handleAction} allMatches={data.matches} />
                      </div>
                    ))}
                  </div>
                  {searchResults.length === 0 && (
                    <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>No matches found</div>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {/* Schedule Tab */}
        {activeTab === 'schedule' && (
          <ScheduleTab matches={data.matches} isDraft={isDraft} onMatchClick={m => setDrawerMatch(m)} />
        )}

        {/* Draws Tab */}
        {activeTab === 'draws' && (
          <DrawsTab
            tournamentId={tid!}
            versionId={data.version_id}
            matches={data.matches}
          />
        )}

        {/* Impact Tab */}
        {activeTab === 'impact' && (
          <ImpactTab
            tournamentId={tid!}
            versionId={data.version_id}
            onMatchClick={m => setDrawerMatch(m)}
          />
        )}

        {activeTab === 'pools' && (
          <PoolProjectionPanel
            tournamentId={tid!}
            versionId={data.version_id}
            isDraft={isDraft}
            onPlacementComplete={() => loadSnapshot(data.version_id)}
          />
        )}

        {activeTab === 'bulk' && (
          <BulkControlsPanel
            isDraft={isDraft}
            data={data}
            onBulkPause={() => {
              setBulkConfirm({
                label: 'Pause All In-Progress Matches',
                fn: handleBulkPause,
              })
            }}
            onBulkResume={() => {
              setBulkConfirm({
                label: 'Resume All Paused Matches',
                fn: handleBulkResume,
              })
            }}
            onBulkDelay={(afterTime, dayIndex) => {
              setBulkConfirm({
                label: `Delay Scheduled Matches After ${afterTime}`,
                fn: () => handleBulkDelay(afterTime, dayIndex),
              })
            }}
            onBulkUndelay={() => {
              setBulkConfirm({
                label: 'Restore All Delayed Matches to Scheduled',
                fn: handleBulkUndelay,
              })
            }}
          />
        )}

        {activeTab === 'grid' && (
          <DeskGridTab
            tournamentId={tournamentId!}
            data={data}
            isDraft={isDraft}
            onRefresh={() => loadSnapshot(data.version_id)}
            onMatchClick={m => setDrawerMatch(m)}
            highlightedMatchIds={rescheduledMatchIds}
          />
        )}

        {activeTab === 'weather' && (
          <WeatherTab
            tournamentId={tid!}
            data={data}
            isDraft={isDraft}
            onBulkPause={() => handleBulkPause()}
            onBulkResume={() => handleBulkResume()}
            onBulkDelay={(afterTime, dayIndex) => handleBulkDelay(afterTime, dayIndex)}
            onBulkUndelay={() => handleBulkUndelay()}
            onRefresh={() => loadSnapshot(data.version_id)}
            onSwitchToGrid={() => setActiveTab('grid')}
            onRescheduled={(ids) => setRescheduledMatchIds(new Set(ids))}
          />
        )}

        {activeTab === 'teams' && (
          <TeamsTab
            tournamentId={tid!}
            versionId={data.version_id}
            onRefresh={() => loadSnapshot(data.version_id)}
          />
        )}
      </div>

      {/* Bulk toast */}
      {bulkToast && (
        <div style={{
          position: 'fixed',
          bottom: 24,
          left: '50%',
          transform: 'translateX(-50%)',
          padding: '10px 24px',
          backgroundColor: '#2e7d32',
          color: '#fff',
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 600,
          zIndex: 2000,
          boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
        }}>
          {bulkToast}
        </div>
      )}

      {/* Bulk confirm modal */}
      {bulkConfirm && (
        <>
          <div
            onClick={() => setBulkConfirm(null)}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              backgroundColor: 'rgba(0,0,0,0.3)',
              zIndex: 1999,
            }}
          />
          <div style={{
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: 400,
            backgroundColor: '#fff',
            borderRadius: 10,
            boxShadow: '0 8px 30px rgba(0,0,0,0.3)',
            zIndex: 2000,
            overflow: 'hidden',
          }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0' }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>Confirm Bulk Action</div>
            </div>
            <div style={{ padding: '16px 20px', fontSize: 13, color: '#555' }}>
              {bulkConfirm.label}
            </div>
            <div style={{
              padding: '12px 20px',
              borderTop: '1px solid #e0e0e0',
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 10,
            }}>
              <button
                onClick={() => setBulkConfirm(null)}
                style={{
                  padding: '8px 18px',
                  fontSize: 13,
                  fontWeight: 600,
                  backgroundColor: '#f5f5f5',
                  color: '#555',
                  border: '1px solid #ddd',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  await bulkConfirm.fn()
                  setBulkConfirm(null)
                }}
                style={{
                  padding: '8px 18px',
                  fontSize: 13,
                  fontWeight: 600,
                  backgroundColor: '#c62828',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                Proceed
              </button>
            </div>
          </div>
        </>
      )}

      {/* Drawer overlay */}
      {drawerMatch && (
        <>
          <div
            onClick={() => setDrawerMatch(null)}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              backgroundColor: 'rgba(0,0,0,0.3)',
              zIndex: 999,
            }}
          />
          <MatchDrawer
            match={drawerMatch}
            isDraft={isDraft}
            versionId={data.version_id}
            tournamentId={tid!}
            onClose={() => setDrawerMatch(null)}
            onRefreshKeepOpen={() => handleRefresh()}
            onRefreshAndClose={() => {
              handleRefresh()
              setDrawerMatch(null)
            }}
            allMatches={data.matches}
          />
        </>
      )}
    </div>
  )
}

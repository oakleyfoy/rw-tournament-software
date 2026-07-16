import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getEvents,
  getTournament,
  getDeskSnapshot,
  getDeskImpact,
  getPoolProjection,
  getDeskStandings,
  confirmPoolPlacement,
  repairPlacementDay,
  checkDeskConflicts,
  createWorkingDraft,
  deskFinalizeMatch,
  deskSendFinalizeSms,
  deskCorrectMatch,
  deskSetMatchStatus,
  deskMoveMatch,
  deskSwapMatches,
  deskAddSlots,
  deskDeleteSlots,
  deskAddCourt,
  deskUpdateCourt,
  deskDeleteCourt,
  deskFillCourtSlots,
  deskRemapCourts,
  deskCheckInPlayer,
  deskCheckInTeam,
  assignReadyMatchToSlot,
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
  Event,
  SnapshotSlot,
  MatchImpactItem,
  ImpactTarget,
  ConflictItem,
  CourtStateItem,
  CheckInMatchItem,
  ReadyQueueResponse,
  ReadyQueueItem,
  AvailableCourtSlot,
  MatchCheckInSideState,
  PlayerCheckInState,
  FinalizeResponse,
  FinalizeSmsPreview,
  PoolProjectionResponse,
  EventProjection,
  StandingsResponse,
  ReschedulePreviewResponse,
  rebuildPreview,
  rebuildApply,
  RebuildPreviewResponse,
  RebuildMatchItem,
  getDeskTeams,
  defaultTeamWeekend,
  updateTeam,
  DeskTeamItem,
  getSmsStatus,
  getSmsMatches,
  getSmsEventDivisions,
  getSmsPlayers,
  getSmsPhoneLists,
  syncSmsPlayerContacts,
  wipeSmsPlayers,
  getTemporaryPlayerLookups,
  importTemporaryPlayerLookups,
  createTemporaryPlayerLookup,
  updateTemporaryPlayerLookup,
  deleteTemporaryPlayerLookup,
  clearTemporaryPlayerLookups,
  sendSmsBlast,
  sendSmsEvent,
  sendSmsEventDivision,
  sendSmsTeam,
  sendSmsPlayer,
  sendSmsMatch,
  sendSmsPhoneList,
  previewSmsBlast,
  previewSmsEvent,
  previewSmsEventDivision,
  previewSmsPlayer,
  previewSmsMatch,
  previewSmsPhoneList,
  getSmsLog,
  getSmsRolloutMetrics,
  runSmsFirstMatchReminders,
  runSmsRrFirstMatchReminders,
  getSmsSettings,
  patchSmsSettings,
  getSmsTemplates,
  putSmsTemplate,
  createSmsPhoneList,
  renameSmsPhoneList,
  deleteSmsPhoneList,
  importSmsPhoneList,
  SmsAutomationRunResponse,
  SmsRrAutomationRunResponse,
  SmsLogEntry,
  SmsPreviewResponse,
  SmsSendResponse,
  SmsSettingsResponse,
  SmsTemplateResponse,
  SmsMatchLookupItem,
  SmsDivisionLookupItem,
  SmsPlayerLookupItem,
  SmsPlayerSyncResponse,
  SmsPlayerWipeResponse,
  SmsPhoneList,
  TemporaryPlayerLookupItem,
  getPublicRoundRobin,
  RoundRobinResponse,
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
import { confirmDialog } from '../../utils/confirm'

const SLOT_TINT_PALETTE = [
  { bg: '#f7fff7', border: '#c8e6c9', accent: '#1b5e20' },
  { bg: '#e3f2fd', border: '#90caf9', accent: '#0d47a1' },
  { bg: '#fce4ec', border: '#f8bbd0', accent: '#880e4f' },
  { bg: '#fff3e0', border: '#ffcc80', accent: '#e65100' },
  { bg: '#f3e5f5', border: '#ce93d8', accent: '#6a1b9a' },
]

const getSlotTint = (index: number | null) =>
  index != null ? SLOT_TINT_PALETTE[index % SLOT_TINT_PALETTE.length] : null

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

const TIME_SLOT_TINTS = [
  { bg: '#fff8e1', border: '#ffe082', accent: '#f57f17' },
  { bg: '#e8f5e9', border: '#a5d6a7', accent: '#2e7d32' },
  { bg: '#e3f2fd', border: '#90caf9', accent: '#1565c0' },
  { bg: '#f3e5f5', border: '#ce93d8', accent: '#6a1b9a' },
  { bg: '#fce4ec', border: '#f8bbd0', accent: '#ad1457' },
  { bg: '#e0f7fa', border: '#80deea', accent: '#00695c' },
  { bg: '#f9fbe7', border: '#dce775', accent: '#558b2f' },
  { bg: '#efebe9', border: '#bcaaa4', accent: '#4e342e' },
] as const

function _hashSlotKey(key: string): number {
  let h = 0
  for (let i = 0; i < key.length; i += 1) {
    h = (h * 31 + key.charCodeAt(i)) >>> 0
  }
  return h
}

function getTimeSlotTint(match: DeskMatchItem): { bg: string; border: string; accent: string } {
  const time = (match.scheduled_time || '').trim()
  if (!time) return { bg: '#fafafa', border: '#e8e8e8', accent: '#546e7a' }
  const day = (match.day_label || '').trim()
  const key = `${day}|${time}`
  return TIME_SLOT_TINTS[_hashSlotKey(key) % TIME_SLOT_TINTS.length]
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

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const normalized = hex.replace('#', '').trim()
  if (!/^[0-9a-f]{3}([0-9a-f]{3})?$/i.test(normalized)) return null
  const full = normalized.length === 3
    ? normalized.split('').map((ch) => ch + ch).join('')
    : normalized
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  }
}

function isLightRgb(r: number, g: number, b: number): boolean {
  const luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
  return luminance >= 186
}

function deriveDynamicTowelStyles(rawColor: string): { backgroundColor: string; color: string; borderColor: string } | null {
  const trimmed = rawColor.trim()
  if (!trimmed) return null

  const normalized = trimmed.toLowerCase()
  const aliasMap: Record<string, string> = {
    neonyellow: '#d4ff2a',
    neonlime: '#c6ff00',
    lightblue: '#64b5f6',
    babyblue: '#81d4fa',
    skyblue: '#4fc3f7',
    darkblue: '#0d47a1',
    huntergreen: '#355e3b',
    forestgreen: '#2e7d32',
    darkgreen: '#1b5e20',
    lightgreen: '#8bc34a',
    hotpink: '#ec407a',
    maroon: '#800000',
    tan: '#d2b48c',
    gold: '#fbc02d',
    silver: '#b0bec5',
  }

  const candidates = [
    trimmed,
    normalized,
    normalized.replace(/\s+/g, ''),
    normalized.replace(/[^a-z0-9#(),.%\s-]/g, '').trim(),
  ].filter((value, index, arr) => value && arr.indexOf(value) === index)

  for (const candidate of candidates) {
    const alias = aliasMap[candidate.replace(/\s+/g, '')]
    const resolved = alias || candidate
    const rgb = hexToRgb(resolved)
    if (rgb) {
      const light = isLightRgb(rgb.r, rgb.g, rgb.b)
      return {
        backgroundColor: resolved,
        color: light ? '#1f2937' : '#ffffff',
        borderColor: light ? 'rgba(15, 23, 42, 0.28)' : 'rgba(255, 255, 255, 0.16)',
      }
    }
    if (typeof window !== 'undefined' && typeof window.CSS !== 'undefined' && window.CSS.supports('color', resolved)) {
      const lowerResolved = resolved.toLowerCase()
      const lightKeyword = /(white|yellow|lime|mint|gold|silver|cream|ivory|tan|beige|khaki|sky|baby|light)/.test(lowerResolved)
      return {
        backgroundColor: resolved,
        color: lightKeyword ? '#1f2937' : '#ffffff',
        borderColor: lightKeyword ? 'rgba(15, 23, 42, 0.28)' : 'rgba(255, 255, 255, 0.16)',
      }
    }
  }

  return null
}

function getTowelPillStyles(colorName: string): { backgroundColor: string; color: string; borderColor: string } {
  const key = colorName.trim().toLowerCase()
  const presets: Record<string, { backgroundColor: string; color: string; borderColor: string }> = {
    lime: { backgroundColor: '#c6ff00', color: '#1b1b1b', borderColor: '#99cc00' },
    black: { backgroundColor: '#111111', color: '#ffffff', borderColor: '#000000' },
    royal: { backgroundColor: '#4169e1', color: '#ffffff', borderColor: '#2746a6' },
    navy: { backgroundColor: '#001f5b', color: '#ffffff', borderColor: '#00143d' },
    red: { backgroundColor: '#d32f2f', color: '#ffffff', borderColor: '#9a0007' },
    purple: { backgroundColor: '#8e24aa', color: '#ffffff', borderColor: '#5c007a' },
    orange: { backgroundColor: '#ef6c00', color: '#ffffff', borderColor: '#b53d00' },
    pine: { backgroundColor: '#1b5e20', color: '#ffffff', borderColor: '#0d3b12' },
    yellow: { backgroundColor: '#ffd54f', color: '#2f2400', borderColor: '#c8a415' },
    gray: { backgroundColor: '#757575', color: '#ffffff', borderColor: '#4a4a4a' },
    grey: { backgroundColor: '#757575', color: '#ffffff', borderColor: '#4a4a4a' },
    blue: { backgroundColor: '#1976d2', color: '#ffffff', borderColor: '#0d47a1' },
    green: { backgroundColor: '#2e7d32', color: '#ffffff', borderColor: '#1b5e20' },
    pink: { backgroundColor: '#d81b60', color: '#ffffff', borderColor: '#8e0038' },
    white: { backgroundColor: '#fafafa', color: '#455a64', borderColor: '#cfd8dc' },
  }
  return presets[key] || deriveDynamicTowelStyles(colorName) || { backgroundColor: '#eef2f7', color: '#334155', borderColor: '#cbd5e1' }
}

function TowelColorPill({
  colorName,
  reportUrl,
  labelMode = 'full',
}: {
  colorName: string | null
  reportUrl?: string | null
  labelMode?: 'full' | 'swatch'
}) {
  if (!colorName) return null
  const styles = getTowelPillStyles(colorName)
  const clickable = !!reportUrl
  return (
    <span
      title={clickable ? `Open report: ${reportUrl}` : colorName}
      onClick={clickable ? () => window.open(reportUrl!, '_blank', 'noopener,noreferrer') : undefined}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: labelMode === 'swatch' ? '0' : '1px 7px',
        borderRadius: 999,
        border: `1px solid ${styles.borderColor}`,
        backgroundColor: styles.backgroundColor,
        color: styles.color,
        fontSize: 10,
        fontWeight: 700,
        lineHeight: labelMode === 'swatch' ? '0' : '16px',
        cursor: clickable ? 'pointer' : 'default',
        whiteSpace: 'nowrap',
        minWidth: labelMode === 'swatch' ? 24 : undefined,
        width: labelMode === 'swatch' ? 24 : undefined,
        height: labelMode === 'swatch' ? 14 : undefined,
      }}
    >
      {labelMode === 'full' ? colorName : ''}
    </span>
  )
}

function TowelCountBar({ colorName, count, maxCount }: { colorName: string; count: number; maxCount: number }) {
  const styles = getTowelPillStyles(colorName)
  const widthPct = maxCount > 0 ? Math.max((count / maxCount) * 100, count > 0 ? 8 : 0) : 0
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'auto minmax(80px, 1fr) 32px', alignItems: 'center', gap: 8 }}>
      <TowelColorPill colorName={colorName} />
      <div style={{ height: 12, borderRadius: 999, backgroundColor: '#edf2f7', overflow: 'hidden', border: '1px solid #e2e8f0' }}>
        <div style={{ height: '100%', width: `${widthPct}%`, backgroundColor: styles.backgroundColor, borderRight: `1px solid ${styles.borderColor}` }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color: '#334155', textAlign: 'right' }}>{count}</span>
    </div>
  )
}

function toLookupDraft(item?: TemporaryPlayerLookupItem | null): { source_name: string; towel_color: string; report_url: string } {
  return {
    source_name: item?.source_name || '',
    towel_color: item?.towel_color || '',
    report_url: item?.report_url || '',
  }
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

function CheckInNoteModal({
  teamLabel,
  note,
  busy,
  onKeep,
  onDelete,
  onCancel,
}: {
  teamLabel: string
  note: string
  busy: boolean
  onKeep: () => void
  onDelete: () => void
  onCancel: () => void
}) {
  return (
    <>
      <div
        onClick={busy ? undefined : onCancel}
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
        width: 460,
        maxWidth: 'calc(100vw - 32px)',
        backgroundColor: '#fff',
        borderRadius: 10,
        boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
        zIndex: 2001,
        overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0', backgroundColor: '#fff8e1' }}>
          <div style={{ fontWeight: 700, fontSize: 16, color: '#8d6e63' }}>
            Team Note
          </div>
          <div style={{ fontSize: 13, color: '#5d4037', marginTop: 4 }}>
            {teamLabel}
          </div>
        </div>
        <div style={{ padding: 20 }}>
          <div style={{ fontSize: 13, color: '#37474f', marginBottom: 10 }}>
            This team has a note attached. Keep it or delete it before check-in continues.
          </div>
          <div style={{
            whiteSpace: 'pre-wrap',
            fontSize: 13,
            lineHeight: 1.45,
            color: '#263238',
            backgroundColor: '#fafafa',
            border: '1px solid #eceff1',
            borderRadius: 6,
            padding: 12,
            minHeight: 72,
          }}>
            {note}
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, padding: '0 20px 18px 20px' }}>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid #cfd8dc', backgroundColor: '#fff', cursor: busy ? 'default' : 'pointer' }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onKeep}
            disabled={busy}
            style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid #90a4ae', backgroundColor: '#eceff1', color: '#263238', fontWeight: 700, cursor: busy ? 'default' : 'pointer' }}
          >
            {busy ? 'Working...' : 'Keep Note'}
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            style={{ padding: '8px 14px', borderRadius: 6, border: 'none', backgroundColor: '#c62828', color: '#fff', fontWeight: 700, cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.7 : 1 }}
          >
            {busy ? 'Working...' : 'Delete Note'}
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
  onSmsTeamClick,
  onSmsMatchClick,
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
  onSmsTeamClick?: (teamId: number) => void
  onSmsMatchClick?: (matchId: number, phaseHint?: 'upcoming' | 'completed') => void
}) {
  const [editingNote, setEditingNote] = useState(false)
  const [noteText, setNoteText] = useState(courtState?.note || '')
  const [showHistory, setShowHistory] = useState(false)
  const isClosed = courtState?.is_closed || false
  const onDeckTint = onDeck ? getTimeSlotTint(onDeck) : null

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
            <MiniMatchCard
              match={nowPlaying}
              isDraft={isDraft}
              onAction={onAction}
              showActions
              allMatches={allMatches}
              onMatchClick={onMatchClick}
              onSmsTeamClick={onSmsTeamClick}
              onSmsMatchClick={onSmsMatchClick}
            />
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
            <MiniMatchCard
              match={upNext}
              isDraft={isDraft}
              onAction={onAction}
              showActions
              allMatches={allMatches}
              onMatchClick={onMatchClick}
              onSmsTeamClick={onSmsTeamClick}
              onSmsMatchClick={onSmsMatchClick}
            />
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
                    border: `1px solid ${onDeckTint?.border || '#eee'}`,
                    borderRadius: 4,
                    padding: '3px 8px',
                    backgroundColor: deckDefault ? '#fce4ec' : (onDeckTint?.bg || '#fafafa'),
                    fontSize: 10,
                    opacity: 0.85,
                    borderLeft: deckDefault ? '3px solid #c62828' : undefined,
                    cursor: onMatchClick ? 'pointer' : undefined,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{ fontWeight: 700, fontSize: 10 }}>#{onDeck.match_number}</span>
                      {onSmsMatchClick && (
                        <SmsQuickActionButton
                          title={`Text match #${onDeck.match_number}`}
                          onClick={() =>
                            onSmsMatchClick(
                              onDeck.match_id,
                              onDeck.status === 'FINAL' ? 'completed' : 'upcoming'
                            )
                          }
                        />
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 2 }}>
                      {deckDefault && <Badge label="DEFAULT" bg="#c62828" color="#fff" />}
                      <EventBadge name={onDeck.event_name} />
                      <Badge label={onDeck.stage} bg={STAGE_COLORS[onDeck.stage] || '#757575'} color="#fff" />
                    </div>
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, flexWrap: 'wrap' }}>
                    <span style={{ color: onDeck.team1_defaulted ? '#c62828' : '#555', textDecoration: onDeck.team1_defaulted ? 'line-through' : 'none' }}>
                      {onDeck.team1_display}
                    </span>
                    {onSmsTeamClick && onDeck.team1_id && (
                      <SmsQuickActionButton
                        title={`Text ${onDeck.team1_display}`}
                        onClick={() => onSmsTeamClick(onDeck.team1_id!)}
                      />
                    )}
                    <span style={{ color: '#999' }}> vs </span>
                    <span style={{ color: onDeck.team2_defaulted ? '#c62828' : '#555', textDecoration: onDeck.team2_defaulted ? 'line-through' : 'none' }}>
                      {onDeck.team2_display}
                    </span>
                    {onSmsTeamClick && onDeck.team2_id && (
                      <SmsQuickActionButton
                        title={`Text ${onDeck.team2_display}`}
                        onClick={() => onSmsTeamClick(onDeck.team2_id!)}
                      />
                    )}
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
              const slotTint = getTimeSlotTint(m)
              return (
                <div key={m.match_id} onClick={() => onMatchClick?.(m)} style={{
                  border: `1px solid ${slotTint.border}`,
                  borderRadius: 4,
                  padding: '3px 8px',
                  marginBottom: 3,
                  backgroundColor: slotTint.bg,
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

function SmsQuickActionButton({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={e => {
        e.preventDefault()
        e.stopPropagation()
        onClick()
      }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 15,
        height: 15,
        borderRadius: 3,
        border: '1px solid #90caf9',
        backgroundColor: '#e3f2fd',
        color: '#0d47a1',
        fontSize: 9,
        lineHeight: 1,
        padding: 0,
        cursor: 'pointer',
        flexShrink: 0,
      }}
    >
      &#9993;
    </button>
  )
}

function MiniMatchCard({
  match,
  isDraft,
  onAction,
  showActions,
  allMatches,
  onMatchClick,
  onSmsTeamClick,
  onSmsMatchClick,
}: {
  match: DeskMatchItem
  isDraft: boolean
  onAction: (match: DeskMatchItem, action: string) => void
  showActions?: boolean
  allMatches?: DeskMatchItem[]
  onMatchClick?: (m: DeskMatchItem) => void
  onSmsTeamClick?: (teamId: number) => void
  onSmsMatchClick?: (matchId: number, phaseHint?: 'upcoming' | 'completed') => void
}) {
  const sc = STATUS_COLORS[match.status] || STATUS_COLORS.SCHEDULED
  const team1TBD = !match.team1_id && match.source_match_a_id
  const team2TBD = !match.team2_id && match.source_match_b_id
  const hasDefault = match.team1_defaulted || match.team2_defaulted
  const slotTint = getTimeSlotTint(match)
  return (
    <div
      onClick={onMatchClick ? () => onMatchClick(match) : undefined}
      style={{
        border: `1px solid ${slotTint.border}`,
        borderRadius: 4,
        padding: '4px 8px',
        backgroundColor: hasDefault ? '#fce4ec' : slotTint.bg,
        fontSize: 11,
        borderLeft: hasDefault ? '3px solid #c62828' : undefined,
        cursor: onMatchClick ? 'pointer' : undefined,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontWeight: 700, fontSize: 11 }}>#{match.match_number}</span>
          {onSmsMatchClick && (
            <SmsQuickActionButton
              title={`Text match #${match.match_number}`}
              onClick={() =>
                onSmsMatchClick(
                  match.match_id,
                  match.status === 'FINAL' ? 'completed' : 'upcoming'
                )
              }
            />
          )}
        </div>
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
        <span>{match.team1_display}</span>
        {match.team1_notes && <NoteIcon note={match.team1_notes} />}
        {onSmsTeamClick && match.team1_id && (
          <SmsQuickActionButton
            title={`Text ${match.team1_display}`}
            onClick={() => onSmsTeamClick(match.team1_id!)}
          />
        )}
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
        <span>{match.team2_display}</span>
        {match.team2_notes && <NoteIcon note={match.team2_notes} />}
        {onSmsTeamClick && match.team2_id && (
          <SmsQuickActionButton
            title={`Text ${match.team2_display}`}
            onClick={() => onSmsTeamClick(match.team2_id!)}
          />
        )}
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
  const [finalizeSmsPreview, setFinalizeSmsPreview] = useState<FinalizeSmsPreview | null>(null)
  const [sendingFinalizeSms, setSendingFinalizeSms] = useState(false)
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

  const finalizeWithPreview = useCallback(async (options?: { score?: string; is_default?: boolean; is_retired?: boolean }) => {
    if (!winnerId) return
    if (!options?.is_default && !options?.is_retired && !score.trim()) return
    if (options?.is_retired && !score.trim()) return
    setSubmitting(true)
    setError(null)
    setResult(null)
    setStatusMsg(null)
    setFinalizeSmsPreview(null)
    try {
      const resp = await deskFinalizeMatch(tournamentId, match.match_id, {
        version_id: versionId,
        score: options?.is_default ? undefined : (options?.score ?? (score || undefined)),
        winner_team_id: winnerId,
        is_default: options?.is_default,
        is_retired: options?.is_retired,
        send_automation_texts: false,
        include_sms_preview: true,
      })
      setResult(resp)
      setFinalized(true)
      setFinalizeSmsPreview(resp.sms_preview ?? null)
      onRefreshKeepOpen()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to finalize')
    } finally {
      setSubmitting(false)
    }
  }, [tournamentId, match.match_id, versionId, score, winnerId, onRefreshKeepOpen])

  const doFinalize = useCallback(async () => {
    await finalizeWithPreview()
  }, [finalizeWithPreview])

  const handleFinalize = useCallback(() => {
    if (!winnerId) return
    runWithConflictCheck('FINALIZE', 'Finalize Match', doFinalize)
  }, [winnerId, runWithConflictCheck, doFinalize])

  const doDefault = useCallback(async () => {
    await finalizeWithPreview({ is_default: true })
  }, [finalizeWithPreview])

  const handleDefault = useCallback(() => {
    if (!winnerId) return
    runWithConflictCheck('FINALIZE', 'Default Match', doDefault)
  }, [winnerId, runWithConflictCheck, doDefault])

  const doRetired = useCallback(async () => {
    await finalizeWithPreview({ score, is_retired: true })
  }, [finalizeWithPreview, score])

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

  const moveBackToReady = useCallback(async () => {
    setError(null)
    setStatusMsg(null)
    try {
      await deskSetMatchStatus(tournamentId, match.match_id, {
        version_id: versionId,
        status: 'SCHEDULED',
        reset_started_at: true,
      })
      setStatusMsg('Moved back to Ready To Go')
      onRefreshAndClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to move match back to ready queue')
    }
  }, [tournamentId, match.match_id, versionId, onRefreshAndClose])

  const reopenToCurrentlyPlaying = useCallback(async () => {
    setError(null)
    setStatusMsg(null)
    try {
      await deskSetMatchStatus(tournamentId, match.match_id, {
        version_id: versionId,
        status: 'IN_PROGRESS',
        allow_reopen_final: true,
        reset_started_at: true,
      })
      setStatusMsg('Reopened match to Currently Playing')
      onRefreshAndClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reopen completed match')
    }
  }, [tournamentId, match.match_id, versionId, onRefreshAndClose])

  const handleSetStatus = useCallback((status: string) => {
    if (status === 'IN_PROGRESS') {
      runWithConflictCheck('SET_IN_PROGRESS', 'Set In Progress', () => doSetStatus(status))
    } else {
      doSetStatus(status)
    }
  }, [runWithConflictCheck, doSetStatus])

  const effectiveMatch = corrResult?.match || result?.match || match
  const effectiveStatus = effectiveMatch.status
  const sc = STATUS_COLORS[effectiveStatus] || STATUS_COLORS.SCHEDULED
  const contextLink = effectiveMatch.stage === 'RR'
    ? `/t/${tournamentId}/draws/${effectiveMatch.event_id}/roundrobin?version_id=${versionId}`
    : `/t/${tournamentId}/draws/${effectiveMatch.event_id}/waterfall?version_id=${versionId}`
  const contextLinkLabel = effectiveMatch.stage === 'RR'
    ? 'View Round Robin'
    : 'View Waterfall Bracket'

  const nextScheduledByTeam = useMemo(() => {
    if (effectiveMatch.stage !== 'RR' || effectiveStatus !== 'FINAL') return []
    if (result && result.downstream_updates.length > 0) return []

    const sourceMatchId = effectiveMatch.match_id
    const sourceDay = effectiveMatch.day_index || 0
    const sourceTime = effectiveMatch.sort_time || ''
    const teamPairs: Array<{ teamId: number; teamName: string }> = []
    if (effectiveMatch.team1_id) {
      teamPairs.push({ teamId: effectiveMatch.team1_id, teamName: effectiveMatch.team1_display })
    }
    if (effectiveMatch.team2_id) {
      teamPairs.push({ teamId: effectiveMatch.team2_id, teamName: effectiveMatch.team2_display })
    }

    const rows: Array<{ teamId: number; teamName: string; nextMatch: DeskMatchItem; opponent: string }> = []
    for (const t of teamPairs) {
      const candidates = allMatches
        .filter(m =>
          m.match_id !== sourceMatchId &&
          (m.team1_id === t.teamId || m.team2_id === t.teamId) &&
          m.status !== 'FINAL' &&
          m.status !== 'CANCELLED' &&
          !!m.scheduled_time &&
          m.day_index > 0
        )
        .filter(m => {
          if (m.day_index > sourceDay) return true
          if (m.day_index < sourceDay) return false
          if (!sourceTime || !m.sort_time) return true
          return m.sort_time >= sourceTime
        })
        .sort((a, b) =>
          (a.day_index - b.day_index) ||
          (a.sort_time || '').localeCompare(b.sort_time || '') ||
          (a.court_name || '').localeCompare(b.court_name || '')
        )

      const nextMatch = candidates[0]
      if (!nextMatch) continue
      const opponent = nextMatch.team1_id === t.teamId ? nextMatch.team2_display : nextMatch.team1_display
      rows.push({ teamId: t.teamId, teamName: t.teamName, nextMatch, opponent })
    }
    return rows
  }, [
    result,
    allMatches,
    effectiveStatus,
    effectiveMatch.stage,
    effectiveMatch.match_id,
    effectiveMatch.day_index,
    effectiveMatch.sort_time,
    effectiveMatch.team1_id,
    effectiveMatch.team2_id,
    effectiveMatch.team1_display,
    effectiveMatch.team2_display,
  ])

  const sendFinalizeTexts = useCallback(async () => {
    if (!finalizeSmsPreview) {
      setStatusMsg('Match finalized without sending texts.')
      return
    }
    setSendingFinalizeSms(true)
    setError(null)
    setStatusMsg(null)
    try {
      const resp = await deskSendFinalizeSms(tournamentId, match.match_id, {
        version_id: versionId,
      })
      const sentCount = resp.sent
      const blockedCount =
        resp.skipped_no_phone +
        resp.skipped_consent +
        resp.skipped_dedupe +
        resp.skipped_test_mode
      setStatusMsg(
        sentCount > 0 || blockedCount > 0
          ? `Finalize texts processed: ${sentCount} sent${blockedCount > 0 ? `, ${blockedCount} skipped` : ''}.`
          : 'No finalize texts were sent.'
      )
      setFinalizeSmsPreview(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to send finalize texts')
    } finally {
      setSendingFinalizeSms(false)
    }
  }, [finalizeSmsPreview, tournamentId, match.match_id, versionId])

  const finalizeSmsEmptyReason = useMemo(() => {
    if (!finalizeSmsPreview || finalizeSmsPreview.recipients.length > 0) return null
    switch (finalizeSmsPreview.disabled_reason) {
      case 'texts_disabled':
        return 'Texts are currently turned off for this tournament.'
      case 'automation_disabled':
        return 'Post-match check-in SMS is currently turned off.'
      case 'template_inactive':
        return 'The post-match SMS template is inactive.'
      case 'match_not_final':
        return 'This match must be finalized before any SMS can be queued.'
      default:
        if (finalizeSmsPreview.teams_with_next_match === 0) {
          return 'No post-match texts are queued because these teams do not have any next matches.'
        }
        return 'No post-match texts are queued for this result.'
    }
  }, [finalizeSmsPreview])

  const finalizeSmsBlockedReasons = useMemo(() => {
    if (!finalizeSmsPreview || finalizeSmsPreview.recipients.length > 0) return []
    const reasons: string[] = []
    if (finalizeSmsPreview.teams_with_next_match > 0) {
      reasons.push(`${finalizeSmsPreview.teams_with_next_match} team${finalizeSmsPreview.teams_with_next_match === 1 ? '' : 's'} have next matches`)
    }
    if (finalizeSmsPreview.teams_without_phone > 0) {
      reasons.push(`${finalizeSmsPreview.teams_without_phone} team${finalizeSmsPreview.teams_without_phone === 1 ? '' : 's'} missing phone numbers`)
    }
    if (finalizeSmsPreview.blocked_test_mode > 0) {
      reasons.push(`${finalizeSmsPreview.blocked_test_mode} recipient${finalizeSmsPreview.blocked_test_mode === 1 ? '' : 's'} blocked by test mode`)
    }
    if (finalizeSmsPreview.blocked_consent > 0) {
      reasons.push(`${finalizeSmsPreview.blocked_consent} recipient${finalizeSmsPreview.blocked_consent === 1 ? '' : 's'} blocked by consent settings`)
    }
    if (finalizeSmsPreview.deduped > 0) {
      reasons.push(`${finalizeSmsPreview.deduped} text${finalizeSmsPreview.deduped === 1 ? '' : 's'} already sent for this matchup`)
    }
    return reasons
  }, [finalizeSmsPreview])

  const actionsPanel = isDraft ? (
    <div style={{ marginBottom: 16 }}>
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
      {(match.status === 'IN_PROGRESS' || match.status === 'PAUSED') && (
        <button
          onClick={moveBackToReady}
          style={{
            width: '100%',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: 600,
            backgroundColor: '#455a64',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
            marginBottom: 12,
          }}
        >
          Back To Ready To Go
        </button>
      )}
      {match.status === 'FINAL' && (
        <button
          onClick={reopenToCurrentlyPlaying}
          style={{
            width: '100%',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: 700,
            backgroundColor: '#1565c0',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
            marginBottom: 12,
          }}
        >
          Reopen To Currently Playing
        </button>
      )}

      {match.status !== 'FINAL' && (
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
              aspectRatio: '1 / 1',
              minHeight: 56,
              padding: '6px',
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: winnerId && score.trim() ? '#2e7d32' : '#ccc',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: winnerId && score.trim() ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              textAlign: 'center',
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
                aspectRatio: '1 / 1',
                minHeight: 56,
                padding: '6px',
                fontSize: 12,
                fontWeight: 600,
                backgroundColor: winnerId ? '#e65100' : '#ccc',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: winnerId ? 'pointer' : 'default',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center',
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
                aspectRatio: '1 / 1',
                minHeight: 56,
                padding: '6px',
                fontSize: 12,
                fontWeight: 600,
                backgroundColor: winnerId && score.trim() ? '#6a1b9a' : '#ccc',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: winnerId && score.trim() ? 'pointer' : 'default',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center',
              }}
            >
              {submitting ? 'Submitting...' : 'Retired'}
            </button>
          )}
        </div>
      </div>
      )}
    </div>
  ) : null

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
        {actionsPanel}

        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          <Badge label={effectiveMatch.stage} bg={STAGE_COLORS[effectiveMatch.stage] || '#757575'} color="#fff" />
          <Badge label={STATUS_LABEL[effectiveStatus] || effectiveStatus} bg={sc.bg} color={sc.text} />
        </div>

        <div style={{ marginBottom: 12, fontSize: 13, color: '#888' }}>
          {effectiveMatch.event_name}
          {effectiveMatch.division_name ? ` — ${effectiveMatch.division_name}` : ''}
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
            {result.downstream_updates.length === 0 && nextScheduledByTeam.length === 0 && result.warnings.length === 0 && (
              <div style={{
                padding: '12px 16px',
                backgroundColor: '#f5f5f5',
                borderRadius: 6,
                fontSize: 13,
                color: '#888',
              }}>
                {effectiveMatch.stage === 'RR'
                  ? 'Round Robin has no bracket advancement path.'
                  : 'No downstream matches to advance into.'}
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
                contextLink,
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
              {contextLinkLabel}
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

        {nextScheduledByTeam.length > 0 && (!result || result.downstream_updates.length === 0) && (
          <div style={{
            marginTop: 12,
            padding: '12px 16px',
            backgroundColor: '#e8f5e9',
            borderRadius: 6,
            border: '1px solid #c8e6c9',
            fontSize: 13,
          }}>
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8, color: '#2e7d32' }}>
              Next Scheduled Matches
            </div>
            {nextScheduledByTeam.map((row, i) => (
              <div key={`${row.teamId}-${row.nextMatch.match_id}`} style={{ padding: '8px 0', borderTop: i > 0 ? '1px solid #c8e6c9' : 'none' }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{row.teamName}</div>
                <div style={{ marginTop: 2 }}>
                  Match #{row.nextMatch.match_number} &middot; {row.nextMatch.day_label}
                </div>
                <div style={{ fontWeight: 600 }}>
                  {row.nextMatch.scheduled_time} &middot; {row.nextMatch.court_name}
                </div>
                <div style={{ marginTop: 2 }}>vs <strong>{row.opponent}</strong></div>
              </div>
            ))}
          </div>
        )}

        {/* Match History Timeline */}
        <MatchTimeline match={effectiveMatch} />
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
      {finalizeSmsPreview && (
        <>
          <div
            onClick={() => {
              if (sendingFinalizeSms) return
              setFinalizeSmsPreview(null)
              setStatusMsg('Match finalized without sending texts.')
            }}
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
            width: 560,
            maxWidth: 'calc(100vw - 24px)',
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
              backgroundColor: '#e8f5e9',
            }}>
              <div style={{ fontWeight: 700, fontSize: 16, color: '#2e7d32' }}>
                Finalize Match SMS Preview
              </div>
              <div style={{ fontSize: 12, color: '#2e7d32', marginTop: 2 }}>
                Match finalized. Review recipients and message text before sending.
              </div>
            </div>
            <div style={{ padding: '14px 20px', overflow: 'auto', flex: 1 }}>
              {finalizeSmsPreview.recipients.length === 0 ? (
                <div style={{
                  padding: '12px 14px',
                  backgroundColor: '#f5f5f5',
                  borderRadius: 6,
                  color: '#666',
                  fontSize: 13,
                }}>
                  <div>{finalizeSmsEmptyReason}</div>
                  {finalizeSmsBlockedReasons.length > 0 && (
                    <div style={{ marginTop: 8, display: 'grid', gap: 4 }}>
                      {finalizeSmsBlockedReasons.map(reason => (
                        <div key={reason}>- {reason}</div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ display: 'grid', gap: 10 }}>
                  {finalizeSmsPreview.recipients.map((recipient, index) => (
                    <div key={`${recipient.phone}-${index}`} style={{
                      border: '1px solid #e0e0e0',
                      borderRadius: 6,
                      padding: '10px 12px',
                      backgroundColor: '#fafafa',
                    }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: '#333' }}>
                        {recipient.player_name || recipient.team_name || 'Recipient'}
                      </div>
                      <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>
                        {recipient.team_name ? `${recipient.team_name} · ` : ''}{recipient.phone}
                      </div>
                      <div style={{
                        marginTop: 8,
                        padding: '10px 12px',
                        borderRadius: 6,
                        backgroundColor: '#fff',
                        border: '1px solid #eee',
                        fontSize: 13,
                        color: '#222',
                        whiteSpace: 'pre-wrap',
                      }}>
                        {recipient.message}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{
              padding: '12px 20px',
              borderTop: '1px solid #e0e0e0',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 10,
            }}>
              <div style={{ fontSize: 12, color: '#666' }}>
                {finalizeSmsPreview.total_messages} text{finalizeSmsPreview.total_messages === 1 ? '' : 's'} ready
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  onClick={() => {
                    if (sendingFinalizeSms) return
                    setFinalizeSmsPreview(null)
                    setStatusMsg('Match finalized without sending texts.')
                  }}
                  style={{
                    padding: '8px 18px',
                    fontSize: 13,
                    fontWeight: 600,
                    backgroundColor: '#f5f5f5',
                    color: '#555',
                    border: '1px solid #ddd',
                    borderRadius: 4,
                    cursor: sendingFinalizeSms ? 'default' : 'pointer',
                  }}
                >
                  Finalize Without Sending
                </button>
                <button
                  onClick={sendFinalizeTexts}
                  disabled={sendingFinalizeSms || finalizeSmsPreview.recipients.length === 0}
                  style={{
                    padding: '8px 18px',
                    fontSize: 13,
                    fontWeight: 700,
                    backgroundColor: finalizeSmsPreview.recipients.length > 0 ? '#2e7d32' : '#ccc',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 4,
                    cursor: sendingFinalizeSms || finalizeSmsPreview.recipients.length === 0 ? 'default' : 'pointer',
                  }}
                >
                  {sendingFinalizeSms ? 'Sending...' : 'Send Text And Finalize'}
                </button>
              </div>
            </div>
          </div>
        </>
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
      // WF_14 loser-flight pools (C/D) are stored as MAIN matches (stage BRACKET)
      // but are round-robin pools, not bracket divisions — count them as RR.
      const isWf14ConsPool =
        m.stage === 'BRACKET' && (m.match_code || '').toUpperCase().includes('_CONS_')
      if (m.stage === 'WF') map[m.event_id].hasWF = true
      if ((m.stage === 'BRACKET' && !isWf14ConsPool) || m.stage === 'CONS') map[m.event_id].hasBracket = true
      if (m.stage === 'RR' || isWf14ConsPool) map[m.event_id].hasRR = true
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
  const [standings, setStandings] = useState<StandingsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingStandings, setLoadingStandings] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [standingsError, setStandingsError] = useState<string | null>(null)
  const [eventFilter, setEventFilter] = useState<number | ''>('')
  const [placing, setPlacing] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [confirmEvt, setConfirmEvt] = useState<EventProjection | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [rrSchedules, setRrSchedules] = useState<Record<number, RoundRobinResponse>>({})
  const [collapsedSchedules, setCollapsedSchedules] = useState<Record<number, boolean>>({})

  const fetchProjection = useCallback(async () => {
    setLoading(true)
    setLoadingStandings(true)
    setError(null)
    setStandingsError(null)
    const [projectionResult, standingsResult] = await Promise.allSettled([
      getPoolProjection(
        tournamentId,
        versionId,
        eventFilter !== '' ? eventFilter : undefined
      ),
      getDeskStandings(
        tournamentId,
        versionId,
        eventFilter !== '' ? eventFilter : undefined
      ),
    ])

    if (projectionResult.status === 'fulfilled') {
      setData(projectionResult.value)
    } else {
      setError(projectionResult.reason instanceof Error ? projectionResult.reason.message : 'Failed to load')
    }

    if (standingsResult.status === 'fulfilled') {
      setStandings(standingsResult.value)
    } else {
      setStandingsError(standingsResult.reason instanceof Error ? standingsResult.reason.message : 'Failed to load standings')
    }

    setLoading(false)
    setLoadingStandings(false)
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

  useEffect(() => {
    if (!data) return
    setCollapsedSchedules(prev => {
      const next = { ...prev }
      for (const evt of data.events) {
        if (next[evt.event_id] == null) next[evt.event_id] = false
      }
      return next
    })
  }, [data])

  // Fetch RR match schedule for each event whenever projection data loads/refreshes
  useEffect(() => {
    if (!data) return
    let cancelled = false
    const fetchAll = async () => {
      const results = await Promise.allSettled(
        data.events.map(evt =>
          getPublicRoundRobin(tournamentId, evt.event_id)
            .then(rr => [evt.event_id, rr] as [number, RoundRobinResponse])
        )
      )
      if (cancelled) return
      const map: Record<number, RoundRobinResponse> = {}
      for (const r of results) {
        if (r.status === 'fulfilled') {
          const [evtId, rr] = r.value
          map[evtId] = rr
        }
      }
      setRrSchedules(map)
    }
    fetchAll()
    return () => { cancelled = true }
  }, [data, tournamentId])

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

  const handleRepairPlacementDay = async (evt: EventProjection) => {
    setPlacing(true)
    try {
      const resp = await repairPlacementDay(tournamentId, {
        version_id: versionId,
        event_id: evt.event_id,
      })
      if (resp.moved === 0 && resp.unscheduled === 0) {
        setToast('Placement matches are already on the final day')
      } else {
        setToast(`Fixed placement day: ${resp.moved} moved, ${resp.unscheduled} unscheduled`)
      }
      fetchProjection()
      onPlacementComplete?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Repair failed')
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
        {loadingStandings && (
          <span style={{ fontSize: 10, color: '#888' }}>Loading standings...</span>
        )}
        {standingsError && !loadingStandings && (
          <span style={{ fontSize: 10, color: '#c62828' }}>{standingsError}</span>
        )}
      </div>

      {allEvents.map(evt => {
        const pct = evt.total_wf_matches > 0 ? Math.round((evt.finalized_wf_matches / evt.total_wf_matches) * 100) : 0
        const isScheduleCollapsed = collapsedSchedules[evt.event_id] ?? false
        // WF_14 loser flight (Division III = Pools C/D) is split mid-tournament on
        // the live version, so it is not gated behind DRAFT like the winner flight.
        const isWf14LoserFlight = evt.pools.some(p => p.pool_label === 'POOLC' || p.pool_label === 'POOLD')
        return (
          <div key={evt.event_id} style={{ marginBottom: 14, border: '1px solid #e0e0e0', borderRadius: 6, backgroundColor: '#fff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, padding: '10px 12px 0' }}>
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

              <div style={{ padding: '0 12px 12px' }}>

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

            {/* Pool Match Schedule */}
            {(() => {
              const rr = rrSchedules[evt.event_id]
              if (!rr) return null
              const poolMatchRows = rr.pools.flatMap(pool =>
                pool.matches.map(m => ({ ...m, pool_label: pool.pool_label, pool_code: pool.pool_code }))
              )
              const scheduled = poolMatchRows.filter(m => m.day_display || m.time_display || m.court_label)
              if (scheduled.length === 0) return null
              return (
                <div style={{ marginTop: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: '#455a64' }}>
                      Pool Match Schedule
                    </div>
                    <button
                      onClick={() => setCollapsedSchedules(prev => ({ ...prev, [evt.event_id]: !isScheduleCollapsed }))}
                      style={{
                        padding: '3px 8px',
                        fontSize: 10,
                        fontWeight: 700,
                        color: '#455a64',
                        backgroundColor: '#fff',
                        border: '1px solid #cfd8dc',
                        borderRadius: 4,
                        cursor: 'pointer',
                      }}
                    >
                      {isScheduleCollapsed ? 'Show' : 'Hide'}
                    </button>
                  </div>
                  {!isScheduleCollapsed && (
                  <div style={{ overflowX: 'auto', border: '1px solid #e0e0e0', borderRadius: 4 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                      <thead>
                        <tr style={{ background: '#e8eaf6' }}>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700, whiteSpace: 'nowrap' }}>Pool</th>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700, whiteSpace: 'nowrap' }}>Match</th>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700, whiteSpace: 'nowrap' }}>Day</th>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700, whiteSpace: 'nowrap' }}>Time</th>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700, whiteSpace: 'nowrap' }}>Court</th>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700 }}>Team A</th>
                          <th style={{ padding: '4px 8px', textAlign: 'center', borderBottom: '1px solid #c5cae9', color: '#999', fontWeight: 400 }}>vs</th>
                          <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700 }}>Team B</th>
                          <th style={{ padding: '4px 8px', textAlign: 'center', borderBottom: '1px solid #c5cae9', color: '#333', fontWeight: 700, whiteSpace: 'nowrap' }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scheduled.map((m, i) => {
                          const isEven = i % 2 === 0
                          const isCompleted = m.status === 'FINAL'
                          return (
                            <tr key={m.match_id} style={{ background: isEven ? '#fff' : '#f9f9ff' }}>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', fontWeight: 700, color: '#1a237e' }}>
                                {m.pool_label}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#555', fontFamily: 'monospace', fontSize: 9 }}>
                                {m.match_code}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#333', whiteSpace: 'nowrap' }}>
                                {m.day_display || '—'}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#333', whiteSpace: 'nowrap', fontWeight: 600 }}>
                                {m.time_display || '—'}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#555', whiteSpace: 'nowrap' }}>
                                {m.court_label || '—'}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#333', fontWeight: 500 }}>
                                {m.line1}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#bbb', textAlign: 'center', fontSize: 9 }}>
                                vs
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', color: '#333', fontWeight: 500 }}>
                                {m.line2}
                              </td>
                              <td style={{ padding: '3px 8px', borderBottom: '1px solid #eee', textAlign: 'center' }}>
                                <span style={{
                                  fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                                  background: isCompleted ? '#e8f5e9' : m.status === 'IN_PROGRESS' ? '#fff3e0' : '#f5f5f5',
                                  color: isCompleted ? '#2e7d32' : m.status === 'IN_PROGRESS' ? '#e65100' : '#666',
                                  textTransform: 'uppercase',
                                }}>
                                  {isCompleted ? 'Final' : m.status === 'IN_PROGRESS' ? 'Live' : 'Sched'}
                                </span>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  )}
                </div>
              )
            })()}

            {/* Confirm placement / split pools button */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              {evt.wf_complete && (isDraft || isWf14LoserFlight) && (
                <button
                  onClick={() => setConfirmEvt(evt)}
                  disabled={placing}
                  style={{
                    marginTop: 6, padding: '4px 12px', fontSize: 10, fontWeight: 700,
                    backgroundColor: '#1a237e', color: '#fff', border: 'none', borderRadius: 3,
                    cursor: placing ? 'not-allowed' : 'pointer', opacity: placing ? 0.6 : 1,
                  }}
                >
                  {placing
                    ? (isWf14LoserFlight ? 'Splitting...' : 'Placing...')
                    : (isWf14LoserFlight ? 'Split Pools' : 'Confirm Pool Placement')}
                </button>
              )}
              {isWf14LoserFlight && (
                <button
                  onClick={() => handleRepairPlacementDay(evt)}
                  disabled={placing}
                  title="Move the Division III placement (C vs D) match to the final tournament day if it landed earlier."
                  style={{
                    marginTop: 6, padding: '4px 12px', fontSize: 10, fontWeight: 700,
                    backgroundColor: '#fff', color: '#1a237e', border: '1px solid #1a237e', borderRadius: 3,
                    cursor: placing ? 'not-allowed' : 'pointer', opacity: placing ? 0.6 : 1,
                  }}
                >
                  {placing ? 'Fixing...' : 'Fix Placement Day'}
                </button>
              )}
            </div>

            {(() => {
              const eventStandings = (standings?.events || []).filter(se => se.event_id === evt.event_id)
              const rrStandings = eventStandings.filter(se => se.rows.length > 0)
              return (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#455a64', marginBottom: 4 }}>
                    Waterfall placement standings
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8 }}>
                    {evt.pools.map(pool => {
                      const placedCount = pool.teams.filter(team => team.status !== 'pending').length
                      const pendingCount = pool.teams.length - placedCount
                      return (
                        <div
                          key={`${evt.event_id}-${pool.pool_label}-wf-placement`}
                          style={{ border: '1px solid #e0e0e0', borderRadius: 4, padding: 8, backgroundColor: '#fff' }}
                        >
                          <div style={{ fontSize: 10, fontWeight: 700, color: '#1a237e', marginBottom: 6 }}>
                            {pool.pool_display}
                          </div>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
                            {[
                              { label: 'Teams', value: pool.teams.length },
                              { label: 'Placed', value: placedCount },
                              { label: 'Pending', value: pendingCount },
                              { label: 'WF Finalized', value: `${evt.finalized_wf_matches}/${evt.total_wf_matches}` },
                            ].map(item => (
                              <span
                                key={item.label}
                                style={{
                                  fontSize: 9,
                                  color: '#37474f',
                                  border: '1px solid #dfe3e6',
                                  backgroundColor: '#f8fafb',
                                  borderRadius: 3,
                                  padding: '1px 6px',
                                }}
                              >
                                <strong>{item.value}</strong> {item.label}
                              </span>
                            ))}
                          </div>
                          <div style={{ overflowX: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                              <thead>
                                <tr>
                                  <th style={{ textAlign: 'left', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>#</th>
                                  <th style={{ textAlign: 'left', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>Team</th>
                                  <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>Bucket</th>
                                  <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>WF W-L</th>
                                  <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>WF2 +/-</th>
                                  <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>Combined +/-</th>
                                  <th style={{ textAlign: 'left', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>How placed</th>
                                </tr>
                              </thead>
                              <tbody>
                                {pool.teams.map((team, idx) => (
                                  <tr key={team.team_id}>
                                    <td style={{ padding: '3px 4px', fontWeight: 700, color: '#1a237e' }}>
                                      {idx + 1}
                                      <span style={{ color: '#90a4ae', marginLeft: 3 }}>S{team.seed_position}</span>
                                    </td>
                                    <td style={{ padding: '3px 4px', fontWeight: 600, color: '#333' }}>
                                      {team.status === 'pending' ? '—' : team.team_display}
                                    </td>
                                    <td style={{ padding: '3px 4px', textAlign: 'center', color: '#333' }}>{team.bucket}</td>
                                    <td style={{ padding: '3px 4px', textAlign: 'center', color: '#333' }}>
                                      {team.status === 'pending' ? '—' : `${team.wf_wins}-${team.wf_losses}`}
                                    </td>
                                    <td style={{ padding: '3px 4px', textAlign: 'center', color: team.wf2_game_diff >= 0 ? '#2e7d32' : '#c62828' }}>
                                      {team.status === 'pending' ? '—' : `${team.wf2_game_diff >= 0 ? '+' : ''}${team.wf2_game_diff}`}
                                    </td>
                                    <td style={{ padding: '3px 4px', textAlign: 'center', color: team.wf_game_diff >= 0 ? '#2e7d32' : '#c62828' }}>
                                      {team.status === 'pending' ? '—' : `${team.wf_game_diff >= 0 ? '+' : ''}${team.wf_game_diff}`}
                                    </td>
                                    <td style={{ padding: '3px 4px', color: '#666' }}>{team.placement_reason}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <div style={{ marginTop: 5, fontSize: 9, color: '#78909c' }}>
                            Placement order: WF wins, then first-round win over second-round win (WW, WL, LW, LL), then WF2 game diff highest to lowest, then combined WF game diff highest to lowest, then highest seed.
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  {rrStandings.length > 0 && (
                    <>
                      <div style={{ fontSize: 10, fontWeight: 700, color: '#455a64', marginTop: 8, marginBottom: 4 }}>
                        Round-robin standings totals
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8 }}>
                        {rrStandings.map(se => {
                          const totalMatches = Math.floor(se.rows.reduce((sum, row) => sum + row.played, 0) / 2)
                          const totalSets = se.rows.reduce((sum, row) => sum + row.sets_won, 0)
                          const totalGames = se.rows.reduce((sum, row) => sum + row.games_won, 0)
                          return (
                            <div
                              key={`${se.event_id}-${se.division_name || 'all'}`}
                              style={{ border: '1px solid #e0e0e0', borderRadius: 4, padding: 8, backgroundColor: '#fff' }}
                            >
                              <div style={{ fontSize: 10, fontWeight: 700, color: '#1a237e', marginBottom: 6 }}>
                                {se.division_name || 'Round Robin standings'}
                              </div>
                              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
                                {[
                                  { label: 'Teams', value: se.rows.length },
                                  { label: 'Completed Matches', value: totalMatches },
                                  { label: 'Sets Logged', value: totalSets },
                                  { label: 'Games Logged', value: totalGames },
                                ].map(item => (
                                  <span
                                    key={item.label}
                                    style={{
                                      fontSize: 9,
                                      color: '#37474f',
                                      border: '1px solid #dfe3e6',
                                      backgroundColor: '#f8fafb',
                                      borderRadius: 3,
                                      padding: '1px 6px',
                                    }}
                                  >
                                    <strong>{item.value}</strong> {item.label}
                                  </span>
                                ))}
                              </div>
                              <div style={{ overflowX: 'auto' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                                  <thead>
                                    <tr>
                                      <th style={{ textAlign: 'left', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>#</th>
                                      <th style={{ textAlign: 'left', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>Team</th>
                                      <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>P</th>
                                      <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>W-L</th>
                                      <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>Set +/-</th>
                                      <th style={{ textAlign: 'center', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>Game +/-</th>
                                      <th style={{ textAlign: 'left', color: '#777', borderBottom: '1px solid #eee', padding: '3px 4px' }}>How ranked</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {se.rows.map(row => (
                                      <tr key={row.team_id}>
                                        <td style={{ padding: '3px 4px', fontWeight: 700, color: '#1a237e' }}>{row.rank}</td>
                                        <td style={{ padding: '3px 4px', fontWeight: 600, color: '#333' }}>{row.team_display}</td>
                                        <td style={{ padding: '3px 4px', textAlign: 'center', color: '#333' }}>{row.played}</td>
                                        <td style={{ padding: '3px 4px', textAlign: 'center', color: '#333' }}>
                                          {row.wins}-{row.losses}
                                        </td>
                                        <td style={{ padding: '3px 4px', textAlign: 'center', color: row.set_diff >= 0 ? '#2e7d32' : '#c62828' }}>
                                          {row.set_diff >= 0 ? '+' : ''}{row.set_diff}
                                        </td>
                                        <td style={{ padding: '3px 4px', textAlign: 'center', color: row.game_diff >= 0 ? '#2e7d32' : '#c62828' }}>
                                          {row.game_diff >= 0 ? '+' : ''}{row.game_diff}
                                        </td>
                                        <td style={{ padding: '3px 4px', color: '#666' }}>{row.rank_explanation}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              <div style={{ marginTop: 5, fontSize: 9, color: '#78909c' }}>
                                {se.tiebreak_notes}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  )}
                </div>
              )
            })()}
              </div>
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
            {(() => {
              const isWf14Loser = confirmEvt.pools.some(p => p.pool_label === 'POOLC' || p.pool_label === 'POOLD')
              return (
                <>
                  <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#1a237e' }}>
                    {isWf14Loser ? 'Split Division III Pools' : 'Confirm Pool Placement'}
                  </h3>
                  <p style={{ fontSize: 11, color: '#555', margin: '0 0 12px' }}>
                    {isWf14Loser ? (
                      <>Split the 6 WF Round-1 losers into Division III (Pool C / Pool D) for{' '}
                      <strong>{confirmEvt.event_name}</strong>? This assigns them to their pool and
                      placement match slots.</>
                    ) : (
                      <>Place teams into RR pools for <strong>{confirmEvt.event_name}</strong>?
                      This will assign teams to all RR match slots.</>
                    )}
                  </p>
                </>
              )
            })()}
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
  const [day1MaxMatches, setDay1MaxMatches] = useState<number | null>(null)
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
      setDay1MaxMatches(resp.day1_match_count)
      setStep('rebuild_preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed')
    } finally {
      setRbLoading(false)
    }
  }

  const handleRebuildPreviewWithOverride = async (maxMatches: number) => {
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
        day1_max_matches: maxMatches,
      })
      setRbPreview(resp)
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
        day1_max_matches: day1MaxMatches ?? undefined,
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

            {/* Day split summary */}
            {rbPreview && day1MaxMatches !== null && (
              <div style={{
                padding: '10px 14px',
                backgroundColor: '#fff3e0',
                borderRadius: 6,
                border: '1px solid #ffe0b2',
                marginBottom: 12,
                fontSize: 13,
                fontWeight: 600,
                display: 'flex',
                justifyContent: 'space-between',
              }}>
                <span>
                  Day 1: {rbPreview.matches.filter(m => m.assigned_day === rbPreview.per_day[0]?.date).length} matches
                  {' | '}
                  Day 2: {rbPreview.matches.filter(m => m.assigned_day === rbPreview.per_day[1]?.date).length} matches
                </span>
              </div>
            )}

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
                      <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #ddd' }}>Day</th>
                      <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #ddd' }}>Time</th>
                      <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #ddd' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rbPreview.matches.map((m: RebuildMatchItem, index: number) => (
                      <React.Fragment key={m.match_id}>
                        {/* Red divider line between Day 1 and Day 2 */}
                        {index === (day1MaxMatches ?? rbPreview.day1_match_count) && (
                          <tr style={{ height: 36 }}>
                            <td colSpan={7} style={{ padding: 0, position: 'relative' }}>
                              <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: 12,
                                padding: '4px 0',
                                backgroundColor: '#ffebee',
                                borderTop: '3px solid #c62828',
                                borderBottom: '3px solid #c62828',
                                cursor: 'ns-resize',
                                userSelect: 'none',
                              }}>
                                <button
                                  onClick={() => {
                                    const newMax = Math.max(1, (day1MaxMatches ?? rbPreview.day1_match_count) - 1)
                                    setDay1MaxMatches(newMax)
                                    handleRebuildPreviewWithOverride(newMax)
                                  }}
                                  style={{
                                    padding: '2px 12px',
                                    fontSize: 16,
                                    fontWeight: 700,
                                    backgroundColor: '#c62828',
                                    color: '#fff',
                                    border: 'none',
                                    borderRadius: 4,
                                    cursor: 'pointer',
                                  }}
                                  title="Move matches from Day 1 to Day 2"
                                >
                                  ▲ Move to Day 2
                                </button>
                                <span style={{
                                  fontSize: 12,
                                  fontWeight: 700,
                                  color: '#c62828',
                                }}>
                                  — Day Break —
                                </span>
                                <button
                                  onClick={() => {
                                    const newMax = Math.min(
                                      rbPreview.remaining_matches,
                                      (day1MaxMatches ?? rbPreview.day1_match_count) + 1
                                    )
                                    setDay1MaxMatches(newMax)
                                    handleRebuildPreviewWithOverride(newMax)
                                  }}
                                  style={{
                                    padding: '2px 12px',
                                    fontSize: 16,
                                    fontWeight: 700,
                                    backgroundColor: '#c62828',
                                    color: '#fff',
                                    border: 'none',
                                    borderRadius: 4,
                                    cursor: 'pointer',
                                  }}
                                  title="Move matches from Day 2 to Day 1"
                                >
                                  ▼ Move to Day 1
                                </button>
                              </div>
                            </td>
                          </tr>
                        )}
                        {/* Regular match row */}
                        <tr style={{
                          borderBottom: '1px solid #f0f0f0',
                          backgroundColor: m.status === 'IN_PROGRESS' ? '#fff3e0' : m.assigned_day ? undefined : '#ffebee',
                        }}>
                          <td style={{ padding: '4px 8px', textAlign: 'center', color: '#888' }}>{m.rank}</td>
                          <td style={{ padding: '4px 8px', fontWeight: 600 }}>{m.match_code}</td>
                          <td style={{ padding: '4px 8px', color: '#555' }}>{m.event_name} ({m.stage})</td>
                          <td style={{ padding: '4px 8px' }}>{m.team1} vs {m.team2}</td>
                          <td style={{ padding: '4px 8px', textAlign: 'center', fontWeight: 600, color: m.assigned_day ? '#1a237e' : '#c62828' }}>
                            {m.assigned_day || '\u2014'}
                          </td>
                          <td style={{ padding: '4px 8px', textAlign: 'center', color: '#555' }}>
                            {m.assigned_time || '\u2014'}
                          </td>
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
                      </React.Fragment>
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
                onClick={() => { setStep('setup'); setRbPreview(null); setDay1MaxMatches(null) }}
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

function DroppableCell({
  slotId,
  children,
  baseBackgroundColor = '#fff',
}: {
  slotId: number
  children: React.ReactNode
  baseBackgroundColor?: string
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${slotId}` })
  return (
    <td
      ref={setNodeRef}
      style={{
        padding: 3,
        borderBottom: '1px solid #eee',
        borderRight: '1px solid #f0f0f0',
        backgroundColor: isOver ? '#e8f5e9' : baseBackgroundColor,
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
  const [deleteSlotOpen, setDeleteSlotOpen] = useState(false)
  const [addCourtOpen, setAddCourtOpen] = useState(false)
  const [manageCourtOpen, setManageCourtOpen] = useState(false)
  const [allCourtLabels, setAllCourtLabels] = useState<string[]>([])
  const [gridToast, setGridToast] = useState<string | null>(null)

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // Build grid data from slots and matches – one section per day, each with its own courts
  const { days, matchBySlot, dayDataList } = useMemo(() => {
    const slots = data.slots || []
    const matchMap = new Map<number, DeskMatchItem>()
    for (const m of data.matches) {
      if (m.slot_id != null) matchMap.set(m.slot_id, m)
    }

    const daySet = new Set<string>()
    for (const s of slots) daySet.add(s.day_date)
    const sortedDays = [...daySet].sort()

    const dayDataList = sortedDays.map(day => {
      // Courts for this specific day (from actual slots)
      const courtNumMap = new Map<number, string>()
      for (const s of slots) {
        if (s.day_date === day) courtNumMap.set(s.court_number, s.court_label)
      }
      // Augment with configured courts that have no slots yet on this day
      if (courtNumMap.size > 0) {
        allCourtLabels.forEach((label, idx) => {
          const cn = idx + 1
          if (!courtNumMap.has(cn)) courtNumMap.set(cn, label)
        })
      }

      const courtNumbers = [...courtNumMap.keys()].sort((a, b) => a - b)
      const courtLabels: Record<number, string> = {}
      for (const [cn, lbl] of courtNumMap) courtLabels[cn] = lbl

      // Time rows for this day
      const timeRowMap = new Map<string, Map<number, SnapshotSlot>>()
      for (const s of slots) {
        if (s.day_date !== day) continue
        if (!timeRowMap.has(s.start_time)) timeRowMap.set(s.start_time, new Map())
        timeRowMap.get(s.start_time)!.set(s.court_number, s)
      }
      const timeRows = [...timeRowMap.keys()].sort().map(t => ({
        time: t,
        slotsByCourt: timeRowMap.get(t)!,
      }))

      return { day, courtNumbers, courtLabels, timeRows }
    })

    return { days: sortedDays, matchBySlot: matchMap, dayDataList }
  }, [data.slots, data.matches, allCourtLabels])

  useEffect(() => {
    if (days.length > 0 && !selectedDay) {
      setSelectedDay(days[0])
    }
  }, [days, selectedDay])

  // Global court list for modals (all configured courts across all days)
  const courtNumbers = useMemo(
    () => allCourtLabels.map((_, idx) => idx + 1),
    [allCourtLabels]
  )
  const courtLabels = useMemo(() => {
    const labels: Record<number, string> = {}
    allCourtLabels.forEach((label, idx) => { labels[idx + 1] = label })
    return labels
  }, [allCourtLabels])

  const formatErrMsg = (raw: any, fallback: string) => {
    const detail = raw?.detail ?? raw?.message
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d: any) => {
        if (typeof d === 'string') return d
        if (d?.msg) return String(d.msg)
        return JSON.stringify(d)
      }).join('; ')
    }
    if (detail && typeof detail === 'object') {
      if (typeof detail.msg === 'string') return detail.msg
      return JSON.stringify(detail)
    }
    if (raw && typeof raw === 'object') {
      if (typeof raw.msg === 'string') return raw.msg
      return JSON.stringify(raw)
    }
    if (typeof raw === 'string') return raw
    return fallback
  }

  const showToast = (msg: any) => {
    const text = typeof msg === 'string' ? msg : formatErrMsg(msg, 'Unexpected error')
    setGridToast(text)
    setTimeout(() => setGridToast(null), 3000)
  }

  const loadAllCourts = useCallback(async () => {
    try {
      const t = await getTournament(tid)
      const names = Array.isArray((t as any)?.court_names)
        ? ((t as any).court_names as string[])
        : []
      setAllCourtLabels(names)
    } catch {
      setAllCourtLabels([])
    }
  }, [tid])

  useEffect(() => {
    loadAllCourts()
  }, [loadAllCourts])

  useEffect(() => {
    if (manageCourtOpen) {
      loadAllCourts()
    }
  }, [manageCourtOpen, loadAllCourts])

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

  const handleDeleteSlot = async (dayDate: string, startTime: string, courtNums: number[]) => {
    try {
      const resp = await deskDeleteSlots(tid, {
        version_id: data.version_id,
        day_date: dayDate,
        start_time: startTime,
        court_numbers: courtNums,
      })
      const deleted = resp.deleted_slots.length
      const blocked = resp.blocked_slots.length
      if (deleted === 0 && blocked === 0) {
        showToast('No matching slots found')
      } else if (deleted > 0 && blocked > 0) {
        showToast(`Deleted ${deleted} slot(s); skipped ${blocked} assigned slot(s)`)
      } else if (deleted > 0) {
        showToast(`Deleted ${deleted} slot(s)`)
      } else {
        showToast(`Could not delete: ${blocked} slot(s) have assigned matches`)
      }
      setDeleteSlotOpen(false)
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err?.message || 'Failed to delete slot')
    }
  }

  const handleAddCourt = async (courtLabel: string) => {
    try {
      await deskAddCourt(tid, {
        version_id: data.version_id,
        court_label: courtLabel,
        create_matching_slots: true,
      })
      showToast(`Court "${courtLabel}" added`)
      setAddCourtOpen(false)
      await loadAllCourts()
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err || 'Failed to add court')
    }
  }

  const handleFillCourtSlots = async (courtLabel: string) => {
    try {
      const resp = await deskFillCourtSlots(tid, courtLabel, { version_id: data.version_id })
      if (resp.created_slots > 0) {
        showToast(`Created ${resp.created_slots} open slot(s) for Court ${courtLabel}`)
      } else {
        showToast(`No missing slots found for Court ${courtLabel}`)
      }
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err || 'Failed to create slots')
    }
  }

  const handleRemapCourts = async (mapping: Record<string, number>) => {
    try {
      const resp = await deskRemapCourts(tid, {
        version_id: data.version_id,
        mapping,
      })
      showToast(`Remapped ${resp.remapped_slots} slot(s) across all events`)
      await loadAllCourts()
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err || 'Failed to remap courts')
    }
  }

  const handleRenameCourt = async (oldLabel: string, newLabel: string) => {
    try {
      await deskUpdateCourt(tid, oldLabel, {
        version_id: data.version_id,
        new_court_label: newLabel,
      })
      showToast(`Renamed "${oldLabel}" to "${newLabel}"`)
      await loadAllCourts()
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err || 'Failed to rename court')
    }
  }

  const handleDeleteCourt = async (courtLabel: string, deleteMatchingSlots: boolean) => {
    try {
      const resp = await deskDeleteCourt(tid, courtLabel, {
        version_id: data.version_id,
        delete_matching_slots: deleteMatchingSlots,
      })
      showToast(
        resp.removed_slots > 0
          ? `Deleted court "${courtLabel}" and ${resp.removed_slots} slot(s)`
          : `Deleted court "${courtLabel}"`
      )
      await loadAllCourts()
      onRefresh()
    } catch (err: any) {
      showToast(err?.detail || err || 'Failed to delete court')
    }
  }

  const slotCountByCourtLabel = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const s of data.slots || []) {
      const lbl = (s.court_label || '').trim()
      if (!lbl) continue
      counts[lbl] = (counts[lbl] || 0) + 1
    }
    return counts
  }, [data.slots])

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
              onClick={() => {
                setSelectedDay(d)
                document.getElementById(`desk-grid-day-${d}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
              style={{
                padding: '5px 14px',
                fontSize: 12,
                fontWeight: 600,
                border: '1px solid #c5cae9',
                borderRadius: 4,
                backgroundColor: '#fff',
                color: '#1a237e',
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
              onClick={() => setDeleteSlotOpen(true)}
              style={{
                padding: '5px 12px',
                fontSize: 11,
                fontWeight: 600,
                border: '1px solid #e53935',
                borderRadius: 4,
                backgroundColor: '#ffebee',
                color: '#c62828',
                cursor: 'pointer',
              }}
            >
              - Time Slot
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
            <button
              onClick={() => setManageCourtOpen(true)}
              style={{
                padding: '5px 12px',
                fontSize: 11,
                fontWeight: 600,
                border: '1px solid #6a1b9a',
                borderRadius: 4,
                backgroundColor: '#f3e5f5',
                color: '#6a1b9a',
                cursor: 'pointer',
              }}
            >
              Edit/Delete Court
            </button>
          </div>
        )}
      </div>

      {/* Grid – all days stacked, drag across days within one DndContext */}
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        {dayDataList.map(({ day, courtNumbers, courtLabels, timeRows }) => (
          <div key={day} id={`desk-grid-day-${day}`} style={{ marginBottom: 32 }}>
            {/* Day header */}
            <div style={{
              padding: '8px 16px',
              background: '#1a237e',
              color: '#fff',
              borderRadius: '6px 6px 0 0',
              fontWeight: 700,
              fontSize: 13,
              letterSpacing: 0.4,
            }}>
              {dayLabel(day)}
            </div>

            <div style={{ overflowX: 'auto', border: '1px solid #c5cae9', borderTop: 'none', borderRadius: '0 0 6px 6px' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: 11, width: '100%' }}>
                <thead>
                  <tr>
                    <th style={{
                      position: 'sticky',
                      left: 0,
                      background: '#1a237e',
                      color: '#fff',
                      padding: '6px 8px',
                      textAlign: 'left',
                      borderBottom: '2px solid #1a237e',
                      minWidth: 70,
                      zIndex: 2,
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
                      }}>
                        Court {courtLabels[cn] || cn}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {timeRows.map((row, rowIndex) => {
                    const rowTint = getSlotTint(rowIndex)
                    const rowHeaderBg = rowTint?.accent || '#546e7a'
                    const rowCellBg = rowTint?.bg || '#fff'
                    return (
                      <tr key={row.time}>
                        <td style={{
                          position: 'sticky',
                          left: 0,
                          background: rowHeaderBg,
                          padding: '6px',
                          borderBottom: '1px solid #eee',
                          fontWeight: 600,
                          whiteSpace: 'nowrap',
                          zIndex: 1,
                          fontSize: 11,
                          color: '#fff',
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
                                backgroundColor: rowCellBg,
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
                            <DroppableCell key={cn} slotId={slot.slot_id} baseBackgroundColor={rowCellBg}>
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
                    )
                  })}
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
          </div>
        ))}

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

      {/* Delete Time Slot Modal */}
      {deleteSlotOpen && (
        <DeleteTimeSlotModal
          days={days}
          courtNumbers={courtNumbers}
          courtLabels={courtLabels}
          onClose={() => setDeleteSlotOpen(false)}
          onSubmit={handleDeleteSlot}
        />
      )}

      {/* Add Court Modal */}
      {addCourtOpen && (
        <AddCourtModal
          onClose={() => setAddCourtOpen(false)}
          onSubmit={handleAddCourt}
        />
      )}

      {/* Manage Courts Modal */}
      {manageCourtOpen && (
        <ManageCourtsModal
          courts={allCourtLabels}
          slotCountByCourtLabel={slotCountByCourtLabel}
          onClose={() => setManageCourtOpen(false)}
          onRemap={handleRemapCourts}
          onRename={handleRenameCourt}
          onDelete={handleDeleteCourt}
          onFillSlots={handleFillCourtSlots}
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


// ── Delete Time Slot Modal ───────────────────────────────────────────────

function DeleteTimeSlotModal({
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
  onSubmit: (dayDate: string, startTime: string, courtNums: number[]) => void
}) {
  const [day, setDay] = useState(days[0] || '')
  const [startTime, setStartTime] = useState('09:00')
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
          <div style={{ fontWeight: 700, fontSize: 15 }}>Delete Time Slot</div>
        </div>
        <div style={{ padding: '16px 20px' }}>
          <div style={{ marginBottom: 10, fontSize: 12, color: '#666' }}>
            Deletes unassigned slots for the selected day/time/courts.
            Assigned slots will be skipped for safety.
          </div>
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
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Start Time</label>
            <input
              type="time"
              value={startTime}
              onChange={e => setStartTime(e.target.value)}
              style={{ width: '100%', padding: '6px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4, boxSizing: 'border-box' }}
            />
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
              onSubmit(day, startTime, selectedCourts)
            }}
            style={{ padding: '6px 16px', fontSize: 12, fontWeight: 600, border: 'none', borderRadius: 4, backgroundColor: '#c62828', color: '#fff', cursor: 'pointer' }}
          >
            Delete Slot
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
  onSubmit: (courtLabel: string) => void
}) {
  const [label, setLabel] = useState('')

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
          <div style={{ fontSize: 11, color: '#2e7d32', fontWeight: 600 }}>
            Matching open slots will be created automatically.
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
              if (!label.trim()) return
              onSubmit(label.trim())
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


// ── Manage Courts Modal ────────────────────────────────────────────────

function ManageCourtsModal({
  courts,
  slotCountByCourtLabel,
  onClose,
  onRemap,
  onRename,
  onDelete,
  onFillSlots,
}: {
  courts: string[]
  slotCountByCourtLabel: Record<string, number>
  onClose: () => void
  onRemap: (mapping: Record<string, number>) => Promise<void> | void
  onRename: (oldLabel: string, newLabel: string) => Promise<void> | void
  onDelete: (courtLabel: string, deleteMatchingSlots: boolean) => Promise<void> | void
  onFillSlots: (courtLabel: string) => Promise<void> | void
}) {
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({})
  const [busyLabel, setBusyLabel] = useState<string | null>(null)
  const [deleteWithSlots, setDeleteWithSlots] = useState(false)
  const [remapText, setRemapText] = useState('')

  const sortedCourts = [...courts]

  return (
    <>
      <div onClick={onClose} style={{
        position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
        backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 1999,
      }} />
      <div style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
        width: 620, maxWidth: '92vw', backgroundColor: '#fff', borderRadius: 10,
        boxShadow: '0 8px 30px rgba(0,0,0,0.3)', zIndex: 2000, overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0' }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Manage Courts</div>
          <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
            Rename or delete any court. Deleting a court shifts higher-numbered courts down in this draft.
          </div>
        </div>
        <div style={{ padding: '12px 20px', maxHeight: '60vh', overflowY: 'auto' }}>
          <div style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid #e0e0e0', borderRadius: 6, backgroundColor: '#fafafa' }}>
            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6, color: '#1a237e' }}>Global Court Number Remap (all events)</div>
            <div style={{ fontSize: 11, color: '#666', marginBottom: 6 }}>
              Format: <code>1:15,2:16,3:17</code> (applies to this draft version only; draws/matches unchanged)
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="text"
                value={remapText}
                onChange={e => setRemapText(e.target.value)}
                placeholder="e.g. 1:15,2:16,3:17,4:18"
                style={{ flex: 1, padding: '6px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4 }}
              />
              <button
                disabled={!remapText.trim() || busyLabel === '__remap__'}
                onClick={async () => {
                  const txt = remapText.trim()
                  const mapping: Record<string, number> = {}
                  for (const piece of txt.split(',').map(s => s.trim()).filter(Boolean)) {
                    const [oldRaw, newRaw] = piece.split(':').map(s => s.trim())
                    const oldNum = Number(oldRaw)
                    const newNum = Number(newRaw)
                    if (!Number.isInteger(oldNum) || oldNum <= 0 || !Number.isInteger(newNum) || newNum <= 0) {
                      window.alert(`Invalid mapping item: "${piece}". Use old:new with positive integers.`)
                      return
                    }
                    mapping[String(oldNum)] = newNum
                  }
                  if (Object.keys(mapping).length === 0) return
                  const ok = window.confirm(`Apply global court remap to this draft schedule?\n\n${txt}`)
                  if (!ok) return
                  setBusyLabel('__remap__')
                  try {
                    await onRemap(mapping)
                  } finally {
                    setBusyLabel(null)
                  }
                }}
                style={{
                  padding: '6px 10px', fontSize: 11, fontWeight: 700,
                  border: '1px solid #e65100', borderRadius: 4,
                  backgroundColor: '#fff3e0', color: '#e65100', cursor: 'pointer',
                }}
              >
                {busyLabel === '__remap__' ? 'Applying...' : 'Apply Remap'}
              </button>
            </div>
          </div>
          {sortedCourts.length === 0 ? (
            <div style={{ fontSize: 12, color: '#999' }}>No courts found.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ backgroundColor: '#f5f5f5' }}>
                  <th style={{ textAlign: 'left', padding: '8px 6px', borderBottom: '1px solid #ddd' }}>#</th>
                  <th style={{ textAlign: 'left', padding: '8px 6px', borderBottom: '1px solid #ddd' }}>Current Label</th>
                  <th style={{ textAlign: 'left', padding: '8px 6px', borderBottom: '1px solid #ddd' }}>Slots</th>
                  <th style={{ textAlign: 'left', padding: '8px 6px', borderBottom: '1px solid #ddd' }}>Rename</th>
                  <th style={{ textAlign: 'center', padding: '8px 6px', borderBottom: '1px solid #ddd' }}>Slots</th>
                  <th style={{ textAlign: 'right', padding: '8px 6px', borderBottom: '1px solid #ddd' }}>Delete</th>
                </tr>
              </thead>
              <tbody>
                {sortedCourts.map((label, idx) => {
                  const draft = renameDrafts[label] ?? label
                  const slotCount = slotCountByCourtLabel[label] || 0
                  const rowBusy = busyLabel === label
                  return (
                    <tr key={label}>
                      <td style={{ padding: '8px 6px', borderBottom: '1px solid #f0f0f0' }}>{idx + 1}</td>
                      <td style={{ padding: '8px 6px', borderBottom: '1px solid #f0f0f0', fontWeight: 600 }}>
                        Court {label}
                      </td>
                      <td style={{ padding: '8px 6px', borderBottom: '1px solid #f0f0f0', color: '#666' }}>
                        {slotCount}
                      </td>
                      <td style={{ padding: '8px 6px', borderBottom: '1px solid #f0f0f0' }}>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <input
                            type="text"
                            value={draft}
                            onChange={e => setRenameDrafts(prev => ({ ...prev, [label]: e.target.value }))}
                            style={{
                              flex: 1, padding: '5px 8px', fontSize: 12,
                              border: '1px solid #ccc', borderRadius: 4,
                            }}
                          />
                          <button
                            disabled={rowBusy || !draft.trim() || draft.trim() === label}
                            onClick={async () => {
                              setBusyLabel(label)
                              try {
                                await onRename(label, draft.trim())
                              } finally {
                                setBusyLabel(null)
                              }
                            }}
                            style={{
                              padding: '5px 10px', fontSize: 11, fontWeight: 600,
                              border: '1px solid #1565c0', borderRadius: 4,
                              backgroundColor: '#e3f2fd', color: '#1565c0',
                              cursor: 'pointer',
                            }}
                          >
                            Rename
                          </button>
                        </div>
                      </td>
                      <td style={{ padding: '8px 6px', borderBottom: '1px solid #f0f0f0', textAlign: 'center' }}>
                        <button
                          disabled={rowBusy}
                          onClick={async () => {
                            setBusyLabel(label)
                            try {
                              await onFillSlots(label)
                            } finally {
                              setBusyLabel(null)
                            }
                          }}
                          style={{
                            padding: '5px 10px', fontSize: 11, fontWeight: 600,
                            border: '1px solid #2e7d32', borderRadius: 4,
                            backgroundColor: '#e8f5e9', color: '#2e7d32',
                            cursor: 'pointer',
                          }}
                        >
                          Create Slots
                        </button>
                      </td>
                      <td style={{ padding: '8px 6px', borderBottom: '1px solid #f0f0f0', textAlign: 'right' }}>
                        <button
                          disabled={rowBusy}
                          title="Delete court"
                          onClick={async () => {
                            const suffix = deleteWithSlots
                              ? ' This will also delete unassigned slots on this court.'
                              : ''
                            const ok = window.confirm(`Delete Court "${label}"?${suffix}`)
                            if (!ok) return
                            setBusyLabel(label)
                            try {
                              await onDelete(label, deleteWithSlots)
                            } finally {
                              setBusyLabel(null)
                            }
                          }}
                          style={{
                            padding: '5px 10px', fontSize: 11, fontWeight: 600,
                            border: '1px solid #c62828', borderRadius: 4,
                            backgroundColor: '#ffebee',
                            color: '#c62828',
                            cursor: 'pointer',
                          }}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 11, color: '#555' }}>
            <input
              type="checkbox"
              checked={deleteWithSlots}
              onChange={e => setDeleteWithSlots(e.target.checked)}
            />
            When deleting a court, also remove its matching slots
          </label>
        </div>
        <div style={{
          padding: '12px 20px', borderTop: '1px solid #e0e0e0',
          display: 'flex', justifyContent: 'flex-end',
        }}>
          <button
            onClick={onClose}
            style={{ padding: '6px 16px', fontSize: 12, fontWeight: 600, border: '1px solid #ccc', borderRadius: 4, backgroundColor: '#fff', cursor: 'pointer' }}
          >
            Close
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
      // Keep all desk tabs in sync (courts/schedule/grid use snapshot data).
      onRefresh()
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
      <div style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
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


// ── SMS Admin Tab ──────────────────────────────────────────────────────

type SmsScope = 'blast' | 'event' | 'division' | 'team' | 'player' | 'match'

type SmsQuickTargetPrefill = {
  scope: 'team' | 'match'
  targetId: number
  matchPhase?: 'upcoming' | 'completed'
}

function formatEventScopeLabel(event: Event): string {
  const categoryPrefix = event.category === 'womens' ? "Women's" : 'Mixed'
  const name = (event.name || '').trim()
  const lower = name.toLowerCase()
  if (lower.startsWith('mixed') || lower.startsWith('women')) {
    return name
  }
  return `${categoryPrefix} ${name}`.trim()
}

// ── Text List Tab ───────────────────────────────────────────────────────

function TextListTab({ tournamentId }: { tournamentId: number }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [phoneLists, setPhoneLists] = useState<SmsPhoneList[]>([])
  const [newPhoneListName, setNewPhoneListName] = useState('')
  const [phoneListImportText, setPhoneListImportText] = useState('')
  const [selectedPhoneListId, setSelectedPhoneListId] = useState('')
  const [savingPhoneList, setSavingPhoneList] = useState(false)
  const [importingPhoneList, setImportingPhoneList] = useState(false)
  const [renamingPhoneListId, setRenamingPhoneListId] = useState<number | null>(null)
  const [deletingPhoneListId, setDeletingPhoneListId] = useState<number | null>(null)

  const [settingsDraft, setSettingsDraft] = useState<SmsSettingsResponse | null>(null)
  const textsEnabled = Boolean(settingsDraft?.texts_enabled)

  const [message, setMessage] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [preview, setPreview] = useState<SmsPreviewResponse | null>(null)
  const [sendResult, setSendResult] = useState<SmsSendResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [sending, setSending] = useState(false)

  const confirmOk = confirmText.trim().toUpperCase() === 'SEND'
  const hasValidTarget = Boolean(selectedPhoneListId)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [phoneListRows, settingsResp] = await Promise.all([
        getSmsPhoneLists(tournamentId),
        getSmsSettings(tournamentId),
      ])
      setPhoneLists(phoneListRows)
      setSettingsDraft(settingsResp)
      setSelectedPhoneListId(prev => {
        if (prev && phoneListRows.some(row => String(row.id) === prev)) return prev
        return phoneListRows[0] ? String(phoneListRows[0].id) : ''
      })
    } catch (e: any) {
      setError(e?.message || 'Failed to load text lists')
    } finally {
      setLoading(false)
    }
  }, [tournamentId])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const handleCreatePhoneList = async () => {
    if (!newPhoneListName.trim()) {
      setError('List name is required')
      return
    }
    setSavingPhoneList(true)
    setError(null)
    try {
      const created = await createSmsPhoneList(tournamentId, { name: newPhoneListName.trim() })
      setPhoneLists(prev => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setSelectedPhoneListId(String(created.id))
      setNewPhoneListName('')
    } catch (e: any) {
      setError(e?.message || 'Failed to create phone list')
    } finally {
      setSavingPhoneList(false)
    }
  }

  const handleImportPhoneList = async () => {
    const phoneListId = parseInt(selectedPhoneListId, 10)
    if (!Number.isFinite(phoneListId) || phoneListId <= 0) {
      setError('Choose a phone list first')
      return
    }
    if (!phoneListImportText.trim()) {
      setError('Paste phone rows to import')
      return
    }
    setImportingPhoneList(true)
    setError(null)
    try {
      const resp = await importSmsPhoneList(tournamentId, phoneListId, { raw_text: phoneListImportText })
      setPhoneLists(prev => prev.map(list => (list.id === resp.phone_list.id ? resp.phone_list : list)))
      setPhoneListImportText('')
      if (resp.rejected_rows.length > 0) {
        setError(resp.rejected_rows.map(row => `Line ${row.line}: ${row.reason}`).join('\n'))
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to import phone list')
    } finally {
      setImportingPhoneList(false)
    }
  }

  const handleRenamePhoneList = async (phoneListId: number, nextName: string) => {
    const trimmed = nextName.trim()
    if (!trimmed) {
      setError('List name is required')
      return
    }
    setRenamingPhoneListId(phoneListId)
    setError(null)
    try {
      const updated = await renameSmsPhoneList(tournamentId, phoneListId, { name: trimmed })
      setPhoneLists(prev => prev.map(list => (list.id === phoneListId ? updated : list)))
    } catch (e: any) {
      setError(e?.message || 'Failed to rename phone list')
    } finally {
      setRenamingPhoneListId(null)
    }
  }

  const handleDeletePhoneList = async (phoneListId: number) => {
    setDeletingPhoneListId(phoneListId)
    setError(null)
    try {
      await deleteSmsPhoneList(tournamentId, phoneListId)
      setPhoneLists(prev => prev.filter(list => list.id !== phoneListId))
      setSelectedPhoneListId(prev => (prev === String(phoneListId) ? '' : prev))
    } catch (e: any) {
      setError(e?.message || 'Failed to delete phone list')
    } finally {
      setDeletingPhoneListId(null)
    }
  }

  const handlePreview = async () => {
    if (!message.trim()) {
      setError('Message is required for preview')
      return
    }
    const phoneListId = parseInt(selectedPhoneListId, 10)
    if (!Number.isFinite(phoneListId) || phoneListId <= 0) {
      setError('Choose a text list first')
      return
    }
    setPreviewing(true)
    setError(null)
    try {
      const resp = await previewSmsPhoneList(tournamentId, phoneListId, { message })
      setPreview(resp)
      setSendResult(null)
    } catch (e: any) {
      setError(e?.message || 'Preview failed')
    } finally {
      setPreviewing(false)
    }
  }

  const handleSend = async () => {
    if (!message.trim()) {
      setError('Message is required to send')
      return
    }
    if (!hasValidTarget) {
      setError('Choose a text list first')
      return
    }
    if (!confirmOk) {
      setError('Type SEND to confirm broad-audience send')
      return
    }
    const phoneListId = parseInt(selectedPhoneListId, 10)
    if (!Number.isFinite(phoneListId) || phoneListId <= 0) {
      setError('Choose a text list first')
      return
    }
    setSending(true)
    setError(null)
    try {
      const resp = await sendSmsPhoneList(tournamentId, phoneListId, { message })
      setSendResult(resp)
    } catch (e: any) {
      setError(e?.message || 'Send failed')
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 24, fontSize: 14, color: '#666' }}>
        Loading…
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#333', margin: '0 0 4px 0' }}>
          Text List
        </h2>
        <div style={{ fontSize: 13, color: '#666' }}>
          Named phone lists for one-off blasts. Manage lists here; sends respect tournament SMS settings (texts on/off, test mode, consent).
        </div>
      </div>

      {error && (
        <div style={{
          padding: 12,
          borderRadius: 6,
          backgroundColor: '#ffebee',
          color: '#b71c1c',
          fontSize: 13,
          whiteSpace: 'pre-wrap',
        }}>
          {error}
        </div>
      )}

      <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff' }}>
        <h3 style={{ marginTop: 0, fontSize: 15 }}>Lists</h3>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 10 }}>
          Create a named list and paste phone numbers. Then preview and send a message to everyone on the selected list.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 320px) minmax(360px, 1fr)', gap: 12, alignItems: 'start' }}>
          <div style={{ display: 'grid', gap: 8 }}>
            <input
              type="text"
              value={newPhoneListName}
              onChange={e => setNewPhoneListName(e.target.value)}
              placeholder="New list name"
              style={{ padding: 7, borderRadius: 4, border: '1px solid #ccc' }}
            />
            <button
              onClick={() => void handleCreatePhoneList()}
              disabled={savingPhoneList || !newPhoneListName.trim()}
              style={{ padding: '7px 12px', fontSize: 12, cursor: 'pointer', justifySelf: 'start' }}
            >
              {savingPhoneList ? 'Creating…' : 'Create List'}
            </button>

            <select
              value={selectedPhoneListId}
              onChange={e => setSelectedPhoneListId(e.target.value)}
              style={{ padding: 7, borderRadius: 4, border: '1px solid #ccc' }}
            >
              <option value="">Choose list to import into…</option>
              {phoneLists.map(list => (
                <option key={list.id} value={String(list.id)}>
                  {list.name} ({list.member_count})
                </option>
              ))}
            </select>
            <textarea
              value={phoneListImportText}
              onChange={e => setPhoneListImportText(e.target.value)}
              placeholder={'Name\tPhone\nJohn Smith\t9013593035\nJane Doe\t+19015551234'}
              rows={6}
              style={{ width: '100%', boxSizing: 'border-box', padding: 8, borderRadius: 4, border: '1px solid #ccc', fontFamily: 'monospace', fontSize: 12 }}
            />
            <button
              onClick={() => void handleImportPhoneList()}
              disabled={importingPhoneList || !selectedPhoneListId || !phoneListImportText.trim()}
              style={{ padding: '7px 12px', fontSize: 12, cursor: 'pointer', justifySelf: 'start' }}
            >
              {importingPhoneList ? 'Importing…' : 'Replace List Members'}
            </button>
            <div style={{ fontSize: 11, color: '#777' }}>
              Paste one phone per line, or `Name` + `Phone` tab-separated. Numbers are normalized to E.164 automatically.
            </div>
          </div>

          <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid #eee', borderRadius: 6 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ backgroundColor: '#fafafa' }}>
                  <th style={{ textAlign: 'left', padding: 6 }}>List</th>
                  <th style={{ textAlign: 'center', padding: 6, width: 80 }}>Members</th>
                  <th style={{ textAlign: 'left', padding: 6 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {phoneLists.length === 0 ? (
                  <tr>
                    <td colSpan={3} style={{ padding: 10, color: '#777', fontStyle: 'italic' }}>
                      No lists yet.
                    </td>
                  </tr>
                ) : phoneLists.map(list => (
                  <tr key={list.id} style={{ borderTop: '1px solid #f0f0f0' }}>
                    <td style={{ padding: 6 }}>
                      <div style={{ fontWeight: 700 }}>{list.name}</div>
                      <div style={{ fontSize: 11, color: '#777', marginTop: 2 }}>
                        {list.members.slice(0, 2).map(member => member.raw_name || member.phone_number).join(', ')}
                        {list.member_count > 2 ? '…' : ''}
                      </div>
                    </td>
                    <td style={{ padding: 6, textAlign: 'center' }}>{list.member_count}</td>
                    <td style={{ padding: 6 }}>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button
                          onClick={() => {
                            const nextName = window.prompt('Rename list', list.name)
                            if (nextName && nextName.trim() && nextName.trim() !== list.name) {
                              void handleRenamePhoneList(list.id, nextName)
                            }
                          }}
                          disabled={renamingPhoneListId === list.id}
                          style={{ padding: '4px 8px', fontSize: 12, cursor: 'pointer' }}
                        >
                          {renamingPhoneListId === list.id ? 'Renaming…' : 'Rename'}
                        </button>
                        <button
                          onClick={() => void handleDeletePhoneList(list.id)}
                          disabled={deletingPhoneListId === list.id}
                          style={{ padding: '4px 8px', fontSize: 12, cursor: 'pointer', color: '#a12626' }}
                        >
                          {deletingPhoneListId === list.id ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff' }}>
        <h3 style={{ marginTop: 0, fontSize: 15 }}>Preview & send</h3>
        <div style={{ display: 'grid', gap: 10, marginBottom: 10 }}>
          <label style={{ fontSize: 12, color: '#666' }}>Send to list</label>
          <select
            value={selectedPhoneListId}
            onChange={e => setSelectedPhoneListId(e.target.value)}
            style={{ padding: 7, borderRadius: 4, border: '1px solid #ccc', maxWidth: 400 }}
          >
            <option value="">Select list…</option>
            {phoneLists.map(list => (
              <option key={list.id} value={String(list.id)}>
                {list.name} ({list.member_count})
              </option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 10, padding: 10, border: '1px solid #ffe0b2', borderRadius: 6, backgroundColor: '#fff8e1' }}>
          <div style={{ fontSize: 12, color: '#e65100', fontWeight: 700, marginBottom: 6 }}>
            High-impact send: this can notify many recipients.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 8 }}>
            <div style={{ fontSize: 12, color: '#666' }}>
              Confirm intent by typing <strong>SEND</strong> before sending.
            </div>
            <input
              type="text"
              value={confirmText}
              onChange={e => setConfirmText(e.target.value)}
              placeholder="Type SEND"
              style={{ padding: 6, borderRadius: 4, border: `1px solid ${confirmOk ? '#81c784' : '#ffcc80'}` }}
            />
          </div>
        </div>

        {!textsEnabled && (
          <div style={{ marginBottom: 8, padding: 10, border: '1px solid #ffcdd2', borderRadius: 6, backgroundColor: '#ffebee', fontSize: 12, color: '#b71c1c' }}>
            All texts are currently turned off for this tournament. Turn texts on under the SMS tab before sending.
          </div>
        )}

        <textarea
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder="Type message..."
          rows={4}
          style={{ width: '100%', boxSizing: 'border-box', padding: 8, borderRadius: 4, border: '1px solid #ccc', marginBottom: 8 }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => void handlePreview()} disabled={previewing || sending || !textsEnabled} style={{ padding: '7px 14px', fontWeight: 600, cursor: 'pointer' }}>
            {previewing ? 'Previewing…' : 'Preview'}
          </button>
          <button
            onClick={() => void handleSend()}
            disabled={sending || previewing || !textsEnabled || !message.trim() || !hasValidTarget || !confirmOk}
            style={{
              padding: '7px 14px',
              fontWeight: 700,
              backgroundColor: (sending || previewing || !textsEnabled || !message.trim() || !hasValidTarget || !confirmOk) ? '#9fa8da' : '#1a237e',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: (sending || previewing || !textsEnabled || !message.trim() || !hasValidTarget || !confirmOk) ? 'not-allowed' : 'pointer',
            }}
          >
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>

        {preview && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #e0e0e0', borderRadius: 6, backgroundColor: '#fafafa' }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>Preview:</strong> {preview.total_messages} messages, {preview.teams_without_phone} targets without phone
            </div>
            <div style={{ maxHeight: 160, overflowY: 'auto', fontSize: 12 }}>
              {preview.recipients.slice(0, 25).map((r, idx) => (
                <div key={`${r.team_id ?? 'p'}-${r.player_id ?? idx}`} style={{ padding: '3px 0', borderBottom: '1px dotted #eee' }}>
                  {(r.player_name || r.team_name || 'Recipient')} → {r.phones.join(', ')}
                </div>
              ))}
            </div>
          </div>
        )}

        {sendResult && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #e0e0e0', borderRadius: 6, backgroundColor: '#fafafa' }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>Send result:</strong> sent {sendResult.sent}, failed {sendResult.failed}, no-phone {sendResult.skipped_no_phone}, consent-blocked {sendResult.skipped_consent}, test-blocked {sendResult.skipped_test_mode}, deduped {sendResult.skipped_dedupe}
            </div>
            <div style={{ maxHeight: 180, overflowY: 'auto', fontSize: 12 }}>
              {sendResult.results.slice(0, 25).map((r, idx) => (
                <div key={`${r.phone}-${idx}`} style={{ padding: '3px 0', borderBottom: '1px dotted #eee' }}>
                  {r.phone} — <strong>{r.status}</strong>{r.error ? ` (${r.error})` : ''}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function SmsAdminTab({
  tournamentId,
  quickTarget,
  managementMode,
}: {
  tournamentId: number
  quickTarget?: SmsQuickTargetPrefill | null
  managementMode?: 'court_management' | 'checkin_management'
}) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [scope, setScope] = useState<SmsScope>('team')
  const [targetId, setTargetId] = useState('')
  const [divisionEventId, setDivisionEventId] = useState('')
  const [division, setDivision] = useState('')
  const [divisionChoices, setDivisionChoices] = useState<SmsDivisionLookupItem[]>([])
  const [loadingDivisionChoices, setLoadingDivisionChoices] = useState(false)
  const [message, setMessage] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [preview, setPreview] = useState<SmsPreviewResponse | null>(null)
  const [sendResult, setSendResult] = useState<SmsSendResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [sending, setSending] = useState(false)

  const [status, setStatus] = useState<{
    twilio_configured: boolean
    from_number: string | null
    tournament_has_settings: boolean
    total_teams: number
    teams_with_phones: number
  } | null>(null)
  const [tournamentTimezone, setTournamentTimezone] = useState<string | null>(null)

  const [settingsDraft, setSettingsDraft] = useState<SmsSettingsResponse | null>(null)
  const [savingSettings, setSavingSettings] = useState(false)
  const [syncingPlayerContacts, setSyncingPlayerContacts] = useState(false)
  const [playerSyncSummary, setPlayerSyncSummary] = useState<SmsPlayerSyncResponse | null>(null)
  const [playerAdminNotice, setPlayerAdminNotice] = useState<string | null>(null)

  const [templates, setTemplates] = useState<SmsTemplateResponse[]>([])
  const [templateBodies, setTemplateBodies] = useState<Record<string, string>>({})
  const [savingTemplateType, setSavingTemplateType] = useState<string | null>(null)
  const [applyingTemplateMode, setApplyingTemplateMode] = useState(false)
  const [showTemplates, setShowTemplates] = useState(false)
  const [showAutomationToggles, setShowAutomationToggles] = useState(true)

  const [logs, setLogs] = useState<SmsLogEntry[]>([])
  const [logTypeFilter, setLogTypeFilter] = useState('')
  const [logLimit, setLogLimit] = useState(100)
  const [rolloutHours] = useState(168)
  const [runningReminder, setRunningReminder] = useState(false)
  const [lastReminderRun, setLastReminderRun] = useState<SmsAutomationRunResponse | null>(null)
  const [runningRrReminder, setRunningRrReminder] = useState(false)
  const [lastRrReminderRun, setLastRrReminderRun] = useState<SmsRrAutomationRunResponse | null>(null)
  const [smsTemplateMode, setSmsTemplateMode] = useState<'court_management' | 'checkin_management'>('court_management')
  const [quickTestPhone, setQuickTestPhone] = useState('')
  const activeCheckinTemplateTypes = useMemo(
    () => new Set(['checkin_first_match', 'checkin_rr_first_match', 'checkin_post_match_next']),
    []
  )
  const [savingQuickTestPhone, setSavingQuickTestPhone] = useState(false)
  const [rrMixedEventId, setRrMixedEventId] = useState('')
  const [events, setEvents] = useState<Event[]>([])
  const [players, setPlayers] = useState<SmsPlayerLookupItem[]>([])
  const [matches, setMatches] = useState<SmsMatchLookupItem[]>([])
  const [matchPhase, setMatchPhase] = useState<'upcoming' | 'completed'>('upcoming')
  const [matchSearch, setMatchSearch] = useState('')
  const [loadingMatches, setLoadingMatches] = useState(false)
  const [teams, setTeams] = useState<DeskTeamItem[]>([])
  const [teamSearch, setTeamSearch] = useState('')
  const [playerSearch, setPlayerSearch] = useState('')
  const [wipingPlayers, setWipingPlayers] = useState(false)
  const skipScopeResetRef = useRef(false)
  const skipMatchPhaseTargetResetRef = useRef(false)
  const appliedTemplateDefaultsForTournamentRef = useRef(false)

  const loadStatusAndSettings = useCallback(async () => {
    const [statusResp, settingsResp] = await Promise.all([
      getSmsStatus(tournamentId),
      getSmsSettings(tournamentId),
    ])
    setStatus(statusResp)
    setSettingsDraft(settingsResp)
  }, [tournamentId])

  const loadTemplates = useCallback(async () => {
    const rows = await getSmsTemplates(tournamentId)
    setTemplates(rows)
    const bodies: Record<string, string> = {}
    rows.forEach(t => { bodies[t.message_type] = t.template_body })
    setTemplateBodies(bodies)
  }, [tournamentId])

  const loadLogs = useCallback(async () => {
    const rows = await getSmsLog(tournamentId, {
      limit: logLimit,
      message_type: logTypeFilter || undefined,
    })
    setLogs(rows)
  }, [tournamentId, logLimit, logTypeFilter])

  const loadRolloutMetrics = useCallback(async () => {
    await getSmsRolloutMetrics(tournamentId, rolloutHours)
  }, [tournamentId, rolloutHours])

  const loadTeams = useCallback(async () => {
    const rows = await getDeskTeams(tournamentId)
    setTeams(rows)
  }, [tournamentId])

  const loadMatches = useCallback(async (phase: 'upcoming' | 'completed') => {
    setLoadingMatches(true)
    try {
      const rows = await getSmsMatches(tournamentId, phase)
      setMatches(rows)
    } finally {
      setLoadingMatches(false)
    }
  }, [tournamentId])

  const loadDivisionChoices = useCallback(async (eventId: number) => {
    setLoadingDivisionChoices(true)
    try {
      const rows = await getSmsEventDivisions(tournamentId, eventId)
      setDivisionChoices(rows)
      setDivision(prev => {
        if (prev && rows.some(r => r.division_label === prev)) return prev
        return rows[0]?.division_label || ''
      })
    } finally {
      setLoadingDivisionChoices(false)
    }
  }, [tournamentId])

  const loadLookups = useCallback(async () => {
    const [eventRows, playerRows, tournament] = await Promise.all([
      getEvents(tournamentId),
      getSmsPlayers(tournamentId),
      getTournament(tournamentId),
    ])
    setEvents(eventRows)
    setPlayers(playerRows)
    setTournamentTimezone(tournament.timezone || null)
    if (eventRows.length > 0) {
      const first = eventRows[0]
      setDivisionEventId(prev => prev || String(first.id))
    }
  }, [tournamentId])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      await Promise.all([
        loadStatusAndSettings(),
        loadTemplates(),
        loadLogs(),
        loadTeams(),
        loadLookups(),
        loadMatches('upcoming'),
      ])
    } catch (e: any) {
      setError(e?.message || 'Failed to load SMS admin data')
    } finally {
      setLoading(false)
    }
  }, [loadStatusAndSettings, loadTemplates, loadLogs, loadTeams, loadLookups, loadMatches])

  useEffect(() => { loadAll() }, [loadAll])
  useEffect(() => {
    loadRolloutMetrics().catch((e: any) => {
      setError(e?.message || 'Failed to load rollout metrics')
    })
  }, [loadRolloutMetrics])

  useEffect(() => {
    const key = `desk:sms-template-mode:${tournamentId}`
    const raw = localStorage.getItem(key)
    if (raw === 'court_management' || raw === 'checkin_management') {
      setSmsTemplateMode(raw)
    }
  }, [tournamentId])

  useEffect(() => {
    const key = `desk:sms-template-mode:${tournamentId}`
    localStorage.setItem(key, smsTemplateMode)
  }, [tournamentId, smsTemplateMode])

  const parseTargetId = (): number | null => {
    const n = parseInt(targetId, 10)
    return Number.isFinite(n) && n > 0 ? n : null
  }

  const requiresBroadConfirm = scope === 'blast' || scope === 'event' || scope === 'division'
  const hasValidTarget = scope === 'blast'
    ? true
    : scope === 'division'
      ? Boolean(divisionEventId && division.trim())
      : parseTargetId() !== null
  const confirmOk = !requiresBroadConfirm || confirmText.trim().toUpperCase() === 'SEND'

  useEffect(() => {
    setConfirmText('')
    if (skipScopeResetRef.current) {
      skipScopeResetRef.current = false
      return
    }
    setTargetId('')
    if (scope !== 'team') setTeamSearch('')
    if (scope !== 'player') setPlayerSearch('')
    if (scope !== 'match') setMatchSearch('')
  }, [scope])

  useEffect(() => {
    if (!quickTarget) return
    const desiredScope: SmsScope = quickTarget.scope
    const desiredMatchPhase = quickTarget.matchPhase || 'upcoming'
    const willTriggerMatchTargetReset =
      desiredScope === 'match' && (scope !== 'match' || matchPhase !== desiredMatchPhase)
    if (willTriggerMatchTargetReset) {
      skipMatchPhaseTargetResetRef.current = true
    }
    setScope(prev => {
      if (prev !== desiredScope) {
        skipScopeResetRef.current = true
        return desiredScope
      }
      skipScopeResetRef.current = false
      return prev
    })
    setError(null)
    setPreview(null)
    setSendResult(null)
    setConfirmText('')
    setTargetId(String(quickTarget.targetId))
    if (desiredScope === 'team') {
      setTeamSearch('')
    } else {
      setMatchPhase(desiredMatchPhase)
      setMatchSearch('')
    }
  }, [quickTarget])

  useEffect(() => {
    if (scope !== 'match') return
    loadMatches(matchPhase).catch((e: any) => {
      setError(e?.message || 'Failed to load match lookup')
    })
  }, [scope, matchPhase, loadMatches])

  useEffect(() => {
    if (scope === 'match') {
      if (skipMatchPhaseTargetResetRef.current) {
        skipMatchPhaseTargetResetRef.current = false
        return
      }
      setTargetId('')
    }
  }, [matchPhase, scope])

  useEffect(() => {
    if (!divisionEventId) {
      setDivisionChoices([])
      setDivision('')
      return
    }
    const eventId = parseInt(divisionEventId, 10)
    if (!Number.isFinite(eventId) || eventId <= 0) {
      setDivisionChoices([])
      setDivision('')
      return
    }
    loadDivisionChoices(eventId).catch((e: any) => {
      setError(e?.message || 'Failed to load division choices')
    })
  }, [divisionEventId, loadDivisionChoices])

  const formatTeamLabel = useCallback((team: DeskTeamItem) => {
    return (team.display_name || team.name || `Team ${team.team_id}`).trim()
  }, [])

  const sortedTeams = useMemo(() => {
    const rows = [...teams]
    rows.sort((a, b) => {
      const byEvent = a.event_name.localeCompare(b.event_name, undefined, { sensitivity: 'base' })
      if (byEvent !== 0) return byEvent
      return formatTeamLabel(a).localeCompare(formatTeamLabel(b), undefined, { sensitivity: 'base' })
    })
    return rows
  }, [teams, formatTeamLabel])

  const filteredTeams = useMemo(() => {
    const query = teamSearch.trim().toLowerCase()
    if (!query) return sortedTeams
    return sortedTeams.filter(team => {
      const haystack = [
        team.event_name,
        team.name,
        team.display_name || '',
        String(team.team_id),
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [sortedTeams, teamSearch])

  const teamGroups = useMemo(() => {
    const groups: Array<{ eventName: string; teams: DeskTeamItem[] }> = []
    for (const team of filteredTeams) {
      const last = groups[groups.length - 1]
      if (!last || last.eventName !== team.event_name) {
        groups.push({ eventName: team.event_name, teams: [team] })
      } else {
        last.teams.push(team)
      }
    }
    return groups
  }, [filteredTeams])

  const sortedEvents = useMemo(() => {
    const rows = [...events]
    rows.sort((a, b) => {
      const aLabel = formatEventScopeLabel(a).toLowerCase()
      const bLabel = formatEventScopeLabel(b).toLowerCase()
      return aLabel.localeCompare(bLabel)
    })
    return rows
  }, [events])

  const rrEventOptions = useMemo(() => {
    return sortedEvents
  }, [sortedEvents])

  useEffect(() => {
    if (rrEventOptions.length === 0) {
      setRrMixedEventId('')
      return
    }
    setRrMixedEventId(prev => {
      if (prev === 'ALL') return prev
      if (prev && rrEventOptions.some(event => String(event.id) === prev)) return prev
      return 'ALL'
    })
  }, [rrEventOptions])

  const divisionEventOptions = useMemo(() => {
    return sortedEvents.map(event => ({
      value: String(event.id),
      label: formatEventScopeLabel(event),
    }))
  }, [sortedEvents])

  const divisionChoicesForEvent = useMemo(() => divisionChoices, [divisionChoices])

  const sortedPlayers = useMemo(() => {
    const rows = [...players]
    rows.sort((a, b) => {
      const byName = (a.player_name || '').localeCompare(b.player_name || '', undefined, { sensitivity: 'base' })
      if (byName !== 0) return byName
      return a.player_id - b.player_id
    })
    return rows
  }, [players])

  const filteredPlayers = useMemo(() => {
    const query = playerSearch.trim().toLowerCase()
    if (!query) return sortedPlayers
    return sortedPlayers.filter(player => {
      const haystack = [
        player.player_name,
        player.phone_e164 || '',
        String(player.player_id),
        player.consent_status,
      ].join(' ').toLowerCase()
      return haystack.includes(query)
    })
  }, [sortedPlayers, playerSearch])

  const filteredMatches = useMemo(() => {
    const query = matchSearch.trim().toLowerCase()
    if (!query) return matches
    return matches.filter(match => {
      const haystack = [
        match.display_label,
        match.event_name,
        match.match_code,
        match.team_a_name,
        match.team_b_name,
        String(match.match_id),
        match.runtime_status,
      ].join(' ').toLowerCase()
      return haystack.includes(query)
    })
  }, [matches, matchSearch])

  const formatLogTime = useCallback((iso: string) => {
    const raw = (iso || '').trim()
    if (!raw) return iso

    // SQLite/JSON can drop timezone info (e.g. "2026-03-03T21:03:32").
    // Treat timezone-less timestamps as UTC before rendering in tournament TZ.
    const hasTz = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(raw)
    const normalizedBase = raw.includes('T') ? raw : raw.replace(' ', 'T')
    const normalized = hasTz ? normalizedBase : `${normalizedBase}Z`

    let dt = new Date(normalized)
    if (Number.isNaN(dt.getTime())) {
      dt = new Date(raw)
    }
    if (Number.isNaN(dt.getTime())) return iso
    try {
      return new Intl.DateTimeFormat(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZone: tournamentTimezone || undefined,
        timeZoneName: 'short',
      }).format(dt)
    } catch {
      return dt.toLocaleString()
    }
  }, [tournamentTimezone])

  const handlePreview = async () => {
    if (!message.trim()) {
      setError('Message is required for preview')
      return
    }
    if (
      (scope === 'division' && !division.trim()) ||
      ((scope === 'event' || scope === 'team' || scope === 'player' || scope === 'match') && parseTargetId() === null)
    ) {
      setError('Target is required for this scope')
      return
    }
    setPreviewing(true)
    setError(null)
    try {
      let resp: SmsPreviewResponse
      if (scope === 'blast') {
        resp = await previewSmsBlast(tournamentId, { message })
      } else if (scope === 'division') {
        const eventId = parseInt(divisionEventId, 10)
        if (!Number.isFinite(eventId) || eventId <= 0 || !division.trim()) {
          throw new Error('Event and division choice are required')
        }
        resp = await previewSmsEventDivision(tournamentId, eventId, division.trim(), { message })
      } else {
        const id = parseTargetId()
        if (!id) throw new Error('Target ID is required for this scope')
        if (scope === 'event') resp = await previewSmsEvent(tournamentId, id, { message })
        else if (scope === 'player') resp = await previewSmsPlayer(tournamentId, id, { message })
        else if (scope === 'match') resp = await previewSmsMatch(tournamentId, id, { message })
        else resp = await previewSmsBlast(tournamentId, { message })
      }
      setPreview(resp)
      setSendResult(null)
    } catch (e: any) {
      setError(e?.message || 'Preview failed')
    } finally {
      setPreviewing(false)
    }
  }

  const handleSend = async () => {
    if (!message.trim()) {
      setError('Message is required to send')
      return
    }
    if (!hasValidTarget) {
      setError('Target is required for this scope')
      return
    }
    if (requiresBroadConfirm && !confirmOk) {
      setError("Type SEND to confirm broad-audience send")
      return
    }
    setSending(true)
    setError(null)
    try {
      const payload = { message }
      let resp: SmsSendResponse
      if (scope === 'blast') {
        resp = await sendSmsBlast(tournamentId, payload)
      } else if (scope === 'division') {
        const eventId = parseInt(divisionEventId, 10)
        if (!Number.isFinite(eventId) || eventId <= 0 || !division.trim()) {
          throw new Error('Event and division choice are required')
        }
        resp = await sendSmsEventDivision(tournamentId, eventId, division.trim(), payload)
      } else {
        const id = parseTargetId()
        if (!id) throw new Error('Target ID is required for this scope')
        if (scope === 'event') resp = await sendSmsEvent(tournamentId, id, payload)
        else if (scope === 'team') resp = await sendSmsTeam(tournamentId, id, payload)
        else if (scope === 'player') resp = await sendSmsPlayer(tournamentId, id, payload)
        else if (scope === 'match') resp = await sendSmsMatch(tournamentId, id, payload)
        else resp = await sendSmsBlast(tournamentId, payload)
      }
      setSendResult(resp)
      await loadLogs()
      await loadRolloutMetrics()
    } catch (e: any) {
      setError(e?.message || 'Send failed')
    } finally {
      setSending(false)
    }
  }

  const handleRunFirstMatchReminder = async (dryRun: boolean) => {
    setRunningReminder(true)
    setError(null)
    try {
      const result = await runSmsFirstMatchReminders(tournamentId, {
        dry_run: dryRun,
        template_mode: smsTemplateMode,
      })
      setLastReminderRun(result)
      if (!dryRun) {
        await loadLogs()
      }
      await loadRolloutMetrics()
    } catch (e: any) {
      setError(e?.message || 'Failed to run first-match reminder scan')
    } finally {
      setRunningReminder(false)
    }
  }

  const handleRunRrFirstMatchReminder = async (dryRun: boolean) => {
    const isAllEvents = rrMixedEventId === 'ALL'
    const selectedEventIds = isAllEvents
      ? rrEventOptions.map(event => event.id)
      : [parseInt(rrMixedEventId, 10)]
    if (selectedEventIds.length === 0 || selectedEventIds.some(id => !Number.isFinite(id) || id <= 0)) {
      setError('Choose an event first')
      return
    }
    setRunningRrReminder(true)
    setError(null)
    try {
      const perEventResults = await Promise.all(
        selectedEventIds.map(eventId => runSmsRrFirstMatchReminders(tournamentId, {
          event_id: eventId,
          dry_run: dryRun,
          template_mode: smsTemplateMode,
        }))
      )
      const result = perEventResults.reduce<SmsRrAutomationRunResponse>((acc, item) => ({
        ...acc,
        considered_teams: acc.considered_teams + (item.considered_teams || 0),
        eligible_teams: acc.eligible_teams + (item.eligible_teams || 0),
        missing_slot: acc.missing_slot + (item.missing_slot || 0),
        sent: acc.sent + (item.sent || 0),
        deduped: acc.deduped + (item.deduped || 0),
        blocked_test_mode: acc.blocked_test_mode + (item.blocked_test_mode || 0),
        blocked_consent: acc.blocked_consent + (item.blocked_consent || 0),
        failed: acc.failed + (item.failed || 0),
        no_active_version: acc.no_active_version && item.no_active_version,
        template_inactive: acc.template_inactive || item.template_inactive,
      }), {
        tournament_id: tournamentId,
        version_id: perEventResults.find(r => r.version_id != null)?.version_id ?? null,
        event_id: isAllEvents ? 0 : selectedEventIds[0],
        disabled: false,
        no_active_version: perEventResults.length > 0,
        dry_run: dryRun,
        force_resend: false,
        resend_run_key: null,
        considered_teams: 0,
        eligible_teams: 0,
        missing_slot: 0,
        sent: 0,
        deduped: 0,
        blocked_test_mode: 0,
        blocked_consent: 0,
        failed: 0,
        template_inactive: false,
      })
      setLastRrReminderRun(result)
      if (!dryRun) {
        await loadLogs()
      }
      await loadRolloutMetrics()
    } catch (e: any) {
      setError(e?.message || 'Failed to run RR first-match force resend')
    } finally {
      setRunningRrReminder(false)
    }
  }

  const handleSyncPlayerContacts = async () => {
    setSyncingPlayerContacts(true)
    setError(null)
    try {
      const summary = await syncSmsPlayerContacts(tournamentId)
      setPlayerSyncSummary(summary)
      setPlayerAdminNotice(
        `Rebuilt player links: +${summary.players_created} players, +${summary.links_created} links, ${summary.links_removed} removed.`
      )
      await Promise.all([
        loadLookups(),
        loadStatusAndSettings(),
      ])
    } catch (e: any) {
      setError(e?.message || 'Failed to sync player contacts')
    } finally {
      setSyncingPlayerContacts(false)
    }
  }

  const handleWipePlayers = async () => {
    const confirmed = await confirmDialog(
      'Clear all players and teams for this tournament?\n\nThis deletes Team rows, Players, Player Links, team/player check-ins, consent history, and imported player lookup rows. Match team assignments will be cleared too.'
    )
    if (!confirmed) return

    setWipingPlayers(true)
    setError(null)
    try {
      const summary: SmsPlayerWipeResponse = await wipeSmsPlayers(tournamentId)
      setPlayerSyncSummary(null)
      setPlayerAdminNotice(
        `Cleared ${summary.teams_deleted} teams, ${summary.players_deleted} players, ${summary.links_deleted} links, ${summary.team_checkins_deleted} team check-ins, ${summary.player_checkins_deleted} player check-ins, ${summary.matches_cleared} match assignments, ${summary.lookup_rows_deleted} lookup rows, and ${summary.consent_events_deleted} consent rows.`
      )
      await Promise.all([
        loadLookups(),
        loadStatusAndSettings(),
      ])
    } catch (e: any) {
      setError(e?.message || 'Failed to wipe players')
    } finally {
      setWipingPlayers(false)
    }
  }

  const handleAddQuickTestPhone = async () => {
    const phone = quickTestPhone.trim()
    if (!phone) {
      setError('Enter your phone number first')
      return
    }
    setSavingQuickTestPhone(true)
    setError(null)
    try {
      const existing = settingsDraft?.test_allowlist || ''
      const tokens = `${existing},${phone}`
        .replace(/[;\n]+/g, ',')
        .split(',')
        .map(v => v.trim())
        .filter(Boolean)
      const deduped = Array.from(new Set(tokens))
      const updated = await patchSmsSettings(tournamentId, {
        test_mode: true,
        test_allowlist: deduped.join(','),
      })
      setSettingsDraft(updated)
      setQuickTestPhone('')
    } catch (e: any) {
      setError(e?.message || 'Failed to add test phone')
    } finally {
      setSavingQuickTestPhone(false)
    }
  }

  const saveSettings = async () => {
    if (!settingsDraft) return
    setSavingSettings(true)
    setError(null)
    try {
      const updated = await patchSmsSettings(tournamentId, {
        auto_first_match: false,
        auto_post_match_next: false,
        auto_on_deck: false,
        auto_up_next: false,
        auto_court_change: false,
        auto_checkin_first_match: false,
        auto_checkin_slot_checkin: false,
        auto_checkin_post_match_next: settingsDraft.auto_checkin_post_match_next,
        auto_checkin_court_assigned: false,
        texts_enabled: settingsDraft.texts_enabled,
        test_mode: settingsDraft.test_mode,
        test_allowlist: settingsDraft.test_allowlist,
        player_contacts_only: settingsDraft.player_contacts_only,
      })
      setSettingsDraft(updated)
    } catch (e: any) {
      setError(e?.message || 'Failed to save settings')
    } finally {
      setSavingSettings(false)
    }
  }

  const saveTemplate = async (row: SmsTemplateResponse) => {
    setSavingTemplateType(row.message_type)
    setError(null)
    try {
      await putSmsTemplate(tournamentId, row.message_type, {
        template_body: templateBodies[row.message_type] ?? row.template_body,
        is_active: row.is_active,
      })
      await loadTemplates()
    } catch (e: any) {
      setError(e?.message || `Failed to save template ${row.message_type}`)
    } finally {
      setSavingTemplateType(null)
    }
  }

  const handleTemplateModeChange = async (
    nextMode: 'court_management' | 'checkin_management'
  ) => {
    setSmsTemplateMode(nextMode)
    const nextAutomationDefaults = {
      auto_first_match: false,
      auto_post_match_next: false,
      auto_on_deck: false,
      auto_up_next: false,
      auto_court_change: false,
      auto_checkin_first_match: false,
      auto_checkin_slot_checkin: false,
      auto_checkin_post_match_next: nextMode === 'checkin_management',
      auto_checkin_court_assigned: false,
    }
    const rows = [...templates]
    const settingsMismatch = settingsDraft
      ? (
          settingsDraft.auto_first_match !== nextAutomationDefaults.auto_first_match ||
          settingsDraft.auto_post_match_next !== nextAutomationDefaults.auto_post_match_next ||
          settingsDraft.auto_on_deck !== nextAutomationDefaults.auto_on_deck ||
          settingsDraft.auto_up_next !== nextAutomationDefaults.auto_up_next ||
          settingsDraft.auto_court_change !== nextAutomationDefaults.auto_court_change ||
          settingsDraft.auto_checkin_first_match !== nextAutomationDefaults.auto_checkin_first_match ||
          settingsDraft.auto_checkin_slot_checkin !== nextAutomationDefaults.auto_checkin_slot_checkin ||
          settingsDraft.auto_checkin_post_match_next !== nextAutomationDefaults.auto_checkin_post_match_next ||
          settingsDraft.auto_checkin_court_assigned !== nextAutomationDefaults.auto_checkin_court_assigned
        )
      : false
    const hasMismatch = rows.some(row => {
      const shouldBeActive = activeCheckinTemplateTypes.has(row.message_type)
      return row.is_active !== shouldBeActive
    })
    if (settingsDraft) {
      setSettingsDraft(prev => prev ? ({ ...prev, ...nextAutomationDefaults }) : prev)
    }
    if (!hasMismatch && !settingsMismatch) return
    setApplyingTemplateMode(true)
    setError(null)
    const nextTemplates = rows.map(row => {
      const shouldBeActive = activeCheckinTemplateTypes.has(row.message_type)
      return { ...row, is_active: shouldBeActive }
    })
    setTemplates(nextTemplates)
    try {
      const tasks: Promise<any>[] = []
      if (hasMismatch) {
        tasks.push(
          Promise.all(
            nextTemplates.map(row =>
              putSmsTemplate(tournamentId, row.message_type, {
                template_body: templateBodies[row.message_type] ?? row.template_body,
                is_active: row.is_active,
              })
            )
          )
        )
      }
      if (settingsMismatch) {
        tasks.push(
          patchSmsSettings(tournamentId, nextAutomationDefaults).then(updated => {
            setSettingsDraft(updated)
          })
        )
      }
      await Promise.all(tasks)
      if (hasMismatch) {
        await loadTemplates()
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to apply template mode defaults')
    } finally {
      setApplyingTemplateMode(false)
    }
  }

  useEffect(() => {
    appliedTemplateDefaultsForTournamentRef.current = false
  }, [tournamentId])

  useEffect(() => {
    if (appliedTemplateDefaultsForTournamentRef.current) return
    if (applyingTemplateMode) return
    if (templates.length === 0) return
    appliedTemplateDefaultsForTournamentRef.current = true
    void handleTemplateModeChange(smsTemplateMode)
  }, [templates, smsTemplateMode, applyingTemplateMode])

  useEffect(() => {
    if (!managementMode) return
    if (applyingTemplateMode) return
    if (smsTemplateMode === managementMode) return
    void handleTemplateModeChange(managementMode)
  }, [managementMode, smsTemplateMode, applyingTemplateMode])

  if (loading) return <div style={{ padding: 20, color: '#888' }}>Loading SMS admin…</div>

  const compactControlStyle: React.CSSProperties = {
    boxSizing: 'border-box',
    width: '100%',
  }
  const templateLabels: Record<string, string> = {
    first_match: 'Court: First match',
    rr_first_match: 'Court: Round Robin first match',
    post_match_next: 'Court: Post-match next',
    on_deck: 'Court: On deck',
    up_next: 'Court: Up next',
    court_change: 'Court: Court change',
    checkin_first_match: 'Check-In: First match check-in',
    checkin_rr_first_match: 'Check-In: Round Robin first match',
    checkin_slot_checkin: 'Check-In: Prior slot started (check-in now)',
    checkin_post_match_next: 'Check-In: Post-match next (no court)',
    checkin_court_assigned: 'Check-In: Court assigned (go to your court)',
  }
  const checkinTemplateRows = templates.filter(row => activeCheckinTemplateTypes.has(row.message_type))
  const textsEnabled = settingsDraft?.texts_enabled ?? true
  const visibleLogs = logs.filter(l => {
    const status = String(l.status || '').trim().toLowerCase()
    if (status === 'blocked_test_mode') return false
    if (status === 'sent' || status === 'delivered') return true
    if (status.includes('fail') || status === 'undelivered') return true
    return Boolean((l.error_message || '').trim())
  })

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      {error && (
        <div style={{ padding: '10px 12px', backgroundColor: '#fce4ec', color: '#ad1457', borderRadius: 6, fontSize: 13 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff', flex: '1 1 560px', minWidth: 460 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>SMS Status</h3>
          <button onClick={loadStatusAndSettings} style={{ padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}>Refresh</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8, fontSize: 13 }}>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: '8px 10px' }}>
            <strong>Twilio:</strong> {status?.twilio_configured ? 'Configured' : 'Not Configured'}
          </div>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: '8px 10px' }}>
            <strong>From #:</strong> {status?.from_number || '—'}
          </div>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: '8px 10px' }}>
            <strong>Teams:</strong> {status?.teams_with_phones}/{status?.total_teams} with phones
          </div>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: '8px 10px' }}>
            <strong>Settings row:</strong> {status?.tournament_has_settings ? 'Yes' : 'No (defaults)'}
          </div>
          <div style={{ border: `1px solid ${textsEnabled ? '#c8e6c9' : '#ffcdd2'}`, borderRadius: 8, padding: '8px 10px', backgroundColor: textsEnabled ? '#f1f8e9' : '#ffebee' }}>
            <strong>Texts:</strong> {textsEnabled ? 'ON' : 'OFF'}
          </div>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: '8px 10px' }}>
            <strong>Test mode:</strong> {settingsDraft?.test_mode ? 'ON (allowlist only)' : 'OFF'}
          </div>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: '8px 10px' }}>
            <strong>Contact mode:</strong> {settingsDraft?.player_contacts_only ? 'Player records only' : 'Legacy team fields'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 12, marginTop: 10 }}>
          <span style={{ color: '#666' }}>Template mode</span>
          <span style={{ fontWeight: 700, color: '#1a237e' }}>Check-In Management</span>
          {applyingTemplateMode && (
            <span style={{ color: '#666' }}>Applying template defaults…</span>
          )}
        </div>
        <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
          Selected template set: <strong>Check-In Management</strong>.
          {' '}First-match texts are manual only. TEST mode + allowlist is the active safety check.
        </div>
        {settingsDraft && (
          <div style={{ marginTop: 10, padding: 10, border: `1px solid ${textsEnabled ? '#dcedc8' : '#ffcdd2'}`, borderRadius: 6, backgroundColor: textsEnabled ? '#f9fff1' : '#fff5f5' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: textsEnabled ? '#2e7d32' : '#c62828' }}>
                  {textsEnabled ? 'All texting is ON' : 'All texting is OFF'}
                </div>
                <div style={{ fontSize: 12, color: '#555', marginTop: 4 }}>
                  This is the tournament-wide emergency switch. When OFF, both automatic texts and manual sends are blocked.
                </div>
              </div>
              <button
                onClick={async () => {
                  setSavingSettings(true)
                  setError(null)
                  try {
                    const updated = await patchSmsSettings(tournamentId, {
                      texts_enabled: !textsEnabled,
                    })
                    setSettingsDraft(updated)
                  } catch (e: any) {
                    setError(e?.message || 'Failed to update text sending status')
                  } finally {
                    setSavingSettings(false)
                  }
                }}
                disabled={savingSettings}
                style={{
                  padding: '8px 14px',
                  fontSize: 12,
                  fontWeight: 700,
                  borderRadius: 4,
                  border: 'none',
                  cursor: savingSettings ? 'default' : 'pointer',
                  backgroundColor: textsEnabled ? '#c62828' : '#2e7d32',
                  color: '#fff',
                  minWidth: 150,
                  opacity: savingSettings ? 0.75 : 1,
                }}
              >
                {savingSettings ? 'Saving…' : textsEnabled ? 'Turn Off All Texts' : 'Turn On All Texts'}
              </button>
            </div>
          </div>
        )}
        {settingsDraft?.test_mode && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #ffe0b2', borderRadius: 6, backgroundColor: '#fff8e1', fontSize: 12, color: '#e65100', maxWidth: 820 }}>
            TEST mode is ON. Sends are restricted to allowlisted numbers:
            <div style={{ marginTop: 4, color: '#6d4c41' }}>
              {settingsDraft.test_allowlist || '(none configured — all recipients will be blocked)'}
            </div>
          </div>
        )}
        {settingsDraft && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #ffe0b2', borderRadius: 6, backgroundColor: '#fff8e1' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={Boolean(settingsDraft.test_mode)}
                onChange={e => setSettingsDraft(prev => prev ? ({ ...prev, test_mode: e.target.checked }) : prev)}
              />
              TEST mode (allowlist-only delivery)
            </label>
            <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>
              When enabled, SMS sends are blocked for everyone except the phone numbers listed below.
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
              <button
                onClick={saveSettings}
                disabled={savingSettings}
                style={{ padding: '7px 14px', fontWeight: 600, cursor: 'pointer' }}
              >
                {savingSettings ? 'Saving…' : 'Save Test Mode'}
              </button>
              <span style={{ fontSize: 11, color: '#666' }}>
                Save after turning test mode on or off so the change takes effect.
              </span>
            </div>
            <div style={{ width: '25%', minWidth: 240, maxWidth: 320 }}>
              <div style={{ display: 'grid', gap: 6, marginBottom: 8 }}>
                <input
                  type="text"
                  value={quickTestPhone}
                  onChange={e => setQuickTestPhone(e.target.value)}
                      placeholder="Add my number (e.g. +19015551234)"
                  style={{ width: '100%', boxSizing: 'border-box', padding: 7, borderRadius: 4, border: '1px solid #ccc' }}
                />
                <button
                  onClick={handleAddQuickTestPhone}
                  disabled={savingQuickTestPhone}
                  style={{ padding: '7px 12px', fontSize: 12, cursor: 'pointer', justifySelf: 'start' }}
                >
                  {savingQuickTestPhone ? 'Adding…' : 'Add My Number'}
                </button>
              </div>
              <input
                type="text"
                value={settingsDraft.test_allowlist ?? ''}
                onChange={e => setSettingsDraft(prev => prev ? ({ ...prev, test_allowlist: e.target.value }) : prev)}
                placeholder="+19013593035, +19703092022"
                style={{ width: '100%', boxSizing: 'border-box', padding: 7, borderRadius: 4, border: '1px solid #ccc' }}
              />
              <div style={{ fontSize: 11, color: '#777', marginTop: 6 }}>
                Use comma or newline-separated numbers. They are normalized to E.164 on save.
              </div>
            </div>
          </div>
        )}
      </div>

      <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff' }}>
        <div style={{ marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>First-Match SMS</h3>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 520px))', gap: 12, justifyContent: 'start' }}>
          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>First Match</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <button
                onClick={() => handleRunFirstMatchReminder(true)}
                disabled={runningReminder || !textsEnabled}
                style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}
              >
                {runningReminder ? 'Running…' : 'Test first-match text'}
              </button>
              <button
                onClick={() => handleRunFirstMatchReminder(false)}
                disabled={runningReminder || !textsEnabled}
                style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}
              >
                {runningReminder ? 'Running…' : 'Send first-match text'}
              </button>
            </div>
            {lastReminderRun && (
              <div style={{ fontSize: 12, color: '#555' }}>
                {lastReminderRun.dry_run ? (
                  <>
                    Last run: Considered {lastReminderRun.considered_teams}, Eligible {lastReminderRun.eligible_teams}, Will be blocked {(lastReminderRun.blocked_test_mode || 0) + (lastReminderRun.blocked_consent || 0) + (lastReminderRun.deduped || 0)}, Will be sent {lastReminderRun.sent}
                  </>
                ) : (
                  <>
                    Last run: considered {lastReminderRun.considered_teams}, eligible {lastReminderRun.eligible_teams}, blocked {(lastReminderRun.blocked_test_mode || 0) + (lastReminderRun.blocked_consent || 0)}, sent {lastReminderRun.sent}, failed {lastReminderRun.failed}
                  </>
                )}
                {lastReminderRun.template_inactive ? ' (template inactive)' : ''}
              </div>
            )}
          </div>

          <div style={{ border: '1px solid #e6e6e6', borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>RR First Match</div>
            <div style={{ display: 'grid', gap: 8 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <label style={{ fontSize: 12, color: '#666' }}>Choose event</label>
                <select
                  value={rrMixedEventId}
                  onChange={e => setRrMixedEventId(e.target.value)}
                  disabled={rrEventOptions.length === 0 || runningRrReminder}
                  className="sms-compact-control"
                  style={{ width: 240 }}
                >
                  {rrEventOptions.length === 0 ? (
                    <option value="">No events found</option>
                  ) : (
                    <>
                      <option value="ALL">ALL Events</option>
                      {rrEventOptions.map(event => (
                        <option key={event.id} value={String(event.id)}>
                          {formatEventScopeLabel(event)}
                        </option>
                      ))}
                    </>
                  )}
                </select>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  onClick={() => handleRunRrFirstMatchReminder(true)}
                  disabled={runningRrReminder || rrEventOptions.length === 0 || !textsEnabled}
                  style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}
                >
                  {runningRrReminder ? 'Running…' : 'Test RR first-match text'}
                </button>
                <button
                  onClick={() => handleRunRrFirstMatchReminder(false)}
                  disabled={runningRrReminder || rrEventOptions.length === 0 || !textsEnabled}
                  style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}
                >
                  {runningRrReminder ? 'Running…' : 'Send RR first-match text'}
                </button>
              </div>
              {lastRrReminderRun && (
                <div style={{ fontSize: 12, color: '#555' }}>
                  {lastRrReminderRun.dry_run ? (
                    <>
                      Last run: Considered {lastRrReminderRun.considered_teams}, Eligible {lastRrReminderRun.eligible_teams}, Will be blocked {(lastRrReminderRun.blocked_test_mode || 0) + (lastRrReminderRun.blocked_consent || 0) + (lastRrReminderRun.deduped || 0)}, Will be sent {lastRrReminderRun.sent}
                    </>
                  ) : (
                    <>
                      Last run: considered {lastRrReminderRun.considered_teams}, eligible {lastRrReminderRun.eligible_teams}, blocked {(lastRrReminderRun.blocked_test_mode || 0) + (lastRrReminderRun.blocked_consent || 0)}, sent {lastRrReminderRun.sent}, failed {lastRrReminderRun.failed}
                    </>
                  )}
                  {lastRrReminderRun.template_inactive ? ' (template inactive)' : ''}
                </div>
              )}
            </div>
          </div>
        </div>

      </div>

      <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff', flex: '1 1 560px', minWidth: 460 }}>
        <h3 style={{ marginTop: 0, fontSize: 15 }}>Manual Send / Preview</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 260px) minmax(360px, 1fr)', gap: 8, marginBottom: 8, alignItems: 'start' }}>
          <label style={{ fontSize: 12, color: '#666' }}>Scope</label>
          <label style={{ fontSize: 12, color: '#666' }}>
            {scope === 'team'
              ? 'Team'
              : scope === 'player'
                ? 'Player'
                : scope === 'match'
                  ? 'Match'
                : scope === 'event'
                  ? 'Event'
                  : scope === 'division'
                    ? 'Division'
                    : 'Target'}
          </label>
          <select
            value={scope}
            onChange={e => setScope(e.target.value as SmsScope)}
            className="sms-compact-control"
            style={compactControlStyle}
          >
            <option value="team">Team</option>
            <option value="player">Player</option>
            <option value="match">Match</option>
            <option value="event">Event</option>
            <option value="division">Division</option>
            <option value="blast">Tournament Blast (ALL teams)</option>
          </select>

          {scope === 'team' ? (
            <div style={{ display: 'grid', gap: 6 }}>
              <input
                type="text"
                value={teamSearch}
                onChange={e => setTeamSearch(e.target.value)}
                placeholder="Search by team, partner, event, or team ID"
                className="sms-compact-control"
                style={compactControlStyle}
              />
              <select
                value={targetId}
                onChange={e => setTargetId(e.target.value)}
                className="sms-compact-control"
                style={compactControlStyle}
              >
                <option value="">Select team ID…</option>
                {teamGroups.map(group => (
                  <optgroup key={group.eventName} label={group.eventName}>
                    {group.teams.map(team => (
                      <option key={team.team_id} value={String(team.team_id)}>
                        {formatTeamLabel(team)} (ID {team.team_id})
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <div style={{ fontSize: 11, color: '#777' }}>
                Showing {filteredTeams.length} of {sortedTeams.length} teams
              </div>
            </div>
          ) : scope === 'player' ? (
            <div style={{ display: 'grid', gap: 6 }}>
              <input
                type="text"
                value={playerSearch}
                onChange={e => setPlayerSearch(e.target.value)}
                placeholder="Search by player name, phone, consent, or player ID"
                className="sms-compact-control"
                style={compactControlStyle}
              />
              <select
                value={targetId}
                onChange={e => setTargetId(e.target.value)}
                className="sms-compact-control"
                style={compactControlStyle}
              >
                <option value="">Select player ID…</option>
                {filteredPlayers.map(player => (
                  <option key={player.player_id} value={String(player.player_id)}>
                    {player.player_name} ({player.phone_e164 || 'no phone'}) [ID {player.player_id}]
                  </option>
                ))}
              </select>
              <div style={{ fontSize: 11, color: '#777' }}>
                Showing {filteredPlayers.length} of {sortedPlayers.length} players
              </div>
            </div>
          ) : scope === 'match' ? (
            <div style={{ display: 'grid', gap: 6 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="radio"
                    name="sms-match-phase"
                    checked={matchPhase === 'upcoming'}
                    onChange={() => setMatchPhase('upcoming')}
                  />
                  Next Upcoming
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="radio"
                    name="sms-match-phase"
                    checked={matchPhase === 'completed'}
                    onChange={() => setMatchPhase('completed')}
                  />
                  Completed
                </label>
              </div>
              <input
                type="text"
                value={matchSearch}
                onChange={e => setMatchSearch(e.target.value)}
                placeholder="Search by player/team/event/match"
                className="sms-compact-control"
                style={compactControlStyle}
              />
              <select
                value={targetId}
                onChange={e => setTargetId(e.target.value)}
                className="sms-compact-control"
                style={compactControlStyle}
              >
                <option value="">Select match…</option>
                {filteredMatches.map(match => (
                  <option key={match.match_id} value={String(match.match_id)}>
                    {match.display_label}
                  </option>
                ))}
              </select>
              <div style={{ fontSize: 11, color: '#777' }}>
                {loadingMatches ? 'Loading matches…' : `Showing ${filteredMatches.length} of ${matches.length} matches (${matchPhase})`}
              </div>
            </div>
          ) : scope === 'event' ? (
            <select
              value={targetId}
              onChange={e => setTargetId(e.target.value)}
              className="sms-compact-control"
              style={compactControlStyle}
            >
              <option value="">Select event…</option>
              {sortedEvents.map(event => (
                <option key={event.id} value={String(event.id)}>
                  {formatEventScopeLabel(event)} (ID {event.id})
                </option>
              ))}
            </select>
          ) : scope === 'division' ? (
            <div style={{ display: 'grid', gap: 6 }}>
              <select
                value={divisionEventId}
                onChange={e => {
                  setDivisionEventId(e.target.value)
                  setDivision('')
                }}
                className="sms-compact-control"
                style={compactControlStyle}
              >
                <option value="">Select event…</option>
                {divisionEventOptions.map(eventOpt => (
                  <option key={eventOpt.value} value={eventOpt.value}>
                    {eventOpt.label}
                  </option>
                ))}
              </select>
              <select
                value={division}
                onChange={e => setDivision(e.target.value)}
                className="sms-compact-control"
                style={compactControlStyle}
                disabled={!divisionEventId}
              >
                <option value="">Select division choice…</option>
                {divisionChoicesForEvent.map(item => (
                  <option key={item.division_label} value={item.division_label}>
                    {item.division_label}
                  </option>
                ))}
              </select>
              <div style={{ fontSize: 11, color: '#777' }}>
                {loadingDivisionChoices
                  ? 'Loading division choices…'
                  : `Showing ${divisionChoicesForEvent.length} division choices`}
              </div>
            </div>
          ) : (
            <input
              type="text"
              value={scope === 'blast' ? 'All teams in tournament (high impact)' : targetId}
              onChange={e => setTargetId(e.target.value)}
              disabled={scope === 'blast'}
              placeholder=""
              className="sms-compact-control"
              style={{ ...compactControlStyle, backgroundColor: scope === 'blast' ? '#f7f7f7' : '#fff' }}
            />
          )}

        </div>

        {requiresBroadConfirm && (
          <div style={{ marginBottom: 8, padding: 10, border: '1px solid #ffe0b2', borderRadius: 6, backgroundColor: '#fff8e1' }}>
            <div style={{ fontSize: 12, color: '#e65100', fontWeight: 700, marginBottom: 6 }}>
              High-impact send: this can notify many recipients.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 8 }}>
              <div style={{ fontSize: 12, color: '#666' }}>
                Confirm intent by typing <strong>SEND</strong> before sending.
              </div>
              <input
                type="text"
                value={confirmText}
                onChange={e => setConfirmText(e.target.value)}
                placeholder="Type SEND"
                style={{ padding: 6, borderRadius: 4, border: `1px solid ${confirmOk ? '#81c784' : '#ffcc80'}` }}
              />
            </div>
          </div>
        )}

        {!textsEnabled && (
          <div style={{ marginBottom: 8, padding: 10, border: '1px solid #ffcdd2', borderRadius: 6, backgroundColor: '#ffebee', fontSize: 12, color: '#b71c1c' }}>
            All texts are currently turned off for this tournament. Manual sends and automatic texts are blocked until you turn texts back on above.
          </div>
        )}

        <textarea
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder="Type message..."
          rows={4}
          style={{ width: '100%', boxSizing: 'border-box', padding: 8, borderRadius: 4, border: '1px solid #ccc', marginBottom: 8 }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handlePreview} disabled={previewing || sending || !textsEnabled} style={{ padding: '7px 14px', fontWeight: 600, cursor: 'pointer' }}>
            {previewing ? 'Previewing…' : 'Preview'}
          </button>
          <button
            onClick={handleSend}
            disabled={sending || previewing || !textsEnabled || !message.trim() || !hasValidTarget || !confirmOk}
            style={{
              padding: '7px 14px',
              fontWeight: 700,
              backgroundColor: (sending || previewing || !textsEnabled || !message.trim() || !hasValidTarget || !confirmOk) ? '#9fa8da' : '#1a237e',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: (sending || previewing || !textsEnabled || !message.trim() || !hasValidTarget || !confirmOk) ? 'not-allowed' : 'pointer',
            }}
          >
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>

        {preview && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #e0e0e0', borderRadius: 6, backgroundColor: '#fafafa' }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>Preview:</strong> {preview.total_messages} messages, {preview.teams_without_phone} targets without phone
            </div>
            <div style={{ maxHeight: 160, overflowY: 'auto', fontSize: 12 }}>
              {preview.recipients.slice(0, 25).map((r, idx) => (
                <div key={`${r.team_id ?? 'p'}-${r.player_id ?? idx}`} style={{ padding: '3px 0', borderBottom: '1px dotted #eee' }}>
                  {(r.player_name || r.team_name || 'Recipient')} → {r.phones.join(', ')}
                </div>
              ))}
            </div>
          </div>
        )}

        {sendResult && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #e0e0e0', borderRadius: 6, backgroundColor: '#fafafa' }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>Send result:</strong> sent {sendResult.sent}, failed {sendResult.failed}, no-phone {sendResult.skipped_no_phone}, consent-blocked {sendResult.skipped_consent}, test-blocked {sendResult.skipped_test_mode}, deduped {sendResult.skipped_dedupe}
            </div>
            <div style={{ maxHeight: 180, overflowY: 'auto', fontSize: 12 }}>
              {sendResult.results.slice(0, 25).map((r, idx) => (
                <div key={`${r.phone}-${idx}`} style={{ padding: '3px 0', borderBottom: '1px dotted #eee' }}>
                  {r.phone} — <strong>{r.status}</strong>{r.error ? ` (${r.error})` : ''}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>

      <div style={{ display: 'grid', gap: 12, alignItems: 'start' }}>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>Automation</h3>
            <button onClick={() => setShowAutomationToggles(v => !v)} style={{ padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}>
              {showAutomationToggles ? 'Hide toggles' : 'Show toggles'}
            </button>
          </div>
          {showAutomationToggles ? (
            settingsDraft && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr)', gap: 12, marginBottom: 12 }}>
                  <div style={{ border: '1px solid #eee', borderRadius: 6, padding: 10 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Check-In Post-Match SMS</div>
                    <div style={{ display: 'grid', gap: 6, fontSize: 13 }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={Boolean(settingsDraft.auto_checkin_post_match_next)}
                          onChange={e => setSettingsDraft(prev => prev ? ({ ...prev, auto_checkin_post_match_next: e.target.checked }) : prev)}
                        />
                        Post-match next (no court)
                      </label>
                      <div style={{ fontSize: 11, color: '#666' }}>
                        All other automatic SMS types are hidden here and will be saved as off.
                      </div>
                    </div>
                  </div>
                </div>
                <div style={{ marginBottom: 10, padding: 10, border: '1px solid #e8eaf6', borderRadius: 6, backgroundColor: '#f5f7ff' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                    <input
                      type="checkbox"
                      checked={Boolean(settingsDraft.player_contacts_only)}
                      onChange={e => setSettingsDraft(prev => prev ? ({ ...prev, player_contacts_only: e.target.checked }) : prev)}
                    />
                    Send texts to player records only
                  </label>
                  <div style={{ fontSize: 12, color: '#555' }}>
                    Use the phone numbers saved on Player records linked to each team. Do not use old phone fields saved directly on the Team.
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                    <button
                      onClick={handleSyncPlayerContacts}
                      disabled={syncingPlayerContacts || wipingPlayers}
                      style={{ padding: '5px 10px', fontSize: 12, cursor: 'pointer' }}
                    >
                      {syncingPlayerContacts ? 'Rebuilding…' : 'Rebuild Player Links'}
                    </button>
                    <button
                      onClick={handleWipePlayers}
                      disabled={wipingPlayers || syncingPlayerContacts}
                      style={{ padding: '5px 10px', fontSize: 12, cursor: 'pointer', backgroundColor: '#fff5f5', border: '1px solid #f1b5b5', color: '#a12626' }}
                    >
                      {wipingPlayers ? 'Clearing…' : 'Temporary: Clear Players + Teams'}
                    </button>
                    <span style={{ fontSize: 11, color: '#666' }}>
                      Team changes sync automatically. Use Rebuild only after a big import or if something looks wrong.
                    </span>
                  </div>
                  {playerSyncSummary && (
                    <div style={{ fontSize: 11, color: '#444', marginTop: 6 }}>
                      Last sync — players +{playerSyncSummary.players_created} created / {playerSyncSummary.players_updated} updated, links +{playerSyncSummary.links_created} created / {playerSyncSummary.links_updated} updated / {playerSyncSummary.links_removed} removed.
                    </div>
                  )}
                  {playerAdminNotice && (
                    <div style={{ fontSize: 11, color: '#444', marginTop: 6 }}>
                      {playerAdminNotice}
                    </div>
                  )}
                </div>
                <button onClick={saveSettings} disabled={savingSettings} style={{ padding: '7px 14px', fontWeight: 600, cursor: 'pointer' }}>
                  {savingSettings ? 'Saving…' : 'Save Settings'}
                </button>
              </>
            )
          ) : (
            <div style={{ fontSize: 12, color: '#666', fontStyle: 'italic' }}>
              Automation toggles are hidden.
            </div>
          )}
        </div>

        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 12, backgroundColor: '#fff' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ marginTop: 0, marginBottom: 8, fontSize: 15 }}>Template</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => setShowTemplates(v => !v)}
                style={{ padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}
              >
                {showTemplates ? 'Hide templates' : 'Show templates'}
              </button>
            </div>
          </div>
          {showTemplates ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(380px, 1fr)', gap: 12 }}>
              {checkinTemplateRows.map(row => (
                <div key={row.message_type} style={{ border: '1px solid #e8eaf6', borderRadius: 8, padding: 10, backgroundColor: '#f8f9ff' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>{templateLabels[row.message_type] || row.message_type}</div>
                    <label style={{ fontSize: 12 }}>
                      <input
                        type="checkbox"
                        checked={row.is_active}
                        onChange={e => setTemplates(prev => prev.map(t => t.message_type === row.message_type ? ({ ...t, is_active: e.target.checked }) : t))}
                      />{' '}
                      Active
                    </label>
                  </div>
                  <textarea
                    rows={3}
                    value={templateBodies[row.message_type] ?? row.template_body}
                    onChange={e => setTemplateBodies(prev => ({ ...prev, [row.message_type]: e.target.value }))}
                    style={{ width: '100%', boxSizing: 'border-box', padding: 6, borderRadius: 4, border: '1px solid #ccc' }}
                  />
                  <div style={{ marginTop: 6 }}>
                    <button
                      onClick={() => saveTemplate(row)}
                      disabled={savingTemplateType === row.message_type}
                      style={{ padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
                    >
                      {savingTemplateType === row.message_type ? 'Saving…' : 'Save Template'}
                    </button>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 11, color: '#666' }}>
                    First-match and post-match check-in templates are available here; other automatic SMS templates stay inactive.
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: '#666', fontStyle: 'italic' }}>
              Templates are hidden. Click "Show templates" to edit the manual first-match or post-match check-in messages.
            </div>
          )}
        </div>
      </div>

      <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 14, backgroundColor: '#fff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>SMS Log</h3>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              type="text"
              value={logTypeFilter}
              onChange={e => setLogTypeFilter(e.target.value)}
              placeholder="message_type filter"
              style={{ padding: 5, borderRadius: 4, border: '1px solid #ccc', fontSize: 12 }}
            />
            <input
              type="number"
              min={1}
              max={500}
              value={logLimit}
              onChange={e => setLogLimit(Math.max(1, Math.min(500, parseInt(e.target.value || '100', 10))))}
              style={{ width: 80, padding: 5, borderRadius: 4, border: '1px solid #ccc', fontSize: 12 }}
            />
            <button onClick={loadLogs} style={{ padding: '5px 10px', fontSize: 12, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>
        <div style={{ maxHeight: 260, overflowY: 'auto', border: '1px solid #eee', borderRadius: 6 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ backgroundColor: '#fafafa' }}>
                <th style={{ textAlign: 'left', padding: 6 }}>Time</th>
                <th style={{ textAlign: 'left', padding: 6 }}>Type</th>
                <th style={{ textAlign: 'left', padding: 6 }}>Phone</th>
                <th style={{ textAlign: 'left', padding: 6 }}>Status</th>
                <th style={{ textAlign: 'left', padding: 6 }}>Dedupe</th>
                <th style={{ textAlign: 'left', padding: 6 }}>Error</th>
              </tr>
            </thead>
            <tbody>
              {visibleLogs.map(l => (
                <tr key={l.id} style={{ borderTop: '1px solid #f0f0f0' }}>
                  <td style={{ padding: 6, whiteSpace: 'nowrap' }}>{formatLogTime(l.sent_at)}</td>
                  <td style={{ padding: 6 }}>{l.message_type}</td>
                  <td style={{ padding: 6 }}>{l.phone_number}</td>
                  <td style={{ padding: 6 }}>{l.status}</td>
                  <td style={{ padding: 6 }}>{l.dedupe_key || '—'}</td>
                  <td style={{ padding: 6, color: '#c62828' }}>{l.error_message || '—'}</td>
                </tr>
              ))}
              {visibleLogs.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: 10, color: '#888', fontStyle: 'italic' }}>
                    No successful sends or true errors yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 8, fontSize: 11, color: '#666' }}>
          Log times shown in: <strong>{tournamentTimezone || 'browser local time'}</strong>.<br />
          Webhook setup for compliance: <code>/api/tournaments/{tournamentId}/sms/webhook/inbound</code> and <code>/api/tournaments/{tournamentId}/sms/webhook/status-callback</code>
        </div>
      </div>
    </div>
  )
}

type CheckInCourtBoardRowData = {
  court: string
  now?: DeskMatchItem
  upNext?: DeskMatchItem
  onDeck?: DeskMatchItem
  displayMatch: DeskMatchItem | null
  isClosed: boolean
  lane: 'current' | 'open'
  slotLabel: string | null
  startAtLabel: string | null
  elapsedLabel: string | null
  availableSlotsForCourt: AvailableCourtSlot[]
}

function CheckInCourtBoardCard({
  row,
  onOpenMatch,
  slotTintIndex,
  nativeDragOverCourt,
}: {
  row: CheckInCourtBoardRowData
  focusSlotLabel?: string | null
  onOpenMatch: (m: DeskMatchItem) => void
  slotTintIndex: number | null
  nativeDragOverCourt: string | null
}) {
  const match = row.displayMatch
  // Tint by scheduled start (day + time) so staff can spot long-running early slots at a glance.
  const tint = match ? getTimeSlotTint(match) : getSlotTint(slotTintIndex)
  const canReceiveReady =
    row.lane === 'open' &&
    !match &&
    !row.isClosed &&
    row.availableSlotsForCourt.length > 0
  const isOver = canReceiveReady && nativeDragOverCourt === row.court

  const headerBg = tint?.accent || '#1a237e'
  const footerBg = tint?.bg || '#eef4ff'

  if (!match && !row.isClosed) {
    return (
      <div
        data-ready-court={canReceiveReady ? row.court : undefined}
        style={{
          border: canReceiveReady && isOver ? '2px solid #1565c0' : '1px solid #d7dee5',
          borderRadius: 8,
          overflow: 'hidden',
          boxShadow: canReceiveReady && isOver ? '0 2px 12px rgba(21, 101, 192, 0.2)' : '0 1px 3px rgba(15, 23, 42, 0.06)',
          transition: 'background-color 0.15s, border-color 0.15s, box-shadow 0.15s',
        }}
      >
        {/* dark header */}
        <div style={{
          backgroundColor: canReceiveReady && isOver ? '#1565c0' : '#546e7a',
          color: '#fff',
          padding: '5px 8px',
          fontSize: 12,
          fontWeight: 700,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 4,
          minWidth: 0,
        }}>
          <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.court.replace(/^Court\s+/i, 'Ct ')}</span>
          {canReceiveReady && (
            <span style={{ fontSize: 10, fontWeight: 600, opacity: 0.85, whiteSpace: 'nowrap', flexShrink: 0 }}>Drop</span>
          )}
        </div>
        {/* body — same minHeight as playing card */}
        <div style={{
          backgroundColor: canReceiveReady && isOver ? '#e3f2fd' : '#fafcfe',
          padding: '5px 7px 6px',
          minHeight: 88,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          fontSize: 10,
          color: '#90a4ae',
          fontStyle: 'italic',
        }}>
          {canReceiveReady ? 'Drag a ready match here' : (row.isClosed ? 'Closed' : 'Open — no slot')}
        </div>
      </div>
    )
  }

  return (
    <div style={{
      border: `1px solid ${tint?.border || '#c8e6c9'}`,
      borderRadius: 8,
      overflow: 'hidden',
      boxShadow: '0 1px 3px rgba(15, 23, 42, 0.06)',
    }}>
      {/* dark header bar */}
      <div style={{
        backgroundColor: headerBg,
        color: '#fff',
        padding: '5px 8px',
        fontSize: 12,
        fontWeight: 700,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 4,
        minWidth: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap', minWidth: 0, overflow: 'hidden' }}>
          <span style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>{row.court.replace(/^Court\s+/i, 'Ct ')}</span>
          {match && (
            <>
              <EventBadge name={match.event_name} />
              <Badge label={match.stage} bg={STAGE_COLORS[match.stage] || '#757575'} color="#fff" />
            </>
          )}
        </div>
        <span style={{ fontSize: 12, fontWeight: 700, opacity: 0.9, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {row.slotLabel ? row.slotLabel.split(' ').slice(-2).join('\u00a0') : ''}
        </span>
      </div>
      {/* body — fixed min-height so all cards stay the same size */}
      <div style={{ backgroundColor: '#fff', padding: '5px 7px 6px', minHeight: 88, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        {match ? (
          <>
            <div>
              <div style={{ color: '#1a1a1a', fontSize: 12, fontWeight: 700, lineHeight: 1.25 }}>
                {match.team1_display}
              </div>
              <div style={{ color: '#999', fontSize: 9, margin: '1px 0' }}>vs</div>
              <div style={{ color: '#1a1a1a', fontSize: 12, fontWeight: 700, lineHeight: 1.25 }}>
                {match.team2_display}
              </div>
              {(row.startAtLabel || row.elapsedLabel) && (
                <div style={{ marginTop: 3, fontSize: 9, color: '#607d8b' }}>
                  {row.startAtLabel && <span>▶ {row.startAtLabel}</span>}
                  {row.startAtLabel && row.elapsedLabel && <span style={{ margin: '0 3px' }}>·</span>}
                  {row.elapsedLabel && <span>{row.elapsedLabel}</span>}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => onOpenMatch(match)}
              style={{
                marginTop: 5,
                width: '100%',
                padding: '3px 6px',
                border: 'none',
                borderRadius: 4,
                backgroundColor: tint?.accent || '#2e7d32',
                color: '#fff',
                fontSize: 10,
                fontWeight: 800,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Open Match
            </button>
          </>
        ) : (
          <div style={{ fontSize: 10, color: '#607d8b', fontStyle: 'italic' }}>
            {row.isClosed ? 'Court closed.' : 'Open — no active match.'}
          </div>
        )}
      </div>
      {match && (
        <div
          style={{
            backgroundColor: footerBg,
            height: 4,
          }}
        />
      )}
    </div>
  )
}

function CheckInReadyQueueCard({
  rq,
  titleLabel,
  headerRightTop,
  queueElapsedLabel,
  deskMatch,
  returning,
  onReturnToCheckIn,
  slotTintIndex,
  nativeDragging,
  onPointerDragStart,
}: {
  rq: ReadyQueueItem
  titleLabel: string
  headerRightTop: string
  queueElapsedLabel: string | null
  deskMatch?: DeskMatchItem
  returning: boolean
  onReturnToCheckIn: () => void
  slotTintIndex: number | null
  nativeDragging: boolean
  onPointerDragStart: (event: React.PointerEvent<HTMLDivElement>, rq: ReadyQueueItem) => void
}) {
  const tint = getSlotTint(slotTintIndex)

  const accentColor = tint?.accent || '#0d47a1'
  const footerBg = tint?.bg || '#eef4ff'

  return (
    <div
      onPointerDown={(event) => onPointerDragStart(event, rq)}
      style={{
        border: `1px solid ${tint?.border || '#90caf9'}`,
        borderRadius: 8,
        overflow: 'hidden',
        cursor: nativeDragging ? 'grabbing' : 'grab',
        opacity: nativeDragging ? 0.25 : 1,
        touchAction: 'none',
        userSelect: 'none',
        boxShadow: '0 1px 3px rgba(15, 23, 42, 0.06)',
      }}
    >
      {/* dark header bar */}
      <div style={{
        backgroundColor: accentColor,
        color: '#fff',
        padding: '5px 8px',
        fontSize: 12,
        fontWeight: 700,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 4,
        minWidth: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap', minWidth: 0, overflow: 'hidden' }}>
          <span style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>{titleLabel}</span>
          <EventBadge name={rq.event_name} />
          {deskMatch && (
            <Badge label={deskMatch.stage} bg={STAGE_COLORS[deskMatch.stage] || '#757575'} color="#fff" />
          )}
        </div>
        {/* return-to-check-in button lives in header */}
        <button
          type="button"
          draggable={false}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation()
            if (!returning) onReturnToCheckIn()
          }}
          disabled={returning}
          title="Return to check-in"
          aria-label="Return to check-in"
          style={{
            flexShrink: 0,
            width: 22,
            height: 22,
            borderRadius: 4,
            border: '1px solid rgba(255,255,255,0.5)',
            backgroundColor: 'rgba(255,255,255,0.15)',
            color: '#fff',
            cursor: returning ? 'wait' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 0,
            opacity: returning ? 0.55 : 1,
          }}
        >
          {returning ? (
            <span style={{ fontSize: 10, fontWeight: 700 }}>...</span>
          ) : (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden style={{ display: 'block' }}>
              <path d="M9 14 4 9l5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 9h11a5 5 0 0 1 0 10h-3" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </button>
      </div>
      {/* body — same minHeight as court card so both card types are identical height */}
      <div style={{ backgroundColor: '#fff', padding: '5px 7px 6px', minHeight: 88, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: '#607d8b', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 3 }}>
            {headerRightTop}
          </div>
          {queueElapsedLabel && (
            <div style={{ fontSize: 10, fontWeight: 700, color: '#455a64', marginBottom: 3 }}>
              Queue: {queueElapsedLabel}
            </div>
          )}
          <div style={{ color: '#1a1a1a', fontSize: 12, fontWeight: 700, lineHeight: 1.25 }}>
            {rq.team1_display}
          </div>
          <div style={{ color: '#999', fontSize: 9, margin: '1px 0' }}>vs</div>
          <div style={{ color: '#1a1a1a', fontSize: 12, fontWeight: 700, lineHeight: 1.25 }}>
            {rq.team2_display}
          </div>
        </div>
      </div>
      <div
        style={{
          backgroundColor: footerBg,
          height: 4,
        }}
      />
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
  const [lookupItems, setLookupItems] = useState<TemporaryPlayerLookupItem[]>([])
  const [lookupImportText, setLookupImportText] = useState('')
  const [lookupImporting, setLookupImporting] = useState(false)
  const [lookupMessage, setLookupMessage] = useState<string | null>(null)
  const [lookupDrafts, setLookupDrafts] = useState<Record<number, { source_name: string; towel_color: string; report_url: string }>>({})
  const [lookupNewDraft, setLookupNewDraft] = useState<{ source_name: string; towel_color: string; report_url: string }>(toLookupDraft())
  const [lookupSavingIds, setLookupSavingIds] = useState<Set<number>>(new Set())
  const [lookupDeletingIds, setLookupDeletingIds] = useState<Set<number>>(new Set())
  const [lookupCreating, setLookupCreating] = useState(false)
  const [lookupClearing, setLookupClearing] = useState(false)

  const [draftVersionId, setDraftVersionId] = useState<number | null>(null)
  const [creatingDraft, setCreatingDraft] = useState(false)

  const [searchText, setSearchText] = useState('')
  const [drawerMatch, setDrawerMatch] = useState<DeskMatchItem | null>(null)
  const [activeTab, setActiveTab] = useState<'courts' | 'checkin' | 'towels' | 'schedule' | 'draws' | 'impact' | 'pools' | 'bulk' | 'grid' | 'weather' | 'teams' | 'sms' | 'text_list'>('checkin')
  const [smsQuickTarget, setSmsQuickTarget] = useState<SmsQuickTargetPrefill | null>(null)
  const [rescheduledMatchIds, setRescheduledMatchIds] = useState<Set<number>>(new Set())
  const [courtStates, setCourtStates] = useState<Record<string, CourtStateItem>>({})
  const [bulkToast, setBulkToast] = useState<string | null>(null)
  const [bulkConfirm, setBulkConfirm] = useState<{ label: string; fn: () => Promise<void> } | null>(null)
  const [checkInNotePrompt, setCheckInNotePrompt] = useState<{
    eventId: number
    teamId: number
    teamLabel: string
    note: string
    proceed: () => Promise<void>
  } | null>(null)
  const [checkInNoteBusy, setCheckInNoteBusy] = useState(false)

  const applyReadyQueueResponse = useCallback((resp: ReadyQueueResponse) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        version_id: resp.version_id,
        management_mode: resp.management_mode,
        checkin_matches: resp.checkin_matches,
        ready_queue: resp.ready_queue,
        available_courts: resp.available_courts,
        available_slots: resp.available_slots,
        checkin_slot_options: resp.checkin_slot_options,
        checkin_slot_rows: resp.checkin_slot_rows,
      }
    })
  }, [])

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

  const loadTemporaryPlayerLookups = useCallback(async () => {
    if (!tid) return
    try {
      const resp = await getTemporaryPlayerLookups(tid)
      setLookupItems(resp.items || [])
    } catch {
      setLookupItems([])
    }
  }, [tid])

  useEffect(() => {
    setLookupDrafts(
      Object.fromEntries(
        lookupItems.map((item) => [item.id, toLookupDraft(item)])
      )
    )
  }, [lookupItems])

  useEffect(() => {
    loadSnapshot()
    loadCourtStates()
    loadTemporaryPlayerLookups()
  }, [loadSnapshot, loadCourtStates, loadTemporaryPlayerLookups])

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
    loadTemporaryPlayerLookups()
  }, [draftVersionId, loadSnapshot, loadTemporaryPlayerLookups])

  const refreshSnapshotAndLookups = useCallback(async () => {
    if (draftVersionId) {
      await loadSnapshot(draftVersionId)
    } else {
      await loadSnapshot()
    }
    await loadTemporaryPlayerLookups()
  }, [draftVersionId, loadSnapshot, loadTemporaryPlayerLookups])

  useEffect(() => {
    if (activeTab === 'checkin' || activeTab === 'towels') {
      refreshSnapshotAndLookups()
    }
  }, [activeTab, refreshSnapshotAndLookups])

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

  const handleQuickSmsTeam = useCallback((teamId: number) => {
    setSmsQuickTarget({
      scope: 'team',
      targetId: teamId,
    })
  }, [])

  const handleQuickSmsMatch = useCallback((matchId: number, phaseHint?: 'upcoming' | 'completed') => {
    setSmsQuickTarget({
      scope: 'match',
      targetId: matchId,
      matchPhase: phaseHint || 'upcoming',
    })
  }, [])

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

  const visibleTabs = useMemo<ReadonlyArray<typeof activeTab>>(
    () => ([
      'checkin',
      'towels',
      'schedule',
      'draws',
      'impact',
      'pools',
      'bulk',
      'grid',
      'weather',
      'teams',
      'sms',
      'text_list',
    ] as const),
    []
  )

  const isCheckInManagement = true


  useEffect(() => {
    if (!visibleTabs.includes(activeTab)) {
      setActiveTab('checkin')
    }
  }, [activeTab, visibleTabs])

  const runCheckInWithNotePrompt = useCallback(async (
    eventId: number | null | undefined,
    teamId: number | null | undefined,
    teamLabel: string,
    note: string | null | undefined,
    proceed: () => Promise<void>
  ) => {
    const trimmedNote = (note || '').trim()
    if (!trimmedNote || !eventId || !teamId) {
      await proceed()
      return
    }
    setCheckInNotePrompt({
      eventId,
      teamId,
      teamLabel,
      note: trimmedNote,
      proceed,
    })
  }, [])

  const handleKeepCheckInNote = useCallback(async () => {
    if (!checkInNotePrompt) return
    setCheckInNoteBusy(true)
    try {
      await checkInNotePrompt.proceed()
      setCheckInNotePrompt(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to complete check-in')
    } finally {
      setCheckInNoteBusy(false)
    }
  }, [checkInNotePrompt])

  const handleDeleteCheckInNote = useCallback(async () => {
    if (!checkInNotePrompt) return
    setCheckInNoteBusy(true)
    try {
      await updateTeam(checkInNotePrompt.eventId, checkInNotePrompt.teamId, { notes: '' })
      await checkInNotePrompt.proceed()
      setCheckInNotePrompt(null)
      await handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete note')
    } finally {
      setCheckInNoteBusy(false)
    }
  }, [checkInNotePrompt, handleRefresh])

  const handlePlayerCheckIn = useCallback(async (match: CheckInMatchItem, side: 'A' | 'B', playerId: number, checked: boolean) => {
    if (!tid || !data) return
    const applyCheckIn = async () => {
      const resp = await deskCheckInPlayer(tid, match.match_id, {
        version_id: data.version_id,
        side,
        player_id: playerId,
        checked_in: checked,
      })
      applyReadyQueueResponse(resp)
    }
    try {
      const note = side === 'A' ? (match as any).team1_notes : (match as any).team2_notes
      const teamId = side === 'A' ? match.side_a.team_id : match.side_b.team_id
      const teamLabel = side === 'A' ? match.side_a.team_display : match.side_b.team_display
      if (checked) {
        await runCheckInWithNotePrompt((match as any).event_id ?? null, teamId, teamLabel, note, applyCheckIn)
      } else {
        await applyCheckIn()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed player check-in update')
    }
  }, [tid, data, applyReadyQueueResponse, runCheckInWithNotePrompt])

  const syncCheckInSide = useCallback(async (
    match: CheckInMatchItem,
    side: 'A' | 'B',
    state: MatchCheckInSideState,
    checkedIn: boolean
  ) => {
    if (!tid || !data) return
    if (checkedIn) {
      const uncheckedPlayers = state.players.filter((p: PlayerCheckInState) => !p.checked_in && p.player_id != null)
      if (uncheckedPlayers.length > 0) {
        const playerResponses = await Promise.all(
          uncheckedPlayers.map((p: PlayerCheckInState) =>
            deskCheckInPlayer(tid, match.match_id, {
              version_id: data.version_id,
              side,
              player_id: p.player_id!,
              checked_in: true,
            })
          )
        )
        const latestPlayerResp = playerResponses[playerResponses.length - 1]
        if (latestPlayerResp) applyReadyQueueResponse(latestPlayerResp)
      }
      const teamResp = await deskCheckInTeam(tid, match.match_id, {
        version_id: data.version_id,
        side,
        checked_in: true,
      })
      applyReadyQueueResponse(teamResp)
      return
    }

    const checkedPlayers = state.players.filter((p: PlayerCheckInState) => p.checked_in && p.player_id != null)
    if (checkedPlayers.length > 0) {
      const playerResponses = await Promise.all(
        checkedPlayers.map((p: PlayerCheckInState) =>
          deskCheckInPlayer(tid, match.match_id, {
            version_id: data.version_id,
            side,
            player_id: p.player_id!,
            checked_in: false,
          })
        )
      )
      const latestPlayerResp = playerResponses[playerResponses.length - 1]
      if (latestPlayerResp) applyReadyQueueResponse(latestPlayerResp)
    }
    const teamResp = await deskCheckInTeam(tid, match.match_id, {
      version_id: data.version_id,
      side,
      checked_in: false,
    })
    applyReadyQueueResponse(teamResp)
  }, [tid, data, applyReadyQueueResponse])

  const handleSideTeamCheckIn = useCallback(async (
    match: CheckInMatchItem,
    side: 'A' | 'B',
    state: MatchCheckInSideState
  ) => {
    if (!tid || !data) return
    const anyChecked = state.team_checked_in || state.players.some((p: PlayerCheckInState) => p.checked_in)
    const desiredChecked = !anyChecked
    const note = side === 'A' ? (match as any).team1_notes : (match as any).team2_notes
    const teamLabel = side === 'A' ? match.side_a.team_display : match.side_b.team_display
    const applyCheckIn = async () => {
      await syncCheckInSide(match, side, state, desiredChecked)
    }
    try {
      if (desiredChecked) {
        await runCheckInWithNotePrompt((match as any).event_id ?? null, state.team_id, teamLabel, note, applyCheckIn)
      } else {
        await applyCheckIn()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed team check-in')
    }
  }, [tid, data, syncCheckInSide, runCheckInWithNotePrompt])

  const handleImportTemporaryLookups = useCallback(async () => {
    if (!tid) return
    if (!lookupImportText.trim()) {
      setLookupMessage('Paste Excel rows first.')
      return
    }
    setLookupImporting(true)
    setLookupMessage(null)
    try {
      const resp = await importTemporaryPlayerLookups(tid, lookupImportText)
      setLookupItems(resp.items || [])
      setLookupMessage(`Imported ${resp.imported_count} rows and replaced the previous towel list. Matched ${resp.matched_count} player${resp.matched_count === 1 ? '' : 's'}.`)
      await refreshSnapshotAndLookups()
    } catch (e) {
      setLookupMessage(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setLookupImporting(false)
    }
  }, [tid, lookupImportText, refreshSnapshotAndLookups])

  const handleLookupDraftChange = useCallback((lookupId: number, field: 'source_name' | 'towel_color' | 'report_url', value: string) => {
    setLookupDrafts((prev) => ({
      ...prev,
      [lookupId]: {
        ...toLookupDraft(lookupItems.find((item) => item.id === lookupId)),
        ...(prev[lookupId] || {}),
        [field]: value,
      },
    }))
  }, [lookupItems])

  const handleCreateLookup = useCallback(async () => {
    if (!tid) return
    if (!lookupNewDraft.source_name.trim() || !lookupNewDraft.towel_color.trim()) {
      setLookupMessage('Player name and towel color are required.')
      return
    }
    setLookupCreating(true)
    setLookupMessage(null)
    try {
      await createTemporaryPlayerLookup(tid, {
        source_name: lookupNewDraft.source_name.trim(),
        towel_color: lookupNewDraft.towel_color.trim(),
        report_url: lookupNewDraft.report_url.trim() || null,
      })
      setLookupNewDraft(toLookupDraft())
      setLookupMessage('Added towel row.')
      await refreshSnapshotAndLookups()
    } catch (e) {
      setLookupMessage(e instanceof Error ? e.message : 'Failed to add towel row')
    } finally {
      setLookupCreating(false)
    }
  }, [tid, lookupNewDraft, refreshSnapshotAndLookups])

  const handleSaveLookup = useCallback(async (lookupId: number) => {
    if (!tid) return
    const draft = lookupDrafts[lookupId]
    if (!draft || !draft.source_name.trim() || !draft.towel_color.trim()) {
      setLookupMessage('Player name and towel color are required.')
      return
    }
    setLookupSavingIds((prev) => new Set(prev).add(lookupId))
    setLookupMessage(null)
    try {
      const updated = await updateTemporaryPlayerLookup(tid, lookupId, {
        source_name: draft.source_name.trim(),
        towel_color: draft.towel_color.trim(),
        report_url: draft.report_url.trim() || null,
      })
      setLookupItems((prev) => prev.map((item) => item.id === lookupId ? updated : item))
      setLookupMessage(`Saved ${updated.source_name}.`)
      await refreshSnapshotAndLookups()
    } catch (e) {
      setLookupMessage(e instanceof Error ? e.message : 'Failed to save towel row')
    } finally {
      setLookupSavingIds((prev) => {
        const next = new Set(prev)
        next.delete(lookupId)
        return next
      })
    }
  }, [tid, lookupDrafts, refreshSnapshotAndLookups])

  const handleDeleteLookup = useCallback(async (lookupId: number) => {
    if (!tid) return
    setLookupDeletingIds((prev) => new Set(prev).add(lookupId))
    setLookupMessage(null)
    try {
      await deleteTemporaryPlayerLookup(tid, lookupId)
      setLookupItems((prev) => prev.filter((item) => item.id !== lookupId))
      setLookupMessage('Deleted towel row.')
      await refreshSnapshotAndLookups()
    } catch (e) {
      setLookupMessage(e instanceof Error ? e.message : 'Failed to delete towel row')
    } finally {
      setLookupDeletingIds((prev) => {
        const next = new Set(prev)
        next.delete(lookupId)
        return next
      })
    }
  }, [tid, refreshSnapshotAndLookups])

  const handleClearAllLookups = useCallback(async () => {
    if (!tid) return
    setLookupClearing(true)
    setLookupMessage(null)
    try {
      const resp = await clearTemporaryPlayerLookups(tid)
      setLookupItems([])
      setLookupDrafts({})
      setLookupMessage(`Cleared ${resp.deleted_count} towel row${resp.deleted_count === 1 ? '' : 's'}.`)
      await refreshSnapshotAndLookups()
    } catch (e) {
      setLookupMessage(e instanceof Error ? e.message : 'Failed to clear towel rows')
    } finally {
      setLookupClearing(false)
    }
  }, [tid, refreshSnapshotAndLookups])

  const formatReadyQueueLabel = useCallback((rq: ReadyQueueItem) => {
    const code = (rq.match_code || '').toUpperCase()
    const isWf = code.includes('_WF_')
    const division = code.includes('BWW') || code.includes('POOLA')
      ? 'Div I'
      : code.includes('BWL') || code.includes('POOLB')
        ? 'Div II'
        : code.includes('BLW') || code.includes('POOLC')
          ? 'Div III'
          : code.includes('BLL') || code.includes('POOLD')
            ? 'Div IV'
            : code.includes('POOLE')
              ? 'Div V'
              : ''
    if (isWf) return `${rq.event_name} WF`
    return division ? `${rq.event_name} ${division}` : rq.event_name
  }, [])

  const [clockNowMs, setClockNowMs] = useState(() => Date.now())
  const tournamentTimeZone = data?.tournament_timezone || undefined

  const parseApiTimestampMs = useCallback((iso?: string | null): number | null => {
    if (!iso) return null
    const hasOffset = /(?:Z|[+-]\d{2}:\d{2})$/i.test(iso)
    const normalized = hasOffset ? iso : `${iso}Z`
    const ms = Date.parse(normalized)
    if (Number.isNaN(ms)) return null
    return ms
  }, [])

  const formatStartedAtLabel = useCallback((iso?: string | null): string | null => {
    const ms = parseApiTimestampMs(iso)
    if (ms === null) return null
    const d = new Date(ms)
    try {
      return d.toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: tournamentTimeZone,
      })
    } catch {
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    }
  }, [parseApiTimestampMs, tournamentTimeZone])

  const formatElapsedLabel = useCallback((startIso?: string | null, endIso?: string | null): string | null => {
    const start = parseApiTimestampMs(startIso)
    if (start === null) return null
    const end = endIso ? parseApiTimestampMs(endIso) : clockNowMs
    if (end === null || end <= start) return '0:00'
    const totalSeconds = Math.floor((end - start) / 1000)
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60
    if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    return `${minutes}:${String(seconds).padStart(2, '0')}`
  }, [clockNowMs, parseApiTimestampMs])

  const handleAssignReadyMatch = useCallback(async (matchId: number, slotId: number) => {
    if (!tid || !data) return
    try {
      const snap = await assignReadyMatchToSlot(tid, {
        version_id: data.version_id,
        match_id: matchId,
        slot_id: slotId,
      })
      setData(snap)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to assign ready match')
    }
  }, [tid, data])

  const handleResetReadyMatch = useCallback(async (matchId: number) => {
    if (!tid || !data) return
    const match = (data.checkin_matches || []).find((cm) => cm.match_id === matchId)
    if (!match) return

    const clearSide = async (side: 'A' | 'B', state: MatchCheckInSideState) => {
      const checkedPlayers = state.players.filter((p: PlayerCheckInState) => p.checked_in && p.player_id != null)
      if (checkedPlayers.length > 0) {
        await Promise.all(
          checkedPlayers.map((player) =>
            deskCheckInPlayer(tid, matchId, {
              version_id: data.version_id,
              side,
              player_id: player.player_id!,
              checked_in: false,
            })
          )
        )
      }
      if (state.team_checked_in) {
        await deskCheckInTeam(tid, matchId, {
          version_id: data.version_id,
          side,
          checked_in: false,
        })
      }
    }

    setReadyResettingIds((prev) => new Set(prev).add(matchId))
    try {
      await clearSide('A', match.side_a)
      await clearSide('B', match.side_b)
      await handleRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to return on-deck match to check-in')
    } finally {
      setReadyResettingIds((prev) => {
        const next = new Set(prev)
        next.delete(matchId)
        return next
      })
    }
  }, [tid, data, handleRefresh])

  const isDraft = data?.version_status === 'draft'

  const [startAllOpen, setStartAllOpen] = useState(false)
  const [startAllExcluded, setStartAllExcluded] = useState<Set<string>>(new Set())
  const [startingAll, setStartingAll] = useState(false)
  const [readyResettingIds, setReadyResettingIds] = useState<Set<number>>(new Set())

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

  const visibleCourts = useMemo(() => {
    if (!data) return []
    return data.courts.filter(court =>
      (() => {
        const courtLabel = court.replace(/^Court\s+/i, '')
        const isClosed = Boolean(courtStates[courtLabel]?.is_closed)
        return isClosed || Boolean(
        data.now_playing_by_court[court] ||
        data.up_next_by_court[court] ||
        data.on_deck_by_court[court]
        )
      })()
    )
  }, [data, courtStates])

  const handleStartAllOpen = useCallback(() => {
    setStartAllExcluded(new Set())
    setStartAllOpen(true)
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setClockNowMs(Date.now()), 1000)
    return () => window.clearInterval(id)
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

  const [nativeDraggedReadyMatchId, setNativeDraggedReadyMatchId] = useState<number | null>(null)
  const [nativeDragOverCourt, setNativeDragOverCourt] = useState<string | null>(null)
  const [pointerDragGhost, setPointerDragGhost] = useState<{
    matchId: number
    eventName: string
    matchNumber: number
    team1: string
    team2: string
    x: number
    y: number
  } | null>(null)
  const handleAssignReadyMatchToCourt = useCallback(async (matchId: number, court: string) => {
    if (!data) return

    const targetCourtLabel = court.replace(/^Court\s+/i, '').trim()
    const draggedMatch = data.matches.find((m) => m.match_id === matchId) || null
    const draggedSlot = draggedMatch?.slot_id != null
      ? data.slots.find((s) => s.slot_id === draggedMatch.slot_id) || null
      : null

    const slotSectionMap = new Map<
      string,
      {
        key: string
        label: string
        order: string
        matches: DeskMatchItem[]
        checkinRows: CheckInMatchItem[]
        assignedMatchIds: Set<number>
        slotIds: Set<number>
      }
    >()
    const formatTimeLabel = (t: string): string => {
      const hhmm = (t || '').slice(0, 5)
      const [hhRaw, mmRaw] = hhmm.split(':')
      const hh = parseInt(hhRaw || '0', 10)
      const mm = parseInt(mmRaw || '0', 10)
      const ampm = hh < 12 ? 'AM' : 'PM'
      const h12 = hh % 12 || 12
      return `${h12}:${String(mm).padStart(2, '0')} ${ampm}`
    }
    const slotById = new Map<number, SnapshotSlot>((data.slots || []).map((s) => [s.slot_id, s]))
    const hasBackendSlotContract = (data.checkin_slot_options || []).length > 0
    if (hasBackendSlotContract) {
      ;(data.checkin_slot_options || []).forEach((opt) => {
        const assignedMatchIds = new Set<number>()
        ;(opt.slot_ids || []).forEach((slotId) => {
          const snapshotSlot = slotById.get(slotId)
          if (snapshotSlot?.assigned_match_id != null) {
            assignedMatchIds.add(snapshotSlot.assigned_match_id)
          }
        })
        slotSectionMap.set(opt.slot_key, {
          key: opt.slot_key,
          label: opt.label,
          order: opt.slot_key,
          matches: [],
          checkinRows: (data.checkin_slot_rows?.[opt.slot_key] || []).slice().sort((a, b) => a.match_number - b.match_number),
          assignedMatchIds,
          slotIds: new Set<number>(opt.slot_ids || []),
        })
      })
    } else {
      ;(data.slots || [])
        .slice()
        .sort((a, b) => {
          const ka = `${a.day_date}|${a.start_time}`
          const kb = `${b.day_date}|${b.start_time}`
          return ka.localeCompare(kb)
        })
        .forEach((s) => {
          const key = `${s.day_date}|${(s.start_time || '').slice(0, 5)}`
          if (!slotSectionMap.has(key)) {
            slotSectionMap.set(key, {
              key,
              label: `${s.day_date} ${formatTimeLabel(s.start_time || '00:00')}`,
              order: key,
              matches: [],
              checkinRows: [],
              assignedMatchIds: new Set<number>(),
              slotIds: new Set<number>(),
            })
          }
          if (s.slot_id != null) {
            slotSectionMap.get(key)!.slotIds.add(s.slot_id)
          }
          if (s.assigned_match_id != null) {
            slotSectionMap.get(key)!.assignedMatchIds.add(s.assigned_match_id)
          }
        })

      ;(data.checkin_matches || []).forEach((cm) => {
        let key = ''
        let label = ''
        if (cm.slot_id != null && slotById.has(cm.slot_id)) {
          const s = slotById.get(cm.slot_id)!
          key = `${s.day_date}|${(s.start_time || '').slice(0, 5)}`
          label = `${s.day_date} ${formatTimeLabel(s.start_time || '00:00')}`
        } else {
          key = `checkin|${cm.day_label}|${(cm.sort_time || '').slice(0, 5)}`
          label = `${cm.day_label} ${cm.scheduled_time || ''}`.trim()
        }
        if (!slotSectionMap.has(key)) {
          slotSectionMap.set(key, {
            key,
            label,
            order: key,
            matches: [],
            checkinRows: [],
            assignedMatchIds: new Set<number>(),
            slotIds: new Set<number>(),
          })
        }
        if (cm.slot_id != null) {
          slotSectionMap.get(key)!.slotIds.add(cm.slot_id)
        }
        slotSectionMap.get(key)!.assignedMatchIds.add(cm.match_id)
      })
    }

    const slotSections = Array.from(slotSectionMap.values()).sort((a, b) => a.order.localeCompare(b.order))
    const slotOrderByKey = new Map<string, number>()
    const slotKeyBySlotId = new Map<number, string>()
    const slotKeyByMatchId = new Map<number, string>()
    slotSections.forEach((section, index) => {
      slotOrderByKey.set(section.key, index)
      section.slotIds.forEach((slotId) => {
        slotKeyBySlotId.set(slotId, section.key)
      })
      section.assignedMatchIds.forEach((assignedMatchId) => {
        if (!slotKeyByMatchId.has(assignedMatchId)) {
          slotKeyByMatchId.set(assignedMatchId, section.key)
        }
      })
    })
    ;(data.checkin_matches || []).forEach((cm) => {
      if (cm.slot_id != null) {
        const slotKey = slotKeyBySlotId.get(cm.slot_id)
        if (slotKey) {
          slotKeyByMatchId.set(cm.match_id, slotKey)
        }
      }
    })

    const rawNowPlayingByCourt = new Map<string, DeskMatchItem | undefined>()
    data.courts.forEach((court) => {
      rawNowPlayingByCourt.set(court, data.now_playing_by_court[court])
    })
    const courtBoardRows = data.courts.map((court) => {
      const now = data.now_playing_by_court[court]
      const courtLabel = court.replace(/^Court\s+/i, '')
      const isClosed = Boolean(courtStates[courtLabel]?.is_closed)
      const visibleReadyAssignSlots = data.available_slots
      const availableSlotsForCourt = visibleReadyAssignSlots.filter((slot) => slot.court_name === court)
      return {
        court,
        now,
        isClosed,
        availableSlotsForCourt,
      }
    })

    const targetRow = courtBoardRows.find((r) => r.court === court)
    const rawNowPlaying = rawNowPlayingByCourt.get(court)
    if (rawNowPlaying) {
      setError('That court is occupied right now.')
      return
    }
    if (targetRow?.now) {
      setError('That court already has a match assigned.')
      return
    }
    let slotId: number | null = null
    if (draggedSlot) {
      const matchingCourtSlot = (data.slots || []).find((slot) =>
        slot.day_date === draggedSlot.day_date &&
        slot.start_time === draggedSlot.start_time &&
        String(slot.court_label || '').trim() === targetCourtLabel
      )
      if (matchingCourtSlot?.slot_id != null) {
        slotId = matchingCourtSlot.slot_id
      }
    }
    if (slotId == null) {
      slotId = targetRow?.availableSlotsForCourt[0]?.slot_id ?? null
    }
    if (!slotId) {
      setError('No open assignment slot on that court.')
      return
    }
    await handleAssignReadyMatch(matchId, slotId)
  }, [data, courtStates, handleAssignReadyMatch])

  const handlePointerDragStart = useCallback((event: React.PointerEvent<HTMLDivElement>, rq: ReadyQueueItem) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    setError(null)
    setNativeDraggedReadyMatchId(rq.match_id)
    setPointerDragGhost({
      matchId: rq.match_id,
      eventName: rq.event_name,
      matchNumber: rq.match_number,
      team1: rq.team1_display,
      team2: rq.team2_display,
      x: event.clientX,
      y: event.clientY,
    })
    setNativeDragOverCourt(null)
  }, [])

  const handleNativeReadyDragEnd = useCallback(() => {
    setNativeDraggedReadyMatchId(null)
    setNativeDragOverCourt(null)
    setPointerDragGhost(null)
  }, [nativeDraggedReadyMatchId, nativeDragOverCourt, pointerDragGhost])

  useEffect(() => {
    if (!pointerDragGhost) return

    const handlePointerMove = (event: PointerEvent) => {
      const hoveredCourtEl = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-ready-court]') as HTMLElement | null
      const hoveredCourt = hoveredCourtEl?.dataset.readyCourt || null
      setPointerDragGhost((prev) => prev ? { ...prev, x: event.clientX, y: event.clientY } : null)
      setNativeDragOverCourt(hoveredCourt)
    }

    const handlePointerUp = () => {
      const matchId = nativeDraggedReadyMatchId
      const court = nativeDragOverCourt
      void (async () => {
        handleNativeReadyDragEnd()
        if (matchId != null && court) {
          await handleAssignReadyMatchToCourt(matchId, court)
        }
      })()
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp, { once: true })
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }
  }, [pointerDragGhost, nativeDraggedReadyMatchId, nativeDragOverCourt, handleNativeReadyDragEnd, handleAssignReadyMatchToCourt])

  useEffect(() => {
    if (nativeDraggedReadyMatchId != null) {
      document.body.style.userSelect = 'none'
      return () => {
        document.body.style.userSelect = ''
      }
    }
    return
  }, [nativeDraggedReadyMatchId])

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

  const slotSectionMap = new Map<
    string,
    {
      key: string
      label: string
      order: string
      matches: DeskMatchItem[]
      checkinRows: CheckInMatchItem[]
      assignedMatchIds: Set<number>
      slotIds: Set<number>
    }
  >()

  const formatTimeLabel = (t: string): string => {
    const hhmm = (t || '').slice(0, 5)
    const [hhRaw, mmRaw] = hhmm.split(':')
    const hh = parseInt(hhRaw || '0', 10)
    const mm = parseInt(mmRaw || '0', 10)
    const ampm = hh < 12 ? 'AM' : 'PM'
    const h12 = hh % 12 || 12
    return `${h12}:${String(mm).padStart(2, '0')} ${ampm}`
  }

  const hasBackendSlotContract = (data.checkin_slot_options || []).length > 0

  const matchById = new Map<number, DeskMatchItem>(
    (data.matches || []).map((m) => [m.match_id, m])
  )
  const slotById = new Map<number, SnapshotSlot>(
    (data.slots || []).map((s) => [s.slot_id, s])
  )

  if (hasBackendSlotContract) {
    ;(data.checkin_slot_options || []).forEach((opt) => {
      const assignedMatchIds = new Set<number>()
      ;(opt.slot_ids || []).forEach((slotId) => {
        const snapshotSlot = slotById.get(slotId)
        if (snapshotSlot?.assigned_match_id != null) {
          assignedMatchIds.add(snapshotSlot.assigned_match_id)
        }
      })
      slotSectionMap.set(opt.slot_key, {
        key: opt.slot_key,
        label: opt.label,
        order: opt.slot_key,
        matches: [],
        checkinRows: (data.checkin_slot_rows?.[opt.slot_key] || []).slice().sort((a, b) => a.match_number - b.match_number),
        assignedMatchIds,
        slotIds: new Set<number>(opt.slot_ids || []),
      })
    })
  } else {
    ;(data.slots || [])
      .slice()
      .sort((a, b) => {
        const ka = `${a.day_date}|${a.start_time}`
        const kb = `${b.day_date}|${b.start_time}`
        return ka.localeCompare(kb)
      })
      .forEach((s) => {
        const key = `${s.day_date}|${(s.start_time || '').slice(0, 5)}`
        if (!slotSectionMap.has(key)) {
          slotSectionMap.set(key, {
            key,
            label: `${s.day_date} ${formatTimeLabel(s.start_time || '00:00')}`,
            order: key,
            matches: [],
            checkinRows: [],
            assignedMatchIds: new Set<number>(),
            slotIds: new Set<number>(),
          })
        }
        if (s.slot_id != null) {
          slotSectionMap.get(key)!.slotIds.add(s.slot_id)
        }
        if (s.assigned_match_id != null) {
          slotSectionMap.get(key)!.assignedMatchIds.add(s.assigned_match_id)
        }
      })

    ;(data.checkin_matches || []).forEach((cm) => {
      let key = ''
      let label = ''
      if (cm.slot_id != null && slotById.has(cm.slot_id)) {
        const s = slotById.get(cm.slot_id)!
        key = `${s.day_date}|${(s.start_time || '').slice(0, 5)}`
        label = `${s.day_date} ${formatTimeLabel(s.start_time || '00:00')}`
      } else {
        key = `checkin|${cm.day_label}|${(cm.sort_time || '').slice(0, 5)}`
        label = `${cm.day_label} ${cm.scheduled_time || ''}`.trim()
      }
      if (!slotSectionMap.has(key)) {
        slotSectionMap.set(key, {
          key,
          label,
          order: key,
          matches: [],
          checkinRows: [],
          assignedMatchIds: new Set<number>(),
          slotIds: new Set<number>(),
        })
      }
      if (cm.slot_id != null) {
        slotSectionMap.get(key)!.slotIds.add(cm.slot_id)
      }
      slotSectionMap.get(key)!.assignedMatchIds.add(cm.match_id)
    })
  }

  slotSectionMap.forEach((section) => {
    if (section.checkinRows.length > 0) {
      return
    }
    if (section.assignedMatchIds.size > 0) {
      section.matches = Array.from(section.assignedMatchIds)
        .map((id) => matchById.get(id))
        .filter((m): m is DeskMatchItem => !!m && !['FINAL', 'IN_PROGRESS', 'PAUSED'].includes(m.status))
      section.matches.sort((a, b) => a.match_number - b.match_number)
      return
    }
    section.matches = []
  })

  const slotSections = Array.from(slotSectionMap.values()).sort((a, b) => a.order.localeCompare(b.order))
  slotSections.forEach(s => s.matches.sort((a, b) => (a.match_number - b.match_number)))
  const effectiveSelectedCheckInSlotKey = 'all'
  const filteredSlotSections = effectiveSelectedCheckInSlotKey === 'all'
    ? slotSections
    : slotSections.filter(s => s.key === effectiveSelectedCheckInSlotKey)

  const checkInByMatchId = new Map<number, CheckInMatchItem>(
    (data.checkin_matches || []).map((cm) => [cm.match_id, cm])
  )

  const getSectionCheckInMatches = (section: { checkinRows: CheckInMatchItem[]; slotIds: Set<number> }) =>
    (
      section.checkinRows.length > 0
        ? section.checkinRows
        : (data.checkin_matches || [])
            .filter(cm => cm.slot_id != null && section.slotIds.has(cm.slot_id))
            .sort((a, b) => a.match_number - b.match_number)
    ).filter(cm => !cm.match_ready)

  const summarizeTowelCounts = (matches: CheckInMatchItem[]) => {
    const counts = new Map<string, number>()
    matches.forEach((match) => {
      ;[match.side_a, match.side_b].forEach((sideState) => {
        ;(sideState.players || []).forEach((player) => {
          const colorName = (player.towel_color || '').trim()
          if (!colorName) return
          counts.set(colorName, (counts.get(colorName) || 0) + 1)
        })
      })
    })
    return Array.from(counts.entries())
      .map(([colorName, count]) => ({ colorName, count }))
      .sort((a, b) => b.count - a.count || a.colorName.localeCompare(b.colorName))
  }

  const towelSlotSummaries = slotSections
    .map((section) => {
      const matches = getSectionCheckInMatches(section)
      const counts = summarizeTowelCounts(matches)
      return {
        key: section.key,
        label: section.label,
        matchCount: matches.length,
        totalTowels: counts.reduce((sum, row) => sum + row.count, 0),
        counts,
      }
    })
    .filter(section => section.totalTowels > 0)

  const towelOverallCounts = summarizeTowelCounts(towelSlotSummaries.flatMap(section => {
    const slotSection = slotSections.find(s => s.key === section.key)
    return slotSection ? getSectionCheckInMatches(slotSection) : []
  }))
  const towelOverallTotal = towelOverallCounts.reduce((sum, row) => sum + row.count, 0)
  const towelOverallMax = towelOverallCounts.reduce((max, row) => Math.max(max, row.count), 0)
  const towelSlotMax = towelSlotSummaries.reduce(
    (max, section) => Math.max(max, ...section.counts.map(row => row.count), 0),
    0
  )
  const matchedLookupCount = lookupItems.filter(item => item.matched).length
  const unmatchedLookupCount = lookupItems.length - matchedLookupCount
  const slotOrderByKey = new Map<string, number>()
  const slotLabelByKey = new Map<string, string>()
  const slotKeyBySlotId = new Map<number, string>()
  const slotKeyByMatchId = new Map<number, string>()
  slotSections.forEach((section, index) => {
    slotOrderByKey.set(section.key, index)
    slotLabelByKey.set(section.key, section.label)
    section.slotIds.forEach((slotId) => {
      slotKeyBySlotId.set(slotId, section.key)
    })
    section.assignedMatchIds.forEach((matchId) => {
      if (!slotKeyByMatchId.has(matchId)) {
        slotKeyByMatchId.set(matchId, section.key)
      }
    })
  })
  ;(data.checkin_matches || []).forEach((cm) => {
    if (cm.slot_id != null) {
      const slotKey = slotKeyBySlotId.get(cm.slot_id)
      if (slotKey) {
        slotKeyByMatchId.set(cm.match_id, slotKey)
      }
    }
  })
  const autoFocusSlotKey = slotSections.find((section) => {
    const hasWaiting = getSectionCheckInMatches(section).length > 0
    const hasReady = data.ready_queue.some((rq) => slotKeyByMatchId.get(rq.match_id) === section.key)
    const hasCourtOccupancy = data.courts.some((court) => {
      const displayMatch = data.now_playing_by_court[court] || data.up_next_by_court[court] || data.on_deck_by_court[court]
      return !!displayMatch && slotKeyByMatchId.get(displayMatch.match_id) === section.key
    })
    return hasWaiting || hasReady || hasCourtOccupancy
  })?.key ?? slotSections[0]?.key ?? null
  const focusSlotKey = effectiveSelectedCheckInSlotKey === 'all' ? autoFocusSlotKey : effectiveSelectedCheckInSlotKey
  const focusSlotLabel = focusSlotKey ? (slotLabelByKey.get(focusSlotKey) || focusSlotKey) : null
  const visibleReadyAssignSlots = data.available_slots
  const rawNowPlayingByCourt = new Map<string, DeskMatchItem | undefined>()
  data.courts.forEach((court) => {
    rawNowPlayingByCourt.set(court, data.now_playing_by_court[court])
  })

  const buildFallbackDeskMatch = (cm: CheckInMatchItem): DeskMatchItem => ({
    match_id: cm.match_id,
    match_number: cm.match_number,
    match_code: cm.match_code || '',
    stage: 'WF',
    event_id: cm.event_id || 0,
    event_name: cm.event_name || 'Match',
    division_name: null,
    day_index: 0,
    day_label: cm.day_label || '',
    scheduled_time: cm.scheduled_time || null,
    sort_time: cm.sort_time || null,
    court_name: null,
    status: 'SCHEDULED',
    team1_id: cm.side_a.team_id || null,
    team1_display: cm.side_a.team_display || 'TBD',
    team2_id: cm.side_b.team_id || null,
    team2_display: cm.side_b.team_display || 'TBD',
    score_display: null,
    source_match_a_id: null,
    source_match_b_id: null,
    created_at: null,
    started_at: null,
    completed_at: null,
    winner_display: null,
    winner_team_id: null,
    duration_minutes: 0,
    team1_defaulted: false,
    team2_defaulted: false,
    team1_notes: cm.team1_notes || null,
    team2_notes: cm.team2_notes || null,
    slot_id: cm.slot_id || null,
    assignment_id: null,
    court_number: null,
    day_date: null,
  })

  const waitingBoardEntries = filteredSlotSections.flatMap((section) => {
    const actionableCheckInMatchesForSection = getSectionCheckInMatches(section)
    const rowEntries: Array<{ baseMatch: DeskMatchItem | null; cm: CheckInMatchItem | null }> =
      actionableCheckInMatchesForSection.length > 0
        ? actionableCheckInMatchesForSection.map((cm) => ({
            cm,
            baseMatch: matchById.get(cm.match_id) || null,
          }))
        : section.matches
            .filter((baseMatch) => {
              const cm = checkInByMatchId.get(baseMatch.match_id)
              return !cm || !cm.match_ready
            })
            .map((baseMatch) => ({
              baseMatch,
              cm: checkInByMatchId.get(baseMatch.match_id) || null,
            }))

    return rowEntries.map(({ baseMatch, cm }) => {
      const match = baseMatch || (cm ? buildFallbackDeskMatch(cm) : null)
      if (!match) return null
      const disabledState: MatchCheckInSideState = {
        side: 'A',
        team_id: match.team1_id,
        team_display: match.team1_display,
        team_checked_in: false,
        team_checked_in_at: null,
        show_towels: false,
        players: [],
        players_checked_in: 0,
        players_total: 0,
        side_ready: false,
        ready_at: null,
      }
      return {
        key: `${section.key}-${match.match_id}-${cm?.match_id || 'row'}`,
        slotKey: section.key,
        slotLabel: section.label,
        match,
        checkinMatch: cm,
        checkinEnabled: !!cm?.checkin_enabled,
        sideA: cm?.side_a ?? disabledState,
        sideB: cm?.side_b ?? {
          ...disabledState,
          side: 'B',
          team_id: match.team2_id,
          team_display: match.team2_display,
        },
      }
    }).filter((entry): entry is {
      key: string
      slotKey: string
      slotLabel: string
      match: DeskMatchItem
      checkinMatch: CheckInMatchItem | null
      checkinEnabled: boolean
      sideA: MatchCheckInSideState
      sideB: MatchCheckInSideState
    } => entry !== null)
  })
  const waitingBoardGroups = filteredSlotSections
    .map((section) => ({
      key: section.key,
      label: section.label,
      entries: waitingBoardEntries.filter((entry) => entry.slotKey === section.key),
    }))
    .filter((group) => group.entries.length > 0)

  const filteredReadyQueue = data.ready_queue.filter((rq) => (
    effectiveSelectedCheckInSlotKey === 'all' ||
    slotKeyByMatchId.get(rq.match_id) === effectiveSelectedCheckInSlotKey
  ))

  // Matches in the ready queue are waiting for court assignment; they should
  // not count as occupying a court on the board (which would make that court
  // appear "current" and then pop to "open" when dragged away).
  const readyMatchIds = new Set((data.ready_queue || []).map((rq) => rq.match_id))

  const courtBoardRows = data.courts.map((court) => {
    const now = data.now_playing_by_court[court]
    const upNextRaw = data.up_next_by_court[court]
    const onDeckRaw = data.on_deck_by_court[court]
    const upNext = upNextRaw && !readyMatchIds.has(upNextRaw.match_id) ? upNextRaw : undefined
    const onDeck = onDeckRaw && !readyMatchIds.has(onDeckRaw.match_id) ? onDeckRaw : undefined
    const courtLabel = court.replace(/^Court\s+/i, '')
    const isClosed = Boolean(courtStates[courtLabel]?.is_closed)
    // In check-in management we only render a court card as occupied when the
    // match is actively playing/paused. Scheduled up-next/on-deck matches should
    // remain in waiting/ready lanes and not duplicate onto courts.
    const displayMatch = now || null
    const matchSlotKey = displayMatch ? (slotKeyByMatchId.get(displayMatch.match_id) || null) : null
    const matchSlotIndex = matchSlotKey != null ? (slotOrderByKey.get(matchSlotKey) ?? null) : null
    const availableSlotsForCourt = visibleReadyAssignSlots.filter(
      (slot) => slot.court_name === court
    )
    let lane: 'current' | 'open' = 'open'
    let slotStateLabel = isClosed ? 'Closed' : 'Open'
    let slotStateColor = isClosed
      ? { bg: '#eceff1', color: '#455a64' }
      : { bg: '#e8f5e9', color: '#2e7d32' }

    if (now) {
      lane = 'current'
      if (matchSlotKey) {
        slotStateLabel = 'Current Slot'
        slotStateColor = { bg: '#e8f5e9', color: '#2e7d32' }
      } else {
        slotStateLabel = 'Assigned'
        slotStateColor = { bg: '#ede7f6', color: '#5e35b1' }
      }
    } else if (!isClosed && availableSlotsForCourt.length > 0) {
      slotStateLabel = 'Open'
      slotStateColor = { bg: '#e8f5e9', color: '#2e7d32' }
    }

    return {
      court,
      now,
      upNext,
      onDeck,
      displayMatch,
      isClosed,
      lane,
      slotKey: matchSlotKey,
      slotLabel: matchSlotKey ? (slotLabelByKey.get(matchSlotKey) || null) : null,
      slotTintIndex: matchSlotIndex,
      slotStateLabel,
      slotStateColor,
      startAtLabel: formatStartedAtLabel(displayMatch?.started_at),
      elapsedLabel: formatElapsedLabel(displayMatch?.started_at, displayMatch?.completed_at),
      availableSlotsForCourt,
    }
  })

  const currentCourtRows = courtBoardRows.filter((row) => row.lane === 'current')
  const openCourtRows = courtBoardRows.filter(
    (row) => row.lane === 'open' && !row.isClosed && row.availableSlotsForCourt.length > 0
  )

  const getCompactDivisionLabel = (matchCode?: string | null): string => {
    const code = (matchCode || '').toUpperCase()
    if (code.includes('_WF_')) return 'WF'
    if (code.includes('BWW') || code.includes('POOLA')) return 'DIV I'
    if (code.includes('BWL') || code.includes('POOLB')) return 'DIV II'
    if (code.includes('BLW') || code.includes('POOLC')) return 'DIV III'
    if (code.includes('BLL') || code.includes('POOLD')) return 'DIV IV'
    if (code.includes('POOLE')) return 'DIV V'
    return 'DIV'
  }

  const renderCheckInPlayerCircle = (
    checked: boolean,
    disabled: boolean,
    onClick?: () => void
  ) => (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        width: 16,
        height: 16,
        borderRadius: 999,
        border: `1px solid ${checked ? '#2e7d32' : '#90a4ae'}`,
        backgroundColor: checked ? '#2e7d32' : '#fff',
        color: '#fff',
        fontSize: 9,
        lineHeight: '14px',
        textAlign: 'center',
        flexShrink: 0,
        padding: 0,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
      }}
    >
      {checked ? '✓' : ''}
    </button>
  )

  const renderCheckInTeamInline = (
    entry: {
      checkinMatch: CheckInMatchItem | null
      checkinEnabled: boolean
    },
    side: 'A' | 'B',
    state: MatchCheckInSideState
  ) => {
    const cm = entry.checkinMatch
    const teamLabel = (state.team_display || 'TBD').trim()
    const fullTeamChecked = state.team_checked_in || (
      state.players_total > 0 && state.players_checked_in >= state.players_total
    )
    const playerSlots = [0, 1].map((index) => {
      const player = state.players[index]
      return {
        key: `${state.team_id || state.team_display}-${player?.player_id || index}`,
        towelColor: player?.towel_color || null,
        reportUrl: player?.report_url || null,
        checked: Boolean(state.team_checked_in || player?.checked_in),
        disabled: !entry.checkinEnabled || !cm,
        onClick: (entry.checkinEnabled && cm)
          ? () => (
              player?.player_id != null
                ? handlePlayerCheckIn(cm, side, player.player_id, !Boolean(state.team_checked_in || player.checked_in))
                : handleSideTeamCheckIn(cm, side, state)
            )
          : undefined,
      }
    })
    const leftPlayer = playerSlots[0]
    const rightPlayer = playerSlots[1]
    const teamControl = (
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'auto auto auto auto auto',
        gap: 4,
        alignItems: 'center',
        justifyContent: 'center',
        minWidth: 0,
      }}>
        {leftPlayer.towelColor ? (
          <TowelColorPill colorName={leftPlayer.towelColor} reportUrl={leftPlayer.reportUrl} labelMode="swatch" />
        ) : <span style={{ width: 24, height: 14, display: 'inline-block' }} />}
        {renderCheckInPlayerCircle(leftPlayer.checked, leftPlayer.disabled, leftPlayer.onClick)}
        <span style={{
          minWidth: 0,
          whiteSpace: 'nowrap',
          fontSize: 11,
          color: '#37474f',
          fontWeight: 700,
          textAlign: 'center',
        }}>
          {teamLabel}
        </span>
        {renderCheckInPlayerCircle(rightPlayer.checked, rightPlayer.disabled, rightPlayer.onClick)}
        {rightPlayer.towelColor ? (
          <TowelColorPill colorName={rightPlayer.towelColor} reportUrl={rightPlayer.reportUrl} labelMode="swatch" />
        ) : <span style={{ width: 24, height: 14, display: 'inline-block' }} />}
      </div>
    )
    const checkInButton = (
      <button
        type="button"
        disabled={!entry.checkinEnabled}
        onClick={() => entry.checkinEnabled && cm && handleSideTeamCheckIn(cm, side, state)}
        style={{
          padding: '4px 8px',
          fontSize: 10,
          fontWeight: 700,
          borderRadius: 6,
          border: '1px solid #90a4ae',
          backgroundColor: fullTeamChecked ? '#2e7d32' : '#fff',
          color: fullTeamChecked ? '#fff' : '#455a64',
          cursor: entry.checkinEnabled ? 'pointer' : 'default',
          opacity: entry.checkinEnabled ? 1 : 0.5,
          whiteSpace: 'nowrap',
        }}
      >
        CHECK-IN
      </button>
    )

    return (
      <div style={{
        display: 'grid',
        gridTemplateColumns: side === 'B' ? 'auto minmax(0,1fr)' : 'minmax(0,1fr) auto',
        gap: 10,
        alignItems: 'center',
        minWidth: 0,
      }}>
        {side === 'B' && checkInButton}
        {teamControl}
        {side !== 'B' && checkInButton}
      </div>
    )
  }

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
            onClick={() => {
              if (!tid) return
              window.open(`/desk/t/${tid}/draws-display?kiosk=1`, '_blank', 'noopener,noreferrer')
            }}
            style={{
              padding: '6px 14px',
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: 'rgba(255,255,255,0.2)',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: tid ? 'pointer' : 'default',
            }}
          >
            Draws Display
          </button>
          <button
            onClick={() => {
              if (!tid) return
              window.open(`/desk/t/${tid}/checkin-board?kiosk=1`, '_blank', 'noopener,noreferrer')
            }}
            style={{
              padding: '6px 14px',
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: 'rgba(255,255,255,0.2)',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: tid ? 'pointer' : 'default',
            }}
          >
            Check-In Display
          </button>
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
        flexWrap: 'wrap',
        gap: 0,
        backgroundColor: '#fff',
        borderBottom: '2px solid #e0e0e0',
        paddingLeft: 24,
        paddingRight: 24,
      }}>
        {visibleTabs.map(tab => (
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
              textTransform: tab === 'checkin' || tab === 'sms' || tab === 'text_list' ? 'none' : 'capitalize',
              marginBottom: -2,
            }}
          >
            {tab === 'checkin' ? 'Check-In' : tab === 'towels' ? 'Towels' : tab === 'sms' ? 'SMS' : tab === 'text_list' ? 'Text List' : tab}
          </button>
        ))}
      </div>

      <div style={{ padding: '16px 24px' }}>
        {/* Courts Tab */}
        {false && activeTab === 'courts' && (
          <>
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, position: 'relative' }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: '#333', margin: 0 }}>
                  Courts
                </h2>
                {isDraft && startableCourts.length > 0 && !isCheckInManagement && (
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
                {visibleCourts.map(court => {
                  const courtLabel = court.replace(/^Court\s+/i, '')
                  const courtMatches = (data?.matches || [])
                    .filter(m => m.court_name === court && m.status === 'FINAL')
                    .sort((a, b) => (a.day_index - b.day_index) || (a.sort_time || '').localeCompare(b.sort_time || ''))
                  return (
                    <CourtCard
                      key={court}
                      courtName={court}
                      nowPlaying={data?.now_playing_by_court[court]}
                      upNext={data?.up_next_by_court[court]}
                      onDeck={data?.on_deck_by_court[court]}
                      isDraft={isDraft}
                      onAction={handleAction}
                      courtState={courtStates[courtLabel]}
                      onCourtStateChange={handleCourtStateChange}
                      courtMatches={courtMatches}
                      allMatches={data?.matches || []}
                      onMatchClick={m => setDrawerMatch(m)}
                      onSmsTeamClick={handleQuickSmsTeam}
                      onSmsMatchClick={handleQuickSmsMatch}
                    />
                  )
                })}
                {visibleCourts.length === 0 && (
                  <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>
                    No courts with matches right now
                  </div>
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
                    {searchResults!.length} result{searchResults!.length !== 1 ? 's' : ''}
                  </div>
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                    gap: 8,
                  }}>
                    {searchResults!.map(m => (
                      <div
                        key={m.match_id}
                        onClick={() => setDrawerMatch(m)}
                        style={{ cursor: 'pointer' }}
                      >
                        <MiniMatchCard match={m} isDraft={isDraft} onAction={handleAction} allMatches={data?.matches || []} />
                      </div>
                    ))}
                  </div>
                  {searchResults!.length === 0 && (
                    <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>No matches found</div>
                  )}
                </div>
              )}
            </div>
            </div>
          </>
        )}

        {/* Check-In Tab */}
        {activeTab === 'checkin' && (
          <div>
            {!isCheckInManagement ? (
              <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>
                Enable Check-In Management from Actions in the Courts tab.
              </div>
            ) : (
              <>
                <div style={{ display: 'grid', gap: 14 }}>
                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 8, backgroundColor: '#fff', overflow: 'hidden' }}>
                    <div style={{ padding: '10px 12px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 800, color: '#1565c0', backgroundColor: '#f4f9ff' }}>
                      Currently Playing
                    </div>
                    <div style={{ padding: 12 }}>
                      {currentCourtRows.length === 0 ? (
                        <div style={{ fontSize: 12, color: '#90a4ae' }}>No active courts in this view yet.</div>
                      ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(10, minmax(0, 1fr))', gap: 8 }}>
                          {currentCourtRows.map((row) => (
                            <CheckInCourtBoardCard
                              key={row.court}
                              row={row}
                              focusSlotLabel={focusSlotLabel}
                              onOpenMatch={setDrawerMatch}
                              slotTintIndex={row.slotTintIndex}
                              nativeDragOverCourt={nativeDragOverCourt}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 8, backgroundColor: '#fff', overflow: 'hidden' }}>
                    <div style={{ padding: '10px 12px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 800, color: '#2e7d32', backgroundColor: '#f4fbf5' }}>
                      Open Courts
                    </div>
                    <div style={{ padding: 12 }}>
                      {openCourtRows.length === 0 ? (
                        <div style={{ fontSize: 12, color: '#90a4ae' }}>All courts currently have an assignment or are hidden by status.</div>
                      ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(10, minmax(0, 1fr))', gap: 8 }}>
                          {openCourtRows.map((row) => (
                            <CheckInCourtBoardCard
                              key={row.court}
                              row={row}
                              focusSlotLabel={focusSlotLabel}
                              onOpenMatch={setDrawerMatch}
                              slotTintIndex={null}
                              nativeDragOverCourt={nativeDragOverCourt}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 14, alignItems: 'start' }}>
                    <div style={{ border: '1px solid #dfe4ea', borderRadius: 8, backgroundColor: '#fff', overflow: 'hidden' }}>
                      <div style={{ padding: '10px 12px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 800, color: '#455a64', backgroundColor: '#fafcfe' }}>
                        Waiting For Check-In
                      </div>
                      <div style={{ padding: 12 }}>
                        {waitingBoardGroups.length === 0 ? (
                          <div style={{ fontSize: 12, color: '#90a4ae' }}>Nothing is waiting for check-in in this view.</div>
                        ) : (
                          <div style={{ display: 'grid', gap: 12 }}>
                            {waitingBoardGroups.map((group) => (
                              <div key={group.key} style={{
                                border: '1px solid #d7dee5',
                                borderRadius: 10,
                                backgroundColor: '#fff',
                                overflow: 'hidden',
                              }}>
                                <div style={{
                                  padding: '8px 10px',
                                  borderBottom: '1px solid #eef2f5',
                                  backgroundColor: '#f8fafc',
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  alignItems: 'center',
                                  gap: 10,
                                  flexWrap: 'wrap',
                                }}>
                                  <div style={{ fontSize: 13, fontWeight: 800, color: '#334155' }}>{group.label}</div>
                                  <div style={{ fontSize: 11, color: '#607d8b', fontWeight: 700 }}>
                                    {group.entries.length} match{group.entries.length !== 1 ? 'es' : ''}
                                  </div>
                                </div>
                                <div style={{ padding: 8, display: 'grid', gridTemplateColumns: '1fr', gap: 8, overflowX: 'auto' }}>
                                  {group.entries.map((entry) => (
                                    <div key={entry.key} style={{
                                      border: '1px solid #d7dee5',
                                      borderRadius: 8,
                                      padding: '6px 8px',
                                      backgroundColor: '#fff',
                                      minWidth: 'fit-content',
                                    }}>
                                      <div style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'minmax(0, 1fr) 68px minmax(0, 1fr)',
                                        gap: 8,
                                        alignItems: 'center',
                                      }}>
                                        <div>
                                          {renderCheckInTeamInline(entry, 'B', entry.sideB)}
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, whiteSpace: 'nowrap' }}>
                                          <EventBadge name={entry.match.event_name} />
                                          <Badge label={getCompactDivisionLabel(entry.match.match_code)} bg="#455a64" color="#fff" />
                                        </div>
                                        <div>
                                          {renderCheckInTeamInline(entry, 'A', entry.sideA)}
                                        </div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    <div style={{ border: '1px solid #dfe4ea', borderRadius: 8, backgroundColor: '#fff', overflow: 'hidden' }}>
                      <div style={{ padding: '10px 12px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 800, color: '#2e7d32', backgroundColor: '#f4fbf5' }}>
                        Ready To Go
                      </div>
                      <div style={{ padding: 12 }}>
                        {filteredReadyQueue.length === 0 ? (
                          <div style={{ fontSize: 12, color: '#90a4ae' }}>No fully checked-in matches are waiting right now.</div>
                        ) : (
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10 }}>
                            {filteredReadyQueue.map((rq) => {
                              const rqSlotKey = slotKeyByMatchId.get(rq.match_id) || null
                              const slotLabelResolved = rqSlotKey
                                ? slotLabelByKey.get(rqSlotKey) || null
                                : null
                              const rqSlotIndex = rqSlotKey != null ? (slotOrderByKey.get(rqSlotKey) ?? null) : null
                              const headerTop = (slotLabelResolved || `${rq.day_label} ${rq.scheduled_time || ''}`.trim()) || '—'
                              const queueElapsedLabel = formatElapsedLabel(rq.ready_at, null)
                              return (
                                <CheckInReadyQueueCard
                                  key={rq.match_id}
                                  rq={rq}
                                  titleLabel={formatReadyQueueLabel(rq)}
                                  headerRightTop={headerTop}
                                  queueElapsedLabel={queueElapsedLabel}
                                  deskMatch={matchById.get(rq.match_id)}
                                  returning={readyResettingIds.has(rq.match_id)}
                                  onReturnToCheckIn={() => handleResetReadyMatch(rq.match_id)}
                                  slotTintIndex={rqSlotIndex}
                                  nativeDragging={nativeDraggedReadyMatchId === rq.match_id}
                                  onPointerDragStart={handlePointerDragStart}
                                />
                              )
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
                {pointerDragGhost && (
                  <div
                    style={{
                      position: 'fixed',
                      left: pointerDragGhost.x + 12,
                      top: pointerDragGhost.y + 12,
                      width: 220,
                      pointerEvents: 'none',
                      zIndex: 9999,
                      borderRadius: 8,
                      overflow: 'hidden',
                      boxShadow: '0 12px 32px rgba(0,0,0,0.28)',
                      border: '2px solid #1a237e',
                      background: '#fff',
                    }}
                  >
                    <div style={{
                      background: '#1a237e',
                      color: '#fff',
                      padding: '6px 10px',
                      fontSize: 12,
                      fontWeight: 700,
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 6,
                    }}>
                      <span>#{pointerDragGhost.matchNumber}</span>
                      <span style={{ fontSize: 10, opacity: 0.85 }}>{pointerDragGhost.eventName}</span>
                    </div>
                    <div style={{
                      background: '#e8eaf6',
                      padding: '8px 10px',
                      fontSize: 11,
                      fontWeight: 600,
                      color: '#1a237e',
                      lineHeight: 1.5,
                    }}>
                      <div>{pointerDragGhost.team1}</div>
                      <div style={{ color: '#90a4ae', fontSize: 10, margin: '1px 0' }}>vs</div>
                      <div>{pointerDragGhost.team2}</div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Towels Tab */}
        {activeTab === 'towels' && (
          <div>
            {!isCheckInManagement ? (
              <div style={{ color: '#888', fontSize: 13, fontStyle: 'italic' }}>
                Enable Check-In Management from Actions in the Courts tab.
              </div>
            ) : (
              <>
                <div style={{ marginBottom: 10, fontSize: 13, color: '#546e7a', fontWeight: 700 }}>
                  Towel import and planning
                </div>
                <div style={{ marginBottom: 10, fontSize: 12, color: '#607d8b' }}>
                  Counts below are based on current check-in matches that are not marked ready yet.
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1.25fr 1fr', gap: 10, alignItems: 'start' }}>
                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 6, backgroundColor: '#fff' }}>
                    <div style={{ padding: '8px 10px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 700, color: '#1a237e' }}>
                      Towel Import
                    </div>
                    <div style={{ padding: 10 }}>
                      <div style={{ marginBottom: 12, padding: 10, border: '1px solid #e2e8f0', borderRadius: 6, backgroundColor: '#f8fafc' }}>
                        <div style={{ fontSize: 12, color: '#334155', fontWeight: 700, marginBottom: 8 }}>
                          Add Player Manually
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1.5fr auto', gap: 8, alignItems: 'end' }}>
                          <div>
                            <div style={{ fontSize: 11, color: '#607d8b', marginBottom: 4 }}>Player Name</div>
                            <input
                              type="text"
                              value={lookupNewDraft.source_name}
                              onChange={e => setLookupNewDraft(prev => ({ ...prev, source_name: e.target.value }))}
                              placeholder="Player name"
                              style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box' }}
                            />
                          </div>
                          <div>
                            <div style={{ fontSize: 11, color: '#607d8b', marginBottom: 4 }}>Towel Color</div>
                            <input
                              type="text"
                              value={lookupNewDraft.towel_color}
                              onChange={e => setLookupNewDraft(prev => ({ ...prev, towel_color: e.target.value }))}
                              placeholder="Lime"
                              style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box' }}
                            />
                          </div>
                          <div>
                            <div style={{ fontSize: 11, color: '#607d8b', marginBottom: 4 }}>Report URL</div>
                            <input
                              type="text"
                              value={lookupNewDraft.report_url}
                              onChange={e => setLookupNewDraft(prev => ({ ...prev, report_url: e.target.value }))}
                              placeholder="https://..."
                              style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box' }}
                            />
                          </div>
                          <button
                            type="button"
                            onClick={handleCreateLookup}
                            disabled={lookupCreating}
                            style={{
                              padding: '7px 12px',
                              border: 'none',
                              borderRadius: 4,
                              backgroundColor: '#2e7d32',
                              color: '#fff',
                              fontSize: 12,
                              fontWeight: 700,
                              cursor: lookupCreating ? 'default' : 'pointer',
                              opacity: lookupCreating ? 0.6 : 1,
                              height: 32,
                            }}
                          >
                            {lookupCreating ? 'Adding...' : 'Add'}
                          </button>
                        </div>
                      </div>
                      <div style={{ fontSize: 12, color: '#546e7a', marginBottom: 6 }}>
                        Paste Excel rows with exactly these headers: <strong>Player Name</strong>, <strong>Towel Color</strong>, <strong>Report URL</strong>. Leave the report URL cell blank if you do not want the pill clickable.
                      </div>
                      <textarea
                        value={lookupImportText}
                        onChange={e => setLookupImportText(e.target.value)}
                        placeholder={'Player Name\tTowel Color\tReport URL'}
                        style={{ width: '100%', minHeight: 92, padding: '8px 10px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box', resize: 'vertical' }}
                      />
                      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          onClick={handleImportTemporaryLookups}
                          disabled={lookupImporting || lookupClearing}
                          style={{
                            padding: '6px 12px',
                            border: 'none',
                            borderRadius: 4,
                            backgroundColor: '#1a237e',
                            color: '#fff',
                            fontSize: 12,
                            fontWeight: 700,
                            cursor: (lookupImporting || lookupClearing) ? 'default' : 'pointer',
                            opacity: (lookupImporting || lookupClearing) ? 0.6 : 1,
                          }}
                        >
                          {lookupImporting ? 'Importing...' : 'Import Towel Data'}
                        </button>
                        <button
                          type="button"
                          onClick={handleClearAllLookups}
                          disabled={lookupClearing || lookupImporting || lookupItems.length === 0}
                          style={{
                            padding: '6px 12px',
                            border: '1px solid #ef9a9a',
                            borderRadius: 4,
                            backgroundColor: '#fff5f5',
                            color: '#c62828',
                            fontSize: 12,
                            fontWeight: 700,
                            cursor: (lookupClearing || lookupImporting || lookupItems.length === 0) ? 'default' : 'pointer',
                            opacity: (lookupClearing || lookupImporting || lookupItems.length === 0) ? 0.6 : 1,
                          }}
                        >
                          {lookupClearing ? 'Clearing...' : 'Clear All Towels'}
                        </button>
                        <span style={{ fontSize: 12, color: '#546e7a' }}>
                          {lookupItems.length} imported row{lookupItems.length === 1 ? '' : 's'}
                        </span>
                        <span style={{ fontSize: 12, color: '#2e7d32', fontWeight: 700 }}>
                          {matchedLookupCount} matched
                        </span>
                        <span style={{ fontSize: 12, color: unmatchedLookupCount > 0 ? '#ef6c00' : '#607d8b', fontWeight: 700 }}>
                          {unmatchedLookupCount} unmatched
                        </span>
                        {lookupMessage && (
                          <span style={{ fontSize: 12, color: lookupMessage.toLowerCase().includes('fail') ? '#c62828' : '#2e7d32' }}>
                            {lookupMessage}
                          </span>
                        )}
                      </div>
                      {lookupItems.length > 0 && (
                        <div style={{ marginTop: 10, maxHeight: 300, overflow: 'auto', borderTop: '1px solid #eef2f5', paddingTop: 8 }}>
                          <div style={{ fontSize: 12, color: '#334155', fontWeight: 700, marginBottom: 8 }}>
                            Color Table
                          </div>
                          <div style={{ display: 'grid', gap: 8 }}>
                            {lookupItems.map((item) => {
                              const draft = lookupDrafts[item.id] || toLookupDraft(item)
                              const saving = lookupSavingIds.has(item.id)
                              const deleting = lookupDeletingIds.has(item.id)
                              return (
                                <div key={item.id} style={{ display: 'grid', gridTemplateColumns: '1.45fr 1fr 1.4fr auto auto', gap: 8, alignItems: 'center', padding: '6px 0', fontSize: 12, color: '#455a64', borderBottom: '1px dotted #eef2f5' }}>
                                  <input
                                    type="text"
                                    value={draft.source_name}
                                    onChange={e => handleLookupDraftChange(item.id, 'source_name', e.target.value)}
                                    style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box' }}
                                  />
                                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, alignItems: 'center' }}>
                                    <input
                                      type="text"
                                      value={draft.towel_color}
                                      onChange={e => handleLookupDraftChange(item.id, 'towel_color', e.target.value)}
                                      style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box' }}
                                    />
                                    <div style={{ minHeight: 18, display: 'flex', alignItems: 'center' }}>
                                      <TowelColorPill colorName={draft.towel_color || null} reportUrl={draft.report_url || null} />
                                    </div>
                                  </div>
                                  <input
                                    type="text"
                                    value={draft.report_url}
                                    onChange={e => handleLookupDraftChange(item.id, 'report_url', e.target.value)}
                                    placeholder="https://..."
                                    style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e1', fontSize: 12, boxSizing: 'border-box' }}
                                  />
                                  <div style={{ display: 'grid', gap: 4, justifyItems: 'start' }}>
                                    <span style={{ color: item.matched ? '#2e7d32' : '#ef6c00', fontWeight: 700 }}>
                                      {item.matched ? 'Matched' : 'Unmatched'}
                                    </span>
                                    <button
                                      type="button"
                                      onClick={() => handleSaveLookup(item.id)}
                                      disabled={saving || deleting}
                                      style={{
                                        padding: '5px 10px',
                                        border: 'none',
                                        borderRadius: 4,
                                        backgroundColor: '#1565c0',
                                        color: '#fff',
                                        fontSize: 11,
                                        fontWeight: 700,
                                        cursor: (saving || deleting) ? 'default' : 'pointer',
                                        opacity: (saving || deleting) ? 0.6 : 1,
                                      }}
                                    >
                                      {saving ? 'Saving...' : 'Save'}
                                    </button>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => handleDeleteLookup(item.id)}
                                    disabled={saving || deleting}
                                    style={{
                                      padding: '5px 10px',
                                      border: '1px solid #ef9a9a',
                                      borderRadius: 4,
                                      backgroundColor: '#fff5f5',
                                      color: '#c62828',
                                      fontSize: 11,
                                      fontWeight: 700,
                                      cursor: (saving || deleting) ? 'default' : 'pointer',
                                      opacity: (saving || deleting) ? 0.6 : 1,
                                    }}
                                  >
                                    {deleting ? 'Removing...' : 'Remove'}
                                  </button>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 6, backgroundColor: '#fff' }}>
                    <div style={{ padding: '8px 10px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 700, color: '#1a237e' }}>
                      Overall Color Totals
                    </div>
                    <div style={{ padding: 10 }}>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                        <div style={{ padding: '8px 10px', borderRadius: 6, backgroundColor: '#f8fafc', border: '1px solid #e2e8f0', minWidth: 108 }}>
                          <div style={{ fontSize: 11, color: '#607d8b', textTransform: 'uppercase', fontWeight: 700 }}>Total Towels</div>
                          <div style={{ fontSize: 22, fontWeight: 800, color: '#1e293b' }}>{towelOverallTotal}</div>
                        </div>
                        <div style={{ padding: '8px 10px', borderRadius: 6, backgroundColor: '#f8fafc', border: '1px solid #e2e8f0', minWidth: 108 }}>
                          <div style={{ fontSize: 11, color: '#607d8b', textTransform: 'uppercase', fontWeight: 700 }}>Colors Used</div>
                          <div style={{ fontSize: 22, fontWeight: 800, color: '#1e293b' }}>{towelOverallCounts.length}</div>
                        </div>
                        <div style={{ padding: '8px 10px', borderRadius: 6, backgroundColor: '#f8fafc', border: '1px solid #e2e8f0', minWidth: 108 }}>
                          <div style={{ fontSize: 11, color: '#607d8b', textTransform: 'uppercase', fontWeight: 700 }}>Time Slots</div>
                          <div style={{ fontSize: 22, fontWeight: 800, color: '#1e293b' }}>{towelSlotSummaries.length}</div>
                        </div>
                      </div>
                      {towelOverallCounts.length === 0 ? (
                        <div style={{ fontSize: 12, color: '#888' }}>No towel colors are attached to the current not-ready check-in matches.</div>
                      ) : (
                        <div style={{ display: 'grid', gap: 8 }}>
                          {towelOverallCounts.map((row) => (
                            <TowelCountBar key={row.colorName} colorName={row.colorName} count={row.count} maxCount={towelOverallMax} />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: 10, border: '1px solid #dfe4ea', borderRadius: 6, backgroundColor: '#fff' }}>
                  <div style={{ padding: '8px 10px', borderBottom: '1px solid #eef2f5', fontSize: 14, fontWeight: 700, color: '#1a237e' }}>
                    Color Totals By Time Slot
                  </div>
                  <div style={{ padding: 10 }}>
                    {towelSlotSummaries.length === 0 ? (
                      <div style={{ fontSize: 12, color: '#888' }}>No time slots currently need towels.</div>
                    ) : (
                      <div style={{ display: 'grid', gap: 10 }}>
                        {towelSlotSummaries.map((section) => (
                          <div key={section.key} style={{ border: '1px solid #e2e8f0', borderRadius: 6, padding: 10, backgroundColor: '#fcfdff' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                              <div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>{section.label}</div>
                                <div style={{ fontSize: 11, color: '#607d8b' }}>
                                  {section.matchCount} match{section.matchCount === 1 ? '' : 'es'} needing check-in
                                </div>
                              </div>
                              <div style={{ padding: '5px 9px', borderRadius: 999, backgroundColor: '#e8f0fe', color: '#1a237e', fontSize: 12, fontWeight: 800 }}>
                                {section.totalTowels} total towels
                              </div>
                            </div>
                            <div style={{ display: 'grid', gap: 8 }}>
                              {section.counts.map((row) => (
                                <TowelCountBar key={`${section.key}-${row.colorName}`} colorName={row.colorName} count={row.count} maxCount={towelSlotMax} />
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
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

        {activeTab === 'sms' && (
          <SmsAdminTab
            tournamentId={tid!}
            quickTarget={smsQuickTarget}
            managementMode={'checkin_management'}
          />
        )}

        {activeTab === 'text_list' && (
          <TextListTab tournamentId={tid!} />
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

      {checkInNotePrompt && (
        <CheckInNoteModal
          teamLabel={checkInNotePrompt.teamLabel}
          note={checkInNotePrompt.note}
          busy={checkInNoteBusy}
          onKeep={handleKeepCheckInNote}
          onDelete={handleDeleteCheckInNote}
          onCancel={() => !checkInNoteBusy && setCheckInNotePrompt(null)}
        />
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

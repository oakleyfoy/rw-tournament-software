import { useState, type CSSProperties } from 'react'
import type { SimulationSlot, SimulationSummary } from '../../api/client'

type Props = {
  dayLabel: string
  slots: SimulationSlot[]
  selected: string | null
  busy: boolean
  summary: SimulationSummary | null
  error: string | null
  onSelect: (startTime: string) => void
  onSimulate: () => void
  onAdvance: () => void
  onClose: () => void
}

export default function SimulateResultsDialog({
  dayLabel, slots, selected, busy, summary, error, onSelect, onSimulate, onAdvance, onClose,
}: Props) {
  const [showNotes, setShowNotes] = useState(false)
  const chosen = slots.find((slot) => slot.start_time === selected) || null
  return (
    <div role="presentation" onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div role="dialog" aria-label="Simulate results" onClick={(event) => event.stopPropagation()} style={{ width: 520, maxWidth: '100%', maxHeight: '86vh', overflow: 'auto', background: '#fff', borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800 }}>Simulate results</div>
            <div style={{ fontSize: 12, color: '#546e7a' }}>{dayLabel}</div>
          </div>
          <button type="button" onClick={onClose} style={quietButton}>Close</button>
        </div>
        <div style={{ display: 'grid', gap: 6 }}>
          {slots.map((slot) => (
            <button key={slot.start_time} type="button" onClick={() => onSelect(slot.start_time)} style={slotRow(selected === slot.start_time)}>
              <b>{slot.label}</b>
              <span>{slot.match_count} matches</span>
              <span>{slot.completed} completed</span>
              <span>{slot.active} active</span>
              <span>{slot.remaining} remaining</span>
            </button>
          ))}
          {slots.length === 0 && <div style={{ fontSize: 13 }}>This day has no scheduled matches.</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" disabled={busy || !chosen} onClick={onSimulate} style={primaryButton(busy || !chosen)}>
            {busy ? 'Simulating…' : 'Simulate All Matches'}
          </button>
          <button type="button" disabled={busy || !summary} onClick={onAdvance} style={quietButton}>
            Advance to Next Time Slot
          </button>
        </div>
        {error && <div style={{ color: '#b71c1c', fontWeight: 700, fontSize: 13 }}>{error}</div>}
        {summary && (
          <div style={{ display: 'grid', gap: 6, fontSize: 13 }}>
            <div style={{ fontWeight: 800 }}>{summary.slot_label}</div>
            <div>{summary.completed} completed · {summary.skipped} already completed · {summary.blocked} blocked · {summary.failed} failed</div>
            <div>{summary.notification_count} next-match notices prepared. No texts were sent.</div>
            <button type="button" onClick={() => setShowNotes((open) => !open)} style={quietButton}>
              {showNotes ? 'Hide notices' : 'Show notices'}
            </button>
            {summary.results.map((row) => (
              <div key={row.match_id} style={{ borderTop: '1px solid #eceff1', paddingTop: 4 }}>
                <b>Court {row.court}</b> {row.match_code} · {row.team1} vs {row.team2}
                {row.score && <span> · {row.winner} {row.score}</span>}
                {row.reason && <div style={{ color: row.status === 'failed' ? '#b71c1c' : '#546e7a' }}>{row.reason}</div>}
                {showNotes && (row.notifications || []).map((notice, index) => (
                  <div key={index} style={{ color: '#37474f' }}>{notice.team_name}: {notice.message}</div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

const slotRow = (active: boolean): CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: '88px repeat(4, 1fr)',
  gap: 6,
  textAlign: 'left',
  border: `1px solid ${active ? '#1a237e' : '#cfd8dc'}`,
  background: active ? '#e8eaf6' : '#fff',
  borderRadius: 8,
  padding: '6px 8px',
  fontSize: 12,
  cursor: 'pointer',
})

const primaryButton = (disabled: boolean): CSSProperties => ({
  border: 'none',
  background: disabled ? '#b0bec5' : '#1a237e',
  color: '#fff',
  borderRadius: 999,
  padding: '8px 14px',
  fontWeight: 800,
  cursor: disabled ? 'default' : 'pointer',
})

const quietButton: CSSProperties = {
  border: '1px solid #cfd8dc',
  background: '#fff',
  borderRadius: 999,
  padding: '8px 14px',
  fontWeight: 700,
  cursor: 'pointer',
}

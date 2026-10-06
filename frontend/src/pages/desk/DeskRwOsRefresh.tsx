import { useRef, useState, type ReactNode } from 'react'
import { refreshRwOsImport, type RwOsImportResponse } from '../../api/client'

type SnapshotTeam = {
  teamKey?: string
  displayName?: string
  display_name?: string
  fullName?: string
  full_name?: string
  drawLabel?: string
  draw_label?: string
  drawKind?: string
  player1?: { name?: string; towelColor?: string; towel_color?: string }
  player2?: { name?: string; towelColor?: string; towel_color?: string }
}

type FieldChange = {
  teamKey?: string
  teamLabel?: string
  drawLabel?: string
  playerName?: string
  field?: string
  before?: string | null
  after?: string | null
}

type OperationalDrift = {
  reconciliationNeeded?: boolean
  missingFromEvent?: string[]
  extraInEvent?: string[]
  missingFromDraw?: string[]
  extraInDraw?: string[]
}

type RefreshDiff = {
  changed?: boolean
  addedTeams?: SnapshotTeam[]
  withdrawnTeams?: SnapshotTeam[]
  partnerChanges?: Array<{ teamKey?: string }>
  drawChanges?: Array<{ teamKey?: string; before?: string | null; after?: string | null }>
  ratingChanges?: Array<{ teamKey?: string; before?: number | null; after?: number | null }>
  contactChanges?: FieldChange[]
  towelChanges?: FieldChange[]
  avoidGroupChanges?: FieldChange[]
  operationalDrift?: OperationalDrift
}

function sourceRosterUnchanged(diff: RefreshDiff | undefined): boolean {
  if (!diff) return false
  return !(
    (diff.addedTeams || []).length ||
    (diff.withdrawnTeams || []).length ||
    (diff.partnerChanges || []).length ||
    (diff.drawChanges || []).length ||
    (diff.ratingChanges || []).length ||
    (diff.contactChanges || []).length ||
    (diff.towelChanges || []).length ||
    (diff.avoidGroupChanges || []).length
  )
}

type RefreshResult = {
  diff: RefreshDiff
  applied: boolean
  rosterProjection?: RwOsImportResponse['rosterProjection']
}

type Notice = { code?: string; message?: string }

const STAFF_WARNING_CODES = new Set([
  'draw_slot_left_open',
  'roster_draw_placement_unresolved',
  'roster_reconciliation_blocked',
  'team_would_move',
  'draw_protection',
  'live_draw_protection_blocks_structural_change',
])

function teamLabel(team: SnapshotTeam): string {
  return team.displayName || team.display_name || team.fullName || team.full_name || team.teamKey || 'Team'
}

function drawLabel(team: SnapshotTeam): string {
  return team.drawLabel || team.draw_label || team.drawKind || 'Event'
}

function towelPair(team: SnapshotTeam): string {
  const first = team.player1?.towelColor || team.player1?.towel_color || '—'
  const second = team.player2?.towelColor || team.player2?.towel_color || '—'
  return `${first} / ${second}`
}

function showValue(value: string | null | undefined): string {
  return value == null || value === '' ? '—' : value
}

export function staffAttentionItems(result: RefreshResult | null): Notice[] {
  if (!result?.rosterProjection) return []
  const warnings = result.rosterProjection.warnings || []
  const conflicts = result.rosterProjection.conflicts || []
  return [...conflicts, ...warnings].filter((item) => STAFF_WARNING_CODES.has(item.code || ''))
}

function countLine(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`
}

export function appliedSummaryLines(result: RefreshResult | null): string[] {
  const projection = result?.rosterProjection
  if (!projection) return []
  const towelUpdates = (projection.created?.towelRows ?? 0) + (projection.updated?.towelRows ?? 0)
  return [
    countLine(projection.created?.teams ?? 0, 'team added', 'teams added'),
    countLine(projection.reconciled?.withdrawnTeams ?? 0, 'team withdrawn', 'teams withdrawn'),
    countLine(projection.updated?.contactFields ?? 0, 'player/contact change', 'player/contact changes'),
    countLine(towelUpdates, 'towel update', 'towel updates'),
    countLine(projection.created?.wkwEdges ?? 0, 'Who-Knows-Who update', 'Who-Knows-Who updates'),
    countLine(projection.reconciled?.drawSlotsReplaced ?? 0, 'draw position updated', 'draw positions updated'),
  ]
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 16 }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 13, letterSpacing: 0.4 }}>{title}</h3>
      {children}
    </section>
  )
}

function ChangeCard({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: '8px 10px', marginBottom: 8, background: '#f7f7f7', borderRadius: 6, fontSize: 14 }}>
      {children}
    </div>
  )
}

function PreviewBody({ diff }: { diff: RefreshDiff }) {
  const added = diff.addedTeams || []
  const withdrawn = diff.withdrawnTeams || []
  const contacts = (diff.contactChanges || []).filter((change) => change.field !== 'name' || change.before !== change.after)
  const towels = diff.towelChanges || []
  const avoid = diff.avoidGroupChanges || []
  const drift = diff.operationalDrift
  return (
    <div data-testid="rw-os-change-preview">
      {drift?.reconciliationNeeded && (
        <Section title="LOCAL ROSTER DRIFT">
          <ChangeCard>
            <div>Tournament Software event or draw membership does not match the current RW-OS roster.</div>
          </ChangeCard>
        </Section>
      )}
      {added.length > 0 && (
        <Section title="NEW TEAM">
          {added.map((team) => (
            <ChangeCard key={team.teamKey}>
              <div>{drawLabel(team)}</div>
              <strong>{teamLabel(team)}</strong>
              <div>Towels: {towelPair(team)}</div>
            </ChangeCard>
          ))}
        </Section>
      )}
      {withdrawn.length > 0 && (
        <Section title="WITHDRAWN / REMOVED">
          {withdrawn.map((team) => (
            <ChangeCard key={team.teamKey}>
              <div>{drawLabel(team)}</div>
              <strong>{teamLabel(team)}</strong>
            </ChangeCard>
          ))}
        </Section>
      )}
      {contacts.length > 0 && (
        <Section title="PLAYER / CONTACT CHANGES">
          {contacts.map((change, index) => (
            <ChangeCard key={`${change.teamKey}-${change.field}-${index}`}>
              <div>{change.drawLabel}</div>
              <strong>{change.playerName || change.teamLabel}</strong>
              <div>
                {change.field}: {showValue(change.before)} → {showValue(change.after)}
              </div>
            </ChangeCard>
          ))}
        </Section>
      )}
      {towels.length > 0 && (
        <Section title="TOWEL CHANGES">
          {towels.map((change, index) => (
            <ChangeCard key={`${change.teamKey}-towel-${index}`}>
              <div>{change.drawLabel}</div>
              <strong>{change.playerName}</strong>
              <div>
                {showValue(change.before)} → {showValue(change.after)}
              </div>
            </ChangeCard>
          ))}
        </Section>
      )}
      {avoid.length > 0 && (
        <Section title="WHO-KNOWS-WHO CHANGES">
          {avoid.map((change) => (
            <ChangeCard key={change.teamKey}>
              <div>{change.drawLabel}</div>
              <strong>{change.teamLabel}</strong>
              <div>
                Avoid Group {showValue(change.before)} → {showValue(change.after)}
              </div>
            </ChangeCard>
          ))}
        </Section>
      )}
      {(diff.partnerChanges || []).length > 0 && (
        <Section title="PARTNER CHANGES">
          {(diff.partnerChanges || []).map((change) => (
            <ChangeCard key={change.teamKey}>
              <strong>{change.teamKey}</strong>
            </ChangeCard>
          ))}
        </Section>
      )}
      {(diff.drawChanges || []).length > 0 && (
        <Section title="DRAW CHANGES">
          {(diff.drawChanges || []).map((change) => (
            <ChangeCard key={change.teamKey}>
              <strong>{change.teamKey}</strong>
              <div>
                {showValue(change.before)} → {showValue(change.after)}
              </div>
            </ChangeCard>
          ))}
        </Section>
      )}
      {(diff.ratingChanges || []).length > 0 && (
        <Section title="RATING CHANGES">
          {(diff.ratingChanges || []).map((change) => (
            <ChangeCard key={change.teamKey}>
              <strong>{change.teamKey}</strong>
              <div>
                {showValue(change.before == null ? null : String(change.before))} → {showValue(change.after == null ? null : String(change.after))}
              </div>
            </ChangeCard>
          ))}
        </Section>
      )}
    </div>
  )
}

export function DeskRwOsRefresh({
  importId,
  onApplied,
}: {
  importId: number | null
  onApplied: () => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<'idle' | 'checking' | 'preview' | 'applying' | 'done'>('idle')
  const [preview, setPreview] = useState<RefreshResult | null>(null)
  const [applied, setApplied] = useState<RefreshResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const busy = useRef(false)

  if (importId == null) return null

  const close = () => {
    if (phase === 'checking' || phase === 'applying') return
    setOpen(false)
    setPhase('idle')
    setPreview(null)
    setApplied(null)
    setError(null)
  }

  const check = async () => {
    if (busy.current) return
    busy.current = true
    setOpen(true)
    setPhase('checking')
    setError(null)
    setApplied(null)
    try {
      const result = (await refreshRwOsImport(importId, false)) as RefreshResult
      if (result.applied) {
        setApplied(result)
        setPhase('done')
        await onApplied()
      } else {
        setPreview(result)
        setPhase('preview')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not check RW-OS')
      setPhase('preview')
    } finally {
      busy.current = false
    }
  }

  const apply = async () => {
    if (busy.current) return
    busy.current = true
    setPhase('applying')
    setError(null)
    try {
      const result = (await refreshRwOsImport(importId, true)) as RefreshResult
      setApplied(result)
      setPhase('done')
      await onApplied()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply RW-OS changes')
      setPhase('preview')
    } finally {
      busy.current = false
    }
  }

  const attention = staffAttentionItems(applied)
  const current = preview?.diff?.changed === false

  return (
    <>
      <button
        type="button"
        onClick={check}
        disabled={phase === 'checking' || phase === 'applying'}
        style={{
          padding: '6px 14px',
          fontSize: 12,
          fontWeight: 700,
          backgroundColor: '#fff',
          color: '#1a237e',
          border: 'none',
          borderRadius: 4,
          cursor: phase === 'checking' || phase === 'applying' ? 'default' : 'pointer',
        }}
      >
        {phase === 'checking' ? 'Checking RW-OS…' : phase === 'applying' ? 'Applying RW-OS Changes…' : 'Check RW-OS for Changes'}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="RW-OS roster changes"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            zIndex: 3000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div style={{ background: '#fff', color: '#222', borderRadius: 8, maxWidth: 640, width: '100%', maxHeight: '80vh', overflow: 'auto', padding: 20 }}>
            {phase === 'checking' && <p>Checking RW-OS…</p>}
            {error && <p style={{ color: '#b71c1c' }}>{error}</p>}
            {phase === 'preview' && current && (
              <>
                <h2 style={{ marginTop: 0 }}>RW-OS Roster Is Current</h2>
                <p>No player or team changes were found.</p>
                <button type="button" onClick={close}>Close</button>
              </>
            )}
            {phase === 'preview' && preview && !current && (
              <>
                <h2 style={{ marginTop: 0 }}>RW-OS Changes Found</h2>
                <p style={{ fontSize: 13, color: '#555' }}>
                  Nothing is changed until you apply. Apply uses the latest RW-OS roster, not this preview alone.
                </p>
                <PreviewBody diff={preview.diff} />
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button type="button" onClick={close}>Cancel</button>
                  <button type="button" onClick={apply}>Apply RW-OS Changes</button>
                </div>
              </>
            )}
            {phase === 'applying' && <p>Applying RW-OS Changes…</p>}
            {phase === 'done' && applied && (
              <>
                <h2 style={{ marginTop: 0 }}>
                  {sourceRosterUnchanged(applied.diff) && applied.diff.operationalDrift?.reconciliationNeeded
                    ? 'RW-OS Roster Reconciled'
                    : 'RW-OS Changes Applied'}
                </h2>
                {sourceRosterUnchanged(applied.diff) && applied.diff.operationalDrift?.reconciliationNeeded && (
                  <p>The RW-OS download had not changed. Tournament Software event and draw membership was reconciled to that roster.</p>
                )}
                <ul>
                  {appliedSummaryLines(applied).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <p>Tournament Desk has been refreshed.</p>
                {attention.length > 0 && (
                  <div data-testid="rw-os-staff-attention">
                    <h3>{attention.length} items need staff attention</h3>
                    <p>Needs Staff Attention</p>
                    {attention.map((item, index) => (
                      <p key={`${item.code}-${index}`}>{item.message}</p>
                    ))}
                  </div>
                )}
                <button type="button" onClick={close}>Close</button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

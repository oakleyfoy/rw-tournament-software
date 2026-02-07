import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  generateMatchesOnly,
  generateSlotsOnly,
  assignByScope,
  getMatchesPreview,
  wipeScheduleVersionMatches,
  ScheduleVersion,
  MatchesGenerateOnlyResponse,
} from '../../../api/client'
import { showToast } from '../../../utils/toast'

function formatGenerateToast(r: MatchesGenerateOnlyResponse): string {
  const base = `Generated ${r.matches_generated} matches`
  if (r.events_included?.length) {
    const included = r.events_included.join(', ')
    if (r.events_skipped?.length) {
      return `${base} from ${included}. Failed: ${r.events_skipped.join(', ')} — check Draw Builder config.`
    }
    if (r.events_not_finalized?.length) {
      return `${base} from ${included}. Finalize ${r.events_not_finalized.join(', ')} in Draw Builder.`
    }
    return `${base} from ${included}`
  }
  if (r.events_not_finalized?.length && r.finalized_events_found?.length === 0) {
    return `${base}. No events finalized. Finalize events in Draw Builder first.`
  }
  if (r.events_not_finalized?.length) {
    return `${base}. Finalize ${r.events_not_finalized.join(', ')} in Draw Builder.`
  }
  return base
}

interface SchedulePhasedPanelProps {
  tournamentId: number | null
  activeVersion: ScheduleVersion | null
  onCreateDraft: () => void
  onRefresh: () => void
  /** From grid: slots, matches, assigned counts */
  slotsCount?: number
  matchesCount?: number
  assignedCount?: number
  unassignedCount?: number
  /** Expected matches from inventory (sum of event totals). When > matchesCount, suggest Regenerate. */
  inventoryTotalMatches?: number
}

export const SchedulePhasedPanel: React.FC<SchedulePhasedPanelProps> = ({
  tournamentId,
  activeVersion,
  onCreateDraft,
  onRefresh,
  slotsCount = 0,
  matchesCount = 0,
  assignedCount = 0,
  unassignedCount = 0,
  inventoryTotalMatches,
}) => {
  const [busy, setBusy] = useState<string | null>(null)
  const [showWipeConfirm, setShowWipeConfirm] = useState(false)
  const [wipeConfirmText, setWipeConfirmText] = useState('')
  const navigate = useNavigate()

  const isReadOnly = activeVersion?.status === 'final'
  const hasDraft = activeVersion?.status === 'draft'

  const run = async (label: string, fn: () => Promise<unknown>) => {
    if (!tournamentId || !activeVersion) return
    setBusy(label)
    try {
      await fn()
      onRefresh()
    } catch (e) {
      showToast(e instanceof Error ? e.message : `${label} failed`, 'error')
    } finally {
      setBusy(null)
    }
  }

  if (isReadOnly) {
    return (
      <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
        <div style={{ textAlign: 'center', color: '#666' }}>
          <p>This schedule is finalized and read-only.</p>
        </div>
      </div>
    )
  }

  if (!activeVersion) {
    return (
      <div className="card" style={{ padding: '24px', marginBottom: '24px', textAlign: 'center' }}>
        <p style={{ marginBottom: '16px', color: '#666' }}>
          Create a draft version to generate matches and slots.
        </p>
        <button className="btn btn-primary" onClick={onCreateDraft} style={{ fontSize: '16px', padding: '12px 24px' }}>
          Create Draft
        </button>
      </div>
    )
  }

  const versionId = activeVersion.id
  const anyBusy = busy !== null

  const handleReviewMatchCards = async () => {
    if (!tournamentId || !versionId) return
    if (matchesCount > 0) {
      try {
        const preview = await getMatchesPreview(tournamentId, versionId)
        if (preview.matches.length === 0 && preview.diagnostics?.likely_version_mismatch) {
          showToast(
            'Matches exist in summary but not retrievable for this version. Likely version mismatch. Click Refresh.',
            'error'
          )
          onRefresh()
          return
        }
      } catch {
        /* proceed to navigate on error */
      }
    }
    navigate(`/tournaments/${tournamentId}/schedule/versions/${versionId}/matches`)
  }

  const handleWipeMatches = async () => {
    if (!tournamentId || !versionId) return
    setBusy('Wipe All Matches')
    try {
      const result = await wipeScheduleVersionMatches(tournamentId, versionId)
      showToast(`Deleted ${result.deleted_matches} matches`, 'success')
      setShowWipeConfirm(false)
      setWipeConfirmText('')
      onRefresh()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to wipe matches', 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
      <h3 style={{ marginTop: 0 }}>Phased Schedule Build</h3>

      {/* A) Setup */}
      <div style={{ marginBottom: '20px' }}>
        <strong style={{ display: 'block', marginBottom: 8 }}>A) Setup</strong>
        {inventoryTotalMatches != null && inventoryTotalMatches > matchesCount && matchesCount > 0 && (
          <div style={{ marginBottom: 8, padding: '8px 12px', background: '#fff8e6', borderRadius: 4, fontSize: 13 }}>
            Inventory shows {inventoryTotalMatches} matches but you have {matchesCount}. Click <strong>Regenerate Matches</strong> to include all finalized events.
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            style={{ fontSize: 13 }}
            onClick={handleReviewMatchCards}
            disabled={anyBusy}
          >
            Review Match Cards
          </button>
          <button
            className="btn btn-primary"
            disabled={anyBusy}
            onClick={() =>
              run('Generate Matches', () =>
                generateMatchesOnly(tournamentId!, versionId).then((r) => {
                  console.log('[GEN_MATCHES]', {
                    trace_id: r.trace_id,
                    seen_event_ids: r.seen_event_ids,
                    finalized_event_ids: r.finalized_event_ids,
                    events_expected: r.events_expected,
                    matches_generated: r.matches_generated,
                  })
                  const msg = r.already_generated && r.matches_generated === 0
                    ? 'All events complete'
                    : formatGenerateToast(r)
                  showToast(msg, r.events_not_finalized?.length ? 'warning' : 'success')
                })
              )
            }
          >
            {busy === 'Generate Matches' ? '...' : 'Generate Matches'}
          </button>
          {matchesCount > 0 && (
            <>
              <button
                className="btn btn-secondary"
                disabled={anyBusy}
                title="Wipe existing matches and regenerate for all finalized events. Use when you've added events after initial generation."
                onClick={() =>
                  run('Regenerate Matches', () =>
                    generateMatchesOnly(tournamentId!, versionId, { wipeExisting: true }).then((r) => {
                      console.log('[GEN_MATCHES] Regenerate', {
                        trace_id: r.trace_id,
                        seen_event_ids: r.seen_event_ids,
                        finalized_event_ids: r.finalized_event_ids,
                        events_expected: r.events_expected,
                        matches_generated: r.matches_generated,
                      })
                      const msg = formatGenerateToast(r)
                      showToast(msg, r.events_not_finalized?.length ? 'warning' : 'success')
                    })
                  )
                }
              >
                {busy === 'Regenerate Matches' ? '...' : 'Regenerate Matches'}
              </button>
              <button
                className="btn btn-secondary"
                style={{ fontSize: 13, backgroundColor: '#dc3545', color: 'white', borderColor: '#dc3545' }}
                disabled={anyBusy}
                title="Delete all matches for this version. This cannot be undone."
                onClick={() => setShowWipeConfirm(true)}
              >
                Wipe All Matches
              </button>
            </>
          )}
          <button
            className="btn btn-primary"
            disabled={anyBusy}
            onClick={() =>
              run('Generate Slots', () =>
                generateSlotsOnly(tournamentId!, versionId).then((r) =>
                  showToast(r.already_generated ? `Already ${r.slots_generated} slots` : `Generated ${r.slots_generated} slots`, 'success')
                )
              )
            }
          >
            {busy === 'Generate Slots' ? '...' : 'Generate Slots'}
          </button>
        </div>
      </div>

      {/* B) Placement */}
      <div style={{ marginBottom: '20px' }}>
        <strong style={{ display: 'block', marginBottom: 8 }}>B) Placement (round at a time)</strong>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary"
            disabled={anyBusy || slotsCount === 0 || matchesCount === 0}
            onClick={() =>
              run('Place WF R1', () =>
                assignByScope(tournamentId!, versionId, 'WF_R1').then((r) =>
                  showToast(`Placed ${r.assigned_count} (${r.unassigned_count_remaining_in_scope} remaining)`, 'success')
                )
              )
            }
          >
            {busy === 'Place WF R1' ? '...' : 'Place WF Round 1'}
          </button>
          <button
            className="btn btn-secondary"
            disabled={anyBusy || slotsCount === 0 || matchesCount === 0}
            onClick={() =>
              run('Place WF R2', () =>
                assignByScope(tournamentId!, versionId, 'WF_R2').then((r) =>
                  showToast(`Placed ${r.assigned_count}`, 'success')
                )
              )
            }
          >
            {busy === 'Place WF R2' ? '...' : 'Place WF Round 2'}
          </button>
          <button
            className="btn btn-secondary"
            disabled={anyBusy || slotsCount === 0 || matchesCount === 0}
            onClick={() =>
              run('Place Pool RR', () =>
                assignByScope(tournamentId!, versionId, 'RR_POOL').then((r) =>
                  showToast(`Placed ${r.assigned_count}`, 'success')
                )
              )
            }
          >
            {busy === 'Place Pool RR' ? '...' : 'Place Pool RR'}
          </button>
          <button
            className="btn btn-primary"
            disabled={anyBusy || slotsCount === 0 || matchesCount === 0}
            onClick={() =>
              run('Place All', () =>
                assignByScope(tournamentId!, versionId, 'ALL', {
                  clear_existing_assignments_in_scope: false,
                }).then((r) =>
                  showToast(`Placed ${r.assigned_count} (${r.unassigned_count_remaining_in_scope} unassigned)`, 'success')
                )
              )
            }
          >
            {busy === 'Place All' ? '...' : 'Place All'}
          </button>
        </div>
      </div>

      {/* C) Status */}
      <div>
        <strong style={{ display: 'block', marginBottom: 8 }}>C) Status</strong>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 14 }}>
          <span>Version: {versionId} ({activeVersion.status})</span>
          <span>Slots: {slotsCount}</span>
          <span>Matches: {matchesCount}</span>
          <span>Assigned: {assignedCount}</span>
          <span>Unassigned: {unassignedCount}</span>
        </div>
      </div>

      {/* Wipe Confirmation Modal */}
      {showWipeConfirm && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => {
            setShowWipeConfirm(false)
            setWipeConfirmText('')
          }}
        >
          <div
            className="card"
            style={{
              padding: '24px',
              maxWidth: '400px',
              width: '90%',
              backgroundColor: 'white',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginTop: 0, color: '#dc3545' }}>Confirm Wipe All Matches</h3>
            <p style={{ marginBottom: 16 }}>
              This deletes ALL matches for version {versionId}. This cannot be undone.
            </p>
            <p style={{ marginBottom: 16, fontSize: 14, color: '#666' }}>
              Type <strong>WIPE</strong> to confirm:
            </p>
            <input
              type="text"
              value={wipeConfirmText}
              onChange={(e) => setWipeConfirmText(e.target.value)}
              placeholder="Type WIPE"
              style={{
                width: '100%',
                padding: '8px',
                marginBottom: 16,
                fontSize: 14,
                border: '1px solid #ddd',
                borderRadius: 4,
              }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setShowWipeConfirm(false)
                  setWipeConfirmText('')
                }}
                disabled={busy !== null}
              >
                Cancel
              </button>
              <button
                className="btn"
                style={{
                  backgroundColor: '#dc3545',
                  color: 'white',
                  borderColor: '#dc3545',
                }}
                onClick={handleWipeMatches}
                disabled={wipeConfirmText !== 'WIPE' || busy !== null}
              >
                {busy === 'Wipe All Matches' ? 'Deleting...' : 'Confirm Wipe'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  approveRwOsPlan,
  createRwOsImport,
  listRwOsEvents,
  refreshRwOsImport,
  selectRwOsStructure,
  type RwOsBracketPreview,
  type RwOsDrawPlan,
  type RwOsEventSummary,
  type RwOsImportResponse,
  type RwOsSplitOption,
} from '../api/client'
import { showToast } from '../utils/toast'
import './CreateTournamentFromRwOs.css'

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatRating(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return 'unrated'
  return value.toFixed(2)
}

function TeamPreview({
  bracket,
  drawTeams,
}: {
  bracket: RwOsBracketPreview
  drawTeams: NonNullable<RwOsDrawPlan['teams']>
}) {
  const [open, setOpen] = useState(false)
  const teams = (drawTeams.length ? drawTeams : bracket.teams).filter(
    (team) => team.rank >= bracket.rankStart && team.rank <= bracket.rankEnd,
  )
  return (
    <div className="team-preview">
      <button className="btn btn-secondary btn-small" type="button" onClick={() => setOpen((value) => !value)}>
        {open ? 'Hide Teams' : `View Teams (${bracket.size})`}
      </button>
      {open && (
        <ol className="team-preview-list">
          {teams.map((team) => (
            <li key={team.teamKey}>
              #{team.rank} {team.name} — {formatRating(team.teamRating)}
              {team.ratingStatus !== 'complete' ? ` (${team.ratingStatus})` : ''}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function OptionCard({
  option,
  selected,
  onSelect,
  disabled,
  drawTeams,
}: {
  option: RwOsSplitOption
  selected: boolean
  onSelect: () => void
  disabled: boolean
  drawTeams: NonNullable<RwOsDrawPlan['teams']>
}) {
  return (
    <article className={`split-option ${option.recommended ? 'recommended' : ''} ${selected ? 'selected' : ''}`}>
      <header>
        <h4>
          {option.recommended ? 'RECOMMENDED — ' : ''}
          {option.sizes.map((size) => `[${size}]`).join(' ')}
        </h4>
        <p className="score-line">
          Score {option.score.total.toFixed(1)} · Cut {option.score.cutQuality.toFixed(1)} · Size {option.score.sizeQuality.toFixed(1)}
          {option.score.tinyBracketPenalty ? ` · Tiny penalty ${option.score.tinyBracketPenalty.toFixed(1)}` : ''}
        </p>
      </header>
      <ul className="why-list">
        {option.score.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      {option.brackets.map((bracket) => (
        <div key={bracket.label} className="bracket-range">
          <strong>{bracket.label}</strong> — {bracket.size} teams
          {bracket.highestRating != null && bracket.lowestRating != null ? (
            <>
              {' '}
              {formatRating(bracket.highestRating)} → {formatRating(bracket.lowestRating)}
              {bracket.averageRating != null ? ` · Avg ${formatRating(bracket.averageRating)}` : ''}
              {bracket.medianRating != null ? ` · Median ${formatRating(bracket.medianRating)}` : ''}
            </>
          ) : (
            ' · ratings incomplete'
          )}
          <TeamPreview bracket={bracket} drawTeams={drawTeams} />
        </div>
      ))}
      {option.cuts.map((cut) => (
        <div key={`${cut.upperRank}-${cut.lowerRank}`} className="cut-block">
          <strong>CUT BETWEEN {cut.fromLabel} / {cut.toLabel}</strong>
          <div>
            #{cut.upperRank} {cut.upperTeamName} — {formatRating(cut.upperRating)}
          </div>
          <div>
            #{cut.lowerRank} {cut.lowerTeamName} — {formatRating(cut.lowerRating)}
          </div>
          <div>
            Gap: {cut.ratingGap == null ? 'n/a' : cut.ratingGap.toFixed(2)} · {cut.quality}
          </div>
          <div className="neighborhood">
            {cut.neighborhood.map((row) => (
              <div key={row.rank} className={row.isCutBoundary ? 'cut-line' : undefined}>
                #{row.rank} {row.name} — {formatRating(row.teamRating)}
                {row.isCutBoundary ? <span className="cut-marker"> — CUT</span> : null}
              </div>
            ))}
          </div>
        </div>
      ))}
      <button className="btn btn-primary" type="button" disabled={disabled} onClick={onSelect}>
        {selected ? 'Selected Structure' : 'Select This Structure'}
      </button>
    </article>
  )
}

const TOP_OPTIONS_LIMIT = 8

function DrawPlanner({
  draw,
  selectedKey,
  onSelect,
  disabled,
}: {
  draw: RwOsDrawPlan
  selectedKey?: string
  onSelect: (optionKey: string) => void
  disabled: boolean
}) {
  const [showAll, setShowAll] = useState(false)
  const ranked = [...draw.options].sort((left, right) => {
    if (right.score.total !== left.score.total) return right.score.total - left.score.total
    return right.score.cutQuality - left.score.cutQuality
  })
  const recommended = ranked.find((option) => option.recommended) || ranked[0]
  const visible = showAll
    ? ranked
    : ranked.filter((option, index) => {
        if (index < (draw.topOptionCount || TOP_OPTIONS_LIMIT)) return true
        return option.optionKey === selectedKey
      })
  const alternatives = visible.filter((option) => option.optionKey !== recommended?.optionKey)

  return (
    <section className="card draw-planner">
      <h3>
        {draw.drawLabel.toUpperCase()} — {draw.teamCount} TEAMS
      </h3>
      <p className="meta">
        {draw.optionCount || ranked.length} valid ordered structures scored.
        Showing {showAll ? 'all' : `top ${visible.length}`} by recommendation score.
      </p>
      {draw.ratingReviewNeeded > 0 && (
        <div className="warning-banner">
          {draw.ratingReviewNeeded} team{draw.ratingReviewNeeded === 1 ? '' : 's'} need rating review.
          Recommendation confidence is lower.
        </div>
      )}
      {recommended && (
        <>
          <h4 className="option-section-title">Recommended</h4>
          <div className="option-grid">
            <OptionCard
              option={recommended}
              selected={selectedKey === recommended.optionKey}
              disabled={disabled}
              onSelect={() => onSelect(recommended.optionKey)}
              drawTeams={draw.teams || []}
            />
          </div>
        </>
      )}
      {alternatives.length > 0 && (
        <>
          <h4 className="option-section-title">Top Alternatives</h4>
          <div className="option-grid">
            {alternatives.map((option) => (
              <OptionCard
                key={option.optionKey}
                option={option}
                selected={selectedKey === option.optionKey}
                disabled={disabled}
                onSelect={() => onSelect(option.optionKey)}
                drawTeams={draw.teams || []}
              />
            ))}
          </div>
        </>
      )}
      {(draw.optionCount || ranked.length) > (draw.topOptionCount || TOP_OPTIONS_LIMIT) && (
        <button className="btn btn-secondary" type="button" onClick={() => setShowAll((value) => !value)}>
          {showAll ? 'Show Top Options' : `Show All Options (${draw.optionCount || ranked.length})`}
        </button>
      )}
    </section>
  )
}

function CreateTournamentFromRwOs() {
  const navigate = useNavigate()
  const [events, setEvents] = useState<RwOsEventSummary[]>([])
  const [source, setSource] = useState<'fixtures' | 'live' | null>(null)
  const [loading, setLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedEventId, setSelectedEventId] = useState<number | ''>('')
  const [importData, setImportData] = useState<RwOsImportResponse | null>(null)
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [refreshSummary, setRefreshSummary] = useState<string | null>(null)

  useEffect(() => {
    listRwOsEvents()
      .then((payload) => {
        setEvents(payload.events)
        setSource(payload.source ?? null)
      })
      .catch((err) => {
        setEvents([])
        setSource(null)
        setError(err instanceof Error ? err.message : 'Failed to load RW-OS events')
      })
      .finally(() => setLoading(false))
  }, [])

  const selectedEvent = events.find((event) => event.tournamentId === selectedEventId)

  const approved = importData?.import.planStatus === 'approved'

  const defaultSelections = useMemo(() => {
    const next: Record<string, string> = {}
    for (const draw of importData?.planner.draws || []) {
      const recommended = draw.options.find((option) => option.recommended) || draw.options[0]
      if (recommended) next[draw.drawKind] = recommended.optionKey
    }
    return next
  }, [importData])

  const currentSelections = Object.keys(selections).length ? selections : defaultSelections

  const handleImport = async () => {
    if (!selectedEventId) return
    try {
      setImporting(true)
      setError(null)
      const result = await createRwOsImport(Number(selectedEventId))
      setImportData(result)
      const next: Record<string, string> = {}
      for (const draw of result.planner.draws) {
        const recommended = draw.options.find((option) => option.recommended) || draw.options[0]
        if (recommended) next[draw.drawKind] = recommended.optionKey
      }
      setSelections(next)
      showToast(`Imported ${result.import.sourceTeamCount} teams from RW-OS`, 'success')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import RW-OS event')
    } finally {
      setImporting(false)
    }
  }

  const handleSelect = async (drawKind: string, optionKey: string) => {
    if (!importData) return
    try {
      setWorking(true)
      const result = await selectRwOsStructure(importData.import.id, drawKind, optionKey)
      setImportData(result)
      setSelections((prev) => ({ ...prev, [drawKind]: optionKey }))
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not select structure', 'error')
    } finally {
      setWorking(false)
    }
  }

  const handleApprove = async () => {
    if (!importData) return
    try {
      setWorking(true)
      const result = await approveRwOsPlan(importData.import.id, currentSelections)
      setImportData(result)
      showToast('Bracket split plan approved. No brackets were created.', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not approve plan', 'error')
    } finally {
      setWorking(false)
    }
  }

  const handleRefresh = async (apply: boolean) => {
    if (!importData) return
    try {
      setWorking(true)
      const result = await refreshRwOsImport(importData.import.id, apply)
      const diff = result.diff
      setRefreshSummary(
        `RW-OS has changed since this tournament was imported. +${diff.addedCount} teams, -${diff.withdrawnCount} withdrawn, ${diff.partnerChanges?.length || 0} partner change(s), ${diff.ratingChanges?.length || 0} rating change(s).`,
      )
      if (apply) {
        setImportData(result.importResponse)
        showToast('Snapshot refreshed from RW-OS', 'success')
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Refresh failed', 'error')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="container create-from-rwos">
      <div className="page-header">
        <div>
          <h1>Create Tournament from RW-OS</h1>
          <p className="subhead">Import the current eligible teams, then approve a draw split. Brackets are not created in this step.</p>
          {source === 'fixtures' && <p className="rwos-source-indicator">RW-OS Source: Fixtures</p>}
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => navigate('/tournaments')}>
          Back
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      <section className="card">
        <h2>Step 1 — Choose RW-OS Event</h2>
        {loading ? (
          <p>Loading current and upcoming RW-OS events…</p>
        ) : error ? (
          <p>Could not load RW-OS events. Fixture data is not used as a fallback.</p>
        ) : events.length === 0 ? (
          <p>No current or upcoming RW-OS events are available to import.</p>
        ) : (
          <>
            <label className="form-group full-width">
              Select Event
              <select
                value={selectedEventId}
                onChange={(event) => setSelectedEventId(event.target.value ? Number(event.target.value) : '')}
                disabled={Boolean(importData)}
              >
                <option value="">Choose an event…</option>
                {events.map((event) => (
                  <option key={event.tournamentId} value={event.tournamentId}>
                    {event.eventName} — {formatDate(event.eventDate)} — Tournament ID {event.tournamentId}
                  </option>
                ))}
              </select>
            </label>
            {selectedEvent && (
              <div className="event-summary">
                <div><strong>{selectedEvent.eventName}</strong></div>
                <div>{formatDate(selectedEvent.eventDate)}</div>
                <div>Tournament ID {selectedEvent.tournamentId}</div>
                <div>{selectedEvent.teamCount} teams</div>
                <div>{selectedEvent.draws.join(' / ')}</div>
              </div>
            )}
            {!importData && (
              <button className="btn btn-primary" type="button" disabled={!selectedEventId || importing} onClick={handleImport}>
                {importing ? 'Importing…' : 'Import Snapshot'}
              </button>
            )}
          </>
        )}
        <p className="manual-link">
          <button className="link-button" type="button" onClick={() => navigate('/tournaments/new/setup')}>
            Create manually instead
          </button>
        </p>
      </section>

      {importData && (
        <>
          <section className="card">
            <h2>Imported snapshot</h2>
            <p>
              Imported: {importData.import.sourceTeamCount} teams
              {Object.entries(importData.drawCounts).map(([label, count]) => ` · ${label} ${count}`).join('')}
              {importData.waitlistCount ? ` · Waitlist ${importData.waitlistCount} (not placed in brackets)` : ''}
            </p>
            <p className="meta">
              Source hash {importData.import.sourceHash.slice(0, 12)} · Rating rule: NTRP Combined (sum) · Byes: not applicable
            </p>
            {importData.import.validationStatus === 'needs_attention' && (
              <div className="warning-banner">
                Needs Attention: {importData.import.validationIssues.map((issue) => issue.message).join(' ')}
              </div>
            )}
            {refreshSummary && <div className="warning-banner">{refreshSummary}</div>}
            <div className="header-actions">
              <button className="btn btn-secondary" type="button" disabled={working || approved} onClick={() => handleRefresh(false)}>
                Check RW-OS Changes
              </button>
              <button className="btn btn-secondary" type="button" disabled={working || approved} onClick={() => handleRefresh(true)}>
                Refresh from RW-OS
              </button>
            </div>
          </section>

          <h2>Step 2 — Bracket Split Planner</h2>
          {importData.planner.draws.map((draw) => (
            <DrawPlanner
              key={draw.drawKind}
              draw={draw}
              selectedKey={currentSelections[draw.drawKind]}
              disabled={working || approved}
              onSelect={(optionKey) => handleSelect(draw.drawKind, optionKey)}
            />
          ))}

          <section className="card approve-card">
            {approved ? (
              <>
                <h3>Plan approved</h3>
                <p>The draw split is stored. No Waterfall brackets, matches, or seeds were created.</p>
                <ul>
                  {importData.approvedPlans.map((plan) => (
                    <li key={plan.drawKind}>
                      {plan.drawKind}: {plan.brackets.map((bracket) => `${bracket.label} (${bracket.size})`).join(', ')}
                    </li>
                  ))}
                </ul>
                <button className="btn btn-primary" type="button" onClick={() => navigate(`/tournaments/${importData.import.tournamentId}/setup`)}>
                  Continue to Tournament Setup
                </button>
              </>
            ) : (
              <>
                <p>Software recommends. Staff chooses. Approving stores the plan only.</p>
                <button className="btn btn-primary" type="button" disabled={working} onClick={handleApprove}>
                  Approve Selected Structure
                </button>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}

export default CreateTournamentFromRwOs

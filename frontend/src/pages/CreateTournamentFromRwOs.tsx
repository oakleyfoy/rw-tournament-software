import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  approveRwOsPlan,
  createRwOsImport,
  listRwOsEvents,
  refreshRwOsImport,
  resetRwOsForecasts,
  selectRwOsStructure,
  submitRwOsCustomStructure,
  updateRwOsForecasts,
  type RwOsBracketPreview,
  type RwOsDrawPlan,
  type RwOsEventSummary,
  type RwOsImportResponse,
  type RwOsRatingReviewPlayer,
  type RwOsRatingReviewTeam,
  type RwOsExplanation,
  type RwOsSplitOption,
} from '../api/client'
import { showToast } from '../utils/toast'
import './CreateTournamentFromRwOs.css'

const MAX_FORECAST = 160

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatRating(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return 'unrated'
  return value.toFixed(2)
}

function formatNtrp(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return 'Missing'
  return value.toFixed(1).replace(/\.0$/, '.0')
}

function playerRwId(player: RwOsRatingReviewPlayer): string {
  return player.rwId || player.rw_id || ''
}

function reviewStatusLabel(status: string): string {
  if (status === 'partial') return 'Partial rating'
  if (status === 'missing') return 'Missing ratings'
  return status
}

function RatingReviewWarning({ teams }: { teams: RwOsRatingReviewTeam[] }) {
  const [open, setOpen] = useState(false)
  if (!teams.length) return null
  const count = teams.length
  const headline =
    count === 1
      ? '1 team needs rating review. Recommendation confidence is lower.'
      : `${count} teams need rating review. Recommendation confidence is lower.`

  return (
    <div className="warning-banner rating-review-warning">
      <p className="rating-review-headline">⚠ {headline}</p>
      <button className="link-button rating-review-toggle" type="button" onClick={() => setOpen((value) => !value)}>
        {open ? 'View teams needing review ▴' : 'View teams needing review ▾'}
      </button>
      {open && (
        <div className="rating-review-list">
          <h4>Teams needing rating review</h4>
          <ol>
            {teams.map((team) => (
              <li key={team.teamKey}>
                <strong>{team.name}</strong>
                <div className="rating-review-status">{reviewStatusLabel(team.ratingStatus)}</div>
                {[team.player1, team.player2].map((player) => (
                  <div key={`${team.teamKey}-${playerRwId(player)}-${player.name}`} className="rating-review-player">
                    <div>{player.name}</div>
                    {playerRwId(player) ? <div>RW_ID: {playerRwId(player)}</div> : null}
                    <div>NTRP: {formatNtrp(player.rating)}</div>
                  </div>
                ))}
                <div className="rating-review-combined">
                  Combined used by planner:{' '}
                  {team.teamRating == null ? 'Not available' : formatNtrp(team.teamRating)}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function formatStructure(sizes: number[]): string {
  return sizes.join(' / ')
}

function parseStructureInput(raw: string): number[] | null {
  const parts = raw
    .split(/[/,|\s]+/)
    .map((part) => part.trim())
    .filter(Boolean)
  if (!parts.length) return null
  const sizes = parts.map((part) => Number(part))
  if (sizes.some((size) => !Number.isInteger(size) || size <= 0)) return null
  return sizes
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
    (team) => team.rank >= bracket.rankStart && team.rank <= Math.min(bracket.rankEnd, drawTeams.length || bracket.rankEnd),
  )
  const unknown = bracket.unknownTeamCount || 0
  return (
    <div className="team-preview">
      <button className="btn btn-secondary btn-small" type="button" onClick={() => setOpen((value) => !value)}>
        {open ? 'Hide Teams' : `View Known Teams (${bracket.knownTeamCount ?? teams.length})`}
      </button>
      {open && (
        <>
          <ol className="team-preview-list">
            {teams.map((team) => (
              <li key={team.teamKey}>
                #{team.rank} {team.name} — {formatRating(team.teamRating)}
                {team.ratingStatus !== 'complete' ? ` (${team.ratingStatus})` : ''}
              </li>
            ))}
          </ol>
          {unknown > 0 && (
            <p className="provisional-note">
              {unknown} expected team{unknown === 1 ? '' : 's'} in this bracket {unknown === 1 ? 'has' : 'have'} not
              registered yet.
            </p>
          )}
        </>
      )}
    </div>
  )
}

function optionExplanations(option: RwOsSplitOption): { reasons: RwOsExplanation[]; warnings: RwOsExplanation[] } {
  if (option.reasons || option.warnings) {
    return { reasons: option.reasons || [], warnings: option.warnings || [] }
  }
  const fromScore = option.score.explanations
  if (fromScore) return { reasons: fromScore.reasons || [], warnings: fromScore.warnings || [] }
  return { reasons: [], warnings: [] }
}

function OptionCard({
  option,
  selected,
  onSelect,
  disabled,
  drawTeams,
  badge,
}: {
  option: RwOsSplitOption
  selected: boolean
  onSelect: () => void
  disabled: boolean
  drawTeams: NonNullable<RwOsDrawPlan['teams']>
  badge?: string
}) {
  const { reasons, warnings } = optionExplanations(option)
  const recommended = Boolean(option.recommended || badge === 'RECOMMENDED')
  return (
    <article className={`split-option ${recommended ? 'recommended' : ''} ${option.custom ? 'custom' : ''} ${selected ? 'selected' : ''}`}>
      <header>
        <p className="option-badge">{badge || (recommended ? 'RECOMMENDED' : 'ALTERNATIVE')}</p>
        <h4>{formatStructure(option.sizes)}</h4>
      </header>
      {recommended ? (
        <div className="why-block">
          <h5>Why we recommend it</h5>
          <ul className="why-list positives">
            {reasons.map((reason) => (
              <li key={`${reason.code}-${reason.message}`}>✓ {reason.message}</li>
            ))}
          </ul>
          {warnings.length > 0 && (
            <>
              <h5>Tradeoffs</h5>
              <ul className="why-list warnings">
                {warnings.map((warning) => (
                  <li key={`${warning.code}-${warning.message}`}>⚠ {warning.message}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : (
        <div className="why-block">
          {reasons.length > 0 && (
            <>
              <h5>Strengths</h5>
              <ul className="why-list positives">
                {reasons.map((reason) => (
                  <li key={`${reason.code}-${reason.message}`}>✓ {reason.message}</li>
                ))}
              </ul>
            </>
          )}
          {warnings.length > 0 && (
            <>
              <h5>Tradeoffs</h5>
              <ul className="why-list warnings">
                {warnings.map((warning) => (
                  <li key={`${warning.code}-${warning.message}`}>⚠ {warning.message}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
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
          {bracket.unknownTeamCount ? ` · ${bracket.unknownTeamCount} not yet registered` : ''}
          <TeamPreview bracket={bracket} drawTeams={drawTeams} />
        </div>
      ))}
      {option.cuts.map((cut) => (
        <div key={`${cut.upperRank}-${cut.lowerRank}`} className={`cut-block ${cut.provisional ? 'provisional' : ''}`}>
          <strong>{cut.provisional ? 'PROVISIONAL CUT' : 'CUT'} BETWEEN {cut.fromLabel} / {cut.toLabel}</strong>
          {cut.provisional ? (
            <p className="provisional-note">{cut.message}</p>
          ) : (
            <>
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
            </>
          )}
        </div>
      ))}
      <button className="btn btn-primary" type="button" disabled={disabled} onClick={onSelect}>
        {selected ? 'Selected Structure' : 'Select This Structure'}
      </button>
    </article>
  )
}

function CustomStructureForm({
  draw,
  disabled,
  onAnalyze,
  customOption,
  selected,
  onSelect,
}: {
  draw: RwOsDrawPlan
  disabled: boolean
  onAnalyze: (sizes: number[]) => void
  customOption?: RwOsSplitOption | null
  selected: boolean
  onSelect: (optionKey: string) => void
}) {
  const [raw, setRaw] = useState('')
  const [error, setError] = useState<string | null>(null)
  const forecast = draw.forecastCount ?? draw.teamCount

  const handleAnalyze = () => {
    const sizes = parseStructureInput(raw)
    if (!sizes) {
      setError('Enter whole numbers such as 16 / 20 / 32.')
      return
    }
    if (sizes.some((size) => size > 32)) {
      setError('No bracket may be larger than 32.')
      return
    }
    if (forecast >= 8 && sizes.some((size) => size < 8)) {
      setError('Each bracket must have at least 8 teams unless the entire draw has fewer than 8 teams.')
      return
    }
    if (forecast < 8 && (sizes.length !== 1 || sizes[0] !== forecast)) {
      setError('Each bracket must have at least 8 teams unless the entire draw has fewer than 8 teams.')
      return
    }
    if (sizes.reduce((sum, size) => sum + size, 0) !== forecast) {
      setError(`Sizes must sum to the expected final count of ${forecast}.`)
      return
    }
    setError(null)
    onAnalyze(sizes)
  }

  return (
    <section className="custom-structure">
      <h4>Have another structure in mind?</h4>
      <p className="meta">Enter an exact structure for this expected field. Example: 16 / 20 / 32</p>
      <div className="custom-structure-row">
        <input
          type="text"
          value={raw}
          onChange={(event) => setRaw(event.target.value)}
          placeholder="16 / 20 / 32"
          disabled={disabled}
        />
        <button className="btn btn-secondary" type="button" disabled={disabled} onClick={handleAnalyze}>
          Analyze Custom Structure
        </button>
      </div>
      {error && <p className="field-error">{error}</p>}
      {customOption && (
        <OptionCard
          option={customOption}
          badge="CUSTOM STRUCTURE"
          selected={selected}
          disabled={disabled}
          onSelect={() => onSelect(customOption.optionKey)}
          drawTeams={draw.teams || []}
        />
      )}
    </section>
  )
}

function DrawPlanner({
  draw,
  selectedKey,
  onSelect,
  disabled,
  customOption,
  onAnalyzeCustom,
}: {
  draw: RwOsDrawPlan
  selectedKey?: string
  onSelect: (optionKey: string) => void
  disabled: boolean
  customOption?: RwOsSplitOption | null
  onAnalyzeCustom: (sizes: number[]) => void
}) {
  const current = draw.currentCount ?? draw.teamCount
  const expected = draw.forecastCount ?? draw.teamCount
  const recommended = draw.options.find((option) => option.recommended) || draw.options[0]
  const alternatives = draw.options.filter((option) => option.optionKey !== recommended?.optionKey)

  return (
    <section className="card draw-planner">
      <h3>{draw.drawLabel.toUpperCase()}</h3>
      <p className="count-line">
        Current: {current} · Expected: {expected}
      </p>
      {draw.planningNote && <div className="info-banner">{draw.planningNote}</div>}
      <RatingReviewWarning teams={draw.ratingReviewTeams || []} />
      {expected === 0 && <p className="meta">Forecast is 0 — no bracket plan was generated for this draw.</p>}
      {recommended && (
        <>
          <h4 className="option-section-title">Recommended</h4>
          <div className="option-grid">
            <OptionCard
              option={recommended}
              badge="RECOMMENDED"
              selected={selectedKey === recommended.optionKey}
              disabled={disabled}
              onSelect={() => onSelect(recommended.optionKey)}
              drawTeams={draw.teams || []}
            />
          </div>
        </>
      )}
      {alternatives.map((option, index) => (
        <div key={option.optionKey}>
          <h4 className="option-section-title">Alternative {index + 1}</h4>
          <div className="option-grid">
            <OptionCard
              option={option}
              badge={`ALTERNATIVE ${index + 1}`}
              selected={selectedKey === option.optionKey}
              disabled={disabled}
              onSelect={() => onSelect(option.optionKey)}
              drawTeams={draw.teams || []}
            />
          </div>
        </div>
      ))}
      {expected > 0 && (
        <CustomStructureForm
          draw={draw}
          disabled={disabled}
          onAnalyze={onAnalyzeCustom}
          customOption={customOption}
          selected={selectedKey === customOption?.optionKey}
          onSelect={onSelect}
        />
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
  const [forecastDraft, setForecastDraft] = useState<Record<string, string>>({})
  const [forecastErrors, setForecastErrors] = useState<Record<string, string>>({})
  const [customByDraw, setCustomByDraw] = useState<Record<string, RwOsSplitOption>>({})
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
  const maxForecast = importData?.planner.maxForecastTeams ?? MAX_FORECAST

  const currentByKind = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const team of importData?.import.teams || []) {
      counts[team.drawKind] = (counts[team.drawKind] || 0) + 1
    }
    return counts
  }, [importData])

  const draws = importData?.planner.draws || []
  const currentTotal = draws.reduce((sum, draw) => sum + (draw.currentCount ?? draw.teamCount), 0)
  const expectedTotal = draws.reduce((sum, draw) => {
    const raw = forecastDraft[draw.drawKind]
    const parsed = raw == null || raw === '' ? Number.NaN : Number(raw)
    return sum + (Number.isInteger(parsed) ? parsed : 0)
  }, 0)

  const hydrateForecasts = (data: RwOsImportResponse) => {
    const next: Record<string, string> = {}
    for (const draw of data.planner.draws) {
      const stored = data.import.forecasts?.[draw.drawKind] ?? data.forecasts?.[draw.drawKind]
      next[draw.drawKind] = String(stored ?? draw.forecastCount ?? draw.currentCount ?? draw.teamCount)
    }
    setForecastDraft(next)
    setForecastErrors({})
  }

  const validateForecastValue = (drawKind: string, raw: string): string | null => {
    if (raw.trim() === '') return 'Enter a whole number.'
    if (!/^\d+$/.test(raw.trim())) return 'Whole numbers only.'
    const value = Number(raw)
    if (!Number.isInteger(value) || value < 0) return 'Must be 0 or greater.'
    if (value > maxForecast) return `Cannot exceed ${maxForecast}.`
    void drawKind
    return null
  }

  const handleImport = async () => {
    if (!selectedEventId) return
    try {
      setImporting(true)
      setError(null)
      const result = await createRwOsImport(Number(selectedEventId))
      setImportData(result)
      setSelections({})
      setCustomByDraw({})
      hydrateForecasts(result)
      showToast(`Imported ${result.import.sourceTeamCount} teams from RW-OS`, 'success')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import RW-OS event')
    } finally {
      setImporting(false)
    }
  }

  const persistForecasts = async (draft: Record<string, string>) => {
    if (!importData) return
    const errors: Record<string, string> = {}
    const forecasts: Record<string, number> = {}
    for (const draw of importData.planner.draws) {
      const raw = draft[draw.drawKind] ?? ''
      const message = validateForecastValue(draw.drawKind, raw)
      if (message) errors[draw.drawKind] = message
      else forecasts[draw.drawKind] = Number(raw)
    }
    setForecastErrors(errors)
    if (Object.keys(errors).length) return
    try {
      setWorking(true)
      const result = await updateRwOsForecasts(importData.import.id, forecasts)
      setImportData(result)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not save expected field', 'error')
    } finally {
      setWorking(false)
    }
  }

  const handleForecastChange = (drawKind: string, raw: string) => {
    const next = { ...forecastDraft, [drawKind]: raw }
    setForecastDraft(next)
    const message = validateForecastValue(drawKind, raw)
    setForecastErrors((prev) => ({ ...prev, [drawKind]: message || '' }))
  }

  const handleResetForecasts = async () => {
    if (!importData) return
    try {
      setWorking(true)
      const result = await resetRwOsForecasts(importData.import.id)
      setImportData(result)
      hydrateForecasts(result)
      showToast('Forecasts reset to current RW-OS counts', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not reset forecasts', 'error')
    } finally {
      setWorking(false)
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

  const handleCustomAnalyze = async (drawKind: string, sizes: number[]) => {
    if (!importData) return
    try {
      setWorking(true)
      const result = await submitRwOsCustomStructure(importData.import.id, drawKind, sizes)
      if (result.customOption) {
        setCustomByDraw((prev) => ({ ...prev, [drawKind]: result.customOption as RwOsSplitOption }))
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Custom structure is not valid', 'error')
    } finally {
      setWorking(false)
    }
  }

  const handleApprove = async () => {
    if (!importData) return
    const missing = importData.planner.draws.filter(
      (draw) => (draw.forecastCount ?? 0) > 0 && draw.options.length > 0 && !selections[draw.drawKind],
    )
    if (missing.length) {
      showToast('Select a structure for each draw before approving.', 'error')
      return
    }
    try {
      setWorking(true)
      const result = await approveRwOsPlan(importData.import.id, selections)
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
        showToast('Snapshot refreshed from RW-OS. Expected final counts were kept.', 'success')
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
          <p className="subhead">
            Import the current eligible teams, set the expected final field, then choose a draw split.
            Brackets are not created in this step.
          </p>
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
        {importData && (
          <div className="registration-summary">
            <h3>Current RW-OS Registration</h3>
            <table>
              <tbody>
                {draws.map((draw) => (
                  <tr key={draw.drawKind}>
                    <th>{draw.drawLabel}</th>
                    <td>{draw.currentCount ?? currentByKind[draw.drawKind] ?? 0} teams</td>
                  </tr>
                ))}
                <tr className="total-row">
                  <th>Total</th>
                  <td>{currentTotal} teams</td>
                </tr>
              </tbody>
            </table>
            <p className="meta">
              These counts come from the imported RW-OS snapshot and cannot be edited here.
              Source hash {importData.import.sourceHash.slice(0, 12)} · Rating rule: NTRP Combined (sum)
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
          </div>
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
            <h2>Step 2 — Expected Final Field</h2>
            <h3>Where do you think this event will end up?</h3>
            <p>
              Enter the number of teams you expect to have when registration is complete. We&apos;ll use your
              expected field size to build the bracket options while using current team ratings to identify the
              best competitive cut lines.
            </p>
            <h4>Expected Final Team Counts</h4>
            <div className="forecast-grid">
              {draws.map((draw) => (
                <label key={draw.drawKind} className="forecast-field">
                  {draw.drawLabel}
                  <input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={maxForecast}
                    step={1}
                    value={forecastDraft[draw.drawKind] ?? ''}
                    disabled={working || approved}
                    onChange={(event) => handleForecastChange(draw.drawKind, event.target.value)}
                    onBlur={(event) => {
                      const next = { ...forecastDraft, [draw.drawKind]: event.target.value }
                      setForecastDraft(next)
                      void persistForecasts(next)
                    }}
                  />
                  {forecastErrors[draw.drawKind] && <span className="field-error">{forecastErrors[draw.drawKind]}</span>}
                </label>
              ))}
            </div>
            <p className="expected-total">Expected Total: {expectedTotal}</p>
            <button className="btn btn-secondary" type="button" disabled={working || approved} onClick={handleResetForecasts}>
              Reset forecasts to current counts
            </button>
          </section>

          <h2>Step 3 — Bracket Plan</h2>
          {draws.map((draw) => (
            <DrawPlanner
              key={draw.drawKind}
              draw={draw}
              selectedKey={selections[draw.drawKind]}
              disabled={working || approved}
              customOption={customByDraw[draw.drawKind]}
              onSelect={(optionKey) => handleSelect(draw.drawKind, optionKey)}
              onAnalyzeCustom={(sizes) => handleCustomAnalyze(draw.drawKind, sizes)}
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

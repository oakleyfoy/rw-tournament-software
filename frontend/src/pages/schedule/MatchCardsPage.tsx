import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  getMatchesPreview,
  generateMatchesOnly,
  getActiveScheduleVersion,
  MatchPreviewResponse,
} from '../../api/client'
import { showToast } from '../../utils/toast'
import './SchedulePage.css'

/** Redirects /schedule/matches (no versionId) to /schedule/versions/{activeVersionId}/matches */
export function MatchCardsRedirectToActive() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const tournamentId = id ? parseInt(id) : null

  useEffect(() => {
    if (!tournamentId) return
    let cancelled = false
    getActiveScheduleVersion(tournamentId)
      .then((res) => {
        if (!cancelled && res.schedule_version_id)
          navigate(`/tournaments/${tournamentId}/schedule/versions/${res.schedule_version_id}/matches`, { replace: true })
      })
      .catch(() => {
        if (!cancelled) navigate(`/tournaments/${tournamentId}/schedule-builder`, { replace: true })
      })
    return () => { cancelled = true }
  }, [tournamentId, navigate])

  return <div className="container" style={{ padding: 24 }}>Redirecting to match cards…</div>
}

export function MatchCardsPage() {
  const params = useParams<{ id: string; versionId: string }>()
  const tournamentId = Number(params.id)
  const vid = Number(params.versionId)
  const validIds = !Number.isNaN(tournamentId) && tournamentId > 0 && !Number.isNaN(vid) && vid > 0

  const [preview, setPreview] = useState<MatchPreviewResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [is404, setIs404] = useState(false)

  const loadPreview = useCallback(async () => {
    if (!validIds) return
    setLoading(true)
    setError(null)
    setIs404(false)
    try {
      const data = await getMatchesPreview(tournamentId, vid)
      setPreview(data)
    } catch (e) {
      setPreview(null)
      const err = e as Error & { status?: number }
      const status = err.status
      const msg = err instanceof Error ? err.message : 'Failed to load preview'
      setError(msg)
      setIs404(status === 404)
    } finally {
      setLoading(false)
    }
  }, [tournamentId, vid, validIds])

  const handleGenerateMatches = async () => {
    if (!tournamentId || !vid) return
    setGenerating(true)
    setError(null)
    try {
      const result = await generateMatchesOnly(tournamentId, vid)
      showToast(
        result.already_generated
          ? `Matches already generated (${result.matches_generated})`
          : `Generated ${result.matches_generated} matches`,
        'success'
      )
      await loadPreview()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate matches')
      showToast(e instanceof Error ? e.message : 'Failed to generate matches', 'error')
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    loadPreview()
  }, [loadPreview])

  if (!validIds) {
    const backTo = tournamentId > 0 ? `/tournaments/${tournamentId}/schedule-builder` : '/tournaments'
    return (
      <div className="container schedule-page">
        <div className="card" style={{ padding: 24 }}>
          <p style={{ color: '#c00', marginBottom: 16 }}>Invalid tournament or version.</p>
          <Link to={backTo}>
            <button className="btn btn-secondary">Back to Schedule Builder</button>
          </Link>
        </div>
      </div>
    )
  }

  if (is404 && !loading) {
    return (
      <div className="container schedule-page">
        <div className="card" style={{ padding: 24 }}>
          <p style={{ color: '#c00', marginBottom: 16 }}>
            Schedule version not found for this tournament.
          </p>
          <div style={{ display: 'flex', gap: 8 }}>
            <Link to={`/tournaments/${tournamentId}/schedule-builder`}>
              <button className="btn btn-secondary">Back to Schedule Builder</button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  if (error && !loading && !is404) {
    return (
      <div className="container schedule-page">
        <div className="card" style={{ padding: 24 }}>
          <p style={{ color: '#c00', marginBottom: 16 }}>{error}</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <Link to={`/tournaments/${tournamentId}/schedule-builder`}>
              <button className="btn btn-secondary">Back</button>
            </Link>
            <button className="btn btn-primary" onClick={loadPreview}>
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  const byEvent = preview
    ? Object.entries(preview.counts_by_event).map(([name, count]) => ({ name, count }))
    : []
  const byStage = preview
    ? Object.entries(preview.counts_by_stage).map(([stage, count]) => ({ stage, count }))
    : []

  const STAGE_RANK: Record<string, number> = {
    WF: 10,
    RR: 20,
    MAIN: 30,
    BRACKET: 30,
    CONSOLATION: 40,
    PLACEMENT: 50,
  }

  const sortedMatches = useMemo(() => {
    if (!preview?.matches?.length) return []
    const extractPool = (code: string): string => {
      const m = code.match(/POOL([A-Z0-9]+)_/i)
      return m ? m[1].toUpperCase() : ''
    }
    return [...preview.matches].sort((a, b) => {
      const stageRankA = STAGE_RANK[a.stage] ?? STAGE_RANK[a.match_type] ?? 99
      const stageRankB = STAGE_RANK[b.stage] ?? STAGE_RANK[b.match_type] ?? 99
      const poolA = extractPool(a.match_code)
      const poolB = extractPool(b.match_code)
      return (
        a.event_id - b.event_id ||
        stageRankA - stageRankB ||
        poolA.localeCompare(poolB) ||
        (a.round_index ?? 0) - (b.round_index ?? 0) ||
        (a.sequence_in_round ?? 0) - (b.sequence_in_round ?? 0) ||
        (a.match_code ?? '').localeCompare(b.match_code ?? '') ||
        a.id - b.id
      )
    })
  }, [preview?.matches])

  const groupedByEvent = useMemo(() => {
    const map = new Map<number, Array<typeof sortedMatches[0]>>()
    for (const m of sortedMatches) {
      const eid = Number(m.event_id)
      const key = Number.isNaN(eid) ? 0 : eid
      const list = map.get(key) ?? []
      list.push(m)
      map.set(key, list)
    }
    return map
  }, [sortedMatches])

  const eventNameById = useMemo(() => {
    const map = new Map<number, string>()
    const byId = preview?.event_names_by_id ?? {}
    for (const [eidStr, name] of Object.entries(byId)) {
      const id = parseInt(eidStr, 10)
      if (!Number.isNaN(id) && name) map.set(id, name)
    }
    return map
  }, [preview?.event_names_by_id])

  const getEventName = (eventId: number) =>
    eventNameById.get(eventId) ?? preview?.event_names_by_id?.[String(eventId)] ?? `Event ${eventId}`

  const teamMap = useMemo(() => {
    const map = new Map<number, { name: string; seed: number | null; display_name: string | null }>()
    for (const t of preview?.teams ?? []) {
      map.set(t.id, { name: t.name, seed: t.seed, display_name: t.display_name })
    }
    return map
  }, [preview?.teams])

  const teamLabel = (teamId: number | null, placeholder: string): string => {
    if (teamId === null) return prettyPlaceholder(placeholder)
    const t = teamMap.get(teamId)
    if (!t) return prettyPlaceholder(placeholder)
    const label = t.display_name || t.name
    return t.seed ? `#${t.seed} ${label}` : label
  }

  /** Get RR round for Pool matches. Derives from match_code when backend round_index is wrong (legacy data). */
  const getPoolRRRoundIndex = (
    m: { match_code: string; round_index?: number },
    poolMatchCount: number
  ): number => {
    const rrSeqMatch = m.match_code.match(/_RR_(\d+)/)
    if (!rrSeqMatch || poolMatchCount < 2) return m.round_index ?? 1
    const seq = parseInt(rrSeqMatch[1], 10)
    const poolSize = Math.ceil((1 + Math.sqrt(1 + 8 * poolMatchCount)) / 2)
    const matchesPerRound = Math.floor(poolSize / 2) || 1
    const derived = Math.ceil(seq / matchesPerRound)
    return derived
  }

  /** Replace "Bracket WW/WL/LW/LL" with "Division I/II/III/IV" in placeholder text */
  const prettyPlaceholder = (s: string | undefined): string => {
    if (!s) return ''
    return s
      .replace(/Bracket WW/g, 'Division I')
      .replace(/Bracket WL/g, 'Division II')
      .replace(/Bracket LW/g, 'Division III')
      .replace(/Bracket LL/g, 'Division IV')
  }

  /** Get C-match label from match_code (_C1.._C5) */
  const getCMatchLabel = (matchCode: string | undefined): string | null => {
    if (!matchCode) return null
    const cMatch = matchCode.match(/_C(\d+)\b/i)
    const cIdx = cMatch ? Number(cMatch[1]) : null
    if (cIdx != null && cIdx >= 1 && cIdx <= 5) {
      if (cIdx === 1 || cIdx === 2) return 'Cons SF'
      if (cIdx === 3) return 'Cons Final'
      if (cIdx === 4) return 'Main-Cons SF'
      if (cIdx === 5) return '2XL'
    }
    return null
  }

  /** Get bracket round label based on position within a bracket section (1-4=QF, 5-6=SF, 7=Final) */
  const getBracketRoundLabel = (match: typeof sortedMatches[0], positionInSection: number): string => {
    // First check for C-match labels (_C1.._C5) - takes priority
    const cLabel = getCMatchLabel(match.match_code)
    if (cLabel) return cLabel

    // Otherwise use position-based QF/SF/Final mapping
    if (positionInSection >= 1 && positionInSection <= 4) return 'QF'
    if (positionInSection >= 5 && positionInSection <= 6) return 'SF'
    if (positionInSection === 7) return 'Final'
    // Fallback for edge cases
    return `R${positionInSection}`
  }

  /** Get human-readable bracket round label for MAIN bracket matches */
  const getMainBracketDisplayRound = (match: typeof sortedMatches[0]): string => {
    // First check for C-match labels (_C1.._C5) - takes priority
    const cLabel = getCMatchLabel(match.match_code)
    if (cLabel) return cLabel

    // Otherwise use MAIN bracket sequence-based mapping
    const sequence = match.sequence_in_round ?? 0
    // MAIN bracket: sequence 1–4 => "QF", 5–6 => "SF", 7 => "Final"
    if (sequence >= 1 && sequence <= 4) return 'QF'
    if (sequence >= 5 && sequence <= 6) return 'SF'
    if (sequence === 7) return 'Final'
    // Fallback for edge cases
    return `R${match.round_index ?? '?'}`
  }

  return (
    <div className="container schedule-page">
      <div className="card" style={{ padding: '24px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ margin: 0 }}>Match Cards</h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <Link to={`/tournaments/${tournamentId}/schedule-builder`}>
              <button className="btn btn-secondary">Back to Schedule Builder</button>
            </Link>
            <button
              className="btn btn-primary"
              onClick={handleGenerateMatches}
              disabled={generating}
            >
              {generating ? 'Generating...' : 'Generate Matches'}
            </button>
            <button className="btn btn-secondary" onClick={loadPreview} disabled={loading}>
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        {preview?.diagnostics && preview.matches.length > 0 && (
          <div style={{ padding: '8px 12px', background: '#e8f4fd', fontSize: 12, marginBottom: 12, borderRadius: 4 }}>
            Events in preview: {Array.isArray(preview.diagnostics.event_ids_present)
              ? preview.diagnostics.event_ids_present.join(', ')
              : '(update backend for diagnostics)'}
          </div>
        )}

        {error && (
          <div style={{ padding: '12px', background: '#fee', color: '#c00', borderRadius: 4, marginBottom: 16 }}>
            {error}
          </div>
        )}

        {preview?.diagnostics?.likely_version_mismatch && (
          <div style={{ padding: '12px', background: '#ffc', color: '#840', borderRadius: 4, marginBottom: 16 }}>
            <strong>Version mismatch:</strong> preview version = {preview.diagnostics.requested_version_id}, matches = 0.
            Other versions in this tournament have matches. Ensure Schedule Builder summary version matches.
            <button className="btn btn-secondary" onClick={loadPreview} style={{ marginLeft: 12 }}>
              Refresh
            </button>
          </div>
        )}

        {preview && preview.matches.length === 0 && !loading && (
          <div style={{ padding: '24px', textAlign: 'center', color: '#666' }}>
            <p>No matches generated for this version yet.</p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 12, flexWrap: 'wrap' }}>
              <button
                className="btn btn-primary"
                onClick={handleGenerateMatches}
                disabled={generating}
              >
                {generating ? 'Generating...' : 'Generate Matches'}
              </button>
              <button className="btn btn-secondary" onClick={loadPreview} disabled={loading}>
                {loading ? 'Loading...' : 'Refresh'}
              </button>
            </div>
          </div>
        )}

        {preview && preview.matches.length > 0 && (
          <>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 24 }}>
              <div>
                <strong>Total matches:</strong> {preview.matches.length}
              </div>
              {preview.duplicate_codes.length > 0 && (
                <div style={{ color: '#c00' }}>
                  <strong>Duplicates found:</strong> {preview.duplicate_codes.join(', ')}
                </div>
              )}
              <div>
                <strong>Checksum:</strong> <code>{preview.ordering_checksum}</code>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
              <div>
                <strong>By event:</strong>
                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                  {byEvent.map(({ name, count }) => (
                    <li key={name}>{name}: {count}</li>
                  ))}
                </ul>
              </div>
              <div>
                <strong>By stage:</strong>
                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                  {byStage.map(({ stage, count }) => (
                    <li key={stage}>{stage}: {count}</li>
                  ))}
                </ul>
              </div>
            </div>

            {Array.from(groupedByEvent.entries())
              .sort(([a], [b]) => a - b)
              .map(([eventId, matches]) => {
              const wfMatches = matches.filter((m) => m.stage === 'WF' || m.match_type === 'WF')
              const rrMatches = matches.filter((m) => m.stage === 'RR' || m.match_type === 'RR')
              const bracketMatches = matches.filter((m) =>
                ['MAIN', 'BRACKET'].includes(m.stage) || ['MAIN', 'BRACKET'].includes(m.match_type)
              )
              const otherMatches = matches.filter(
                (m) => !['WF', 'RR', 'MAIN', 'BRACKET'].includes(m.stage) && !['WF', 'RR', 'MAIN', 'BRACKET'].includes(m.match_type)
              )

              // Get division key from match_code for grouping (WW, WL, LW, LL)
              const getMainBracketDivision = (matchCode: string): string | null => {
                if (matchCode.includes('_BWW_')) return 'WW'
                if (matchCode.includes('_BWL_')) return 'WL'
                if (matchCode.includes('_BLW_')) return 'LW'
                if (matchCode.includes('_BLL_')) return 'LL'
                return null
              }

              // Group main bracket matches by division
              const mainBracketGroups = new Map<string, typeof bracketMatches>()
              const ungroupedMainBracket: typeof bracketMatches = []
              
              for (const m of bracketMatches) {
                const division = getMainBracketDivision(m.match_code)
                if (division) {
                  const arr = mainBracketGroups.get(division) ?? []
                  arr.push(m)
                  mainBracketGroups.set(division, arr)
                } else {
                  ungroupedMainBracket.push(m)
                }
              }

              // Sort main bracket matches within each division group
              // Sort by: round_index asc, then sequence_in_round asc, then match_code, then id
              for (const [, divMatches] of mainBracketGroups.entries()) {
                divMatches.sort((a, b) => {
                  return (
                    (a.round_index ?? 0) - (b.round_index ?? 0) ||
                    (a.sequence_in_round ?? 0) - (b.sequence_in_round ?? 0) ||
                    (a.match_code ?? '').localeCompare(b.match_code ?? '') ||
                    a.id - b.id
                  )
                })
              }

              // Group consolation matches by division bucket (_BWW_, _BWL_, _BLW_, _BLL_)
              const getDivisionBucket = (matchCode: string): string | null => {
                if (matchCode.includes('_BWW_')) return 'DIV_I_WW'
                if (matchCode.includes('_BWL_')) return 'DIV_II_WL'
                if (matchCode.includes('_BLW_')) return 'DIV_III_LW'
                if (matchCode.includes('_BLL_')) return 'DIV_IV_LL'
                return null
              }

              const divisionGroups = new Map<string, typeof otherMatches>()
              const ungroupedMatches: typeof otherMatches = []
              
              for (const m of otherMatches) {
                const bucket = getDivisionBucket(m.match_code)
                if (bucket) {
                  const arr = divisionGroups.get(bucket) ?? []
                  arr.push(m)
                  divisionGroups.set(bucket, arr)
                } else {
                  ungroupedMatches.push(m)
                }
              }

              // Sort division matches within each group deterministically (same as sortedMatches logic)
              for (const [, divMatches] of divisionGroups.entries()) {
                divMatches.sort((a, b) => {
                  return (
                    (a.round_index ?? 0) - (b.round_index ?? 0) ||
                    (a.sequence_in_round ?? 0) - (b.sequence_in_round ?? 0) ||
                    (a.match_code ?? '').localeCompare(b.match_code ?? '') ||
                    a.id - b.id
                  )
                })
              }

              const renderSection = (
                title: string,
                list: typeof matches,
                roundOverride?: number,
                getRoundLabel?: (match: typeof matches[0], position: number) => string
              ) =>
                list.length > 0 ? (
                  <div key={title} style={{ marginBottom: 12 }}>
                    <div style={{ fontWeight: 600, padding: '6px 0', borderBottom: '1px solid #ddd', marginBottom: 4 }}>
                      {title}
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid #ddd', textAlign: 'left' }}>
                          <th style={{ padding: 6 }}>Round</th>
                          <th style={{ padding: 6 }}>match_code</th>
                          <th style={{ padding: 6 }}>sequence</th>
                          <th style={{ padding: 6 }}>Side A / B</th>
                          <th style={{ padding: 6 }}>Duration</th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.map((m, idx) => {
                          let roundLabel: string
                          if (roundOverride != null) {
                            roundLabel = `R${roundOverride}`
                          } else if (getRoundLabel) {
                            roundLabel = getRoundLabel(m, idx + 1)
                          } else {
                            roundLabel = m.round_index ? `R${m.round_index}` : 'R?'
                          }
                          return (
                            <tr key={m.id} style={{ borderBottom: '1px solid #eee' }}>
                              <td style={{ padding: 6 }}>{roundLabel}</td>
                              <td style={{ padding: 6 }}><code>{m.match_code}</code></td>
                              <td style={{ padding: 6 }}>{m.sequence_in_round}</td>
                              <td style={{ padding: 6 }}>{teamLabel(m.team_a_id, m.placeholder_side_a)} / {teamLabel(m.team_b_id, m.placeholder_side_b)}</td>
                              <td style={{ padding: 6 }}>{m.duration_minutes}m</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null

              const poolGroups = new Map<string, typeof rrMatches>()
              for (const m of rrMatches) {
                const pool = (m.match_code.match(/POOL([A-Z0-9]+)_/i) ?? [])[1] ?? ''
                const key = pool ? `Pool ${pool}` : 'Round Robin'
                const arr = poolGroups.get(key) ?? []
                arr.push(m)
                poolGroups.set(key, arr)
              }
              const rrSections = Array.from(poolGroups.entries()).sort(([a], [b]) => {
                if (a === 'Round Robin' && b !== 'Round Robin') return 1
                if (b === 'Round Robin' && a !== 'Round Robin') return -1
                return a.localeCompare(b)
              })

              const rrRendered = rrSections.flatMap(([poolLabel, poolList]) => {
                const byRound = new Map<number, typeof poolList>()
                for (const m of poolList) {
                  const r = getPoolRRRoundIndex(m, poolList.length)
                  const arr = byRound.get(r) ?? []
                  arr.push(m)
                  byRound.set(r, arr)
                }
                const rounds = Array.from(byRound.keys())
                  .filter((k) => k > 0)
                  .sort((a, b) => a - b)
                return rounds.map((r) => renderSection(`${poolLabel} - R${r}`, byRound.get(r) ?? [], r))
              })

              // Render main bracket division sections in order: WW, WL, LW, LL
              const mainBracketDivisionOrder = ['WW', 'WL', 'LW', 'LL']
              const mainBracketDivisionLabels: Record<string, string> = {
                'WW': 'Division I',
                'WL': 'Division II',
                'LW': 'Division III',
                'LL': 'Division IV',
              }

              const mainBracketSections = mainBracketDivisionOrder
                .filter((division) => mainBracketGroups.has(division))
                .map((division) => {
                  const divMatches = mainBracketGroups.get(division) ?? []
                  return renderSection(
                    mainBracketDivisionLabels[division],
                    divMatches,
                    undefined,
                    (match) => getMainBracketDisplayRound(match)
                  )
                })

              // Render consolation division sections in order: I (WW), II (WL), III (LW), IV (LL)
              const divisionOrder = ['DIV_I_WW', 'DIV_II_WL', 'DIV_III_LW', 'DIV_IV_LL']
              const divisionLabels: Record<string, string> = {
                'DIV_I_WW': 'Division I',
                'DIV_II_WL': 'Division II',
                'DIV_III_LW': 'Division III',
                'DIV_IV_LL': 'Division IV',
              }

              const divisionSections = divisionOrder
                .filter((bucket) => divisionGroups.has(bucket))
                .map((bucket) => {
                  const divMatches = divisionGroups.get(bucket) ?? []
                  return renderSection(
                    divisionLabels[bucket],
                    divMatches,
                    undefined,
                    (match, position) => getBracketRoundLabel(match, position)
                  )
                })

              return (
                <div key={eventId} style={{ marginBottom: 24, border: '1px solid #ddd', borderRadius: 4, padding: 16 }}>
                  <h3 style={{ margin: '0 0 12px 0', fontSize: 18 }}>{getEventName(eventId)} ({matches.length} matches)</h3>
                  {renderSection('WF Round 1', wfMatches.filter((m) => (m.round_index ?? m.round_number) === 1))}
                  {renderSection('WF Round 2', wfMatches.filter((m) => (m.round_index ?? m.round_number) === 2))}
                  {rrRendered}
                  {mainBracketSections.length > 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ fontWeight: 600, padding: '6px 0', borderBottom: '1px solid #ddd', marginBottom: 4 }}>
                        Main Bracket
                      </div>
                      {mainBracketSections}
                    </div>
                  )}
                  {ungroupedMainBracket.length > 0 && renderSection('Main Bracket (Other)', ungroupedMainBracket, undefined, (match) => getMainBracketDisplayRound(match))}
                  {divisionSections.length > 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ fontWeight: 600, padding: '6px 0', borderBottom: '1px solid #ddd', marginBottom: 4 }}>
                        Consolation
                      </div>
                      {divisionSections}
                    </div>
                  )}
                  {ungroupedMatches.length > 0 && renderSection('Other', ungroupedMatches)}
                </div>
              )
            })}
          </>
        )}

        {loading && !preview && <div className="loading">Loading...</div>}
      </div>
    </div>
  )
}

export default MatchCardsPage

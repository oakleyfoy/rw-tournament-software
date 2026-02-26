import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getPublicSchedule,
  PublicScheduleResponse,
  ScheduleMatchItem,
} from '../../api/client'

const STAGE_COLORS: Record<string, string> = {
  WF: '#1a237e',
  RR: '#2e7d32',
  BRACKET: '#3949ab',
  CONS: '#e65100',
  PLACEMENT: '#6a1b9a',
}

function StageBadge({ stage }: { stage: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 3,
        fontSize: 11,
        fontWeight: 700,
        color: '#fff',
        backgroundColor: STAGE_COLORS[stage] || '#757575',
        letterSpacing: 0.5,
        textTransform: 'uppercase',
      }}
    >
      {stage}
    </span>
  )
}

function MatchCard({ match }: { match: ScheduleMatchItem }) {
  const isFinal = match.status === 'FINAL'
  const w = match.winner_team_id
  const t1Won = isFinal && w != null && match.team_a_id === w
  const t2Won = isFinal && w != null && match.team_b_id === w
  return (
    <div
      style={{
        border: '1px solid #e0e0e0',
        borderRadius: 8,
        padding: '12px 16px',
        backgroundColor: '#fff',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#333' }}>
          Match #{match.match_number}
        </span>
        <StageBadge stage={match.stage} />
      </div>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>
        {match.event_name}
        {match.division_name ? ` — ${match.division_name}` : ''}
      </div>
      <div style={{ textAlign: 'center', padding: '6px 0' }}>
        <div style={{
          fontWeight: t1Won ? 700 : 600,
          fontSize: 14,
          color: t1Won ? '#1b5e20' : '#222',
        }}>
          {t1Won && <span style={{ fontSize: 10, marginRight: 4 }}>&#9654;</span>}
          {match.team1_display}
        </div>
        <div style={{ fontSize: 12, color: '#999', margin: '3px 0' }}>vs</div>
        <div style={{
          fontWeight: t2Won ? 700 : 600,
          fontSize: 14,
          color: t2Won ? '#1b5e20' : '#222',
        }}>
          {t2Won && <span style={{ fontSize: 10, marginRight: 4 }}>&#9654;</span>}
          {match.team2_display}
        </div>
      </div>
      <div
        style={{
          marginTop: 8,
          paddingTop: 8,
          borderTop: '1px solid #f0f0f0',
          textAlign: 'center',
          fontSize: 13,
          color: isFinal ? '#2e7d32' : '#555',
          fontWeight: isFinal ? 700 : 400,
        }}
      >
        {isFinal ? (
          `Score: ${match.score_display || '—'}`
        ) : (
          <>
            {match.court_name && <span>{match.court_name}</span>}
            {match.court_name && match.scheduled_time && <span> &middot; </span>}
            {match.scheduled_time && <span>{match.scheduled_time}</span>}
            {!match.court_name && !match.scheduled_time && <span style={{ color: '#bbb' }}>Unscheduled</span>}
          </>
        )}
      </div>
    </div>
  )
}

export default function PublicSchedulePage() {
  const { tournamentId } = useParams<{ tournamentId: string }>()
  const tid = tournamentId ? parseInt(tournamentId, 10) : null

  const [data, setData] = useState<PublicScheduleResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notPublished, setNotPublished] = useState(false)

  const [eventFilter, setEventFilter] = useState<number | null>(null)
  const [divisionFilter, setDivisionFilter] = useState<string | null>(null)
  const [dayFilter, setDayFilter] = useState<number | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(value.trim())
    }, 300)
  }, [])

  const clearFilters = useCallback(() => {
    setEventFilter(null)
    setDivisionFilter(null)
    setDayFilter(null)
    setSearchInput('')
    setSearchQuery('')
  }, [])

  useEffect(() => {
    if (!tid) return
    setLoading(true)
    setNotPublished(false)
    setError(null)

    const filters: Record<string, any> = {}
    if (eventFilter != null) filters.event_id = eventFilter
    if (divisionFilter) filters.division = divisionFilter
    if (dayFilter != null) filters.day = dayFilter
    if (searchQuery) filters.search = searchQuery

    getPublicSchedule(tid, filters)
      .then((resp: any) => {
        if (resp.status === 'NOT_PUBLISHED') {
          setNotPublished(true)
          setData(null)
        } else {
          setData(resp)
          setNotPublished(false)
        }
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [tid, eventFilter, divisionFilter, dayFilter, searchQuery])

  const grouped = useMemo(() => {
    if (!data) return new Map<number, { label: string; times: { sortKey: string; displayTime: string; matches: ScheduleMatchItem[] }[] }>()
    const byDay = new Map<number, { label: string; timeMap: Map<string, { sortKey: string; displayTime: string; matches: ScheduleMatchItem[] }> }>()
    for (const m of data.matches) {
      if (!byDay.has(m.day_index)) {
        byDay.set(m.day_index, { label: m.day_label, timeMap: new Map() })
      }
      const dayGroup = byDay.get(m.day_index)!
      const displayTime = m.scheduled_time || 'Unscheduled'
      const sortKey = m.sort_time || '99:99'
      if (!dayGroup.timeMap.has(displayTime)) {
        dayGroup.timeMap.set(displayTime, { sortKey, displayTime, matches: [] })
      }
      dayGroup.timeMap.get(displayTime)!.matches.push(m)
    }
    const result = new Map<number, { label: string; times: { sortKey: string; displayTime: string; matches: ScheduleMatchItem[] }[] }>()
    for (const [dayIdx, dayGroup] of byDay) {
      const sortedTimes = Array.from(dayGroup.timeMap.values()).sort((a, b) => a.sortKey.localeCompare(b.sortKey))
      result.set(dayIdx, { label: dayGroup.label, times: sortedTimes })
    }
    return result
  }, [data])

  const hasActiveFilters = eventFilter != null || divisionFilter != null || dayFilter != null || searchQuery !== ''
  const isSearchMode = searchQuery !== ''

  if (loading && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#666' }}>
        Loading schedule...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#c62828' }}>
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

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '24px 16px' }}>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{
          fontSize: 22,
          fontWeight: 700,
          color: '#1a237e',
          margin: 0,
          textAlign: 'center',
          textTransform: 'uppercase',
          letterSpacing: 1,
        }}>
          {data.tournament_name}
        </h1>
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          gap: 20,
          marginTop: 10,
          fontSize: 14,
          fontWeight: 600,
        }}>
          <Link
            to={`/t/${tid}/draws`}
            style={{ color: '#666', textDecoration: 'none' }}
          >
            Draws
          </Link>
          <span style={{
            color: '#1a237e',
            textDecoration: 'none',
            borderBottom: '2px solid #1a237e',
            paddingBottom: 2,
          }}>
            Schedule
          </span>
        </div>
      </div>

      {/* Filter Bar */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 10,
        marginBottom: 20,
        padding: '12px 16px',
        backgroundColor: '#f5f5f5',
        borderRadius: 8,
        alignItems: 'center',
      }}>
        <select
          value={eventFilter ?? ''}
          onChange={e => setEventFilter(e.target.value ? parseInt(e.target.value, 10) : null)}
          style={{
            padding: '6px 10px',
            borderRadius: 4,
            border: '1px solid #ccc',
            fontSize: 13,
            minWidth: 140,
            flex: '1 1 140px',
          }}
        >
          <option value="">All Events</option>
          {data.events.map(ev => (
            <option key={ev.event_id} value={ev.event_id}>{ev.event_name}</option>
          ))}
        </select>

        <select
          value={divisionFilter ?? ''}
          onChange={e => setDivisionFilter(e.target.value || null)}
          style={{
            padding: '6px 10px',
            borderRadius: 4,
            border: '1px solid #ccc',
            fontSize: 13,
            minWidth: 140,
            flex: '1 1 140px',
          }}
        >
          <option value="">All Divisions</option>
          {data.divisions.map(d => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>

        <select
          value={dayFilter ?? ''}
          onChange={e => setDayFilter(e.target.value ? parseInt(e.target.value, 10) : null)}
          style={{
            padding: '6px 10px',
            borderRadius: 4,
            border: '1px solid #ccc',
            fontSize: 13,
            minWidth: 120,
            flex: '1 1 120px',
          }}
        >
          <option value="">All Days</option>
          {data.days.map(d => (
            <option key={d.day_index} value={d.day_index}>{d.label}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Search team/player..."
          value={searchInput}
          onChange={e => handleSearchChange(e.target.value)}
          style={{
            padding: '6px 10px',
            borderRadius: 4,
            border: '1px solid #ccc',
            fontSize: 13,
            minWidth: 160,
            flex: '2 1 160px',
          }}
        />

        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            style={{
              padding: '6px 14px',
              borderRadius: 4,
              border: '1px solid #ccc',
              backgroundColor: '#fff',
              fontSize: 13,
              cursor: 'pointer',
              fontWeight: 500,
              color: '#c62828',
            }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Content */}
      {loading && (
        <div style={{ textAlign: 'center', color: '#888', padding: 20, fontSize: 13 }}>
          Updating...
        </div>
      )}

      {data.matches.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#888', padding: 40, fontSize: 14 }}>
          No matches found.
        </div>
      ) : isSearchMode ? (
        /* Search results: flat list */
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#333', marginBottom: 16 }}>
            Search Results for &lsquo;{searchQuery}&rsquo;
            <span style={{ fontWeight: 400, color: '#888', marginLeft: 8 }}>
              ({data.matches.length} match{data.matches.length !== 1 ? 'es' : ''})
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {data.matches.map(m => (
              <MatchCard key={m.match_id} match={m} />
            ))}
          </div>
        </div>
      ) : (
        /* Timeline view: grouped by day, then time (sorted by 24h sort_time) */
        <div>
          {Array.from(grouped.entries())
            .sort(([a], [b]) => a - b)
            .map(([dayIdx, dayGroup]) => (
              <div key={dayIdx} style={{ marginBottom: 24 }}>
                {grouped.size > 1 && (
                  <div style={{
                    fontSize: 16,
                    fontWeight: 700,
                    color: '#1a237e',
                    marginBottom: 12,
                    paddingBottom: 6,
                    borderBottom: '2px solid #e0e0e0',
                  }}>
                    Day {dayIdx} &mdash; {dayGroup.label}
                  </div>
                )}
                {dayGroup.times.map(timeGroup => (
                  <div key={timeGroup.displayTime} style={{ marginBottom: 16 }}>
                    <div style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: '#555',
                      marginBottom: 8,
                      paddingLeft: 2,
                    }}>
                      {timeGroup.displayTime}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
                      {timeGroup.matches.map(m => (
                        <MatchCard key={m.match_id} match={m} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ))}
        </div>
      )}
    </div>
  )
}

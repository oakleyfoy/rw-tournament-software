import type { RwOsRosterFieldChange } from '../../api/client'

type RefreshNotice = { code?: string; message?: string; teamKey?: string }

const TOWEL_NOTICE_CODE = 'missing_towel_color'
const WKW_NOTICE_CODE = 'missing_who_knows_who'
const DRAW_PROTECTION_CODE = 'live_draw_protection_blocks_structural_change'

function teamKeyFromNotice(notice: RefreshNotice): string | null {
  if (notice.teamKey) return notice.teamKey
  const snakeKey = (notice as { team_key?: string }).team_key
  if (snakeKey) return snakeKey
  const match = notice.message?.match(/Team\s+(\d+\/\d+)/i)
  return match?.[1] || null
}

export function summarizeRwOsRefreshNotices(notices: RefreshNotice[]): RefreshNotice[] {
  const towels = new Set<string>()
  const wkw = new Set<string>()
  const protectedDraws: string[] = []
  const rest: RefreshNotice[] = []
  for (const notice of notices) {
    const code = notice.code || ''
    const message = notice.message || ''
    if (code === TOWEL_NOTICE_CODE || /missing a towel color/i.test(message)) {
      towels.add(teamKeyFromNotice(notice) || message)
      continue
    }
    if (code === WKW_NOTICE_CODE || /missing Who-knows-who/i.test(message)) {
      wkw.add(teamKeyFromNotice(notice) || message)
      continue
    }
    if (code === DRAW_PROTECTION_CODE || /event has generated draw/i.test(message)) {
      if (message && !protectedDraws.includes(message)) protectedDraws.push(message)
      continue
    }
    rest.push(notice)
  }
  const summarized = [...rest]
  if (towels.size) {
    summarized.push({
      code: TOWEL_NOTICE_CODE,
      message: `${towels.size} team${towels.size === 1 ? '' : 's'} still missing a towel color in RW-OS`,
    })
  }
  if (wkw.size) {
    summarized.push({
      code: WKW_NOTICE_CODE,
      message: `${wkw.size} team${wkw.size === 1 ? '' : 's'} still missing Who Knows Who in RW-OS`,
    })
  }
  if (protectedDraws.length) {
    summarized.push({
      code: DRAW_PROTECTION_CODE,
      message: 'Live draws were left in place. Withdrawals and new teams were not added or removed from the bracket.',
    })
  }
  return summarized
}

export type RwOsRosterSnapshotDiff = {
  addedCount?: number
  withdrawnCount?: number
  addedTeams?: unknown[]
  withdrawnTeams?: unknown[]
  partnerChanges?: unknown[]
  drawChanges?: unknown[]
  ratingChanges?: unknown[]
}

export function isRwOsBackedTournament(
  tournament: { rw_os_import_id?: number | null; source_rw_os_tournament_id?: number | null } | null,
): boolean {
  return tournament?.rw_os_import_id != null || tournament?.source_rw_os_tournament_id != null
}

export function formatRwOsRosterRefreshSummary(updated?: {
  teams: number
  contactFields: number
  towelRows: number
} | null): string {
  if (!updated) return 'Roster refreshed from RW-OS'
  const parts = [
    `${updated.teams} team${updated.teams === 1 ? '' : 's'} updated`,
    `${updated.contactFields} contact field${updated.contactFields === 1 ? '' : 's'}`,
    `${updated.towelRows} towel${updated.towelRows === 1 ? '' : 's'}`,
  ]
  return parts.join(' · ')
}

export function formatRwOsChangeValue(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  return String(value)
}

export function groupRwOsRosterFieldChanges(changes: RwOsRosterFieldChange[]): Array<{
  teamKey: string
  teamLabel: string
  changes: RwOsRosterFieldChange[]
}> {
  const groups: Array<{ teamKey: string; teamLabel: string; changes: RwOsRosterFieldChange[] }> = []
  const index = new Map<string, (typeof groups)[number]>()
  for (const change of changes) {
    let group = index.get(change.teamKey)
    if (!group) {
      group = { teamKey: change.teamKey, teamLabel: change.teamLabel || change.teamKey, changes: [] }
      index.set(change.teamKey, group)
      groups.push(group)
    }
    group.changes.push(change)
  }
  return groups
}

function snapshotTeamLabel(team: unknown): string {
  if (!team || typeof team !== 'object') return 'Team'
  const row = team as { teamKey?: string; displayName?: string; fullName?: string }
  return row.displayName || row.fullName || row.teamKey || 'Team'
}

export function RwOsRosterRefreshCard({
  loading,
  summary,
  notices,
  fieldChanges,
  snapshotDiff,
  onRefresh,
}: {
  loading: boolean
  summary: string | null
  notices?: RefreshNotice[]
  fieldChanges?: RwOsRosterFieldChange[]
  snapshotDiff?: RwOsRosterSnapshotDiff | null
  onRefresh: () => void
}) {
  const groups = groupRwOsRosterFieldChanges(fieldChanges ?? [])
  const added = snapshotDiff?.addedTeams ?? []
  const withdrawn = snapshotDiff?.withdrawnTeams ?? []
  const summarizedNotices = summarizeRwOsRefreshNotices(notices ?? [])
  const showSnapshot =
    added.length > 0 ||
    withdrawn.length > 0 ||
    (snapshotDiff?.partnerChanges?.length ?? 0) > 0 ||
    (snapshotDiff?.drawChanges?.length ?? 0) > 0

  return (
    <div className="card" style={{ marginBottom: 24 }} data-testid="rw-os-roster-refresh">
      <h2 className="section-title">Refresh roster from RW-OS</h2>
      <p style={{ fontSize: 13, color: 'var(--theme-text)', lineHeight: 1.5, marginTop: 0 }}>
        Pull the latest names, ratings, contacts, and towels from RW-OS onto teams already in this tournament.
        Teams stay in their draws; matches are not regenerated.
      </p>
      <button
        type="button"
        className="btn btn-primary"
        disabled={loading}
        onClick={onRefresh}
        style={{ fontSize: 13, padding: '6px 14px' }}
      >
        {loading ? 'Refreshing…' : 'Refresh roster from RW-OS'}
      </button>
      {summary && (
        <div style={{ marginTop: 12, fontSize: 13 }} data-testid="rw-os-roster-refresh-summary">
          {summary}
        </div>
      )}
      {groups.length > 0 && (
        <div style={{ marginTop: 12 }} data-testid="rw-os-roster-refresh-changes">
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Applied changes</div>
          {groups.map((group) => (
            <div key={group.teamKey} style={{ marginBottom: 10, fontSize: 12, lineHeight: 1.5 }}>
              <div style={{ fontWeight: 600 }}>{group.teamLabel}</div>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {group.changes.map((change) => (
                  <li key={`${group.teamKey}-${change.field}`}>
                    {change.label}: {formatRwOsChangeValue(change.before)} → {formatRwOsChangeValue(change.after)}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {summary && groups.length === 0 && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>No field changes on existing teams.</div>
      )}
      {showSnapshot && (
        <div style={{ marginTop: 12, fontSize: 12 }} data-testid="rw-os-roster-refresh-snapshot">
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>RW-OS snapshot changes not applied to draws</div>
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.5 }}>
            {added.map((team, index) => (
              <li key={`added-${index}`}>Added: {snapshotTeamLabel(team)}</li>
            ))}
            {withdrawn.map((team, index) => (
              <li key={`withdrawn-${index}`}>Withdrawn: {snapshotTeamLabel(team)}</li>
            ))}
            {(snapshotDiff?.partnerChanges?.length ?? 0) > 0 && (
              <li>{snapshotDiff?.partnerChanges?.length} partner change{(snapshotDiff?.partnerChanges?.length ?? 0) === 1 ? '' : 's'}</li>
            )}
            {(snapshotDiff?.drawChanges?.length ?? 0) > 0 && (
              <li>{snapshotDiff?.drawChanges?.length} draw move{(snapshotDiff?.drawChanges?.length ?? 0) === 1 ? '' : 's'}</li>
            )}
          </ul>
        </div>
      )}
      {summarizedNotices.length > 0 && (
        <ul
          style={{ margin: '10px 0 0', paddingLeft: 18, fontSize: 12, color: '#8a6d3b' }}
          data-testid="rw-os-roster-refresh-notices"
        >
          {summarizedNotices.map((notice, index) => (
            <li key={`${notice.code || 'notice'}-${index}`}>{notice.message || notice.code}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

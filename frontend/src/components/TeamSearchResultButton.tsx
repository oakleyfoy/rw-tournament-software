export interface PhotoTeamSearchHit {
  team_id: number
  event_id: number
  division: string
  seed?: number | null
  player_names: string[]
  avoid_group?: string | null
  source_team_key?: string | null
  has_official_photo: boolean
}

export function teamSearchDistinguishers(hit: PhotoTeamSearchHit): string {
  const parts = [`Team ${hit.team_id}`, hit.division || 'Division unknown']
  if (hit.seed != null) parts.push(`Seed ${hit.seed}`)
  if (hit.avoid_group) parts.push(`Avoid ${hit.avoid_group}`)
  if (hit.source_team_key) parts.push(hit.source_team_key)
  if (hit.has_official_photo) parts.push('Has official photo')
  return parts.join(' · ')
}

export function TeamSearchResultButton({
  hit,
  onSelect,
}: {
  hit: PhotoTeamSearchHit
  onSelect: (hit: PhotoTeamSearchHit) => void
}) {
  const names = hit.player_names.length >= 2 ? hit.player_names : [...hit.player_names, 'Partner not on file']
  return (
    <button
      type="button"
      onClick={() => onSelect(hit)}
      style={{
        width: '100%',
        textAlign: 'left',
        padding: '12px 14px',
        borderRadius: 10,
        border: '1px solid #cfd8dc',
        background: '#fff',
        cursor: 'pointer',
      }}
    >
      <div style={{ fontWeight: 800, fontSize: 16 }}>{names[0]}</div>
      <div style={{ fontWeight: 800, fontSize: 16 }}>{names[1]}</div>
      <div style={{ marginTop: 4, fontSize: 13, color: '#546e7a' }}>{teamSearchDistinguishers(hit)}</div>
    </button>
  )
}

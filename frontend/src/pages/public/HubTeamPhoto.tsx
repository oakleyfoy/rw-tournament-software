import { useState } from 'react'
import { publicTeamPhotoUrl, type PublicTeamDirectoryItem } from '../../api/client'
import { teamInitials } from '../../lib/publicMobileDraw'

export function HubTeamPhoto({
  tournamentId,
  team,
  large = false,
  onEnlarge,
}: {
  tournamentId: number
  team: Pick<PublicTeamDirectoryItem, 'team_id' | 'full_name' | 'photo_version' | 'players'> | null
  large?: boolean
  onEnlarge?: () => void
}) {
  const [broken, setBroken] = useState(false)
  const name = team?.full_name || 'Team'
  const version = team?.photo_version
  if (!team || !version || broken) {
    return (
      <span
        className={large ? 'hub-photo-fallback large' : 'hub-photo-fallback'}
        aria-hidden="true"
        data-testid={team ? `hub-photo-fallback-${team.team_id}` : 'hub-photo-fallback'}
      >
        {teamInitials(name)}
      </span>
    )
  }
  const image = (
    <img
      className={large ? 'hub-photo large' : 'hub-photo'}
      src={publicTeamPhotoUrl(tournamentId, team.team_id, version)}
      alt=""
      width={large ? 96 : 48}
      height={large ? 96 : 48}
      loading="lazy"
      data-testid={`hub-photo-${team.team_id}`}
      onError={() => setBroken(true)}
    />
  )
  if (!large || !onEnlarge) return image
  return (
    <button
      type="button"
      className="hub-photo-enlarge"
      onClick={onEnlarge}
      aria-label={`Enlarge photo of ${name}`}
      data-testid={`hub-photo-enlarge-${team.team_id}`}
    >
      {image}
    </button>
  )
}

export function HubPhotoDialog({
  tournamentId,
  team,
  onClose,
}: {
  tournamentId: number
  team: Pick<PublicTeamDirectoryItem, 'team_id' | 'full_name' | 'photo_version'>
  onClose: () => void
}) {
  if (!team.photo_version) return null
  return (
    <div className="hub-dialog" role="dialog" aria-modal="true" aria-label="Team photograph">
      <button type="button" onClick={onClose}>Close</button>
      <img
        src={publicTeamPhotoUrl(tournamentId, team.team_id, team.photo_version)}
        alt={team.full_name}
      />
    </div>
  )
}

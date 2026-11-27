import { createContext, useContext, useState } from 'react'
import { publicTeamPhotoUrl } from '../../api/client'

export const DrawPhotoTournamentContext = createContext<number | null>(null)

export function DrawTeamPhoto({
  teamId,
  version,
  size,
}: {
  teamId?: number | null
  version?: string | null
  size: number
}) {
  const tournamentId = useContext(DrawPhotoTournamentContext)
  const [broken, setBroken] = useState(false)
  if (tournamentId == null || teamId == null || !version || broken) return null
  return (
    <img
      src={publicTeamPhotoUrl(tournamentId, teamId, version)}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      onError={() => setBroken(true)}
      style={{
        width: size,
        height: size,
        objectFit: 'cover',
        borderRadius: 3,
        flex: '0 0 auto',
        display: 'block',
      }}
    />
  )
}

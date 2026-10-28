import { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'

export function TournamentHubQrButton({
  tournamentId,
  className = 'btn btn-secondary',
  style,
}: {
  tournamentId: number
  className?: string
  style?: CSSProperties
}) {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      className={className}
      style={style}
      data-testid="tournament-qr-code"
      onClick={() => navigate(`/tournaments/${tournamentId}/tournament-qr`)}
    >
      Tournament QR Code
    </button>
  )
}

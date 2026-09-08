import { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'

export function DrawQrBoardButton({
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
      data-testid="print-draw-qr-board"
      onClick={() => navigate(`/tournaments/${tournamentId}/draw-qr-board`)}
    >
      Print Draw QR Board
    </button>
  )
}

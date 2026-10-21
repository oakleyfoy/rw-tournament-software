import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { getAuthToken } from '../api/client'
import { officialTeamPhotoContentUrl } from '../api/photography'

export interface TeamPhotoContextValue {
  photos: Record<number, string>
  refresh: () => Promise<void>
  tournamentId: number | null
}

const TeamPhotoContext = createContext<TeamPhotoContextValue>({
  photos: {},
  refresh: async () => undefined,
  tournamentId: null,
})

export function TeamPhotoProvider({
  value,
  children,
}: {
  value: TeamPhotoContextValue
  children: ReactNode
}) {
  return <TeamPhotoContext.Provider value={value}>{children}</TeamPhotoContext.Provider>
}

export function useTeamPhotos(): TeamPhotoContextValue {
  return useContext(TeamPhotoContext)
}

const objectUrlCache = new Map<string, string>()

function Placeholder({ size, surface }: { size: number; surface?: string }) {
  return (
    <span
      data-testid="team-photo-placeholder"
      data-photo-surface={surface}
      title="No team photo"
      aria-label="No team photo"
      style={{
        width: size,
        height: size,
        borderRadius: 4,
        background: '#eceff1',
        border: '1px solid #cfd8dc',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        color: '#90a4ae',
      }}
    >
      <svg width={Math.max(10, size - 8)} height={Math.max(10, size - 8)} viewBox="0 0 24 24" aria-hidden>
        <circle cx="12" cy="8" r="3.2" fill="currentColor" />
        <path d="M5 19c1.2-3.2 3.4-4.8 7-4.8S17.8 15.8 19 19" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    </span>
  )
}

export function TeamPhotoThumb({
  teamId,
  size = 28,
  surface,
}: {
  teamId?: number | null
  size?: number
  surface?: string
}) {
  const { photos } = useTeamPhotos()
  const version = teamId != null ? photos[teamId] : undefined
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (teamId == null || !version) {
      setSrc(null)
      setFailed(false)
      return
    }
    const url = officialTeamPhotoContentUrl(teamId, version)
    const cached = objectUrlCache.get(url)
    if (cached) {
      setSrc(cached)
      setFailed(false)
      return
    }
    let cancelled = false
    const token = getAuthToken()
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (cancelled) return
        if (!blob) {
          setFailed(true)
          setSrc(null)
          return
        }
        const objectUrl = URL.createObjectURL(blob)
        objectUrlCache.set(url, objectUrl)
        setSrc(objectUrl)
        setFailed(false)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [teamId, version])

  if (!version || failed || !src) {
    return <Placeholder size={size} surface={surface} />
  }
  return (
    <>
      <button
        type="button"
        aria-label="View larger team photo"
        onClick={() => setOpen(true)}
        style={{
          padding: 0,
          border: 0,
          background: 'transparent',
          lineHeight: 0,
          cursor: 'pointer',
        }}
      >
        <img
          data-testid="team-photo"
          data-photo-surface={surface}
          src={src}
          alt="Official team photo"
          width={size}
          height={size}
          style={{
            width: size,
            height: size,
            objectFit: 'cover',
            borderRadius: 4,
            border: '1px solid #cfd8dc',
            flexShrink: 0,
            background: '#eceff1',
          }}
        />
      </button>
      {open && createPortal(
        <div
          role="dialog"
          aria-label="Official team photo"
          onClick={() => setOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 20000,
            background: 'rgba(0,0,0,0.72)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
          }}
        >
          <img
            src={src}
            alt="Official team photo"
            style={{ maxWidth: '92vw', maxHeight: '92vh', objectFit: 'contain', borderRadius: 8 }}
          />
        </div>,
        document.body,
      )}
    </>
  )
}

export function MatchTeamPhotos({
  teamIds,
  size = 22,
  surface,
}: {
  teamIds: Array<number | null | undefined>
  size?: number
  surface?: string
}) {
  return (
    <div data-testid="match-team-photos" data-photo-surface={surface} style={{ display: 'flex', gap: 4, marginBottom: 3 }}>
      {teamIds.map((teamId, index) => (
        <TeamPhotoThumb key={`${teamId ?? 'open'}-${index}`} teamId={teamId} size={size} surface={surface} />
      ))}
    </div>
  )
}

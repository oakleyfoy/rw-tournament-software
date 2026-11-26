import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { getAuthToken } from '../api/client'
import { officialTeamPhotoContentUrl, officialTeamPhotoThumbUrl } from '../api/photography'

export interface TeamPhotoContextValue {
  photos: Record<number, string>
  thumbUrls?: Record<number, string>
  refresh: () => Promise<void>
  showSaved?: (teamId: number, version: string) => void
  tournamentId: number | null
}

const TeamPhotoContext = createContext<TeamPhotoContextValue>({
  photos: {},
  thumbUrls: {},
  refresh: async () => undefined,
  showSaved: () => undefined,
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

function Placeholder({ size, surface, frame }: { size: number; surface?: string; frame: 'square' | 'card' }) {
  const icon = frame === 'card' ? 72 : Math.max(10, size - 8)
  return (
    <span
      data-testid="team-photo-placeholder"
      data-photo-surface={surface}
      data-photo-frame={frame}
      title="No team photo"
      aria-label="No team photo"
      style={{
        width: frame === 'card' ? '100%' : size,
        height: frame === 'card' ? 220 : size,
        borderRadius: frame === 'card' ? 8 : 4,
        background: '#eceff1',
        border: '1px solid #cfd8dc',
        display: frame === 'card' ? 'flex' : 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        color: '#90a4ae',
        boxSizing: 'border-box',
      }}
    >
      <svg width={icon} height={icon} viewBox="0 0 24 24" aria-hidden>
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
  frame = 'square',
  missing = 'placeholder',
  lazy = false,
  enlargePreview = false,
}: {
  teamId?: number | null
  size?: number
  surface?: string
  frame?: 'square' | 'card'
  missing?: 'placeholder' | 'hide'
  lazy?: boolean
  enlargePreview?: boolean
}) {
  const { photos, thumbUrls } = useTeamPhotos()
  const version = teamId != null ? photos[teamId] : undefined
  const directThumb = teamId != null ? thumbUrls?.[teamId] : undefined
  const [src, setSrc] = useState<string | null>(null)
  const [loadedVersion, setLoadedVersion] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState(false)
  const [fullSrc, setFullSrc] = useState<string | null>(null)

  useEffect(() => {
    if (teamId == null || !version) {
      setSrc(null)
      setLoadedVersion(null)
      setFailed(false)
      setOpen(false)
      setFullSrc(null)
      return
    }
    setFullSrc(null)
    if (directThumb) {
      setSrc(directThumb)
      setLoadedVersion(version)
      setFailed(false)
      return
    }
    const url = officialTeamPhotoThumbUrl(teamId, version)
    const cached = objectUrlCache.get(url)
    if (cached) {
      setSrc(cached)
      setLoadedVersion(version)
      setFailed(false)
      return
    }
    let cancelled = false
    const token = getAuthToken()
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined
    const load = async () => {
      try {
        const response = await fetch(url, { headers })
        if (!response.ok) throw new Error('missing thumb')
        const blob = await response.blob()
        if (cancelled) return
        if (!blob.size) throw new Error('empty thumb')
        const objectUrl = URL.createObjectURL(blob)
        objectUrlCache.set(url, objectUrl)
        if (cancelled) return
        setSrc(objectUrl)
        setLoadedVersion(version)
        setFailed(false)
      } catch {
        if (!cancelled) {
          setFailed(true)
          setSrc(null)
          setLoadedVersion(null)
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [directThumb, teamId, version])

  useEffect(() => {
    if (!open || frame !== 'card' || teamId == null || !version) return
    const url = officialTeamPhotoContentUrl(teamId, version)
    const cached = objectUrlCache.get(url)
    if (cached) {
      setFullSrc(cached)
      return
    }
    let cancelled = false
    const token = getAuthToken()
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined
    const load = async () => {
      try {
        const response = await fetch(url, { headers })
        if (!response.ok) return
        const blob = await response.blob()
        if (cancelled || !blob.size) return
        const objectUrl = URL.createObjectURL(blob)
        objectUrlCache.set(url, objectUrl)
        if (!cancelled) setFullSrc(objectUrl)
      } catch {
        // The card already shows the thumbnail. Leave the camera file unloaded.
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [frame, open, teamId, version])

  if (!version || failed || !src || loadedVersion !== version) {
    if (missing === 'hide') return null
    return <Placeholder size={size} surface={surface} frame={frame} />
  }
  const card = frame === 'card'
  return (
    <>
      <span
        role="button"
        tabIndex={0}
        aria-label="View larger team photo"
        onMouseDown={(event) => {
          event.stopPropagation()
        }}
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          setOpen(true)
        }}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return
          event.preventDefault()
          event.stopPropagation()
          setOpen(true)
        }}
        style={{
          display: card ? 'block' : 'inline-flex',
          width: card ? '100%' : undefined,
          padding: 0,
          border: 0,
          background: 'transparent',
          lineHeight: 0,
          cursor: 'pointer',
          flexShrink: 0,
          touchAction: 'manipulation',
        }}
      >
        <img
          data-testid="team-photo"
          data-photo-surface={surface}
          data-photo-frame={frame}
          data-photo-version={version}
          draggable={false}
          loading={lazy ? 'lazy' : undefined}
          decoding="async"
          src={src}
          alt="Official team photo"
          width={card ? undefined : size}
          height={card ? undefined : size}
          style={card ? {
            width: '100%',
            height: 'auto',
            maxHeight: '70vh',
            objectFit: 'contain',
            borderRadius: 8,
            border: '1px solid #cfd8dc',
            background: '#eceff1',
            display: 'block',
          } : {
            width: size,
            height: size,
            objectFit: 'cover',
            borderRadius: 4,
            border: '1px solid #cfd8dc',
            flexShrink: 0,
            background: '#eceff1',
          }}
        />
      </span>
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
            src={frame === 'card' && fullSrc ? fullSrc : src}
            alt="Official team photo"
            style={enlargePreview
              ? { width: 'min(720px, 92vw)', maxHeight: '92vh', objectFit: 'contain', borderRadius: 8 }
              : { maxWidth: '92vw', maxHeight: '92vh', objectFit: 'contain', borderRadius: 8 }}
          />
        </div>,
        document.body,
      )}
    </>
  )
}

export function TeamPhotoNameRow({
  teamId,
  name,
  size = 22,
  surface,
}: {
  teamId?: number | null
  name: string
  size?: number
  surface?: string
}) {
  return (
    <div
      data-testid="team-photo-name-row"
      data-team-id={teamId ?? ''}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        minWidth: 0,
      }}
    >
      <TeamPhotoThumb teamId={teamId} size={size} surface={surface} />
      <span
        data-testid="team-photo-name"
        style={{
          minWidth: 0,
          overflowWrap: 'anywhere',
          lineHeight: 1.2,
        }}
      >
        {name}
      </span>
    </div>
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

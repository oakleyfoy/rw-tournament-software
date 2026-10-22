import { FormEvent, useEffect, useReducer, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { clearAuthToken, logoutAuth } from '../api/client'
import {
  deleteOfficialTeamPhoto,
  listOfficialTeamPhotos,
  listPhotographyTournaments,
  PhotographyTournament,
  postOfficialTeamPhoto,
  searchPhotographyTeams,
} from '../api/photography'
import { TeamPhotoProvider, TeamPhotoThumb } from '../components/TeamPhotoThumb'
import { TeamSearchResultButton } from '../components/TeamSearchResultButton'
import type { PhotoTeamSearchHit } from '../components/TeamSearchResultButton'
import { initialPhotographerSession, photographerReducer } from '../lib/photographerSession'
import { prepareTeamPhoto } from '../lib/prepareTeamPhoto'

export default function PhotographerPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [tournaments, setTournaments] = useState<PhotographyTournament[]>([])
  const [session, dispatch] = useReducer(photographerReducer, initialPhotographerSession)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<PhotoTeamSearchHit[]>([])
  const [selectedTeam, setSelectedTeam] = useState<PhotoTeamSearchHit | null>(null)
  const [savedOfficial, setSavedOfficial] = useState<{ teamId: number; version: string } | null>(null)
  const [photoVersions, setPhotoVersions] = useState<Record<number, string>>({})
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deleteLock = useRef(false)
  const [searching, setSearching] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const blobsRef = useRef<Record<string, Blob>>({})
  const confirmLock = useRef(false)
  const cameraRef = useRef<HTMLInputElement>(null)
  const libraryRef = useRef<HTMLInputElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    listPhotographyTournaments()
      .then((rows) => {
        setTournaments(rows)
        const requested = Number(searchParams.get('tournament') || '')
        const initial = rows.find((row) => row.id === requested) || rows[0]
        if (initial) dispatch({ type: 'selectTournament', tournamentId: initial.id })
      })
      .catch((error: unknown) => {
        setPageError(error instanceof Error ? error.message : 'Could not load tournaments')
      })
  }, [searchParams])

  useEffect(() => {
    if (!session.tournamentId || query.trim().length < 1 || session.phase !== 'search') {
      setResults([])
      return
    }
    const handle = window.setTimeout(() => {
      setSearching(true)
      searchPhotographyTeams(session.tournamentId as number, query.trim())
        .then((hits) => setResults(hits))
        .catch((error: unknown) => {
          setResults([])
          setActionError(error instanceof Error ? error.message : 'Team search failed')
        })
        .finally(() => setSearching(false))
    }, 250)
    return () => window.clearTimeout(handle)
  }, [query, session.tournamentId, session.phase])

  useEffect(() => {
    if (session.phase === 'search') searchRef.current?.focus()
  }, [session.phase, session.confirmationMessage])

  useEffect(() => {
    if (!session.tournamentId) return
    let cancelled = false
    listOfficialTeamPhotos(session.tournamentId)
      .then((rows) => {
        if (cancelled) return
        const next: Record<number, string> = {}
        for (const row of rows) {
          const version = row.version || row.updated_at
          if (version) next[row.team_id] = version
        }
        setPhotoVersions(next)
      })
      .catch(() => {
        // The team card still shows a placeholder when the current version is unknown.
      })
    return () => {
      cancelled = true
    }
  }, [session.tournamentId])

  const selectTeam = (hit: PhotoTeamSearchHit) => {
    blobsRef.current = {}
    setConfirmDelete(false)
    setSelectedTeam(hit)
    setActionError(null)
    dispatch({ type: 'selectTeam', teamId: hit.team_id })
  }

  const teamLabel = (names: string[]) => names.filter((name) => name !== 'Partner not on file').join(' / ')

  const confirmDeletePhoto = async () => {
    if (deleteLock.current || deleting || !session.tournamentId || !selectedTeam) return
    deleteLock.current = true
    setDeleting(true)
    setActionError(null)
    const teamId = selectedTeam.team_id
    try {
      await deleteOfficialTeamPhoto(session.tournamentId, teamId)
      setPhotoVersions((current) => {
        if (!(teamId in current)) return current
        const next = { ...current }
        delete next[teamId]
        return next
      })
      setSelectedTeam({ ...selectedTeam, has_official_photo: false })
      setSavedOfficial((current) => (current?.teamId === teamId ? null : current))
      setConfirmDelete(false)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not delete the official photo. You can retry.')
    } finally {
      deleteLock.current = false
      setDeleting(false)
    }
  }

  const onPickFile = async (file: File | undefined) => {
    if (!file || !selectedTeam) return
    setActionError(null)
    try {
      const prepared = await prepareTeamPhoto(file)
      const localId = prepared.clientUploadId
      blobsRef.current[localId] = prepared.blob
      dispatch({
        type: 'addCapture',
        capture: {
          localId,
          clientUploadId: prepared.clientUploadId,
          previewUrl: URL.createObjectURL(prepared.blob),
          progress: 100,
          status: 'ready',
        },
      })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not prepare the photograph')
    }
  }

  const confirmOfficial = async () => {
    if (confirmLock.current || !session.tournamentId || !selectedTeam || !session.selectedLocalId) return
    const chosen = session.captures.find((capture) => capture.localId === session.selectedLocalId)
    const blob = chosen ? blobsRef.current[chosen.localId] : undefined
    if (!chosen || !blob) return
    if (chosen.status !== 'ready' && chosen.status !== 'uploaded') return
    confirmLock.current = true
    dispatch({ type: 'confirmStart' })
    dispatch({ type: 'uploadProgress', localId: chosen.localId, progress: 0 })
    setActionError(null)
    try {
      const saved = await postOfficialTeamPhoto({
        tournamentId: session.tournamentId,
        teamId: selectedTeam.team_id,
        blob,
        clientUploadId: chosen.clientUploadId,
        onProgress: (fraction) =>
          dispatch({ type: 'uploadProgress', localId: chosen.localId, progress: Math.round(fraction * 100) }),
      })
      setSavedOfficial({
        teamId: selectedTeam.team_id,
        version: saved.version || saved.updated_at,
      })
      const label = selectedTeam.player_names.filter((name) => name !== 'Partner not on file').join(' / ')
      blobsRef.current = {}
      setSelectedTeam(null)
      setQuery('')
      setResults([])
      dispatch({ type: 'confirmSucceeded', teamLabel: label || `team ${selectedTeam.team_id}` })
    } catch (error) {
      dispatch({
        type: 'uploadFailed',
        localId: chosen.localId,
        error: error instanceof Error ? error.message : 'Upload failed',
      })
      dispatch({ type: 'confirmFailed' })
      setActionError(error instanceof Error ? error.message : 'Could not save the official photo. You can retry.')
    } finally {
      confirmLock.current = false
    }
  }

  const retryCapture = (localId: string) => {
    if (!blobsRef.current[localId]) {
      setActionError('That photograph is no longer on this device. Capture it again.')
      return
    }
    dispatch({ type: 'retryUpload', localId })
    dispatch({ type: 'selectCapture', localId })
  }

  const logout = async (event: FormEvent) => {
    event.preventDefault()
    try {
      await logoutAuth()
    } catch {
      // Clear the local session even if the server is unreachable.
    }
    clearAuthToken()
    navigate('/login')
  }

  const selectedCapture = session.captures.find((capture) => capture.localId === session.selectedLocalId)
  const canConfirm = Boolean(
    selectedCapture && (selectedCapture.status === 'ready' || selectedCapture.status === 'uploaded') && !session.confirming,
  )

  const step = session.confirming ? 'Save' : session.phase === 'capture' ? (session.selectedLocalId ? 'Select' : 'Pictures') : 'Search'

  return (
    <div style={{ minHeight: '100vh', background: '#eef3f8', padding: '16px 16px calc(24px + env(safe-area-inset-bottom))' }}>
      <div style={{ maxWidth: 560, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <h1 style={{ margin: 0, fontSize: 22, color: '#1a237e' }}>Team Photos</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            {session.tournamentId && (
              <button type="button" onClick={() => navigate(`/tournaments/${session.tournamentId}/photo-print`)} style={secondaryButton}>
                Watermark & Print
              </button>
            )}
            <button type="button" onClick={logout} style={secondaryButton}>Log out</button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
          {['Search', 'Pictures', 'Select', 'Save'].map((label) => (
            <span key={label} style={{ ...stepStyle, background: step === label ? '#1a237e' : '#fff', color: step === label ? '#fff' : '#546e7a' }}>
              {label}
            </span>
          ))}
        </div>
        {pageError && <div style={errorBox}>{pageError}</div>}
        {session.confirmationMessage && <div style={successBox}>{session.confirmationMessage}. Search the next team.</div>}
        {session.confirmationMessage && savedOfficial && (
          <TeamPhotoProvider
            value={{
              photos: { [savedOfficial.teamId]: savedOfficial.version },
              refresh: async () => undefined,
              tournamentId: session.tournamentId,
            }}
          >
            <div data-testid="saved-official-photo" style={{ marginTop: 10 }}>
              <TeamPhotoThumb teamId={savedOfficial.teamId} size={96} surface="photographer" />
            </div>
          </TeamPhotoProvider>
        )}

        {tournaments.length > 1 && <label style={labelStyle}>
          Tournament
          <select
            value={session.tournamentId ?? ''}
            onChange={(event) => {
              setSelectedTeam(null)
              setQuery('')
              setResults([])
              dispatch({ type: 'selectTournament', tournamentId: Number(event.target.value) })
            }}
            style={fieldStyle}
          >
            {tournaments.length === 0 && <option value="">No authorized tournaments</option>}
            {tournaments.map((tournament) => (
              <option key={tournament.id} value={tournament.id}>
                {tournament.name}
              </option>
            ))}
          </select>
        </label>}

        {session.phase === 'search' && (
          <form
            onSubmit={(event) => event.preventDefault()}
            style={{ marginTop: 16 }}
          >
            <label style={labelStyle}>
              Search team
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Either player's name"
                enterKeyHint="search"
                autoComplete="off"
                style={fieldStyle}
              />
            </label>
            {searching && <div style={{ marginTop: 8, color: '#546e7a' }}>Searching teams…</div>}
            <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
              {results.map((hit) => (
                <TeamSearchResultButton key={hit.team_id} hit={hit} onSelect={selectTeam} />
              ))}
            </div>
            {query.trim() && !searching && results.length === 0 && (
              <div style={{ marginTop: 12, color: '#546e7a' }}>No teams match that name in this tournament.</div>
            )}
          </form>
        )}

        {session.phase === 'capture' && selectedTeam && (
          <section style={{ marginTop: 16 }}>
            <button type="button" onClick={() => { setSelectedTeam(null); dispatch({ type: 'backToSearch' }) }} style={secondaryButton}>
              Next team
            </button>
            <div style={{ marginTop: 12, padding: 14, borderRadius: 12, background: '#fff', border: '1px solid #d7dee5' }}>
              <TeamPhotoProvider
                value={{
                  photos: photoVersions,
                  refresh: async () => undefined,
                  tournamentId: session.tournamentId,
                }}
              >
                <div data-testid="selected-team-photo" style={{ marginBottom: 10 }}>
                  <TeamPhotoThumb teamId={selectedTeam.team_id} size={96} surface="photographer" />
                </div>
              </TeamPhotoProvider>
              <div style={{ fontWeight: 800, fontSize: 20, lineHeight: 1.25 }}>{selectedTeam.player_names[0]}</div>
              <div style={{ fontWeight: 800, fontSize: 20, lineHeight: 1.25 }}>{selectedTeam.player_names[1]}</div>
              {selectedTeam.has_official_photo && (
                <div style={{ marginTop: 8, fontSize: 13, color: '#1565c0' }}>This team already has an official photo. A confirmed selection replaces it.</div>
              )}
            </div>

            <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
              <button type="button" style={primaryButton} onClick={() => cameraRef.current?.click()}>
                Take pictures
              </button>
              <button type="button" style={secondaryButton} onClick={() => libraryRef.current?.click()}>
                Photo library
              </button>
            </div>
            <input
              ref={cameraRef}
              type="file"
              accept="image/*,.heic,.heif"
              capture="environment"
              style={{ display: 'none' }}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ''
                void onPickFile(file)
              }}
            />
            <input
              ref={libraryRef}
              type="file"
              accept="image/*,.heic,.heif"
              style={{ display: 'none' }}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ''
                void onPickFile(file)
              }}
            />

            <div data-testid="capture-previews" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, marginTop: 14 }}>
              {session.captures.map((capture) => {
                const selected = session.selectedLocalId === capture.localId
                return (
                  <button
                    key={capture.localId}
                    type="button"
                    data-testid="capture-preview"
                    onClick={() => dispatch({ type: 'selectCapture', localId: capture.localId })}
                    style={{
                      padding: 4,
                      borderRadius: 10,
                      border: selected ? '3px solid #1a237e' : '1px solid #cfd8dc',
                      background: '#fff',
                    }}
                  >
                    <img src={capture.previewUrl} alt="Captured team photograph" style={{ width: '100%', aspectRatio: '1', objectFit: 'cover', borderRadius: 8 }} />
                    <div style={{ fontSize: 12, marginTop: 4, color: capture.status === 'failed' ? '#c62828' : '#455a64' }}>
                      {capture.status === 'uploading' && `Uploading ${capture.progress}%`}
                      {(capture.status === 'ready' || capture.status === 'uploaded') && (selected ? 'Selected' : 'Tap to select')}
                      {capture.status === 'failed' && (capture.error || 'Upload failed')}
                    </div>
                    {capture.status === 'failed' && (
                      <span
                        role="button"
                        onClick={(event) => {
                          event.stopPropagation()
                          retryCapture(capture.localId)
                        }}
                        style={{ display: 'inline-block', marginTop: 4, color: '#1a237e', fontWeight: 700 }}
                      >
                        Retry
                      </span>
                    )}
                  </button>
                )
              })}
            </div>

            {actionError && <div style={{ ...errorBox, marginTop: 12 }}>{actionError}</div>}

            <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
              <button
                type="button"
                disabled={!canConfirm}
                onClick={() => void confirmOfficial()}
                style={{ ...primaryButton, flex: 1, opacity: canConfirm ? 1 : 0.55 }}
              >
                {session.confirming ? 'Saving…' : 'Save official photo'}
              </button>
              {selectedTeam.has_official_photo && (
                <button
                  type="button"
                  disabled={deleting || session.confirming}
                  onClick={() => setConfirmDelete(true)}
                  style={{ ...dangerButton, flex: 1, opacity: deleting || session.confirming ? 0.55 : 1 }}
                >
                  Delete Photo
                </button>
              )}
            </div>
          </section>
        )}
        {confirmDelete && selectedTeam && (
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Delete official photo"
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0,0,0,0.45)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 16,
              zIndex: 20,
            }}
          >
            <div style={{ width: 'min(420px, 100%)', background: '#fff', borderRadius: 12, padding: 16 }}>
              <p style={{ margin: '0 0 16px', fontSize: 16, lineHeight: 1.4, color: '#1a1a1a' }}>
                Are you sure you want to permanently delete the official photograph for {teamLabel(selectedTeam.player_names)}?
              </p>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" disabled={deleting} onClick={() => setConfirmDelete(false)} style={{ ...secondaryButton, flex: 1 }}>
                  Cancel
                </button>
                <button type="button" disabled={deleting} onClick={() => void confirmDeletePhoto()} style={{ ...dangerButton, flex: 1 }}>
                  {deleting ? 'Deleting…' : 'Delete Photo'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const stepStyle: CSSProperties = {
  border: '1px solid #c5d0dc',
  borderRadius: 999,
  padding: '4px 10px',
  fontSize: 12,
  fontWeight: 800,
}

const fieldStyle: CSSProperties = {
  display: 'block',
  width: '100%',
  marginTop: 6,
  padding: '12px 14px',
  fontSize: 16,
  borderRadius: 10,
  border: '1px solid #c5d0dc',
  boxSizing: 'border-box',
}

const labelStyle: CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 700,
  color: '#37474f',
}

const primaryButton: CSSProperties = {
  width: '100%',
  minHeight: 52,
  border: 'none',
  borderRadius: 10,
  background: '#1a237e',
  color: '#fff',
  fontSize: 16,
  fontWeight: 800,
  cursor: 'pointer',
}

const dangerButton: CSSProperties = {
  minHeight: 52,
  border: 'none',
  borderRadius: 10,
  background: '#b71c1c',
  color: '#fff',
  fontSize: 16,
  fontWeight: 800,
  cursor: 'pointer',
}

const secondaryButton: CSSProperties = {
  minHeight: 44,
  padding: '10px 14px',
  borderRadius: 10,
  border: '1px solid #c5d0dc',
  background: '#fff',
  color: '#1a237e',
  fontWeight: 700,
  cursor: 'pointer',
}

const errorBox: CSSProperties = {
  background: '#ffebee',
  color: '#b71c1c',
  border: '1px solid #ffcdd2',
  borderRadius: 8,
  padding: 10,
  marginBottom: 12,
}

const successBox: CSSProperties = {
  background: '#e8f5e9',
  color: '#1b5e20',
  border: '1px solid #c8e6c9',
  borderRadius: 8,
  padding: 10,
  marginBottom: 12,
  fontWeight: 700,
}

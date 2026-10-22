import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getAuthToken } from '../../api/client'
import { officialTeamPhotoContentUrl } from '../../api/photography'
import {
  applyPhotoPrintToAll,
  downloadPhotoPrintFile,
  downloadPhotoPrintPackage,
  exportPhotoPrints,
  loadPhotoPrintWorkspace,
  photoPrintLogoUrl,
  resetPhotoPrintOverride,
  reviewPhotoPrint,
  saveBlob,
  savePhotoPrintDefault,
  savePhotoPrintOverride,
  uploadPhotoPrintLogo,
  type PhotoPrintWorkspace,
} from '../../api/photoPrint'
import {
  CONTENT_MODES,
  FONT_FAMILIES,
  FONT_STYLES,
  NAMED_COLORS,
  POSITION_LABELS,
  POSITIONS,
  PRINT_SIZE,
  cropCutsPhoto,
  defaultWatermarkSettings,
  logoPixelWidth,
  printFilename,
  watermarkBox,
  wordingFontSize,
  wordingPixelWidth,
  type WatermarkSettings,
} from '../../lib/photoPrintSettings'
import './photoPrint.css'

type GalleryFilter = 'all' | 'edited' | 'review'

async function authorizedBlob(url: string): Promise<string> {
  const token = getAuthToken()
  const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
  if (!response.ok) throw new Error('Photograph could not be loaded')
  return URL.createObjectURL(await response.blob())
}

export default function PhotoPrintPage() {
  const { tournamentId } = useParams()
  const navigate = useNavigate()
  const tid = Number(tournamentId)
  const [workspace, setWorkspace] = useState<PhotoPrintWorkspace | null>(null)
  const [filter, setFilter] = useState<GalleryFilter>('all')
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [settings, setSettings] = useState<WatermarkSettings | null>(null)
  const [zoom, setZoom] = useState(100)
  const printSize = PRINT_SIZE
  const [quantity, setQuantity] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [images, setImages] = useState<Record<number, string>>({})
  const [logoSrc, setLogoSrc] = useState<string | null>(null)
  const [logoVersion, setLogoVersion] = useState(0)
  const [removeLogoBackground, setRemoveLogoBackground] = useState(true)
  const frameRef = useRef<HTMLDivElement>(null)
  const [frameSize, setFrameSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = [
      'https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,400;0,500;0,700;1,400',
      'family=Poppins:ital,wght@0,400;0,500;0,700;1,400',
      'family=Roboto:ital,wght@0,400;0,500;0,700;1,400',
      'family=Lato:ital,wght@0,400;0,500;0,700;1,400',
      'family=Oswald:wght@400;500;700',
      'family=Nunito:ital,wght@0,400;0,500;0,700;1,400',
      'family=Raleway:ital,wght@0,400;0,500;0,700;1,400',
      'family=Josefin+Sans:ital,wght@0,400;0,500;0,700;1,400',
      'family=Barlow+Condensed:ital,wght@0,400;0,500;0,700;1,400',
      'family=Playfair+Display:ital,wght@0,400;0,500;0,700;1,400',
      'family=Lora:ital,wght@0,400;0,500;0,700;1,400',
      'family=Libre+Baskerville:ital,wght@0,400;0,700;1,400',
      'family=Cinzel:wght@400;500;700',
      'display=swap',
    ].join('&')
    document.head.appendChild(link)
    return () => link.remove()
  }, [])

  useEffect(() => {
    if (!Number.isFinite(tid)) return
    loadPhotoPrintWorkspace(tid)
      .then((data) => {
        setWorkspace(data)
        setSettings(data.default_settings)
        setSelectedIds(data.photos.map((photo) => photo.team_id))
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not open the print center'))
  }, [tid])

  const photos = workspace?.photos || []
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return photos.filter((photo) => {
      if (filter === 'edited' && !photo.has_override) return false
      if (filter === 'review' && photo.reviewed) return false
      if (!needle) return true
      return photo.player_names.some((name) => name.toLowerCase().includes(needle))
    })
  }, [photos, filter, query])

  const current = filtered[Math.min(index, Math.max(filtered.length - 1, 0))] || null

  useEffect(() => {
    if (!current) return
    setSettings(current.has_override ? current.settings : workspace?.default_settings || current.settings)
  }, [current?.team_id, current?.has_override, current?.version])

  const loadedImages = useRef<Map<number, string>>(new Map())
  useEffect(() => {
    let cancelled = false
    photos.forEach((photo) => {
      if (loadedImages.current.get(photo.team_id) === photo.version) return
      authorizedBlob(officialTeamPhotoContentUrl(photo.team_id, photo.version))
        .then((url) => {
          if (cancelled) {
            URL.revokeObjectURL(url)
            return
          }
          loadedImages.current.set(photo.team_id, photo.version)
          setImages((prev) => {
            const previous = prev[photo.team_id]
            if (previous) URL.revokeObjectURL(previous)
            return { ...prev, [photo.team_id]: url }
          })
        })
        .catch(() => {
          if (loadedImages.current.get(photo.team_id) === photo.version) {
            loadedImages.current.delete(photo.team_id)
          }
        })
    })
    return () => {
      cancelled = true
    }
  }, [photos])

  useEffect(() => {
    if (!workspace?.has_custom_logo) {
      setLogoSrc(null)
      return
    }
    let url = ''
    authorizedBlob(`${photoPrintLogoUrl(tid)}?v=${logoVersion}`)
      .then((next) => {
        url = next
        setLogoSrc(next)
      })
      .catch(() => setLogoSrc(null))
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [workspace?.has_custom_logo, tid, logoVersion])

  useEffect(() => {
    const node = frameRef.current
    if (!node) return
    const update = () => setFrameSize({ width: node.clientWidth, height: node.clientHeight })
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [current?.team_id, zoom, images, settings?.crop_mode])

  const patch = (partial: Partial<WatermarkSettings>) => {
    setSettings((prev) => ({ ...(prev || defaultWatermarkSettings(workspace?.tournament_name || '')), ...partial }))
  }

  const refresh = async (next?: PhotoPrintWorkspace) => {
    const data = next || await loadPhotoPrintWorkspace(tid)
    setWorkspace(data)
    return data
  }

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The print action failed')
    } finally {
      setBusy(false)
    }
  }

  const saveDefault = () => run(async () => {
    if (!settings) return
    const saved = await savePhotoPrintDefault(tid, settings)
    setWorkspace((prev) => prev ? { ...prev, default_settings: saved.default_settings } : prev)
    setNotice('Tournament watermark default saved.')
  })

  const applyAll = () => run(async () => {
    if (!settings) return
    const data = await applyPhotoPrintToAll(tid, settings)
    setWorkspace(data)
    setNotice('The same watermark now applies to every team photograph.')
  })

  const savePhoto = () => run(async () => {
    if (!settings || !current) return
    await savePhotoPrintOverride(tid, current.team_id, settings)
    await refresh()
    setNotice('This photograph keeps its own watermark.')
  })

  const resetPhoto = () => run(async () => {
    if (!current) return
    const reset = await resetPhotoPrintOverride(tid, current.team_id)
    setSettings(reset.settings)
    await refresh()
    setNotice('This photograph uses the tournament default again.')
  })

  const markReviewed = (reviewed: boolean) => run(async () => {
    if (!current) return
    await reviewPhotoPrint(tid, current.team_id, reviewed)
    await refresh()
  })

  const packageFor = (teamIds: number[], acknowledge: boolean) => run(async () => {
    const result = await downloadPhotoPrintPackage(tid, {
      team_ids: teamIds,
      print_size: printSize,
      quantity,
      acknowledge_low_resolution: acknowledge,
    })
    saveBlob(result.blob, result.filename)
    setReviewOpen(false)
    setNotice('Print files downloaded. Walgreens has not confirmed an order.')
    await refresh()
  })

  const downloadCurrent = () => run(async () => {
    if (!current) return
    const low = current.low_resolution_sizes.includes(printSize)
    await exportPhotoPrints(tid, {
      team_ids: [current.team_id],
      print_size: printSize,
      quantity,
      acknowledge_low_resolution: low,
    })
    const file = await downloadPhotoPrintFile(tid, current.team_id, printSize)
    saveBlob(file.blob, file.filename)
    setNotice(`${file.filename} downloaded. The original photograph was not changed.`)
  })

  const orderWalgreens = () => run(async () => {
    const ids = selectedIds.filter((id) => photos.some((photo) => photo.team_id === id))
    if (!ids.length) throw new Error('Select at least one photograph')
    const low = photos.some((photo) => ids.includes(photo.team_id) && photo.low_resolution_sizes.includes(printSize))
    const result = await downloadPhotoPrintPackage(tid, {
      team_ids: ids,
      print_size: printSize,
      quantity,
      acknowledge_low_resolution: low,
    })
    saveBlob(result.blob, result.filename)
    const url = workspace?.walgreens.ordering_url || 'https://photo.walgreens.com/store/prints'
    window.open(url, '_blank', 'noopener,noreferrer')
    setNotice(workspace?.walgreens.note || 'Upload the downloaded files on Walgreens Photo. An order has not been placed.')
  })

  const onDragCrop = (event: React.PointerEvent<HTMLImageElement>) => {
    if (!settings || !frameRef.current) return
    const frame = frameRef.current.getBoundingClientRect()
    const startX = event.clientX
    const startY = event.clientY
    const origin = { x: settings.crop_x, y: settings.crop_y }
    const move = (ev: PointerEvent) => {
      patch({
        crop_mode: 'fill',
        crop_x: Math.max(0, Math.min(1, origin.x - (ev.clientX - startX) / frame.width)),
        crop_y: Math.max(0, Math.min(1, origin.y - (ev.clientY - startY) / frame.height)),
      })
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  const onDragWatermark = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation()
    if (!settings || !frameRef.current) return
    const frame = frameRef.current.getBoundingClientRect()
    const startX = event.clientX
    const startY = event.clientY
    const origin = { x: settings.offset_x, y: settings.offset_y }
    const move = (ev: PointerEvent) => {
      patch({
        offset_x: Math.max(-1, Math.min(1, origin.x + (ev.clientX - startX) / frame.width)),
        offset_y: Math.max(-1, Math.min(1, origin.y + (ev.clientY - startY) / frame.height)),
      })
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  const onResizeWatermark = (event: React.PointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (!settings || !frameRef.current) return
    const frame = frameRef.current.getBoundingClientRect()
    const startX = event.clientX
    const startSize = settings.size_percent
    const move = (ev: PointerEvent) => {
      const next = startSize + ((ev.clientX - startX) / frame.width) * 100
      patch({ size_percent: Math.max(8, Math.min(100, Math.round(next))) })
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  const frameWidth = frameSize.width || 640
  const frameHeight = frameSize.height || 480
  const watermarkText = settings?.content_mode === 'custom_text'
    ? settings.custom_text
    : settings?.content_mode === 'logo_only'
      ? ''
      : settings?.event_text || ''
  const showLogo = settings ? ['logo_and_text', 'logo_only', 'custom_logo'].includes(settings.content_mode) : false
  const logoWidth = showLogo && settings ? logoPixelWidth(frameWidth, settings.logo_scale) : 0
  const logoHeight = showLogo ? logoWidth * (547 / 1011) : 0
  const textWidth = settings && watermarkText ? wordingPixelWidth(frameWidth, settings.size_percent) : 0
  const wordingWeight = settings?.font_style === 'bold' ? 700 : settings?.font_style === 'medium' ? 500 : 400
  const wordingStyle = settings?.font_style === 'italic' ? 'italic' : 'normal'
  const wordingFamily = settings?.font_family.includes(' ') ? `"${settings.font_family}"` : settings?.font_family
  const wordingFont = settings && watermarkText
    ? wordingFontSize(watermarkText, textWidth, `${wordingStyle} ${wordingWeight} 100px ${wordingFamily}`)
    : 16
  const textHeight = watermarkText ? wordingFont * 1.05 : 0
  const stackGap = showLogo && watermarkText && settings ? settings.spacing / 2 : 0
  const box = settings
    ? watermarkBox(frameWidth, frameHeight, settings, {
      width: Math.max(logoWidth, textWidth, 24),
      height: Math.max(logoHeight + stackGap + textHeight, 24),
    })
    : null
  const selectedPhotos = photos.filter((photo) => selectedIds.includes(photo.team_id))
  const lowSelected = selectedPhotos.filter((photo) => photo.low_resolution_sizes.includes(printSize))

  return (
    <div className="photo-print-page">
      <header className="photo-print-top">
        <button type="button" onClick={() => navigate(-1)}>Back</button>
        <strong>Watermark & Print</strong>
        <span>{workspace?.tournament_name || 'Tournament'}</span>
        <span style={{ marginLeft: 'auto' }}>{photos.length} photographs</span>
      </header>
      <div className="photo-print-progress">
        <span>Teams {workspace?.totals.teams ?? 0}</span>
        <span>Official photos {workspace?.totals.with_photos ?? 0}</span>
        <span>Reviewed {workspace?.totals.reviewed ?? 0}</span>
        <span>Ready for printing {workspace?.totals.ready ?? 0}</span>
        <span>Needing attention {workspace?.totals.needs_attention ?? 0}</span>
        {current && <span>Photo {Math.min(index, filtered.length - 1) + 1} of {filtered.length}</span>}
      </div>
      <div className="photo-print-columns">
        <aside className="photo-print-gallery">
          <div className="photo-print-field" style={{ padding: 8 }}>
            <input value={query} onChange={(event) => { setQuery(event.target.value); setIndex(0) }} placeholder="Search either player's name" aria-label="Search photographs" />
            <select value={filter} onChange={(event) => { setFilter(event.target.value as GalleryFilter); setIndex(0) }} aria-label="Filter photographs">
              <option value="all">All photos</option>
              <option value="edited">Edited photos</option>
              <option value="review">Photos awaiting review</option>
            </select>
          </div>
          <div className="photo-print-list">
            {filtered.map((photo, photoIndex) => (
              <div key={photo.team_id} className={current?.team_id === photo.team_id ? 'photo-print-card selected' : 'photo-print-card'}>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(photo.team_id)}
                  aria-label={`Select ${photo.player_names.join(' and ')}`}
                  onChange={(event) => {
                    setSelectedIds((prev) => event.target.checked ? [...prev, photo.team_id] : prev.filter((id) => id !== photo.team_id))
                  }}
                />
                <button type="button" onClick={() => setIndex(photoIndex)} style={{ display: 'contents' }}>
                  {images[photo.team_id] ? <img src={images[photo.team_id]} alt="" /> : <span className="photo-print-thumb-fallback" />}
                  <span>
                    <strong>{photo.player_names.filter((name) => name !== 'Partner not on file').join(' / ')}</strong>
                    <div style={{ fontSize: 11, color: '#607d8b' }}>
                      {photo.has_override ? 'Edited' : 'Tournament default'}
                      {photo.reviewed ? ' · Reviewed' : ' · Awaiting review'}
                    </div>
                  </span>
                </button>
              </div>
            ))}
            {filtered.length === 0 && <div style={{ padding: 12, color: '#78909c' }}>No official photographs match this list.</div>}
          </div>
        </aside>
        <main className="photo-print-stage">
          <div className="photo-print-stage-nav">
            <button type="button" disabled={index <= 0} onClick={() => setIndex((value) => Math.max(0, value - 1))}>Previous</button>
            <button type="button" disabled={index >= filtered.length - 1} onClick={() => setIndex((value) => Math.min(filtered.length - 1, value + 1))}>Next</button>
            <label>Zoom {zoom}%
              <input type="range" min={50} max={200} value={zoom} onChange={(event) => setZoom(Number(event.target.value))} />
            </label>
          </div>
          {current && settings && (
            <div ref={frameRef} className="photo-print-frame" style={{ width: `min(100%, ${Math.round(720 * zoom / 100)}px)`, aspectRatio: '2 / 3' }}>
              {images[current.team_id]
                ? (
                  <img
                    src={images[current.team_id]}
                    alt={current.player_names.join(' and ')}
                    onPointerDown={onDragCrop}
                    style={{
                      position: 'absolute',
                      inset: 0,
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                      objectPosition: `${settings.crop_x * 100}% ${settings.crop_y * 100}%`,
                      cursor: 'grab',
                    }}
                  />
                )
                : <div style={{ height: '100%' }} />}
              {settings.show_margins && box && (
                <div className="photo-print-margins" style={{ left: box.margin, top: box.margin, right: box.margin, bottom: box.margin }} />
              )}
              {settings.visible && box && (
                <div
                  className="photo-print-watermark"
                  onPointerDown={onDragWatermark}
                  style={{
                    left: box.x,
                    top: box.y,
                    width: box.width,
                    color: settings.color,
                    opacity: settings.opacity / 100,
                    fontFamily: settings.font_family,
                    fontStyle: settings.font_style === 'italic' ? 'italic' : 'normal',
                    fontWeight: settings.font_style === 'bold' ? 700 : settings.font_style === 'medium' ? 500 : 400,
                    textShadow: settings.shadow ? '0 2px 2px rgba(0,0,0,0.65)' : 'none',
                    gap: settings.spacing / 2,
                  }}
                >
                  {showLogo && (settings.content_mode === 'custom_logo' && logoSrc
                    ? <img className="photo-print-logo" src={logoSrc} alt="" style={{ width: logoWidth, height: 'auto' }} />
                    : (
                      <span
                        className="photo-print-logo"
                        aria-label="RacquetWar"
                        style={{
                          width: logoWidth,
                          height: logoWidth * (547 / 1011),
                          backgroundColor: settings.color,
                          maskImage: 'url(/assets/rw-watermark-logo.png)',
                          WebkitMaskImage: 'url(/assets/rw-watermark-logo.png)',
                          maskRepeat: 'no-repeat',
                          WebkitMaskRepeat: 'no-repeat',
                          maskPosition: 'center',
                          WebkitMaskPosition: 'center',
                          maskSize: 'contain',
                          WebkitMaskSize: 'contain',
                        }}
                      />
                    ))}
                  {watermarkText && <span className="photo-print-wording" style={{ fontSize: wordingFont }}>{watermarkText}</span>}
                  <button type="button" aria-label="Resize wording" onPointerDown={onResizeWatermark} />
                </div>
              )}
            </div>
          )}
          <div style={{ fontSize: 12, color: '#546e7a', maxWidth: 520, textAlign: 'center' }}>
            4×6 portrait preview. Drag the photograph so both players stay inside the frame.
            {current && cropCutsPhoto(current.source_width, current.source_height, 'fill') && (
              <div style={{ color: '#c62828', fontWeight: 700, marginTop: 4 }}>
                This crop removes part of the photo. Reposition it so both players stay fully visible.
              </div>
            )}
            {current?.low_resolution_sizes.includes(printSize) && (
              <div style={{ color: '#c62828', fontWeight: 700, marginTop: 4 }}>
                This original is below 1200 × 1800, so a 300 DPI 4×6 print would enlarge it.
              </div>
            )}
          </div>
        </main>
        <aside className="photo-print-controls">
          {settings && (
            <div className="photo-print-controls-scroll">
              <label className="photo-print-field">Watermark content
                <select value={settings.content_mode} onChange={(event) => patch({ content_mode: event.target.value })}>
                  {CONTENT_MODES.map((mode) => <option key={mode.id} value={mode.id}>{mode.label}</option>)}
                </select>
              </label>
              <label className="photo-print-field">Event text
                <input value={settings.event_text} onChange={(event) => patch({ event_text: event.target.value })} />
              </label>
              {settings.content_mode === 'custom_text' && (
                <label className="photo-print-field photo-print-span">Custom text
                  <input value={settings.custom_text} onChange={(event) => patch({ custom_text: event.target.value })} />
                </label>
              )}
              {showLogo && (
                <div className="photo-print-field photo-print-span">
                  <span>Upload logo</span>
                  <div className="photo-print-logo-upload">
                    {logoSrc && (
                      <span className="photo-print-logo-preview">
                        <img src={logoSrc} alt="Uploaded logo" />
                      </span>
                    )}
                    <div>
                      <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="Upload logo" onChange={(event) => {
                        const file = event.target.files?.[0]
                        event.target.value = ''
                        if (!file) return
                        run(async () => {
                          await uploadPhotoPrintLogo(tid, file, removeLogoBackground)
                          await refresh()
                          setLogoVersion((version) => version + 1)
                          patch({ content_mode: 'custom_logo' })
                        })
                      }} />
                      <label>
                        <input type="checkbox" checked={removeLogoBackground} onChange={(event) => setRemoveLogoBackground(event.target.checked)} />
                        Remove background
                      </label>
                      <p>A solid white or colored backdrop is removed. Artwork that is already transparent is kept.</p>
                      {workspace?.has_custom_logo && settings.content_mode !== 'custom_logo' && (
                        <button type="button" onClick={() => patch({ content_mode: 'custom_logo' })}>Use uploaded logo</button>
                      )}
                      {settings.content_mode === 'custom_logo' && (
                        <button type="button" onClick={() => patch({ content_mode: 'logo_and_text' })}>Use RW emblem</button>
                      )}
                    </div>
                  </div>
                </div>
              )}
              <label className="photo-print-field">Font
                <select value={settings.font_family} onChange={(event) => patch({ font_family: event.target.value })}>
                  {FONT_FAMILIES.map((font) => <option key={font} value={font}>{font}</option>)}
                </select>
              </label>
              <label className="photo-print-field">Style
                <select value={settings.font_style} onChange={(event) => patch({ font_style: event.target.value })}>
                  {FONT_STYLES.map((style) => <option key={style} value={style}>{style}</option>)}
                </select>
              </label>
              <div className="photo-print-field">Colors
                <div className="photo-print-colors">
                  {NAMED_COLORS.map((color) => (
                    <button key={color.id} type="button" className="photo-print-swatch" aria-label={color.label} style={{ background: color.value }} onClick={() => patch({ color: color.value })} />
                  ))}
                  <input type="color" aria-label="Custom color" value={settings.color} onChange={(event) => patch({ color: event.target.value })} />
                </div>
              </div>
              <label className="photo-print-field">Wording size {settings.size_percent}%
                <input type="range" min={8} max={100} value={settings.size_percent} onChange={(event) => patch({ size_percent: Number(event.target.value) })} />
              </label>
              <div className="photo-print-field photo-print-span">Position
                <div className="photo-print-positions">
                  {POSITIONS.map((position) => (
                    <button key={position} type="button" aria-label={POSITION_LABELS[position]} onClick={() => patch({ position, offset_x: 0, offset_y: 0 })} style={{ background: settings.position === position ? '#e8eaf6' : '#fff' }}>
                      {POSITION_LABELS[position]}
                    </button>
                  ))}
                </div>
              </div>
              <label className="photo-print-field">Opacity {settings.opacity}%
                <input type="range" min={10} max={100} value={settings.opacity} onChange={(event) => patch({ opacity: Number(event.target.value) })} />
              </label>
              <label className="photo-print-field">Logo size {Math.round(settings.logo_scale * 100)}%
                <input type="range" min={40} max={250} value={Math.round(settings.logo_scale * 100)} onChange={(event) => patch({ logo_scale: Number(event.target.value) / 100 })} />
              </label>
              <label className="photo-print-field">Spacing {settings.spacing}
                <input type="range" min={0} max={40} value={settings.spacing} onChange={(event) => patch({ spacing: Number(event.target.value) })} />
              </label>
              <label className="photo-print-field"><input type="checkbox" checked={settings.shadow} onChange={(event) => patch({ shadow: event.target.checked })} /> Text shadow or outline</label>
              <label className="photo-print-field"><input type="checkbox" checked={settings.visible} onChange={(event) => patch({ visible: event.target.checked })} /> Show watermark</label>
              <label className="photo-print-field"><input type="checkbox" checked={settings.show_margins} onChange={(event) => patch({ show_margins: event.target.checked })} /> Show safe print margins</label>
              <label className="photo-print-field">Crop horizontal
                <input type="range" min={0} max={100} value={Math.round(settings.crop_x * 100)} onChange={(event) => patch({ crop_x: Number(event.target.value) / 100, crop_mode: 'fill' })} />
              </label>
              <label className="photo-print-field">Crop vertical
                <input type="range" min={0} max={100} value={Math.round(settings.crop_y * 100)} onChange={(event) => patch({ crop_y: Number(event.target.value) / 100, crop_mode: 'fill' })} />
              </label>
              <div className="photo-print-field">Print format
                <strong>4×6 portrait (2:3)</strong>
              </div>
              <label className="photo-print-field">Quantity
                <input type="number" min={1} max={20} value={quantity} onChange={(event) => setQuantity(Number(event.target.value) || 1)} />
              </label>
              {current && <p className="photo-print-span" style={{ fontSize: 12, margin: 0 }}>{printFilename(workspace?.tournament_name || '', current.player_names, printSize)}</p>}
            </div>
          )}
          {settings && (
            <div className="photo-print-controls-actions">
              <button type="button" disabled={busy} onClick={() => patch(workspace?.default_settings || defaultWatermarkSettings(workspace?.tournament_name || ''))}>Reset watermark</button>
              <button type="button" disabled={busy} onClick={saveDefault}>Save Tournament Default</button>
              <button type="button" disabled={busy} onClick={applyAll}>Apply to All Photos</button>
              <button type="button" disabled={busy || !current} onClick={savePhoto}>Save This Photo</button>
              <button type="button" disabled={busy || !current} onClick={resetPhoto}>Reset This Photo to Default</button>
              <button type="button" disabled={busy || !current} onClick={() => markReviewed(!current?.reviewed)}>{current?.reviewed ? 'Mark as awaiting review' : 'Mark reviewed'}</button>
            </div>
          )}
        </aside>
      </div>
      <footer className="photo-print-actions">
        {error && <span style={{ color: '#c62828' }}>{error}</span>}
        {notice && <span>{notice}</span>}
        <button type="button" disabled={busy || !current} onClick={downloadCurrent}>Download Current Photo</button>
        <button type="button" disabled={busy || photos.length === 0} onClick={() => packageFor(photos.map((photo) => photo.team_id), photos.some((photo) => photo.low_resolution_sizes.includes(printSize)))}>Download All Photos as ZIP</button>
        <button type="button" disabled={busy || selectedIds.length === 0} onClick={() => packageFor(selectedIds, lowSelected.length > 0)}>Export Selected Photos</button>
        <button type="button" disabled={busy || selectedIds.length === 0} onClick={() => setReviewOpen(true)}>Generate Print Package</button>
        <button type="button" className="photo-print-walgreens" disabled={busy || selectedIds.length === 0} onClick={orderWalgreens}>Order Prints at Walgreens</button>
      </footer>
      {reviewOpen && (
        <div className="photo-print-review">
          <section>
            <h2>Review print package</h2>
            <p>{selectedPhotos.length} photographs · {printSize} · quantity {quantity}. Walgreens has not confirmed an order.</p>
            <ul>
              {selectedPhotos.map((photo) => (
                <li key={photo.team_id}>
                  {photo.player_names.filter((name) => name !== 'Partner not on file').join(' / ')}
                  {photo.low_resolution_sizes.includes(printSize) ? ' — below 300 DPI, export will enlarge it' : ''}
                  {photo.reviewed ? '' : ' — not reviewed'}
                </li>
              ))}
            </ul>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" onClick={() => setReviewOpen(false)}>Back</button>
              <button type="button" disabled={busy} onClick={() => packageFor(selectedIds, true)}>Create print files</button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}


import { getAuthToken } from './client'
import type { WatermarkSettings } from '../lib/photoPrintSettings'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export interface PhotoPrintPhoto {
  team_id: number
  player_names: string[]
  version: string
  reviewed: boolean
  has_override: boolean
  settings: WatermarkSettings
  source_width: number
  source_height: number
  low_resolution_sizes: string[]
  crop_warning?: boolean
  needs_attention: boolean
}

export interface PhotoPrintWorkspace {
  tournament_id: number
  tournament_name: string
  default_settings: WatermarkSettings
  has_custom_logo: boolean
  totals: {
    teams: number
    with_photos: number
    reviewed: number
    ready: number
    needs_attention: number
  }
  walgreens: {
    ordering_url: string
    direct_ordering_available: boolean
    note: string
  }
  photos: PhotoPrintPhoto[]
}

export interface PrintFileResult {
  team_id: number
  player_names: string[]
  print_size: string
  filename: string
  width: number
  height: number
  source_width: number
  source_height: number
  low_resolution: boolean
  quantity: number
  byte_size: number
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // The package endpoint returns a file, not JSON, when it succeeds.
  }
  return `HTTP error! status: ${response.status}`
}

function authHeaders(json = false): HeadersInit {
  const token = getAuthToken()
  return {
    Accept: 'application/json',
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function photoPrintFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { ...authHeaders(typeof init?.body === 'string'), ...init?.headers },
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<T>
}

export function loadPhotoPrintWorkspace(tournamentId: number) {
  return photoPrintFetch<PhotoPrintWorkspace>(`/photography/tournaments/${tournamentId}/photo-print`)
}

export function savePhotoPrintDefault(tournamentId: number, settings: WatermarkSettings) {
  return photoPrintFetch<{ default_settings: WatermarkSettings }>(
    `/photography/tournaments/${tournamentId}/photo-print/default`,
    { method: 'PUT', body: JSON.stringify({ settings }) },
  )
}

export function applyPhotoPrintToAll(tournamentId: number, settings: WatermarkSettings) {
  return photoPrintFetch<PhotoPrintWorkspace>(
    `/photography/tournaments/${tournamentId}/photo-print/apply-all`,
    { method: 'POST', body: JSON.stringify({ settings }) },
  )
}

export function savePhotoPrintOverride(tournamentId: number, teamId: number, settings: WatermarkSettings) {
  return photoPrintFetch<{ team_id: number; settings: WatermarkSettings; reviewed: boolean; has_override: boolean }>(
    `/photography/tournaments/${tournamentId}/photo-print/photos/${teamId}`,
    { method: 'PUT', body: JSON.stringify({ settings }) },
  )
}

export function resetPhotoPrintOverride(tournamentId: number, teamId: number) {
  return photoPrintFetch<{ team_id: number; settings: WatermarkSettings; has_override: boolean }>(
    `/photography/tournaments/${tournamentId}/photo-print/photos/${teamId}`,
    { method: 'DELETE' },
  )
}

export function reviewPhotoPrint(tournamentId: number, teamId: number, reviewed: boolean) {
  return photoPrintFetch<{ team_id: number; reviewed: boolean }>(
    `/photography/tournaments/${tournamentId}/photo-print/photos/${teamId}/review`,
    { method: 'POST', body: JSON.stringify({ reviewed }) },
  )
}

export async function uploadPhotoPrintLogo(tournamentId: number, file: File, removeBackground = true) {
  const body = new FormData()
  body.append('file', file)
  body.append('remove_background', removeBackground ? 'true' : 'false')
  const token = getAuthToken()
  const response = await fetch(`${API_BASE_URL}/photography/tournaments/${tournamentId}/photo-print/logo`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body,
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<{ has_custom_logo: boolean }>
}

export function photoPrintLogoUrl(tournamentId: number) {
  return `${API_BASE_URL}/photography/tournaments/${tournamentId}/photo-print/logo`
}

export function exportPhotoPrints(
  tournamentId: number,
  payload: { team_ids: number[]; print_size: string; quantity: number; acknowledge_low_resolution: boolean },
) {
  return photoPrintFetch<{ files: PrintFileResult[]; order_placed: boolean; walgreens: PhotoPrintWorkspace['walgreens'] }>(
    `/photography/tournaments/${tournamentId}/photo-print/exports`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export async function downloadPhotoPrintPackage(
  tournamentId: number,
  payload: { team_ids: number[]; print_size: string; quantity: number; acknowledge_low_resolution: boolean },
) {
  const response = await fetch(`${API_BASE_URL}/photography/tournaments/${tournamentId}/photo-print/package`, {
    method: 'POST',
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="([^"]+)"/)
  return { blob, filename: match?.[1] || 'team-photos.zip' }
}

export async function downloadPhotoPrintFile(tournamentId: number, teamId: number, size: string) {
  const token = getAuthToken()
  const response = await fetch(
    `${API_BASE_URL}/photography/tournaments/${tournamentId}/photo-print/photos/${teamId}/file?size=${encodeURIComponent(size)}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
  )
  if (!response.ok) throw new Error(await readError(response))
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="([^"]+)"/)
  return { blob, filename: match?.[1] || 'team-photo.jpg' }
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

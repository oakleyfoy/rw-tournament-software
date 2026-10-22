import { getAuthToken } from './client'
import type { PhotoTeamSearchHit } from '../components/TeamSearchResultButton'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export interface PhotographyTournament {
  id: number
  name: string
  location: string
  start_date: string
  end_date: string
}

export interface CaptureResponse {
  id: number
  team_id: number
  tournament_id: number
  session_id: string
  client_upload_id: string
  created_at: string
}

export interface OfficialPhotoResponse {
  team_id: number
  tournament_id: number
  photographer_user_id?: number | null
  captured_at: string
  updated_at: string
  byte_size: number
  version: string
}

export interface OfficialPhotoSummary {
  team_id: number
  updated_at: string
  version: string
}

export interface PhotographyAccess {
  user_id: number
  tournament_ids: number[]
}

export function officialTeamPhotoContentUrl(teamId: number, version: string): string {
  return `${API_BASE_URL}/photography/teams/${teamId}/official/content?v=${encodeURIComponent(version)}`
}

export function officialTeamPhotoThumbUrl(teamId: number, version: string): string {
  return `${API_BASE_URL}/photography/teams/${teamId}/official/thumb?v=${encodeURIComponent(version)}`
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // Ignore invalid JSON.
  }
  return `HTTP error! status: ${response.status}`
}

async function photoFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body instanceof FormData ? {} : init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<T>
}

export function listPhotographyTournaments(): Promise<PhotographyTournament[]> {
  return photoFetch('/photography/tournaments')
}

export function searchPhotographyTeams(tournamentId: number, query: string): Promise<PhotoTeamSearchHit[]> {
  return photoFetch(`/photography/tournaments/${tournamentId}/teams/search?q=${encodeURIComponent(query)}`)
}

export function getTeamPhotoSms(tournamentId: number, teamId: number): Promise<{ players: { name: string; status: string; detail?: string | null }[] }> {
  return photoFetch(`/photography/tournaments/${tournamentId}/teams/${teamId}/photo-sms`)
}

export function listOfficialTeamPhotos(tournamentId: number): Promise<OfficialPhotoSummary[]> {
  return photoFetch(`/photography/tournaments/${tournamentId}/official-photos`)
}

export function deleteGroupPhoto(tournamentId: number, groupPhotoId: number): Promise<{ group_photo_id: number; deleted: boolean }> {
  return photoFetch(`/photography/tournaments/${tournamentId}/group-photos/${groupPhotoId}`, { method: 'DELETE' })
}

export function deleteOfficialTeamPhoto(tournamentId: number, teamId: number): Promise<{ team_id: number; deleted: boolean }> {
  return photoFetch(`/photography/tournaments/${tournamentId}/teams/${teamId}/official`, { method: 'DELETE' })
}

export function listPhotographyAccess(): Promise<PhotographyAccess[]> {
  return photoFetch('/auth/photography-access')
}

export function setPhotographyTournaments(userId: number, tournamentIds: number[]): Promise<PhotographyAccess> {
  return photoFetch(`/auth/users/${userId}/photography-tournaments`, {
    method: 'PUT',
    body: JSON.stringify({ tournament_ids: tournamentIds }),
  })
}

export interface GroupPhotoResponse {
  id: number
  tournament_id: number
  captured_at: string
  byte_size: number
  version: string
  label: string
}

export function groupPhotoContentUrl(tournamentId: number, groupPhotoId: number, version: string): string {
  return `${API_BASE_URL}/photography/tournaments/${tournamentId}/group-photos/${groupPhotoId}/content?v=${encodeURIComponent(version)}`
}

export function postGroupPhoto(args: {
  tournamentId: number
  blob: Blob
  clientUploadId: string
  onProgress?: (fraction: number) => void
}): Promise<GroupPhotoResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/photography/tournaments/${args.tournamentId}/group-photos`)
    const token = getAuthToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && args.onProgress) args.onProgress(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as GroupPhotoResponse)
        return
      }
      let message = `HTTP error! status: ${xhr.status}`
      try {
        const body = JSON.parse(xhr.responseText)
        if (typeof body?.detail === 'string') message = body.detail
      } catch {
        // Keep the status message.
      }
      reject(new Error(message))
    }
    xhr.onerror = () => reject(new Error('Network error while uploading the photograph. You can retry.'))
    const form = new FormData()
    form.append('file', args.blob, 'group-photo.jpg')
    form.append('client_upload_id', args.clientUploadId)
    xhr.send(form)
  })
}

export function postOfficialTeamPhoto(args: {
  tournamentId: number
  teamId: number
  blob: Blob
  clientUploadId: string
  onProgress?: (fraction: number) => void
}): Promise<OfficialPhotoResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/photography/tournaments/${args.tournamentId}/teams/${args.teamId}/official`)
    const token = getAuthToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && args.onProgress) args.onProgress(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as OfficialPhotoResponse)
        return
      }
      let message = `HTTP error! status: ${xhr.status}`
      try {
        const body = JSON.parse(xhr.responseText)
        if (typeof body?.detail === 'string') message = body.detail
      } catch {
        // Keep the status message.
      }
      reject(new Error(message))
    }
    xhr.onerror = () => reject(new Error('Network error while uploading the photograph. You can retry.'))
    const form = new FormData()
    form.append('file', args.blob, 'team-photo.jpg')
    form.append('client_upload_id', args.clientUploadId)
    xhr.send(form)
  })
}

export async function uploadAndSetOfficialTeamPhoto(args: {
  tournamentId: number
  teamId: number
  file: File
}): Promise<OfficialPhotoResponse> {
  const { prepareTeamPhoto } = await import('../lib/prepareTeamPhoto')
  const prepared = await prepareTeamPhoto(args.file)
  return postOfficialTeamPhoto({
    tournamentId: args.tournamentId,
    teamId: args.teamId,
    blob: prepared.blob,
    clientUploadId: prepared.clientUploadId,
  })
}

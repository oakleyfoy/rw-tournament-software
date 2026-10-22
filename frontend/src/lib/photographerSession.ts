export interface SessionCapture {
  localId: string
  clientUploadId: string
  previewUrl: string
  serverId?: number
  progress: number
  status: 'ready' | 'uploading' | 'uploaded' | 'failed'
  error?: string
}

export type PhotoMode = 'team' | 'group'

export interface PhotographerSessionState {
  tournamentId: number | null
  photoMode: PhotoMode
  selectedTeamId: number | null
  captures: SessionCapture[]
  selectedLocalId: string | null
  confirming: boolean
  phase: 'search' | 'capture' | 'confirmed'
  confirmationMessage: string | null
}

export const initialPhotographerSession: PhotographerSessionState = {
  tournamentId: null,
  photoMode: 'team',
  selectedTeamId: null,
  captures: [],
  selectedLocalId: null,
  confirming: false,
  phase: 'search',
  confirmationMessage: null,
}

export type PhotographerAction =
  | { type: 'selectTournament'; tournamentId: number }
  | { type: 'chooseTeamPhoto' }
  | { type: 'chooseGroupPhoto' }
  | { type: 'beginTeamSearch' }
  | { type: 'selectTeam'; teamId: number }
  | { type: 'addCapture'; capture: SessionCapture }
  | { type: 'uploadProgress'; localId: string; progress: number }
  | { type: 'uploadSucceeded'; localId: string; serverId: number }
  | { type: 'uploadFailed'; localId: string; error: string }
  | { type: 'retryUpload'; localId: string }
  | { type: 'selectCapture'; localId: string }
  | { type: 'clearCaptures' }
  | { type: 'confirmStart' }
  | { type: 'confirmSucceeded'; teamLabel: string }
  | { type: 'confirmFailed' }
  | { type: 'backToSearch' }

export function photographerReducer(
  state: PhotographerSessionState,
  action: PhotographerAction,
): PhotographerSessionState {
  switch (action.type) {
    case 'selectTournament':
      return { ...initialPhotographerSession, tournamentId: action.tournamentId }
    case 'chooseTeamPhoto':
      if (state.confirming || state.captures.some((capture) => capture.status === 'uploading')) return state
      return {
        ...state,
        photoMode: 'team',
        phase: 'search',
        selectedTeamId: null,
        captures: [],
        selectedLocalId: null,
        confirming: false,
      }
    case 'chooseGroupPhoto':
      if (state.confirming || state.captures.some((capture) => capture.status === 'uploading')) return state
      if (state.photoMode === 'group' && state.phase === 'capture' && state.captures.length > 0) return state
      return {
        ...state,
        photoMode: 'group',
        selectedTeamId: null,
        captures: [],
        selectedLocalId: null,
        confirming: false,
        phase: 'capture',
        confirmationMessage: null,
      }
    case 'beginTeamSearch':
      if (state.confirming || state.captures.some((capture) => capture.status === 'uploading' || capture.status === 'ready' || capture.status === 'failed')) {
        return state
      }
      if (state.photoMode === 'team' && state.phase === 'search') return state
      return {
        ...state,
        photoMode: 'team',
        phase: 'search',
        selectedTeamId: null,
        captures: [],
        selectedLocalId: null,
        confirming: false,
      }
    case 'selectTeam':
      return {
        ...state,
        photoMode: 'team',
        selectedTeamId: action.teamId,
        captures: [],
        selectedLocalId: null,
        confirming: false,
        phase: 'capture',
        confirmationMessage: null,
      }
    case 'addCapture': {
      if (state.photoMode !== 'group' && state.selectedTeamId == null) return state
      if (state.captures.some((capture) => capture.clientUploadId === action.capture.clientUploadId)) {
        return state
      }
      return { ...state, phase: 'capture', captures: [...state.captures, action.capture] }
    }
    case 'uploadProgress':
      return {
        ...state,
        captures: state.captures.map((capture) =>
          capture.localId === action.localId
            ? { ...capture, progress: action.progress, status: 'uploading' }
            : capture,
        ),
      }
    case 'uploadSucceeded':
      return {
        ...state,
        captures: state.captures.map((capture) =>
          capture.localId === action.localId
            ? { ...capture, status: 'uploaded', serverId: action.serverId, progress: 100, error: undefined }
            : capture,
        ),
      }
    case 'uploadFailed':
      return {
        ...state,
        captures: state.captures.map((capture) =>
          capture.localId === action.localId ? { ...capture, status: 'failed', error: action.error } : capture,
        ),
      }
    case 'retryUpload':
      return {
        ...state,
        captures: state.captures.map((capture) =>
          capture.localId === action.localId && capture.status === 'failed'
            ? { ...capture, status: 'ready', progress: 100, error: undefined }
            : capture,
        ),
      }
    case 'selectCapture':
      if (
        !state.captures.some(
          (capture) =>
            capture.localId === action.localId && (capture.status === 'ready' || capture.status === 'uploaded'),
        )
      ) {
        return state
      }
      return { ...state, selectedLocalId: action.localId }
    case 'clearCaptures':
      return { ...state, captures: [], selectedLocalId: null, confirming: false, phase: 'capture' }
    case 'confirmStart':
      if (!state.selectedLocalId || state.confirming) return state
      if (
        !state.captures.some(
          (capture) =>
            capture.localId === state.selectedLocalId &&
            (capture.status === 'ready' || capture.status === 'uploaded'),
        )
      ) {
        return state
      }
      return { ...state, confirming: true }
    case 'confirmSucceeded':
      return {
        ...initialPhotographerSession,
        tournamentId: state.tournamentId,
        photoMode: 'team',
        phase: 'search',
        confirmationMessage: state.photoMode === 'group' ? 'Saved group photo' : `Saved for ${action.teamLabel}`,
      }
    case 'confirmFailed':
      return { ...state, confirming: false }
    case 'backToSearch':
      return {
        ...state,
        photoMode: 'team',
        phase: 'search',
        selectedTeamId: null,
        captures: [],
        selectedLocalId: null,
        confirming: false,
      }
    default:
      return state
  }
}

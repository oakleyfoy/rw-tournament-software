const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
const AUTH_TOKEN_STORAGE_KEY = 'rw_auth_token';

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
}

export function setAuthToken(token: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
}

export function clearAuthToken(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
}

export interface Tournament {
  id: number;
  name: string;
  location: string;
  timezone: string;
  start_date: string;
  end_date: string;
  notes?: string;
  is_archived: boolean;
  use_time_windows: boolean;
  court_names?: string[] | null;
  public_schedule_version_id: number | null;
  shared_screen_config_json?: string | null;
  /** JSON `{"day_orders":[[event_id,...],...]}` — schedule policy prefix per calendar day */
  event_schedule_day_orders_json?: string | null;
  source_rw_os_tournament_id?: number | null;
  source_rw_os_organization_slug?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TournamentCreate {
  name: string;
  location: string;
  timezone: string;
  start_date: string;
  end_date: string;
  notes?: string;
}

export interface TournamentUpdate {
  name?: string;
  location?: string;
  timezone?: string;
  start_date?: string;
  end_date?: string;
  notes?: string;
  is_archived?: boolean;
  use_time_windows?: boolean;
  court_names?: string[] | null;
  shared_screen_config_json?: string | null;
  event_schedule_day_orders_json?: string | null;
}

export interface TournamentStartOverResponse {
  tournament_id: number
  matches_reset: number
  match_checkins_cleared: number
  player_checkins_cleared: number
  match_locks_cleared: number
  slot_locks_cleared: number
  sms_logs_cleared: number
}

export interface TournamentDay {
  id: number;
  tournament_id: number;
  date: string;
  is_active: boolean;
  start_time?: string;
  end_time?: string;
  courts_available: number;
}

export interface DayUpdate {
  date: string;
  is_active: boolean;
  start_time?: string;
  end_time?: string;
  courts_available: number;
}

export interface Event {
  id: number;
  tournament_id: number;
  category: 'mixed' | 'womens';
  name: string;
  team_count: number;
  notes?: string;
  // Phase 2 fields
  draw_plan_json?: string | null;
  draw_plan_version?: string | null;
  draw_status?: string | null;
  wf_block_minutes?: number | null;
  standard_block_minutes?: number | null;
  guarantee_selected?: number | null;
  schedule_profile_json?: string | null;
}

export interface EventCreate {
  category: 'mixed' | 'womens';
  name: string;
  team_count: number;
  notes?: string;
}

export interface EventUpdate {
  category?: 'mixed' | 'womens';
  name?: string;
  team_count?: number;
  notes?: string;
  // Phase 2 fields
  draw_plan_json?: string | null;
  draw_plan_version?: string | null;
  draw_status?: string | null;
  wf_block_minutes?: number | null;
  standard_block_minutes?: number | null;
  guarantee_selected?: number | null;
  schedule_profile_json?: string | null;
}

export interface Phase1Status {
  is_ready: boolean;
  errors: string[];
  summary: {
    active_days: number;
    total_court_minutes: number;
    events_count: number;
  };
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const isPublicRoute = url.includes('/public/')
  const isAuthLogin = url.includes('/auth/login')
  const isAuthBootstrap = url.includes('/auth/bootstrap-admin') || url.includes('/auth/bootstrap-needed')
  const method = options?.method || 'GET'
  const isGetRequest = method.toUpperCase() === 'GET'

  // Include JSON content-type whenever we send a body (including DELETE with body).
  const hasBody = options?.body != null
  let headers: HeadersInit = hasBody
    ? {
        'Content-Type': 'application/json',
        ...options?.headers,
      }
    : { ...options?.headers }
  if (token && !isPublicRoute && !isAuthLogin && !isAuthBootstrap) {
    headers = {
      ...headers,
      Authorization: `Bearer ${token}`,
    }
  }
  
  // #region agent log
  if (url.includes('/desk/') || url.includes('/auth/login') || url.includes('/auth/bootstrap')) {
    fetch('http://127.0.0.1:7242/ingest/3aa7eda4-e97a-402c-ac3d-b6b632d2544d',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({runId:'pre-fix',hypothesisId:'H10',location:'client.ts:fetchJson:request',message:'frontend request dispatch',data:{method:options?.method||'GET',url,apiBase:API_BASE_URL,pageHref:typeof window!=='undefined'?window.location.href:null},timestamp:Date.now()})}).catch(()=>{});
  }
  // #endregion
  console.log('fetchJson:', method, url, { headers, body: options?.body })
  let response: Response
  try {
    response = await fetch(url, {
      ...options,
      headers,
      cache: isPublicRoute && isGetRequest ? 'no-store' : options?.cache,
    });
    // #region agent log
    if (url.includes('/desk/') || url.includes('/auth/login') || url.includes('/auth/bootstrap')) {
      fetch('http://127.0.0.1:7242/ingest/3aa7eda4-e97a-402c-ac3d-b6b632d2544d',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({runId:'pre-fix',hypothesisId:'H10',location:'client.ts:fetchJson:response',message:'frontend response received',data:{method:options?.method||'GET',url,status:response.status,statusText:response.statusText,responseUrl:response.url},timestamp:Date.now()})}).catch(()=>{});
    }
    // #endregion
    console.log('fetchJson response:', response.status, response.statusText, response.url)
  } catch (networkError) {
    console.error('Network error (failed to fetch):', networkError)
    const errorMsg = networkError instanceof Error 
      ? `Network error: ${networkError.message}. Is the backend running at ${url}?`
      : 'Network error: Failed to connect to backend. Is the server running?'
    throw new Error(errorMsg)
  }

  if (!response.ok) {
    let errorMessage = `HTTP error! status: ${response.status}`;
    let errorDetail: any = null;
    try {
      const error = await response.json();
      errorDetail = error;
      // Handle Pydantic validation errors
      if (error.detail) {
        if (Array.isArray(error.detail)) {
          // Pydantic v2 format
          errorMessage = error.detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join(', ');
        } else if (typeof error.detail === 'string') {
          errorMessage = error.detail;
        } else if (typeof error.detail === 'object') {
          // Structured error response (e.g., from build endpoint)
          errorMessage = error.detail.message || error.detail.error || JSON.stringify(error.detail);
        } else {
          errorMessage = JSON.stringify(error.detail);
        }
      } else if (error.message) {
        errorMessage = error.message;
      }
    } catch {
      // If JSON parsing fails, use default message
    }
    if (response.status === 500) {
      if (errorDetail?.detail && typeof errorDetail.detail === 'string') {
        errorMessage = errorDetail.detail;
      }
      errorMessage += ` (${url.replace(/^.*\/api/, '/api')})`;
    }
    // Handle auth expiry centrally for protected routes.
    if (response.status === 401 && !isPublicRoute && !isAuthLogin && !isAuthBootstrap) {
      clearAuthToken()
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/t/')) {
        window.location.assign('/login')
      }
    }

    // Log the failed URL for debugging
    console.error(`API call failed: ${response.status} ${response.statusText}`, {
      url,
      status: response.status,
      error: errorMessage,
      detail: errorDetail
    });
    // Create error with status code attached for fallback logic
    const error = new Error(errorMessage) as any;
    error.status = response.status;
    error.detail = errorDetail;
    error.url = url;
    throw error;
  }

  // Handle empty responses (e.g., DELETE requests returning 204 No Content)
  const contentType = response.headers.get('content-type');
  
  // If status is 204 No Content, return undefined
  if (response.status === 204) {
    return undefined as T;
  }
  
  // If content type exists but isn't JSON, don't try to parse
  if (contentType && !contentType.includes('application/json')) {
    return undefined as T;
  }
  
  // Try to parse JSON, but handle empty responses gracefully
  try {
    const text = await response.text();
    if (!text || text.trim() === '') {
      return undefined as T;
    }
    return JSON.parse(text);
  } catch {
    // If JSON parsing fails, return undefined (for void responses)
    return undefined as T;
  }
}

export interface AuthUser {
  id: number
  username: string
  display_name?: string | null
  role: 'admin' | 'director' | string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface BootstrapNeededResponse {
  bootstrap_needed: boolean
}

export interface AuthLoginResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

export interface AuthBootstrapAdminRequest {
  username: string
  password: string
  display_name?: string
}

export interface AuthCreateUserRequest {
  username: string
  password: string
  display_name?: string
  role: 'admin' | 'director'
  is_active?: boolean
}

export interface AuthUpdateUserRequest {
  display_name?: string
  role?: 'admin' | 'director'
  is_active?: boolean
  password?: string
}

export async function getAuthBootstrapNeeded(): Promise<BootstrapNeededResponse> {
  return fetchJson<BootstrapNeededResponse>(`${API_BASE_URL}/auth/bootstrap-needed`)
}

export async function bootstrapAdmin(payload: AuthBootstrapAdminRequest): Promise<AuthUser> {
  return fetchJson<AuthUser>(`${API_BASE_URL}/auth/bootstrap-admin`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function loginWithPassword(username: string, password: string): Promise<AuthLoginResponse> {
  return fetchJson<AuthLoginResponse>(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function logoutAuth(): Promise<void> {
  return fetchJson<void>(`${API_BASE_URL}/auth/logout`, { method: 'POST' })
}

export async function getAuthMe(): Promise<AuthUser> {
  return fetchJson<AuthUser>(`${API_BASE_URL}/auth/me`)
}

export async function listAuthUsers(): Promise<AuthUser[]> {
  return fetchJson<AuthUser[]>(`${API_BASE_URL}/auth/users`)
}

export async function createAuthUser(payload: AuthCreateUserRequest): Promise<AuthUser> {
  return fetchJson<AuthUser>(`${API_BASE_URL}/auth/users`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateAuthUser(userId: number, payload: AuthUpdateUserRequest): Promise<AuthUser> {
  return fetchJson<AuthUser>(`${API_BASE_URL}/auth/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

// Tournament functions
export async function listTournaments(): Promise<Tournament[]> {
  return fetchJson<Tournament[]>(`${API_BASE_URL}/tournaments`);
}

export async function createTournament(payload: TournamentCreate): Promise<Tournament> {
  return fetchJson<Tournament>(`${API_BASE_URL}/tournaments`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export interface RwOsEventSummary {
  organizationSlug: string
  tournamentId: number
  eventName: string
  eventDate: string
  teamCount: number
  draws: string[]
  updatedAt?: string
  version?: string
  alreadyImported?: boolean
  available?: boolean
}

export interface RwOsSnapshotPlayer {
  rw_id: string
  name: string
  rating: number | null
}

export interface RwOsSnapshotTeam {
  teamKey: string
  drawKind: string
  drawLabel: string
  player1: RwOsSnapshotPlayer
  player2: RwOsSnapshotPlayer
  teamRating: number | null
  ratingStatus: string
  status: string
  bucket: string
}

export interface RwOsCutAnalysis {
  fromLabel: string
  toLabel: string
  upperRank: number
  lowerRank: number
  upperTeamName: string
  lowerTeamName: string
  upperRating: number | null
  lowerRating: number | null
  ratingGap: number | null
  quality: string
  provisional?: boolean
  message?: string | null
  neighborhood: Array<{
    rank: number
    name: string
    teamRating: number | null
    isCutBoundary: boolean
  }>
}

export interface RwOsBracketPreview {
  label: string
  letter: string
  size: number
  rankStart: number
  rankEnd: number
  highestRating: number | null
  lowestRating: number | null
  averageRating: number | null
  medianRating: number | null
  ratingSpread: number | null
  knownTeamCount?: number
  unknownTeamCount?: number
  teams: Array<{
    rank: number
    teamKey: string
    name: string
    teamRating: number | null
    ratingStatus: string
  }>
}

export interface RwOsExplanation {
  type?: 'positive' | 'warning'
  code: string
  message: string
}

export interface RwOsSplitOption {
  optionKey: string
  sizes: number[]
  brackets: RwOsBracketPreview[]
  cuts: RwOsCutAnalysis[]
  recommended: boolean
  custom?: boolean
  fakeTeamCount?: number
  reasons?: RwOsExplanation[]
  warnings?: RwOsExplanation[]
  score: {
    cutQuality: number
    sizeQuality: number
    awkwardSizePenalty?: number
    tinyBracketPenalty: number
    provisionalCutPenalty?: number
    unratedTeamPenalty: number
    extraBracketPenalty?: number
    total: number
    reasons: string[]
    explanations?: {
      reasons: RwOsExplanation[]
      warnings: RwOsExplanation[]
    }
  }
}

export interface RwOsRatingReviewPlayer {
  name: string
  rwId?: string
  rw_id?: string
  rating: number | null
}

export interface RwOsRatingReviewTeam {
  teamKey: string
  name: string
  drawKind: string
  ratingStatus: string
  teamRating: number | null
  player1: RwOsRatingReviewPlayer
  player2: RwOsRatingReviewPlayer
}

export interface RwOsDrawPlan {
  drawKind: string
  drawLabel: string
  teamCount: number
  currentCount?: number
  forecastCount?: number
  unknownCount?: number
  shrinkCount?: number
  unratedCount: number
  partialCount: number
  ratingReviewNeeded: number
  ratingReviewTeams?: RwOsRatingReviewTeam[]
  optionCount?: number
  topOptionCount?: number
  generatedCount?: number
  planningNote?: string | null
  options: RwOsSplitOption[]
  teams?: Array<{
    rank: number
    teamKey: string
    name: string
    teamRating: number | null
    ratingStatus: string
    player1?: RwOsRatingReviewPlayer
    player2?: RwOsRatingReviewPlayer
  }>
}

export interface RwOsImportResponse {
  import: {
    id: number
    tournamentId: number
    organizationSlug: string
    sourceTournamentId: number
    eventName: string
    eventDate: string
    importedAt: string | null
    sourceUpdatedAt: string | null
    sourceVersion: string | null
    sourceTeamCount: number
    sourceHash: string
    validationStatus: string
    validationIssues: Array<{ code: string; message: string; team_key?: string | null }>
    refreshDiff: {
      addedCount: number
      withdrawnCount: number
      partnerChanges: unknown[]
      drawChanges: unknown[]
      ratingChanges: unknown[]
      changed: boolean
    } | null
    planStatus: string
    forecasts?: Record<string, number>
    currentCounts?: Record<string, number>
    approvedAt: string | null
    teams: RwOsSnapshotTeam[]
    waitlistTeams: RwOsSnapshotTeam[]
  }
  planner: {
    draws: RwOsDrawPlan[]
    maxBracketSize: number
    minBracketSize: number
    maxForecastTeams?: number
    preferredBracketSizes: number[]
    awkwardBracketSizes?: number[]
    maxDefaultScenarios?: number
    byeLogicApplicable: boolean
    teamRatingFormula: string
    forecasts?: Record<string, number>
  }
  drawCounts: Record<string, number>
  currentCounts?: Record<string, number>
  forecasts?: Record<string, number>
  customOption?: RwOsSplitOption
  customDrawKind?: string
  waitlistCount: number
  approvedPlans: Array<{
    drawKind: string
    optionKey: string
    approved: boolean
    isRecommended: boolean
    brackets: Array<{ label: string; size: number; rankStart: number; rankEnd: number }>
  }>
  selectedPlans: Array<{
    drawKind: string
    optionKey: string
    approved: boolean
    isRecommended: boolean
  }>
  bracketsCreated: boolean
}

export async function listRwOsEvents(): Promise<{
  events: RwOsEventSummary[]
  source?: 'fixtures' | 'live'
}> {
  return fetchJson<{ events: RwOsEventSummary[]; source?: 'fixtures' | 'live' }>(`${API_BASE_URL}/rw-os/events`)
}

export async function createRwOsImport(tournamentId: number, organizationSlug = 'rw'): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports`, {
    method: 'POST',
    body: JSON.stringify({ tournament_id: tournamentId, organization_slug: organizationSlug }),
  })
}

export async function getRwOsImport(importId: number): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports/${importId}`)
}

export async function refreshRwOsImport(importId: number, apply = false): Promise<{
  diff: NonNullable<RwOsImportResponse['import']['refreshDiff']> & { addedTeams?: unknown[]; withdrawnTeams?: unknown[] }
  applied: boolean
  importResponse: RwOsImportResponse
}> {
  return fetchJson(`${API_BASE_URL}/rw-os/imports/${importId}/refresh`, {
    method: 'POST',
    body: JSON.stringify({ apply }),
  })
}

export async function updateRwOsForecasts(
  importId: number,
  forecasts: Record<string, number>,
): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports/${importId}/forecasts`, {
    method: 'PUT',
    body: JSON.stringify({ forecasts }),
  })
}

export async function resetRwOsForecasts(importId: number): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports/${importId}/forecasts/reset`, {
    method: 'POST',
  })
}

export async function submitRwOsCustomStructure(
  importId: number,
  drawKind: string,
  sizes: number[],
): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports/${importId}/custom-structure`, {
    method: 'POST',
    body: JSON.stringify({ draw_kind: drawKind, sizes }),
  })
}

export async function selectRwOsStructure(
  importId: number,
  drawKind: string,
  optionKey: string,
): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports/${importId}/select-structure`, {
    method: 'POST',
    body: JSON.stringify({ draw_kind: drawKind, option_key: optionKey }),
  })
}

export async function approveRwOsPlan(
  importId: number,
  selections: Record<string, string>,
): Promise<RwOsImportResponse> {
  return fetchJson<RwOsImportResponse>(`${API_BASE_URL}/rw-os/imports/${importId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ selections }),
  })
}

export async function getTournament(id: number): Promise<Tournament> {
  return fetchJson<Tournament>(`${API_BASE_URL}/tournaments/${id}`);
}

export async function updateTournament(id: number, payload: TournamentUpdate): Promise<Tournament> {
  return fetchJson<Tournament>(`${API_BASE_URL}/tournaments/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function duplicateTournament(id: number): Promise<Tournament> {
  const url = `${API_BASE_URL}/tournaments/${id}/duplicate`
  console.log('duplicateTournament: POST', url)
  return fetchJson<Tournament>(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  });
}

export async function deleteTournament(id: number): Promise<void> {
  const url = `${API_BASE_URL}/tournaments/${id}`
  console.log('deleteTournament: DELETE', url)
  return fetchJson<void>(url, {
    method: 'DELETE',
  });
}

export async function startOverTournament(id: number): Promise<TournamentStartOverResponse> {
  return fetchJson<TournamentStartOverResponse>(`${API_BASE_URL}/tournaments/${id}/start-over`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function downloadTournamentPrintPacket(
  id: number,
  category: 'womens' | 'mixed'
): Promise<Blob> {
  const url = `${API_BASE_URL}/tournaments/${id}/print-packet/${category}.pdf`
  const token = getAuthToken()
  const response = await fetch(url, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    let message = `Failed to download ${category} print packet`
    try {
      const err = await response.json()
      if (typeof err?.detail === 'string') message = err.detail
    } catch {
      // keep default message
    }
    throw new Error(message)
  }
  return await response.blob()
}

// Tournament Days functions
export async function getTournamentDays(tournamentId: number): Promise<TournamentDay[]> {
  return fetchJson<TournamentDay[]>(`${API_BASE_URL}/tournaments/${tournamentId}/days`);
}

export async function updateTournamentDays(
  tournamentId: number,
  days: DayUpdate[]
): Promise<TournamentDay[]> {
  return fetchJson<TournamentDay[]>(`${API_BASE_URL}/tournaments/${tournamentId}/days`, {
    method: 'PUT',
    body: JSON.stringify({ days }),
  });
}

// Events functions
export async function getEvents(tournamentId: number): Promise<Event[]> {
  return fetchJson<Event[]>(`${API_BASE_URL}/tournaments/${tournamentId}/events`);
}

export async function createEvent(tournamentId: number, payload: EventCreate): Promise<Event> {
  return fetchJson<Event>(`${API_BASE_URL}/tournaments/${tournamentId}/events`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateEvent(eventId: number, payload: EventUpdate): Promise<Event> {
  return fetchJson<Event>(`${API_BASE_URL}/events/${eventId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteEvent(eventId: number): Promise<void> {
  await fetchJson<void>(`${API_BASE_URL}/events/${eventId}`, {
    method: 'DELETE',
  });
}

// Phase 1 Status
export async function getPhase1Status(tournamentId: number): Promise<Phase1Status> {
  return fetchJson<Phase1Status>(`${API_BASE_URL}/tournaments/${tournamentId}/phase1-status`);
}

// Phase 2 Draw Builder
export interface DrawPlanData {
  id: number;
  draw_plan_json: string | null;
  draw_plan_version: string | null;
  draw_status: string | null;
  wf_block_minutes: number | null;
  standard_block_minutes: number | null;
  guarantee_selected: number | null;
  schedule_profile_json: string | null;
}

export async function getDrawPlan(eventId: number): Promise<DrawPlanData> {
  return fetchJson<DrawPlanData>(`${API_BASE_URL}/events/${eventId}/draw-plan`);
}

export interface DrawPlanUpdate {
  draw_plan_json?: string | null;
  schedule_profile_json?: string | null;
  wf_block_minutes?: number | null;
  standard_block_minutes?: number | null;
}

export async function updateDrawPlan(eventId: number, payload: DrawPlanUpdate): Promise<DrawPlanData> {
  return fetchJson<DrawPlanData>(`${API_BASE_URL}/events/${eventId}/draw-plan`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function finalizeDrawPlan(eventId: number, guaranteeSelected: number): Promise<{ id: number; draw_status: string; guarantee_selected: number | null }> {
  return fetchJson<{ id: number; draw_status: string; guarantee_selected: number | null }>(`${API_BASE_URL}/events/${eventId}/draw-plan/finalize`, {
    method: 'POST',
    body: JSON.stringify({ guarantee_selected: guaranteeSelected }),
  });
}

export async function reopenDrawPlan(eventId: number): Promise<{ id: number; draw_status: string; matches_cleared: number }> {
  return fetchJson<{ id: number; draw_status: string; matches_cleared: number }>(`${API_BASE_URL}/events/${eventId}/draw-plan/reopen`, {
    method: 'POST',
  });
}

// Schedule Builder — authoritative match inventory (read-only)
export interface ScheduleBuilderEvent {
  event_id: number;
  event_name: string;
  division: string;
  team_count: number;
  template_type: string;
  guarantee: number;
  schedule_order?: number | null;
  waterfall_rounds: number;
  wf_matches: number;
  bracket_matches: number;
  round_robin_matches: number;
  match_lengths: { waterfall: number; standard: number };
  total_matches: number;
  /** Stage breakdown: WF, RR_POOL, BRACKET_MAIN, CONSOLATION_T1, CONSOLATION_T2, PLACEMENT */
  counts_by_stage?: Record<string, number>;
  status?: string;
  is_finalized?: boolean;
  error?: string;
  warning?: string;
}

export interface ScheduleBuilderResponse {
  tournament_id: number;
  events: ScheduleBuilderEvent[];
  /** Sorted ISO dates; same ordering as schedule policy day_index for policy_calendar_version_id. */
  policy_calendar_days?: string[];
  policy_calendar_version_id?: number | null;
}

export async function getScheduleBuilder(
  tournamentId: number,
  options?: { scheduleVersionId?: number | null },
): Promise<ScheduleBuilderResponse> {
  let url = `${API_BASE_URL}/tournaments/${tournamentId}/schedule-builder`;
  if (options?.scheduleVersionId != null) {
    url += `?schedule_version_id=${options.scheduleVersionId}`;
  }
  return fetchJson<ScheduleBuilderResponse>(url);
}

// Time Windows interfaces and functions
export interface TimeWindow {
  id: number;
  tournament_id: number;
  day_date: string;
  start_time: string;
  end_time: string;
  courts_available: number;
  extra_courts: number;
  block_minutes: number;
  label?: string | null;
  is_active: boolean;
}

export interface TimeWindowCreate {
  day_date: string;
  start_time: string;
  end_time: string;
  courts_available: number;
  extra_courts: number;
  block_minutes: number;
  label?: string | null;
  is_active?: boolean;
}

export interface TimeWindowUpdate {
  day_date?: string;
  start_time?: string;
  end_time?: string;
  courts_available?: number;
  extra_courts?: number;
  block_minutes?: number;
  label?: string | null;
  is_active?: boolean;
}

export interface TimeWindowSummary {
  total_capacity_minutes: number;
  slot_capacity_by_block: Record<number, number>;
  total_slots_all_blocks: number;
}

export async function getTimeWindows(tournamentId: number): Promise<TimeWindow[]> {
  return fetchJson<TimeWindow[]>(`${API_BASE_URL}/tournaments/${tournamentId}/time-windows`);
}

export async function createTimeWindow(tournamentId: number, payload: TimeWindowCreate): Promise<TimeWindow> {
  const url = `${API_BASE_URL}/tournaments/${tournamentId}/time-windows`
  console.log('createTimeWindow URL:', url)
  console.log('createTimeWindow payload:', payload)
  console.log('POST payload day_date=', payload.day_date) // Debug log for date fix verification
  return fetchJson<TimeWindow>(url, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateTimeWindow(windowId: number, payload: TimeWindowUpdate): Promise<TimeWindow> {
  return fetchJson<TimeWindow>(`${API_BASE_URL}/time-windows/${windowId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteTimeWindow(windowId: number): Promise<void> {
  return fetchJson<void>(`${API_BASE_URL}/time-windows/${windowId}`, {
    method: 'DELETE',
  });
}

export async function getTimeWindowsSummary(tournamentId: number): Promise<TimeWindowSummary> {
  return fetchJson<TimeWindowSummary>(`${API_BASE_URL}/tournaments/${tournamentId}/time-windows/summary`);
}

// Schedule interfaces and functions (Phase 3A)
export interface ScheduleVersion {
  id: number;
  tournament_id: number;
  version_number: number;
  status: 'draft' | 'final';
  created_at: string;
  created_by?: string | null;
  notes?: string | null;
}

export interface ScheduleVersionCreate {
  notes?: string | null;
}

export interface ScheduleSlot {
  id: number;
  tournament_id: number;
  schedule_version_id: number;
  day_date: string;
  start_time: string;
  end_time: string;
  court_number: number;
  court_label: string;  // Immutable label for this version
  block_minutes: number;
  label?: string | null;
  is_active: boolean;
  match_id?: number | null;
  match_code?: string | null;
  assignment_id?: number | null;
}

export interface SlotGenerateRequest {
  source: 'time_windows' | 'days_courts' | 'auto';
  schedule_version_id?: number | null;
  wipe_existing?: boolean;
}

export interface Match {
  id: number;
  tournament_id: number;
  event_id: number;
  schedule_version_id: number;
  match_code: string;
  match_type: 'WF' | 'RR' | 'BRACKET' | 'PLACEMENT';
  round_number: number;
  round_index?: number | null;
  sequence_in_round: number;
  duration_minutes: number;
  placeholder_side_a: string;
  placeholder_side_b: string;
  status: 'unscheduled' | 'scheduled' | 'complete' | 'cancelled';
  created_at: string;
  slot_id?: number | null;
  team_a_id?: number | null;
  team_b_id?: number | null;
}

export interface MatchGenerateRequest {
  event_id?: number | null;
  schedule_version_id?: number | null;
  wipe_existing?: boolean;
}

export interface AssignmentCreate {
  schedule_version_id: number;
  match_id: number;
  slot_id: number;
}

// Schedule Version functions
export async function getScheduleVersions(tournamentId: number): Promise<ScheduleVersion[]> {
  return fetchJson<ScheduleVersion[]>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions`);
}

export async function createScheduleVersion(tournamentId: number, payload?: ScheduleVersionCreate): Promise<ScheduleVersion> {
  return fetchJson<ScheduleVersion>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions`, {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

export interface ActiveVersionResponse {
  schedule_version_id: number
  status: string
  created_at: string | null
  none_found: boolean
}

/** Canonical active draft version — backend source of truth. */
export async function getActiveScheduleVersion(tournamentId: number): Promise<ActiveVersionResponse> {
  return fetchJson<ActiveVersionResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/active`
  )
}

export async function finalizeScheduleVersion(tournamentId: number, versionId: number): Promise<ScheduleVersion> {
  return fetchJson<ScheduleVersion>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/finalize`, {
    method: 'POST',
  });
}

export interface PublishResponse {
  success: boolean
  tournament_id: number
  public_schedule_version_id: number | null
  version_status?: string
}

export async function publishScheduleVersion(tournamentId: number, versionId: number): Promise<PublishResponse> {
  return fetchJson<PublishResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/publish`,
    { method: 'PATCH' }
  )
}

export async function unpublishSchedule(tournamentId: number): Promise<PublishResponse> {
  return fetchJson<PublishResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/unpublish`,
    { method: 'PATCH' }
  )
}

export async function cloneScheduleVersion(tournamentId: number, versionId: number): Promise<ScheduleVersion> {
  return fetchJson<ScheduleVersion>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/clone`, {
    method: 'POST',
  });
}

export async function deleteScheduleVersion(tournamentId: number, versionId: number): Promise<void> {
  return fetchJson<void>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}`, {
    method: 'DELETE',
  });
}

// Slots functions
export async function generateSlots(tournamentId: number, payload: SlotGenerateRequest): Promise<{ schedule_version_id: number; slots_created: number }> {
  return fetchJson<{ schedule_version_id: number; slots_created: number }>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/slots/generate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getSlots(tournamentId: number, scheduleVersionId?: number, dayDate?: string): Promise<ScheduleSlot[]> {
  const params = new URLSearchParams();
  if (scheduleVersionId) params.append('schedule_version_id', scheduleVersionId.toString());
  if (dayDate) params.append('day_date', dayDate);
  const query = params.toString();
  return fetchJson<ScheduleSlot[]>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/slots${query ? `?${query}` : ''}`);
}

// Matches functions
export interface MatchGenerateRequest {
  event_id?: number | null;
  schedule_version_id?: number | null;
  wipe_existing?: boolean;
}

/** Calls orchestrator build endpoint — match generation only allowed via build. */
export async function generateMatches(tournamentId: number, payload?: MatchGenerateRequest): Promise<{ schedule_version_id: number; total_matches_created: number; per_event: Record<number, { event_name: string; matches: number }> }> {
  const versionId = payload?.schedule_version_id;
  if (!versionId) throw new Error('schedule_version_id required');
  const result = await buildScheduleVersion(tournamentId, versionId);
  return {
    schedule_version_id: versionId,
    total_matches_created: result.matches_created,
    per_event: {}, // build returns aggregate; per_event not needed for UI
  };
}

export async function getMatches(tournamentId: number, scheduleVersionId?: number, eventId?: number, status?: string): Promise<Match[]> {
  const params = new URLSearchParams();
  if (scheduleVersionId) params.append('schedule_version_id', scheduleVersionId.toString());
  if (eventId) params.append('event_id', eventId.toString());
  if (status) params.append('status', status);
  const query = params.toString();
  return fetchJson<Match[]>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/matches${query ? `?${query}` : ''}`);
}

export interface WfR1SwapSlotsRequest {
  schedule_version_id: number;
  event_id: number;
  match_id_a: number;
  slot_a: 'A' | 'B';
  match_id_b: number;
  slot_b: 'A' | 'B';
}

/** Swap teams between two WF round-1 sides (draft / non-final schedule version only). */
export async function wfR1SwapSlots(tournamentId: number, body: WfR1SwapSlotsRequest): Promise<{ ok: boolean; match_ids: number[] }> {
  return fetchJson<{ ok: boolean; match_ids: number[] }>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/wf-r1-swap-slots`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

// Assignment functions
export async function createAssignment(tournamentId: number, payload: AssignmentCreate): Promise<{ id: number; schedule_version_id: number; match_id: number; slot_id: number; assigned_at: string }> {
  return fetchJson<{ id: number; schedule_version_id: number; match_id: number; slot_id: number; assigned_at: string }>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/assignments`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function deleteAssignment(tournamentId: number, assignmentId: number): Promise<void> {
  return fetchJson<void>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/assignments/${assignmentId}`, {
    method: 'DELETE',
  });
}

// Grid Population V1
export interface GridSlot {
  slot_id: number;
  start_time: string;
  duration_minutes: number;
  court_id: number;
  court_label: string;
  day_date: string;
}

export interface GridAssignment {
  id: number;  // Assignment database ID (required for PATCH endpoint)
  slot_id: number;
  match_id: number;
  locked: boolean;
}

export interface GridMatchLock {
  match_id: number;
  slot_id: number;
}

export interface GridSlotLock {
  slot_id: number;
  status: string;
}

export interface GridMatch {
  match_id: number;
  stage: string;
  round_index: number;
  sequence_in_round: number;
  duration_minutes: number;
  match_code: string;
  event_id: number;
  // Team injection fields (nullable)
  team_a_id: number | null;
  team_b_id: number | null;
  placeholder_side_a: string;
  placeholder_side_b: string;
}

export interface TeamInfo {
  id: number;
  name: string;
  seed: number | null;
  event_id: number;
  display_name: string | null;
  avoid_group: string | null;
}

export interface ConflictSummary {
  tournament_id: number;
  schedule_version_id: number;
  total_slots: number;
  total_matches: number;
  assigned_matches: number;
  unassigned_matches: number;
  assignment_rate: number;
}

export interface ScheduleGridV1 {
  slots: GridSlot[];
  assignments: GridAssignment[];
  matches: GridMatch[];
  teams: TeamInfo[];
  conflicts_summary: ConflictSummary | null;
  match_locks: GridMatchLock[];
  slot_locks: GridSlotLock[];
}

export interface LocksResponse {
  match_locks: Array<{
    id: number;
    schedule_version_id: number;
    match_id: number;
    slot_id: number;
    created_at: string | null;
    created_by: string | null;
  }>;
  slot_locks: Array<{
    id: number;
    schedule_version_id: number;
    slot_id: number;
    status: string;
    created_at: string | null;
  }>;
}

export async function getScheduleGrid(tournamentId: number, scheduleVersionId: number): Promise<ScheduleGridV1> {
  const params = new URLSearchParams();
  params.append('schedule_version_id', scheduleVersionId.toString());
  return fetchJson<ScheduleGridV1>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/grid?${params.toString()}`);
}

// Phase 4 runtime (match status + scoring; no schedule mutation)
export interface MatchRuntimeState {
  id: number;
  tournament_id: number;
  schedule_version_id: number;
  event_id: number;
  match_code: string;
  match_type: string;
  round_index: number;
  sequence_in_round: number;
  runtime_status: string;
  score_json: Record<string, unknown> | null;
  winner_team_id: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface MatchRuntimeUpdate {
  status?: string;
  score?: Record<string, unknown>;
  winner_team_id?: number | null;
}

/** PATCH runtime response: match state + advancement count when finalized */
export interface MatchRuntimeUpdateResponse {
  match: MatchRuntimeState;
  advanced_count: number;
}

export async function getVersionRuntimeMatches(
  tournamentId: number,
  scheduleVersionId: number
): Promise<MatchRuntimeState[]> {
  return fetchJson<MatchRuntimeState[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/runtime/versions/${scheduleVersionId}/matches`
  );
}

export async function updateMatchRuntime(
  tournamentId: number,
  matchId: number,
  payload: MatchRuntimeUpdate
): Promise<MatchRuntimeUpdateResponse> {
  return fetchJson<MatchRuntimeUpdateResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/runtime/matches/${matchId}`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  );
}

// Build Schedule function (one-click build)
export interface BuildScheduleRequest {
  schedule_version_id: number
}

export interface BuildScheduleResponse {
  schedule_version_id: number
  slots_created: number
  matches_created: number
  matches_assigned: number
  matches_unassigned: number
  conflicts?: { reason: string; count: number }[]
  warnings?: { message: string; count: number }[]
}

/** Full build response from backend (orchestrator returns summary object). */
interface BuildFullScheduleResponseRaw {
  status: string
  schedule_version_id: number
  summary?: {
    slots_generated?: number
    matches_generated?: number
    assignments_created?: number
    unassigned_matches?: number
  }
  warnings?: { message: string; count?: number; code?: string }[]
  conflicts?: unknown
}

/** POST /api/tournaments/{tournamentId}/schedule/versions/{versionId}/build — One-click build (orchestrator). */
export async function buildScheduleVersion(tournamentId: number, versionId: number): Promise<BuildScheduleResponse> {
  const raw = await fetchJson<BuildFullScheduleResponseRaw>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/build`,
    { method: 'POST' }
  )
  // Normalize orchestrator response (summary.*) to flat BuildScheduleResponse for UI
  if (raw.summary != null && (raw as unknown as BuildScheduleResponse).slots_created === undefined) {
    return {
      schedule_version_id: raw.schedule_version_id,
      slots_created: raw.summary.slots_generated ?? 0,
      matches_created: raw.summary.matches_generated ?? 0,
      matches_assigned: raw.summary.assignments_created ?? 0,
      matches_unassigned: raw.summary.unassigned_matches ?? 0,
      conflicts: undefined,
      warnings: raw.warnings?.map((w) => ({ message: (w as { message?: string }).message ?? String(w), count: (w as { count?: number }).count ?? 1 })),
    }
  }
  return raw as unknown as BuildScheduleResponse
}

export async function buildSchedule(tournamentId: number, versionId: number): Promise<BuildScheduleResponse> {
  return await buildScheduleVersion(tournamentId, versionId);
}

// Phase Flow V1 - Match Preview, Generate Matches/Slots Only, Assign by Scope
export interface MatchPreviewItem {
  id: number
  event_id: number
  match_code: string
  stage: string
  round_number: number
  round_index: number
  sequence_in_round: number
  match_type: string
  consolation_tier?: number | null
  duration_minutes: number
  placeholder_side_a: string
  placeholder_side_b: string
  team_a_id: number | null
  team_b_id: number | null
}

export interface MatchPreviewDiagnostics {
  requested_version_id: number
  matches_found: number
  grid_reported_matches_for_version: number
  likely_version_mismatch: boolean
  event_ids_present?: number[]
  event_counts_by_id?: Record<string, number>
}

export interface MatchPreviewTeam {
  id: number
  name: string
  seed: number | null
  display_name: string | null
  event_id: number
}

export interface MatchPreviewResponse {
  matches: MatchPreviewItem[]
  counts_by_event: Record<string, number>
  counts_by_stage: Record<string, number>
  event_names_by_id?: Record<string, string>
  duplicate_codes: string[]
  ordering_checksum: string
  diagnostics: MatchPreviewDiagnostics
  teams?: MatchPreviewTeam[]
}

export async function getMatchesPreview(
  tournamentId: number,
  versionId: number
): Promise<MatchPreviewResponse> {
  return fetchJson<MatchPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/matches/preview`
  )
}

/** Alias for clarity. */
export const getMatchCardsPreview = getMatchesPreview

/**
 * Fetch match cards for review. Uses preview endpoint first; if it returns
 * empty matches, falls back to getMatches (ensures page never shows empty
 * when matches actually exist).
 */
export async function getMatchCardsPreviewWithFallback(
  tournamentId: number,
  versionId: number
): Promise<MatchPreviewResponse> {
  const preview = await getMatchesPreview(tournamentId, versionId)
  if (preview.matches.length > 0) return preview

  const matches = await getMatches(tournamentId, versionId)
  if (matches.length === 0) return preview

  const codes = matches.map((m) => m.match_code)
  const seen: Record<string, number> = {}
  const duplicate_codes: string[] = []
  for (const c of codes) {
    seen[c] = (seen[c] ?? 0) + 1
  }
  for (const [c, cnt] of Object.entries(seen)) {
    if (cnt > 1) duplicate_codes.push(...Array(cnt - 1).fill(c))
  }

  const eventCounts: Record<string, number> = {}
  const stageCounts: Record<string, number> = {}
  for (const m of matches) {
    eventCounts[String(m.event_id)] = (eventCounts[String(m.event_id)] ?? 0) + 1
    stageCounts[m.match_type] = (stageCounts[m.match_type] ?? 0) + 1
  }

  const sorted = [...matches].sort(
    (a, b) =>
      (a.event_id - b.event_id) ||
      (a.match_type.localeCompare(b.match_type)) ||
      ((a.round_index ?? 0) - (b.round_index ?? 0)) ||
      ((a.sequence_in_round ?? 0) - (b.sequence_in_round ?? 0)) ||
      (a.match_code.localeCompare(b.match_code)) ||
      ((a.id ?? 0) - (b.id ?? 0))
  )

  const checksum = Array.from(codes.join(',')).reduce(
    (h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0,
    0
  ).toString(16).slice(0, 16)

  return {
    matches: sorted.map((m) => ({
      id: m.id,
      event_id: m.event_id,
      match_code: m.match_code,
      stage: m.match_type,
      round_number: m.round_number,
      round_index: m.round_index ?? 0,
      sequence_in_round: m.sequence_in_round ?? 0,
      match_type: m.match_type,
      duration_minutes: m.duration_minutes,
      placeholder_side_a: m.placeholder_side_a,
      placeholder_side_b: m.placeholder_side_b,
      team_a_id: (m as { team_a_id?: number | null }).team_a_id ?? null,
      team_b_id: (m as { team_b_id?: number | null }).team_b_id ?? null,
    })),
    counts_by_event: eventCounts,
    counts_by_stage: stageCounts,
    event_names_by_id: {},
    duplicate_codes: [...new Set(duplicate_codes)],
    ordering_checksum: checksum,
    diagnostics: {
      requested_version_id: versionId,
      matches_found: matches.length,
      grid_reported_matches_for_version: matches.length,
      likely_version_mismatch: false,
    },
  }
}

export interface EventExpectedItem {
  event_id: number
  event_name: string
  expected: number
  existing_before: number
  generated_added: number
  decision?: string
  reason?: string
}

export interface MatchesGenerateOnlyResponse {
  matches_generated: number
  already_generated: boolean
  debug_stamp: string
  trace_id?: string
  seen_event_ids?: number[]
  finalized_event_ids?: number[]
  events_included?: string[]
  events_skipped?: string[]
  events_not_finalized?: string[]
  finalized_events_found?: string[]
  events_expected?: EventExpectedItem[]
  already_complete?: boolean
}

export interface MatchesGenerateOnlyOptions {
  wipeExisting?: boolean
}

export async function generateMatchesOnly(
  tournamentId: number,
  versionId: number,
  options?: MatchesGenerateOnlyOptions
): Promise<MatchesGenerateOnlyResponse> {
  return fetchJson<MatchesGenerateOnlyResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/matches/generate`,
    {
      method: 'POST',
      body: options?.wipeExisting ? JSON.stringify({ wipe_existing: true }) : undefined,
    }
  )
}

export interface WipeMatchesResponse {
  deleted_matches: number
}

export async function wipeScheduleVersionMatches(
  tournamentId: number,
  versionId: number
): Promise<WipeMatchesResponse> {
  return fetchJson<WipeMatchesResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/matches`,
    {
      method: 'DELETE',
    }
  )
}

export interface SlotsGenerateOnlyResponse {
  slots_generated: number
  already_generated: boolean
  debug_stamp: string
}

export async function generateSlotsOnly(
  tournamentId: number,
  versionId: number
): Promise<SlotsGenerateOnlyResponse> {
  return fetchJson<SlotsGenerateOnlyResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/slots/generate`,
    { method: 'POST' }
  )
}

export async function regenerateSlots(
  tournamentId: number,
  versionId: number
): Promise<SlotsGenerateOnlyResponse> {
  return fetchJson<SlotsGenerateOnlyResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/slots/regenerate`,
    { method: 'POST' }
  )
}

export interface AssignScopeResponse {
  assigned_count: number
  unassigned_count_remaining_in_scope: number
  debug_stamp: string
}

export async function assignByScope(
  tournamentId: number,
  versionId: number,
  scope: 'WF_R1' | 'WF_R2' | 'RR_POOL' | 'BRACKET_MAIN' | 'ALL',
  options?: { event_id?: number; clear_existing_assignments_in_scope?: boolean }
): Promise<AssignScopeResponse> {
  return fetchJson<AssignScopeResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/assign`,
    {
      method: 'POST',
      body: JSON.stringify({
        scope,
        event_id: options?.event_id ?? null,
        clear_existing_assignments_in_scope: options?.clear_existing_assignments_in_scope ?? false,
      }),
    }
  )
}

// ============================================================================
// Assign Subset — place specific match IDs (per-round buttons)
// ============================================================================

export interface AssignSubsetResponse {
  assigned_count: number
  unassigned_count_remaining: number
  debug_stamp: string
}

/**
 * Place a specific list of matches by ID.
 * Used by per-round buttons (RR Round 1, Bracket QFs, etc.)
 * Match ID order is preserved by the backend; SchedulePhasedPanel orders by tournament day lists when set.
 * Optional targetDay restricts placement to slots on that calendar day (same as daily policy runs).
 */
export async function placeMatchSubset(
  tournamentId: number,
  versionId: number,
  matchIds: number[],
  options?: { targetDay?: string }
): Promise<AssignSubsetResponse> {
  const body: { match_ids: number[]; target_day?: string } = { match_ids: matchIds }
  if (options?.targetDay?.trim()) {
    body.target_day = options.targetDay.trim()
  }
  return fetchJson<AssignSubsetResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/assign-subset`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

// Conflicts Report V1 (Phase 3D)
export interface UnassignedMatchDetail {
  match_id: number;
  match_code: string;
  stage: string;
  round_index: number;
  sequence_in_round: number;
  duration_minutes: number;
  event_id: number;
  team_a_id: number | null;
  team_b_id: number | null;
  placeholder_side_a: string;
  placeholder_side_b: string;
}

export interface ConflictReportSummary {
  tournament_id: number;
  schedule_version_id: number;
  total_slots: number;
  total_matches: number;
  assigned_matches: number;
  unassigned_matches: number;
  assignment_rate: number;
}

export interface SlotPressure {
  slot_id: number;
  day_date: string;
  start_time: string;
  court_label: string;
  match_count: number;
}

export interface StageTimeline {
  stage: string;
  earliest_slot: string | null;
  latest_slot: string | null;
}

export interface OrderingViolation {
  earlier_match_id: number;
  earlier_match_code: string;
  earlier_slot_time: string;
  later_match_id: number;
  later_match_code: string;
  later_slot_time: string;
  reason: string;
}

export interface OrderingIntegrity {
  violations_detected: number;
  violations: OrderingViolation[];
}

export interface TeamConflictDetail {
  match_id: number;
  match_code: string;
  slot_id: number;
  team_id: number;
  conflicting_match_id: number;
  conflicting_match_code: string;
  conflicting_slot_id: number;
  details: string;
}

export interface TeamConflictsSummary {
  known_team_conflicts_count: number;
  unknown_team_matches_count: number;
  conflicts: TeamConflictDetail[];
}

export interface ConflictReportV1 {
  summary: ConflictReportSummary;
  unassigned_matches: UnassignedMatchDetail[];
  slot_pressure: SlotPressure[];
  stage_timeline: StageTimeline[];
  ordering_integrity: OrderingIntegrity;
  team_conflicts?: TeamConflictsSummary;
}

export async function getConflicts(
  tournamentId: number,
  scheduleVersionId: number,
  eventId?: number
): Promise<ConflictReportV1> {
  const params = new URLSearchParams();
  params.append('schedule_version_id', scheduleVersionId.toString());
  if (eventId !== undefined) {
    params.append('event_id', eventId.toString());
  }
  return fetchJson<ConflictReportV1>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/conflicts?${params.toString()}`
  );
}

export async function getTeamConflicts(
  tournamentId: number,
  scheduleVersionId: number
): Promise<TeamConflictsSummary> {
  const params = new URLSearchParams();
  params.append('schedule_version_id', scheduleVersionId.toString());
  return fetchJson<TeamConflictsSummary>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/team-conflicts?${params.toString()}`
  );
}

// ============================================================================
// Schedule Plan Report (authoritative contract)
// ============================================================================

export interface PlanReportError {
  code: string
  message: string
  event_id?: number | null
  context?: Record<string, unknown> | null
}

export interface WaterfallInfo {
  rounds: number
  r1_matches: number
  r2_matches: number
  r2_sequences_total: number
}

export interface PoolsInfo {
  pool_count: number
  pool_size: number
  rr_rounds: number
  rr_matches: number
}

export interface BracketsInfo {
  divisions: number
  main_matches: number
  consolation_matches: number
  total_matches: number
}

export interface PlaceholderInfo {
  rr_wired: boolean
  bracket_wired: boolean
  bye_count: number
}

export interface InventoryInfo {
  expected_total: number
  actual_total: number
}

export interface EventReport {
  event_id: number
  name: string
  teams_count: number
  template_code: string
  waterfall: WaterfallInfo
  pools: PoolsInfo
  brackets: BracketsInfo
  placeholders: PlaceholderInfo
  inventory: InventoryInfo
}

export interface TotalsInfo {
  events: number
  matches_total: number
}

export interface AvoidanceItemR1 {
  match_id: number
  match_code: string
  seed_a?: number | null
  seed_b?: number | null
  team_a?: string | null
  team_b?: string | null
  avoid_group: string
  message: string
}

export interface AvoidanceItemR2 {
  match_id: number
  match_code: string
  source_match_codes: string[]
  overlap_groups: string[]
  message: string
}

export interface AvoidanceSummary {
  r1_unavoidable_count: number
  r1_unavoidable_items: AvoidanceItemR1[]
  r2_potential_count: number
  r2_potential_items: AvoidanceItemR2[]
}

export interface SchedulePlanReport {
  tournament_id: number
  schedule_version_id: number | null
  version_status: string | null
  ok: boolean
  blocking_errors: PlanReportError[]
  warnings: PlanReportError[]
  events: EventReport[]
  totals: TotalsInfo
  avoidance_summary?: AvoidanceSummary | null
}

/** Draw-plan-only validation (no version required). */
export async function getPlanReport(tournamentId: number): Promise<SchedulePlanReport> {
  return fetchJson<SchedulePlanReport>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/plan-report`
  )
}

/** Full validation with match inventory comparison. */
export async function getPlanReportVersioned(
  tournamentId: number,
  versionId: number
): Promise<SchedulePlanReport> {
  return fetchJson<SchedulePlanReport>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/plan-report`
  )
}

// ── Schedule Report ───────────────────────────────────────────────────────

export interface EventStageBreakdown {
  event_name: string
  stage: string
  match_count: number
}

export interface TimeSlotReport {
  time: string
  total_courts: number
  assigned_matches: number
  auto_courts?: number
  manual_only_courts?: number
  breakdown: EventStageBreakdown[]
}

export interface DayReport {
  day: string
  time_slots: TimeSlotReport[]
}

export interface ScheduleReportResponse {
  days: DayReport[]
}

export async function getScheduleReport(
  tournamentId: number,
  versionId: number
): Promise<ScheduleReportResponse> {
  return fetchJson<ScheduleReportResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/schedule-report`
  )
}

// Manual Assignment PATCH endpoint
export interface UpdateAssignmentRequest {
  new_slot_id: number;
}

export interface AssignmentDetail {
  id: number;
  schedule_version_id: number;
  match_id: number;
  slot_id: number;
  locked: boolean;
  assigned_by: string;
  assigned_at: string;
}

export async function updateAssignment(
  tournamentId: number,
  assignmentId: number,
  newSlotId: number
): Promise<AssignmentDetail> {
  return fetchJson<AssignmentDetail>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/assignments/${assignmentId}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ new_slot_id: newSlotId }),
    }
  );
}

// ── Policy-based placement ─────────────────────────────────────────────

export interface PolicyBatchResult {
  name: string
  attempted: number
  assigned: number
  failed_count: number
  failed_match_ids: number[]
}

export interface PolicyBatchPreview {
  name: string
  match_ids: number[]
  match_count: number
  description: string
}

export interface PolicyPlanPreview {
  day_date: string
  day_index: number
  total_match_ids: number
  reserved_slot_count: number
  batches: PolicyBatchPreview[]
}

export interface PolicyRunResponse {
  day_date: string
  total_assigned: number
  total_failed: number
  reserved_slot_count: number
  duration_ms: number | null
  batches: PolicyBatchResult[]
}

export interface PolicyDaysResponse {
  days: string[]
}

export async function getPolicyDays(
  tournamentId: number,
  versionId: number
): Promise<PolicyDaysResponse> {
  return fetchJson<PolicyDaysResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/policy-days`
  )
}

export async function previewPolicyPlan(
  tournamentId: number,
  versionId: number,
  day: string
): Promise<PolicyPlanPreview> {
  return fetchJson<PolicyPlanPreview>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/policy-plan?day=${day}`
  )
}

export async function runDailyPolicy(
  tournamentId: number,
  versionId: number,
  day: string
): Promise<PolicyRunResponse> {
  return fetchJson<PolicyRunResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/run-policy?day=${day}`,
    { method: 'POST' }
  )
}

export interface FullPolicyDayResult {
  day: string
  assigned: number
  failed: number
  duration_ms: number | null
  batches: Array<{ name: string; attempted: number; assigned: number; failed_count: number }>
}

export interface FullPolicyRunResponse {
  total_assigned: number
  total_failed: number
  duration_ms: number | null
  day_results: FullPolicyDayResult[]
  input_hash?: string | null
  output_hash?: string | null
  invariant_ok?: boolean | null
  invariant_violations?: Array<{
    code: string
    message: string
    event_id?: number | null
    match_id?: number | null
    team_id?: number | null
    context?: Record<string, unknown> | null
  }> | null
  invariant_stats?: {
    teams_over_cap: number
    fairness_violations: number
    unresolved_scheduled: number
    consolation_partial: number
  } | null
  policy_run_id?: number | null
  failed_matches?: Array<{
    match_id: number
    match_code: string
    event_name: string
    round_label: string
    reason: string
  }> | null
}

export async function runFullPolicy(
  tournamentId: number,
  versionId: number,
  force: boolean = false
): Promise<FullPolicyRunResponse> {
  const qs = force ? '?force=true' : ''
  return fetchJson<FullPolicyRunResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/run-full-policy${qs}`,
    { method: 'POST' }
  )
}

// ── Policy Run Snapshots ───────────────────────────────────────────────

export interface PolicyRunSummary {
  id: number
  tournament_id: number
  schedule_version_id: number
  day_date: string | null
  policy_version: string
  created_at: string
  input_hash: string
  output_hash: string
  ok: boolean
  total_assigned: number
  total_failed: number
  duration_ms: number
}

export interface PolicyRunDetail extends PolicyRunSummary {
  snapshot_json?: Record<string, unknown> | null
  invariant_report?: Record<string, unknown> | null
}

export interface PolicyRunDiffResponse {
  run_a: PolicyRunSummary
  run_b: PolicyRunSummary
  hash_changed: boolean
  assignment_delta: {
    run_a_assigned: number
    run_b_assigned: number
    delta: number
  }
  changed_batches: Array<{
    label: string
    run_a_count: number
    run_b_count: number
    delta: number
  }>
}

export async function listPolicyRuns(
  tournamentId: number,
  versionId: number,
  day?: string
): Promise<PolicyRunSummary[]> {
  const params = day ? `?day=${day}` : ''
  return fetchJson<PolicyRunSummary[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/policy-runs${params}`
  )
}

export async function getPolicyRun(
  tournamentId: number,
  versionId: number,
  runId: number
): Promise<PolicyRunDetail> {
  return fetchJson<PolicyRunDetail>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/policy-runs/${runId}`
  )
}

export async function diffPolicyRuns(
  tournamentId: number,
  versionId: number,
  runIdA: number,
  runIdB: number
): Promise<PolicyRunDiffResponse> {
  return fetchJson<PolicyRunDiffResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/policy-runs/diff?run_id_a=${runIdA}&run_id_b=${runIdB}`
  )
}

export async function replayPolicyRun(
  tournamentId: number,
  versionId: number,
  runId: number
): Promise<{
  deterministic: boolean
  original_output_hash: string
  replay_output_hash: string
  invariant_ok: boolean
  replay_run_id: number
  total_assigned: number
}> {
  return fetchJson(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/policy-runs/${runId}/replay`,
    { method: 'POST' }
  )
}

// ── Quality Report ──────────────────────────────────────────────────────

export interface QualityCheckResult {
  name: string
  passed: boolean
  summary: string
  details: string[]
  detail_count: number
}

export interface QualityReportStats {
  total_matches: number
  total_slots: number
  assigned: number
  unassigned: number
  utilization_pct: number
  matches_per_day: Record<string, number>
  matches_per_event: Record<string, { total: number; assigned: number }>
}

export interface QualityReport {
  version_id: number
  overall_passed: boolean
  checks: QualityCheckResult[]
  stats: QualityReportStats
}

export async function getQualityReport(
  tournamentId: number,
  versionId: number
): Promise<QualityReport> {
  return fetchJson<QualityReport>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/quality-report`
  )
}

// ── Seeded Team Import ─────────────────────────────────────────────────

export interface SeededImportRejectedRow {
  line: number
  text: string
  reason: string
}

export interface SeededImportResponse {
  imported_count: number
  updated_count: number
  total_seeds: number
  rejected_rows: SeededImportRejectedRow[]
  warnings: string[]
}

export interface CombinedTeamImportResponse {
  imported_count: number
  updated_count: number
  total_rows: number
  events_touched: number
  towel_rows_imported: number
  towel_rows_matched: number
  rejected_rows: SeededImportRejectedRow[]
  warnings: string[]
}

export async function importSeededTeams(
  tournamentId: number,
  eventId: number,
  text: string
): Promise<SeededImportResponse> {
  return fetchJson<SeededImportResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/events/${eventId}/teams/import-seeded`,
    {
      method: 'POST',
      body: JSON.stringify({ format: 'sectioned_text', text }),
    }
  )
}

export async function importCombinedTeams(
  tournamentId: number,
  text: string
): Promise<CombinedTeamImportResponse> {
  return fetchJson<CombinedTeamImportResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/teams/import-combined`,
    {
      method: 'POST',
      body: JSON.stringify({ text }),
    }
  )
}

export interface TeamListItem {
  id: number
  event_id: number
  name: string
  seed: number | null
  rating: number | null
  avoid_group: string | null
  display_name: string | null
  created_at: string
  wf_group_index: number | null
  p1_cell: string | null
  p1_email: string | null
  p2_cell: string | null
  p2_email: string | null
}

export async function getEventTeams(
  eventId: number
): Promise<TeamListItem[]> {
  return fetchJson<TeamListItem[]>(
    `${API_BASE_URL}/events/${eventId}/teams`
  )
}

// ── Schedule Locks ────────────────────────────────────────────────────

export async function getLocks(
  tournamentId: number,
  versionId: number
): Promise<LocksResponse> {
  return fetchJson<LocksResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks`
  )
}

export async function createMatchLock(
  tournamentId: number,
  versionId: number,
  matchId: number,
  slotId: number
): Promise<{ id: number; match_id: number; slot_id: number; created_at: string }> {
  return fetchJson(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks/match`,
    { method: 'POST', body: JSON.stringify({ match_id: matchId, slot_id: slotId }) }
  )
}

export async function deleteMatchLock(
  tournamentId: number,
  versionId: number,
  matchId: number
): Promise<void> {
  const token = getAuthToken()
  const res = await fetch(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks/match/${matchId}`,
    {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    }
  )
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `Delete match lock failed: ${res.status}`)
  }
}

export async function createSlotLock(
  tournamentId: number,
  versionId: number,
  slotId: number,
  status: 'BLOCKED' | 'OPEN' = 'BLOCKED'
): Promise<{ id: number; slot_id: number; status: string; created_at: string }> {
  return fetchJson(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks/slot`,
    { method: 'POST', body: JSON.stringify({ slot_id: slotId, status }) }
  )
}

export async function deleteSlotLock(
  tournamentId: number,
  versionId: number,
  slotId: number
): Promise<void> {
  const token = getAuthToken()
  const res = await fetch(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks/slot/${slotId}`,
    {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    }
  )
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `Delete slot lock failed: ${res.status}`)
  }
}

// ── Public API (read-only, no auth) ───────────────────────────────────

export interface PublicMatchBox {
  match_id: number
  match_number: number
  court_label: string | null
  start_time_local: string | null
  status: 'UNSCHEDULED' | 'SCHEDULED' | 'IN_PROGRESS' | 'FINAL'
  score_display: string | null
  top_line: string
  line1: string
  line2: string
  notes: string | null
  winner_team_id: number | null
  team_a_id: number | null
  team_b_id: number | null
}

export interface PublicWaterfallRow {
  loser_box: PublicMatchBox | null
  center_box: PublicMatchBox
  winner_box: PublicMatchBox | null
  winner_dest: string | null
  loser_dest: string | null
  r2_winner_team_name: string | null
  r2_loser_team_name: string | null
  /** Populated when WF R2 winner-bracket match is FINAL (Division I vs II names). */
  r2_winner_bracket_winner_name?: string | null
  r2_winner_bracket_loser_name?: string | null
  /** Populated when WF R2 loser-bracket match is FINAL (Division III vs IV names). */
  r2_loser_bracket_winner_name?: string | null
  r2_loser_bracket_loser_name?: string | null
}

export interface PublicWaterfallResponse {
  tournament_name: string
  event_name: string
  rows: PublicWaterfallRow[]
  division_type: 'bracket' | 'roundrobin'
  show_court_info: boolean
}

export interface DivisionItem {
  code: string
  label: string
}

export interface PublicEventItem {
  event_id: number
  name: string
  category: string
  team_count: number
  has_waterfall: boolean
  has_round_robin: boolean
  divisions: DivisionItem[]
  round_robin_divisions?: DivisionItem[]
}

export interface PublicDrawsListResponse {
  tournament_name: string
  events: PublicEventItem[]
}

export async function getPublicDrawsList(
  tournamentId: number
): Promise<PublicDrawsListResponse> {
  return fetchJson<PublicDrawsListResponse>(
    `${API_BASE_URL}/public/tournaments/${tournamentId}/draws`
  )
}

export async function getPublicWaterfall(
  tournamentId: number,
  eventId: number,
  versionId?: number
): Promise<PublicWaterfallResponse> {
  const qs = versionId != null ? `?version_id=${versionId}` : ''
  return fetchJson<PublicWaterfallResponse>(
    `${API_BASE_URL}/public/tournaments/${tournamentId}/events/${eventId}/waterfall${qs}`
  )
}

// ── Bracket types ──────────────────────────────────────────────────────

export interface BracketMatchBox {
  match_id: number
  match_code: string
  match_type: string
  round_index: number
  sequence_in_round: number
  top_line: string
  line1: string
  line2: string
  status: string
  score_display: string | null
  court_label: string | null
  day_display: string | null
  time_display: string | null
  source_match_a_id: number | null
  source_match_b_id: number | null
}

export interface BracketResponse {
  tournament_name: string
  event_name: string
  division_label: string
  division_code: string
  main_matches: BracketMatchBox[]
  consolation_matches: BracketMatchBox[]
  show_court_info: boolean
}

export async function getPublicBracket(
  tournamentId: number,
  eventId: number,
  divisionCode: string,
  versionId?: number
): Promise<BracketResponse> {
  const qs = versionId != null ? `?version_id=${versionId}` : ''
  return fetchJson<BracketResponse>(
    `${API_BASE_URL}/public/tournaments/${tournamentId}/events/${eventId}/bracket/${divisionCode}${qs}`
  )
}

// ── Round Robin types ─────────────────────────────────────────────────

export interface RRMatchBox {
  match_id: number
  match_code: string
  round_index: number
  line1: string
  line2: string
  status: string
  score_display: string | null
  court_label: string | null
  day_display: string | null
  time_display: string | null
  winner_name: string | null
}

export interface RRPool {
  pool_code: string
  pool_label: string
  matches: RRMatchBox[]
}

export interface RRStandingsRow {
  team_id: number
  team_display: string
  wins: number
  losses: number
  sets_won: number
  sets_lost: number
  games_won: number
  games_lost: number
  played: number
}

export interface RRPoolStandings {
  pool_code: string
  pool_label: string
  rows: RRStandingsRow[]
}

export interface RoundRobinResponse {
  tournament_name: string
  event_name: string
  pools: RRPool[]
  standings: RRPoolStandings[]
  tiebreaker_note: string
  show_court_info: boolean
}

export async function getPublicRoundRobin(
  tournamentId: number,
  eventId: number,
  versionId?: number | null
): Promise<RoundRobinResponse> {
  const qs =
    versionId != null && Number.isFinite(versionId)
      ? `?version_id=${encodeURIComponent(String(versionId))}`
      : ''
  return fetchJson<RoundRobinResponse>(
    `${API_BASE_URL}/public/tournaments/${tournamentId}/events/${eventId}/roundrobin${qs}`
  )
}

// ── Public Schedule types ────────────────────────────────────────────

export interface ScheduleMatchItem {
  match_id: number
  match_number: number
  match_code: string
  stage: string
  event_id: number
  event_name: string
  division_name: string | null
  day_index: number
  day_label: string
  scheduled_time: string | null
  sort_time: string | null
  court_name: string | null
  status: string
  team1_display: string
  team2_display: string
  team1_full_name: string
  team2_full_name: string
  score_display: string | null
  winner_team_id: number | null
  team_a_id: number | null
  team_b_id: number | null
}

export interface ScheduleEventOption {
  event_id: number
  event_name: string
}

export interface ScheduleDayOption {
  day_index: number
  label: string
}

export interface PublicScheduleResponse {
  status: string
  tournament_name: string
  published_version_id: number
  matches: ScheduleMatchItem[]
  events: ScheduleEventOption[]
  divisions: string[]
  days: ScheduleDayOption[]
  show_court_info: boolean
}

export async function getPublicSchedule(
  tournamentId: number,
  filters?: {
    event_id?: number
    division?: string
    day?: number
    search?: string
  }
): Promise<PublicScheduleResponse> {
  const params = new URLSearchParams()
  if (filters?.event_id != null) params.set('event_id', String(filters.event_id))
  if (filters?.division) params.set('division', filters.division)
  if (filters?.day != null) params.set('day', String(filters.day))
  if (filters?.search) params.set('search', filters.search)
  const qs = params.toString()
  const url = `${API_BASE_URL}/public/tournaments/${tournamentId}/schedule${qs ? '?' + qs : ''}`
  return fetchJson<PublicScheduleResponse>(url)
}

// ── Desk Runtime Console ─────────────────────────────────────────────

export interface DeskMatchItem {
  match_id: number
  match_number: number
  match_code: string
  stage: string
  event_id: number
  event_name: string
  division_name: string | null
  day_index: number
  day_label: string
  scheduled_time: string | null
  sort_time: string | null
  court_name: string | null
  status: string
  team1_id: number | null
  team1_display: string
  team2_id: number | null
  team2_display: string
  score_display: string | null
  source_match_a_id: number | null
  source_match_b_id: number | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  winner_display: string | null
  winner_team_id?: number | null
  duration_minutes?: number | null
  team1_defaulted?: boolean | null
  team2_defaulted?: boolean | null
  team1_notes?: string | null
  team2_notes?: string | null
  slot_id: number | null
  assignment_id: number | null
  court_number: number | null
  day_date: string | null
}

export interface BoardCourtSlot {
  court_name: string
  now_playing: DeskMatchItem | null
  up_next: DeskMatchItem | null
  on_deck: DeskMatchItem | null
}

export interface SnapshotSlot {
  slot_id: number
  day_date: string
  start_time: string
  end_time: string
  court_number: number
  court_label: string
  block_minutes: number
  is_active: boolean
  assigned_match_id: number | null
}

export interface PlayerCheckInState {
  player_id: number | null
  player_display: string
  checked_in: boolean
  checked_in_at: string | null
  towel_color: string | null
  report_url: string | null
}

export interface MatchCheckInSideState {
  side: 'A' | 'B'
  team_id: number | null
  team_display: string
  team_checked_in: boolean
  team_checked_in_at: string | null
  show_towels: boolean
  players: PlayerCheckInState[]
  players_checked_in: number
  players_total: number
  side_ready: boolean
  ready_at: string | null
}

export interface CheckInMatchItem {
  match_id: number
  match_number: number
  match_code: string
  event_id?: number | null
  event_name: string
  day_label: string
  scheduled_time: string | null
  sort_time: string | null
  slot_id: number | null
  team1_notes?: string | null
  team2_notes?: string | null
  side_a: MatchCheckInSideState
  side_b: MatchCheckInSideState
  match_ready: boolean
  ready_at: string | null
  checkin_enabled: boolean
}

export interface ReadyQueueItem {
  match_id: number
  match_number: number
  match_code: string
  event_name: string
  day_label: string
  scheduled_time: string | null
  ready_at: string | null
  team1_display: string
  team2_display: string
}

export interface AvailableCourtSlot {
  slot_id: number
  court_name: string
  day_label: string
  scheduled_time: string | null
  currently_assigned_match_id: number | null
}

export interface CheckInSlotOption {
  slot_key: string
  label: string
  day_label: string
  scheduled_time: string | null
  slot_ids: number[]
}

export interface DeskSnapshotResponse {
  tournament_id: number
  tournament_name: string
  tournament_timezone: string | null
  version_id: number
  version_status: string
  courts: string[]
  matches: DeskMatchItem[]
  now_playing_by_court: Record<string, DeskMatchItem>
  up_next_by_court: Record<string, DeskMatchItem>
  on_deck_by_court: Record<string, DeskMatchItem>
  board_by_court: BoardCourtSlot[]
  slots: SnapshotSlot[]
  management_mode: 'court_management' | 'checkin_management'
  checkin_matches: CheckInMatchItem[]
  ready_queue: ReadyQueueItem[]
  available_courts: string[]
  available_slots: AvailableCourtSlot[]
  checkin_slot_options: CheckInSlotOption[]
  checkin_slot_rows: Record<string, CheckInMatchItem[]>
}

export interface TemporaryPlayerLookupItem {
  id: number
  player_id: number | null
  matched: boolean
  source_name: string
  source_phone: string | null
  source_email: string | null
  towel_color: string
  report_url: string | null
}

export interface TemporaryPlayerLookupListResponse {
  tournament_id: number
  items: TemporaryPlayerLookupItem[]
}

export interface TemporaryPlayerLookupImportResponse {
  tournament_id: number
  imported_count: number
  matched_count: number
  items: TemporaryPlayerLookupItem[]
}

export interface TemporaryPlayerLookupClearResponse {
  tournament_id: number
  deleted_count: number
}

export interface TemporaryPlayerLookupUpsert {
  source_name: string
  towel_color: string
  report_url?: string | null
}

export interface DeskManagementModeResponse {
  tournament_id: number
  version_id: number
  management_mode: 'court_management' | 'checkin_management'
}

export interface ReadyQueueResponse {
  tournament_id: number
  version_id: number
  management_mode: 'court_management' | 'checkin_management'
  checkin_matches: CheckInMatchItem[]
  ready_queue: ReadyQueueItem[]
  available_courts: string[]
  available_slots: AvailableCourtSlot[]
  checkin_slot_options: CheckInSlotOption[]
  checkin_slot_rows: Record<string, CheckInMatchItem[]>
}

export interface WorkingDraftResponse {
  version_id: number
  version_number: number
  status: string
  notes: string | null
  created: boolean
}

export interface DownstreamUpdate {
  match_id: number
  slot_filled: string
  team_id: number
  team_name: string
  role: string
  next_day: string | null
  next_time: string | null
  next_court: string | null
  opponent: string | null
}

export interface AdvancementWarning {
  match_id: number
  reason: string
  detail: string | null
}

export interface FinalizeResponse {
  match: DeskMatchItem
  downstream_updates: DownstreamUpdate[]
  warnings: AdvancementWarning[]
  auto_started: DeskMatchItem | null
  sms_preview?: FinalizeSmsPreview | null
}

export interface FinalizeSmsPreviewRecipient {
  team_id: number | null
  team_name: string | null
  player_id: number | null
  player_name: string | null
  phone: string
  message: string
}

export interface FinalizeSmsPreview {
  message_type: string
  total_messages: number
  recipients: FinalizeSmsPreviewRecipient[]
  teams_with_next_match: number
  teams_without_phone: number
  blocked_test_mode: number
  blocked_consent: number
  deduped: number
  disabled_reason: string | null
}

export interface FinalizeSmsSendResult {
  phone: string
  team_id: number | null
  team_name: string | null
  player_id: number | null
  player_name: string | null
  status: string
  error: string | null
}

export interface FinalizeSmsSendResponse {
  total: number
  sent: number
  failed: number
  skipped_no_phone: number
  skipped_consent: number
  skipped_dedupe: number
  skipped_test_mode: number
  message_type: string
  results: FinalizeSmsSendResult[]
}

export async function getDeskSnapshot(
  tournamentId: number,
  versionId?: number
): Promise<DeskSnapshotResponse> {
  const qs = versionId != null ? `?version_id=${versionId}` : ''
  return fetchJson<DeskSnapshotResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/snapshot${qs}`
  )
}

export async function createWorkingDraft(
  tournamentId: number
): Promise<WorkingDraftResponse> {
  return fetchJson<WorkingDraftResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/working-draft`,
    { method: 'POST' }
  )
}

export async function deskFinalizeMatch(
  tournamentId: number,
  matchId: number,
  payload: {
    version_id: number
    score?: string
    winner_team_id: number
    is_default?: boolean
    is_retired?: boolean
    send_automation_texts?: boolean
    include_sms_preview?: boolean
  }
): Promise<FinalizeResponse> {
  return fetchJson<FinalizeResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/finalize`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deskSendFinalizeSms(
  tournamentId: number,
  matchId: number,
  payload: { version_id: number }
): Promise<FinalizeSmsSendResponse> {
  return fetchJson<FinalizeSmsSendResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/finalize-sms`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function deskCorrectMatch(
  tournamentId: number,
  matchId: number,
  payload: { version_id: number; score: string; winner_team_id: number }
): Promise<FinalizeResponse> {
  return fetchJson<FinalizeResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/correct`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deskRepairAdvancement(
  tournamentId: number,
  versionId: number
): Promise<{ matches_processed: number; teams_advanced: number; unknown_before: number; unknown_after: number }> {
  return fetchJson(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/repair-advancement?version_id=${versionId}`,
    { method: 'POST' }
  )
}

export async function deskSetMatchStatus(
  tournamentId: number,
  matchId: number,
  payload: { version_id: number; status: string; allow_reopen_final?: boolean; reset_started_at?: boolean }
): Promise<{ match_id: number; status: string }> {
  return fetchJson<{ match_id: number; status: string }>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/status`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function getDeskManagementMode(
  tournamentId: number,
  versionId: number
): Promise<DeskManagementModeResponse> {
  return fetchJson<DeskManagementModeResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/management-mode?version_id=${versionId}`
  )
}

export async function setDeskManagementMode(
  tournamentId: number,
  payload: { version_id: number; management_mode: 'court_management' | 'checkin_management' }
): Promise<DeskManagementModeResponse> {
  return fetchJson<DeskManagementModeResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/management-mode`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deskCheckInTeam(
  tournamentId: number,
  matchId: number,
  payload: { version_id: number; side: 'A' | 'B'; checked_in: boolean }
): Promise<ReadyQueueResponse> {
  return fetchJson<ReadyQueueResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/checkin/team`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deskCheckInPlayer(
  tournamentId: number,
  matchId: number,
  payload: { version_id: number; side: 'A' | 'B'; player_id: number; checked_in: boolean }
): Promise<ReadyQueueResponse> {
  return fetchJson<ReadyQueueResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/checkin/player`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function getDeskCheckInQueue(
  tournamentId: number,
  versionId: number
): Promise<ReadyQueueResponse> {
  return fetchJson<ReadyQueueResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/checkin/queue?version_id=${versionId}`
  )
}

export async function assignReadyMatchToSlot(
  tournamentId: number,
  payload: { version_id: number; match_id: number; slot_id: number }
): Promise<DeskSnapshotResponse> {
  return fetchJson<DeskSnapshotResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/checkin/assign`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function getTemporaryPlayerLookups(
  tournamentId: number
): Promise<TemporaryPlayerLookupListResponse> {
  return fetchJson<TemporaryPlayerLookupListResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/temporary-player-lookups`
  )
}

export async function importTemporaryPlayerLookups(
  tournamentId: number,
  rawText: string
): Promise<TemporaryPlayerLookupImportResponse> {
  return fetchJson<TemporaryPlayerLookupImportResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/temporary-player-lookups/import`,
    { method: 'POST', body: JSON.stringify({ raw_text: rawText }) }
  )
}

export async function createTemporaryPlayerLookup(
  tournamentId: number,
  payload: TemporaryPlayerLookupUpsert
): Promise<TemporaryPlayerLookupItem> {
  return fetchJson<TemporaryPlayerLookupItem>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/temporary-player-lookups`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function updateTemporaryPlayerLookup(
  tournamentId: number,
  lookupId: number,
  payload: TemporaryPlayerLookupUpsert
): Promise<TemporaryPlayerLookupItem> {
  return fetchJson<TemporaryPlayerLookupItem>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/temporary-player-lookups/${lookupId}`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deleteTemporaryPlayerLookup(
  tournamentId: number,
  lookupId: number
): Promise<void> {
  return fetchJson<void>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/temporary-player-lookups/${lookupId}`,
    { method: 'DELETE' }
  )
}

export async function clearTemporaryPlayerLookups(
  tournamentId: number
): Promise<TemporaryPlayerLookupClearResponse> {
  return fetchJson<TemporaryPlayerLookupClearResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/temporary-player-lookups`,
    { method: 'DELETE' }
  )
}

// ── Impact ──────────────────────────────────────────────────────────────

export interface ImpactTarget {
  target_match_number: number | null
  target_match_id: number | null
  target_slot: string | null
  target_current_team_display: string | null
  target_current_team_id: number | null
  target_opponent_display: string | null
  target_status: string | null
  target_stage: string | null
  target_event_name: string | null
  target_division_name: string | null
  target_day_label: string | null
  target_time: string | null
  target_court: string | null
  waiting_on_match_id: number | null
  waiting_on_match_number: number | null
  waiting_on_role: string | null
  waiting_on_status: string | null
  waiting_on_day_label: string | null
  waiting_on_time: string | null
  waiting_on_court: string | null
  blocked_reason: string | null
  advanced: boolean | null
}

export interface MatchImpactItem {
  match_id: number
  match_number: number
  match_code: string
  stage: string
  status: string
  team1_display: string
  team2_display: string
  team1_id: number | null
  team2_id: number | null
  winner_team_id: number | null
  winner_target: ImpactTarget | null
  loser_target: ImpactTarget | null
  winner_terminal_label: string | null
  loser_terminal_label: string | null
}

export interface ImpactResponse {
  version_id: number
  impacts: MatchImpactItem[]
}

export async function getDeskImpact(
  tournamentId: number,
  versionId: number,
  matchId?: number
): Promise<ImpactResponse> {
  let qs = `?version_id=${versionId}`
  if (matchId != null) qs += `&match_id=${matchId}`
  return fetchJson<ImpactResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/impact${qs}`
  )
}

// ── Conflict check ──────────────────────────────────────────────────────

export interface ConflictItem {
  code: string
  severity: string
  team_display: string
  message: string
  details: Record<string, any>
}

export interface ConflictCheckResponse {
  conflicts: ConflictItem[]
}

export async function checkDeskConflicts(
  tournamentId: number,
  payload: { version_id: number; action_type: string; match_id: number; target_slot_id?: number }
): Promise<ConflictCheckResponse> {
  return fetchJson<ConflictCheckResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/conflicts/check`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

// ── Match Move / Swap ───────────────────────────────────────────────────

export interface MoveMatchResponse {
  success: boolean
  match: DeskMatchItem
  warnings: string[]
}

export interface SwapMatchesResponse {
  success: boolean
  match_a: DeskMatchItem
  match_b: DeskMatchItem
  warnings: string[]
}

export async function deskMoveMatch(
  tournamentId: number,
  matchId: number,
  payload: { version_id: number; target_slot_id: number }
): Promise<MoveMatchResponse> {
  return fetchJson<MoveMatchResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/move`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deskSwapMatches(
  tournamentId: number,
  payload: { version_id: number; match_a_id: number; match_b_id: number }
): Promise<SwapMatchesResponse> {
  return fetchJson<SwapMatchesResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/swap`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

// ── Add Slot / Court ────────────────────────────────────────────────────

export interface AddSlotItem {
  slot_id: number
  day_date: string
  start_time: string
  end_time: string
  court_number: number
  court_label: string
  block_minutes: number
}

export interface AddSlotResponse {
  success: boolean
  created_slots: AddSlotItem[]
}

export interface DeleteSlotItem {
  slot_id: number
  day_date: string
  start_time: string
  court_number: number
  court_label: string
}

export interface DeleteSlotBlockedItem {
  slot_id: number
  day_date: string
  start_time: string
  court_number: number
  court_label: string
  match_id: number | null
  match_code: string | null
}

export interface DeleteSlotResponse {
  success: boolean
  deleted_slots: DeleteSlotItem[]
  blocked_slots: DeleteSlotBlockedItem[]
}

export interface AddCourtResponse {
  success: boolean
  court_label: string
  court_number: number
  courts: string[]
  created_slots: number
}

export interface UpdateCourtResponse {
  success: boolean
  old_court_label: string
  new_court_label: string
  court_number: number
  updated_slots: number
}

export interface DeleteCourtResponse {
  success: boolean
  court_label: string
  court_number: number
  removed_slots: number
  remaining_courts: string[]
}

export interface FillCourtSlotsResponse {
  success: boolean
  court_label: string
  court_number: number
  created_slots: number
}

export interface RemapCourtsResponse {
  success: boolean
  version_id: number
  remapped_slots: number
  remapped_states: number
  mapping: Record<string, number>
}

export async function deskAddSlots(
  tournamentId: number,
  payload: { version_id: number; day_date: string; start_time: string; end_time: string; court_numbers: number[] }
): Promise<AddSlotResponse> {
  return fetchJson<AddSlotResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/slots`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function deskDeleteSlots(
  tournamentId: number,
  payload: { version_id: number; day_date: string; start_time: string; court_numbers: number[] }
): Promise<DeleteSlotResponse> {
  return fetchJson<DeleteSlotResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/slots/delete`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function deskAddCourt(
  tournamentId: number,
  payload: { version_id: number; court_label: string; create_matching_slots?: boolean }
): Promise<AddCourtResponse> {
  return fetchJson<AddCourtResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function deskUpdateCourt(
  tournamentId: number,
  courtLabel: string,
  payload: { version_id: number; new_court_label: string }
): Promise<UpdateCourtResponse> {
  return fetchJson<UpdateCourtResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts/${encodeURIComponent(courtLabel)}`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deskDeleteCourt(
  tournamentId: number,
  courtLabel: string,
  payload: { version_id: number; delete_matching_slots?: boolean }
): Promise<DeleteCourtResponse> {
  return fetchJson<DeleteCourtResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts/${encodeURIComponent(courtLabel)}`,
    { method: 'DELETE', body: JSON.stringify(payload) }
  )
}

export async function deskFillCourtSlots(
  tournamentId: number,
  courtLabel: string,
  payload: { version_id: number }
): Promise<FillCourtSlotsResponse> {
  return fetchJson<FillCourtSlotsResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts/${encodeURIComponent(courtLabel)}/slots/fill`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function deskRemapCourts(
  tournamentId: number,
  payload: { version_id: number; mapping: Record<string, number> }
): Promise<RemapCourtsResponse> {
  return fetchJson<RemapCourtsResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts/remap`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

// ── Bulk Status ─────────────────────────────────────────────────────────

export interface BulkStatusResponse {
  updated_count: number
  updated_match_numbers: number[]
}

export async function bulkPauseInProgress(
  tournamentId: number,
  versionId: number
): Promise<BulkStatusResponse> {
  return fetchJson<BulkStatusResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/bulk/pause-in-progress`,
    { method: 'POST', body: JSON.stringify({ version_id: versionId }) }
  )
}

export async function bulkDelayAfter(
  tournamentId: number,
  payload: { version_id: number; after_time: string; day_index?: number }
): Promise<BulkStatusResponse> {
  return fetchJson<BulkStatusResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/bulk/delay-after`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function bulkResumePaused(
  tournamentId: number,
  versionId: number
): Promise<BulkStatusResponse> {
  return fetchJson<BulkStatusResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/bulk/resume-paused`,
    { method: 'POST', body: JSON.stringify({ version_id: versionId }) }
  )
}

export async function bulkUndelay(
  tournamentId: number,
  versionId: number
): Promise<BulkStatusResponse> {
  return fetchJson<BulkStatusResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/bulk/undelay`,
    { method: 'POST', body: JSON.stringify({ version_id: versionId }) }
  )
}

// ── Court State ─────────────────────────────────────────────────────────

export interface CourtStateItem {
  court_label: string
  is_closed: boolean
  note: string | null
  updated_at: string | null
}

export async function getCourtStates(
  tournamentId: number
): Promise<CourtStateItem[]> {
  return fetchJson<CourtStateItem[]>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts/state`
  )
}

export async function patchCourtState(
  tournamentId: number,
  courtLabel: string,
  payload: { is_closed?: boolean; note?: string }
): Promise<CourtStateItem> {
  return fetchJson<CourtStateItem>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts/${encodeURIComponent(courtLabel)}/state`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

// ── Standings ───────────────────────────────────────────────────────────

export interface StandingsRow {
  team_id: number
  team_display: string
  rank: number
  wins: number
  losses: number
  sets_won: number
  sets_lost: number
  set_diff: number
  games_won: number
  games_lost: number
  game_diff: number
  point_diff: number | null
  played: number
  rank_explanation: string
}

export interface StandingsEvent {
  event_id: number
  event_name: string
  division_name: string | null
  rows: StandingsRow[]
  tiebreak_notes: string
  warnings: { match_number: number; reason: string }[]
}

export interface StandingsResponse {
  tournament_id: number
  version_id: number
  events: StandingsEvent[]
}

export async function getDeskStandings(
  tournamentId: number,
  versionId: number,
  eventId?: number
): Promise<StandingsResponse> {
  let qs = `?version_id=${versionId}`
  if (eventId != null) qs += `&event_id=${eventId}`
  return fetchJson<StandingsResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/standings${qs}`
  )
}

// ── Pool Projection ─────────────────────────────────────────────────────

export interface ProjectedTeam {
  team_id: number
  team_display: string
  seed_position: number
  bucket: string
  status: 'confirmed' | 'projected' | 'pending'
  wf_wins: number
  wf_losses: number
  wf_game_diff: number
  wf_games_lost: number
  wf2_game_diff: number
  wf2_games_lost: number
  placement_reason: string
}

export interface ProjectedPool {
  pool_label: string
  pool_display: string
  teams: ProjectedTeam[]
}

export interface EventProjection {
  event_id: number
  event_name: string
  wf_complete: boolean
  total_wf_matches: number
  finalized_wf_matches: number
  pools: ProjectedPool[]
  unresolved_teams: { team_id: number; team_display: string }[]
}

export interface PoolProjectionResponse {
  tournament_id: number
  version_id: number
  events: EventProjection[]
}

export interface PoolPlacementResponse {
  success: boolean
  updated_matches: number
  assignments: { match_id: number; match_code: string; team_a_id: number; team_b_id: number }[]
}

export async function getPoolProjection(
  tournamentId: number,
  versionId: number,
  eventId?: number
): Promise<PoolProjectionResponse> {
  let qs = `?version_id=${versionId}`
  if (eventId != null) qs += `&event_id=${eventId}`
  return fetchJson<PoolProjectionResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/pool-projection${qs}`
  )
}

export async function confirmPoolPlacement(
  tournamentId: number,
  payload: { version_id: number; event_id: number; pools: { pool_label: string; team_ids: number[] }[] }
): Promise<PoolPlacementResponse> {
  return fetchJson<PoolPlacementResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/pool-placement`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export interface RepairPlacementDayResponse {
  success: boolean
  moved: number
  needs_slot: number
  cleared_locks: number
  created: number
  messages: string[]
}

export async function repairPlacementDay(
  tournamentId: number,
  payload: { version_id: number; event_id?: number | null }
): Promise<RepairPlacementDayResponse> {
  return fetchJson<RepairPlacementDayResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/repair-placement-day`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

// ── Reschedule ──────────────────────────────────────────────────────────

export interface FormatFeasibilityItem {
  format: string
  duration: number
  label: string
  fits: boolean
  utilization: number
}

export interface FeasibilityResponse {
  affected_count: number
  formats: FormatFeasibilityItem[]
}

export interface ReschedulePreviewRequest {
  version_id: number
  mode: 'PARTIAL_DAY' | 'FULL_WASHOUT' | 'COURT_LOSS'
  affected_day: string
  unavailable_from?: string
  available_from?: string
  unavailable_courts?: number[]
  target_days?: string[]
  extend_day_end?: string
  add_time_slots?: boolean
  block_minutes?: number
  scoring_format?: string
}

export interface ProposedMoveItem {
  match_id: number
  match_number: number
  match_code: string
  event_name: string
  stage: string
  old_slot_id: number | null
  old_court: string | null
  old_time: string | null
  old_day: string | null
  new_slot_id: number
  new_court: string
  new_time: string
  new_day: string
}

export interface UnplaceableItem {
  match_id: number
  match_number: number
  match_code: string
  event_name: string
  stage: string
  reason: string
}

export interface ReschedulePreviewResponse {
  proposed_moves: ProposedMoveItem[]
  unplaceable: UnplaceableItem[]
  new_slots_created: number
  stats: { total_affected: number; total_moved: number; total_unplaceable: number; total_kept: number }
  format_applied: string | null
  duration_updates: Record<string, number> | null
}

export interface RescheduleApplyResponse {
  updated_matches: number
  applied_moves: number
}

export async function rescheduleFeasibility(
  tournamentId: number,
  payload: { version_id: number; mode: string; affected_day: string; target_days?: string[] }
): Promise<FeasibilityResponse> {
  return fetchJson<FeasibilityResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/reschedule/feasibility`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function reschedulePreview(
  tournamentId: number,
  payload: ReschedulePreviewRequest
): Promise<ReschedulePreviewResponse> {
  return fetchJson<ReschedulePreviewResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/reschedule/preview`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function rescheduleApply(
  tournamentId: number,
  payload: {
    version_id: number
    moves: { match_id: number; new_slot_id: number }[]
    duration_updates?: Record<string, number>
  }
): Promise<RescheduleApplyResponse> {
  return fetchJson<RescheduleApplyResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/reschedule/apply`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

// ── Rebuild Remaining Schedule ──────────────────────────────────────────

export interface RebuildDayConfig {
  date: string
  start_time: string
  end_time: string
  courts: number
  format: string
}

export interface RebuildRequest {
  version_id: number
  days: RebuildDayConfig[]
  drop_consolation: 'none' | 'finals' | 'all'
  day1_max_matches?: number
}

export interface RebuildMatchItem {
  match_id: number
  match_number: number
  match_code: string
  event_name: string
  stage: string
  team1: string
  team2: string
  status: string
  rank: number
  assigned_day: string | null
  assigned_time: string | null
}

export interface RebuildDaySummary {
  date: string
  slots: number
  courts: number
  format: string
  block_minutes: number
}

export interface RebuildPreviewResponse {
  remaining_matches: number
  in_progress_matches: number
  total_slots: number
  fits: boolean
  overflow: number
  matches: RebuildMatchItem[]
  per_day: RebuildDaySummary[]
  dropped_count: number
  day1_match_count: number
}

export interface RebuildApplyResponse {
  assigned: number
  unplaceable: number
  slots_created: number
  duration_updates: number
  dropped_count: number
}

export async function rebuildPreview(
  tournamentId: number,
  payload: RebuildRequest
): Promise<RebuildPreviewResponse> {
  return fetchJson<RebuildPreviewResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/rebuild/preview`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function rebuildApply(
  tournamentId: number,
  payload: RebuildRequest
): Promise<RebuildApplyResponse> {
  return fetchJson<RebuildApplyResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/rebuild/apply`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

// ── Desk Teams ──────────────────────────────────────────────────────────

export interface DeskTeamItem {
  team_id: number
  event_id: number
  event_name: string
  seed: number | null
  name: string
  display_name: string | null
  rating: number | null
  player1_cellphone: string | null
  player1_email: string | null
  player2_cellphone: string | null
  player2_email: string | null
  is_defaulted: boolean
  notes: string | null
}

export async function getDeskTeams(
  tournamentId: number
): Promise<DeskTeamItem[]> {
  return fetchJson<DeskTeamItem[]>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/teams`
  )
}

export interface MergeDuplicateTeamsResponse {
  groups_merged: number
  teams_removed: number
  matches_relinked: number
  checkins_relinked: number
  player_links_relinked: number
  avoid_edges_relinked: number
  sms_logs_relinked: number
}

export async function mergeDuplicateTeams(
  tournamentId: number
): Promise<MergeDuplicateTeamsResponse> {
  return fetchJson<MergeDuplicateTeamsResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/teams/merge-duplicates`,
    { method: 'POST' }
  )
}

export interface DefaultWeekendResponse {
  team_id: number
  team_name: string
  matches_defaulted: number
  match_ids: number[]
}

export async function defaultTeamWeekend(
  tournamentId: number,
  teamId: number,
  versionId: number
): Promise<DefaultWeekendResponse> {
  return fetchJson<DefaultWeekendResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/teams/${teamId}/default-weekend`,
    { method: 'POST', body: JSON.stringify({ version_id: versionId }) }
  )
}

export async function updateTeam(
  eventId: number,
  teamId: number,
  payload: {
    name?: string
    display_name?: string
    player1_cellphone?: string
    player1_email?: string
    player2_cellphone?: string
    player2_email?: string
    is_defaulted?: boolean
    notes?: string
  }
): Promise<unknown> {
  return fetchJson(
    `${API_BASE_URL}/events/${eventId}/teams/${teamId}`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

// ── SMS ─────────────────────────────────────────────────────────────────

export interface SmsStatusResponse {
  twilio_configured: boolean
  from_number: string | null
  tournament_has_settings: boolean
  total_teams: number
  teams_with_phones: number
}

export interface SmsSendResult {
  phone: string
  team_id: number | null
  team_name: string | null
  player_id: number | null
  player_name: string | null
  status: string
  error: string | null
}

export interface SmsSendRequest {
  message: string
  dedupe_key?: string
}

export interface SmsSendResponse {
  total: number
  sent: number
  failed: number
  skipped_no_phone: number
  skipped_consent: number
  skipped_dedupe: number
  skipped_test_mode: number
  message_type: string
  results: SmsSendResult[]
}

export interface SmsPreviewRecipient {
  team_id: number | null
  team_name: string | null
  player_id: number | null
  player_name: string | null
  phones: string[]
  message: string
}

export interface SmsPreviewResponse {
  total_teams: number
  total_messages: number
  teams_without_phone: number
  recipients: SmsPreviewRecipient[]
}

export interface SmsLogEntry {
  id: number
  tournament_id: number
  team_id: number | null
  phone_number: string
  message_body: string
  message_type: string
  twilio_sid: string | null
  status: string
  error_message: string | null
  trigger: string
  dedupe_key: string | null
  sent_at: string
}

export interface SmsSettingsResponse {
  tournament_id: number
  auto_first_match: boolean
  auto_post_match_next: boolean
  auto_on_deck: boolean
  auto_up_next: boolean
  auto_court_change: boolean
  auto_checkin_first_match: boolean
  auto_checkin_slot_checkin: boolean
  auto_checkin_post_match_next: boolean
  auto_checkin_court_assigned: boolean
  texts_enabled: boolean
  test_mode: boolean
  test_allowlist: string | null
  player_contacts_only: boolean
}

export interface SmsTemplateResponse {
  id: number
  tournament_id: number
  message_type: string
  template_body: string
  is_active: boolean
}

export interface SmsTimeslotRequest {
  message: string
  day_date: string
  start_time: string
  schedule_version_id: number
  dedupe_key?: string
}

export interface SmsPlayerLookupItem {
  player_id: number
  player_name: string
  phone_e164: string | null
  consent_status: string
}

export interface SmsPlayerSyncResponse {
  tournament_id: number
  players_created: number
  players_updated: number
  links_created: number
  links_updated: number
  links_removed: number
}

export interface SmsPlayerWipeResponse {
  tournament_id: number
  players_deleted: number
  teams_deleted: number
  links_deleted: number
  team_checkins_deleted: number
  player_checkins_deleted: number
  lookup_rows_deleted: number
  consent_events_deleted: number
  avoid_edges_deleted: number
  sms_logs_unlinked: number
  matches_cleared: number
}

export interface SmsMatchLookupItem {
  match_id: number
  match_code: string
  event_name: string
  team_a_name: string
  team_b_name: string
  runtime_status: string
  phase: 'upcoming' | 'completed'
  day_date: string | null
  start_time: string | null
  display_label: string
}

export interface SmsDivisionLookupItem {
  division_label: string
  match_count: number
  team_count: number
}

export interface SmsAutomationRunResponse {
  tournament_id: number
  version_id: number | null
  disabled: boolean
  no_active_version: boolean
  dry_run: boolean
  force_resend: boolean
  resend_run_key: string | null
  window_minutes: number
  timezone: string | null
  now_utc: string | null
  considered_teams: number
  eligible_teams: number
  outside_window: number
  sent: number
  deduped: number
  blocked_test_mode: number
  blocked_consent: number
  failed: number
  template_inactive: boolean
}

export interface SmsPhoneListMember {
  id: number
  raw_name: string | null
  phone_number: string
}

export interface SmsPhoneList {
  id: number
  tournament_id: number
  name: string
  member_count: number
  created_at: string
  updated_at: string
  members: SmsPhoneListMember[]
}

export interface SmsPhoneListImportRejectedRow {
  line: number
  text: string
  reason: string
}

export interface SmsPhoneListImportResponse {
  phone_list: SmsPhoneList
  imported_count: number
  rejected_rows: SmsPhoneListImportRejectedRow[]
}

export interface SmsRrAutomationRunResponse {
  tournament_id: number
  version_id: number | null
  event_id: number
  disabled: boolean
  no_active_version: boolean
  dry_run: boolean
  force_resend: boolean
  resend_run_key: string | null
  considered_teams: number
  eligible_teams: number
  missing_slot: number
  sent: number
  deduped: number
  blocked_test_mode: number
  blocked_consent: number
  failed: number
  template_inactive: boolean
}

export interface SmsRolloutMetricBucket {
  message_type: string
  trigger: string
  total: number
  sent: number
  failed: number
  blocked_test_mode: number
  blocked_consent: number
  queued_or_other: number
}

export interface SmsRolloutFailureItem {
  id: number
  sent_at: string
  phone_number: string
  message_type: string
  trigger: string
  status: string
  error_message: string | null
}

export interface SmsRolloutMetricsResponse {
  tournament_id: number
  lookback_hours: number
  window_start: string
  window_end: string
  total_logs: number
  sent: number
  failed: number
  blocked_test_mode: number
  blocked_consent: number
  queued_or_other: number
  distinct_phones: number
  opt_out_events: number
  opt_in_events: number
  by_message_type: SmsRolloutMetricBucket[]
  recent_failures: SmsRolloutFailureItem[]
}

export async function getSmsStatus(tournamentId: number): Promise<SmsStatusResponse> {
  return fetchJson<SmsStatusResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/status`
  )
}

export async function getSmsPlayers(
  tournamentId: number
): Promise<SmsPlayerLookupItem[]> {
  return fetchJson<SmsPlayerLookupItem[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/players`
  )
}

export async function syncSmsPlayerContacts(
  tournamentId: number
): Promise<SmsPlayerSyncResponse> {
  return fetchJson<SmsPlayerSyncResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/sync-player-contacts`,
    { method: 'POST' }
  )
}

export async function wipeSmsPlayers(
  tournamentId: number
): Promise<SmsPlayerWipeResponse> {
  return fetchJson<SmsPlayerWipeResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/players/wipe`,
    { method: 'POST' }
  )
}

export async function getSmsMatches(
  tournamentId: number,
  phase: 'upcoming' | 'completed'
): Promise<SmsMatchLookupItem[]> {
  const params = new URLSearchParams()
  params.set('phase', phase)
  return fetchJson<SmsMatchLookupItem[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/matches?${params.toString()}`
  )
}

export async function getSmsEventDivisions(
  tournamentId: number,
  eventId: number
): Promise<SmsDivisionLookupItem[]> {
  return fetchJson<SmsDivisionLookupItem[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/event/${eventId}/divisions`
  )
}

export async function sendSmsBlast(
  tournamentId: number,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/blast`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsEvent(
  tournamentId: number,
  eventId: number,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/event/${eventId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsEventDivision(
  tournamentId: number,
  eventId: number,
  division: string,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/event/${eventId}/division/${encodeURIComponent(division)}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsDivision(
  tournamentId: number,
  division: string,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/division/${encodeURIComponent(division)}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsTeam(
  tournamentId: number,
  teamId: number,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/team/${teamId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsPlayer(
  tournamentId: number,
  playerId: number,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/player/${playerId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsMatch(
  tournamentId: number,
  matchId: number,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/match/${matchId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsTimeslot(
  tournamentId: number,
  payload: SmsTimeslotRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/timeslot`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsBlast(
  tournamentId: number,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/blast`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsEvent(
  tournamentId: number,
  eventId: number,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/event/${eventId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsEventDivision(
  tournamentId: number,
  eventId: number,
  division: string,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/event/${eventId}/division/${encodeURIComponent(division)}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsDivision(
  tournamentId: number,
  division: string,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/division/${encodeURIComponent(division)}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsPlayer(
  tournamentId: number,
  playerId: number,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/player/${playerId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsMatch(
  tournamentId: number,
  matchId: number,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/match/${matchId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function getSmsPhoneLists(
  tournamentId: number
): Promise<SmsPhoneList[]> {
  return fetchJson<SmsPhoneList[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/phone-lists`
  )
}

export async function createSmsPhoneList(
  tournamentId: number,
  payload: { name: string }
): Promise<SmsPhoneList> {
  return fetchJson<SmsPhoneList>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/phone-lists`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function renameSmsPhoneList(
  tournamentId: number,
  phoneListId: number,
  payload: { name: string }
): Promise<SmsPhoneList> {
  return fetchJson<SmsPhoneList>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/phone-lists/${phoneListId}`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function deleteSmsPhoneList(
  tournamentId: number,
  phoneListId: number
): Promise<{ ok: boolean }> {
  return fetchJson<{ ok: boolean }>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/phone-lists/${phoneListId}`,
    { method: 'DELETE' }
  )
}

export async function importSmsPhoneList(
  tournamentId: number,
  phoneListId: number,
  payload: { raw_text: string }
): Promise<SmsPhoneListImportResponse> {
  return fetchJson<SmsPhoneListImportResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/phone-lists/${phoneListId}/import`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function previewSmsPhoneList(
  tournamentId: number,
  phoneListId: number,
  payload: SmsSendRequest
): Promise<SmsPreviewResponse> {
  return fetchJson<SmsPreviewResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/preview/phone-lists/${phoneListId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function sendSmsPhoneList(
  tournamentId: number,
  phoneListId: number,
  payload: SmsSendRequest
): Promise<SmsSendResponse> {
  return fetchJson<SmsSendResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/phone-lists/${phoneListId}`,
    { method: 'POST', body: JSON.stringify(payload) }
  )
}

export async function getSmsLog(
  tournamentId: number,
  opts?: { limit?: number; message_type?: string }
): Promise<SmsLogEntry[]> {
  const params = new URLSearchParams()
  if (opts?.limit != null) params.append('limit', String(opts.limit))
  if (opts?.message_type) params.append('message_type', opts.message_type)
  const qs = params.toString()
  return fetchJson<SmsLogEntry[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/log${qs ? `?${qs}` : ''}`
  )
}

export async function getSmsRolloutMetrics(
  tournamentId: number,
  lookbackHours: number = 168
): Promise<SmsRolloutMetricsResponse> {
  const params = new URLSearchParams()
  params.set('lookback_hours', String(lookbackHours))
  return fetchJson<SmsRolloutMetricsResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/rollout-metrics?${params.toString()}`
  )
}

export async function runSmsFirstMatchReminders(
  tournamentId: number,
  opts?: {
    dry_run?: boolean
    window_minutes?: number
    now_utc?: string
    force_resend?: boolean
    resend_run_key?: string
    template_mode?: 'court_management' | 'checkin_management'
  }
): Promise<SmsAutomationRunResponse> {
  const params = new URLSearchParams()
  if (opts?.dry_run != null) params.set('dry_run', String(opts.dry_run))
  if (opts?.window_minutes != null) params.set('window_minutes', String(opts.window_minutes))
  if (opts?.now_utc) params.set('now_utc', opts.now_utc)
  if (opts?.force_resend != null) params.set('force_resend', String(opts.force_resend))
  if (opts?.resend_run_key) params.set('resend_run_key', opts.resend_run_key)
  if (opts?.template_mode) params.set('template_mode', opts.template_mode)
  const qs = params.toString()
  return fetchJson<SmsAutomationRunResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/automation/run-first-match-reminders${qs ? `?${qs}` : ''}`,
    { method: 'POST' }
  )
}

export async function runSmsRrFirstMatchReminders(
  tournamentId: number,
  opts: {
    event_id: number
    dry_run?: boolean
    force_resend?: boolean
    template_mode?: 'court_management' | 'checkin_management'
  }
): Promise<SmsRrAutomationRunResponse> {
  const params = new URLSearchParams()
  params.set('event_id', String(opts.event_id))
  if (opts.dry_run != null) params.set('dry_run', String(opts.dry_run))
  if (opts.force_resend != null) params.set('force_resend', String(opts.force_resend))
  if (opts.template_mode) params.set('template_mode', opts.template_mode)
  const qs = params.toString()
  return fetchJson<SmsRrAutomationRunResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/automation/run-rr-first-match-reminders${qs ? `?${qs}` : ''}`,
    { method: 'POST' }
  )
}

export async function getSmsSettings(
  tournamentId: number
): Promise<SmsSettingsResponse> {
  return fetchJson<SmsSettingsResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/settings`
  )
}

export async function patchSmsSettings(
  tournamentId: number,
  payload: Partial<Pick<SmsSettingsResponse,
    'auto_first_match' |
    'auto_post_match_next' |
    'auto_on_deck' |
    'auto_up_next' |
    'auto_court_change' |
    'auto_checkin_first_match' |
    'auto_checkin_slot_checkin' |
    'auto_checkin_post_match_next' |
    'auto_checkin_court_assigned' |
    'texts_enabled' |
    'test_mode' |
    'test_allowlist' |
    'player_contacts_only'
  >>
): Promise<SmsSettingsResponse> {
  return fetchJson<SmsSettingsResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/settings`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

export async function getSmsTemplates(
  tournamentId: number
): Promise<SmsTemplateResponse[]> {
  return fetchJson<SmsTemplateResponse[]>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/templates`
  )
}

export async function putSmsTemplate(
  tournamentId: number,
  messageType: string,
  payload: { template_body: string; is_active?: boolean }
): Promise<SmsTemplateResponse> {
  return fetchJson<SmsTemplateResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/templates/${messageType}`,
    { method: 'PUT', body: JSON.stringify(payload) }
  )
}

export async function resetSmsTemplates(
  tournamentId: number
): Promise<{ deleted: number; message: string }> {
  return fetchJson<{ deleted: number; message: string }>(
    `${API_BASE_URL}/tournaments/${tournamentId}/sms/templates/reset`,
    { method: 'POST' }
  )
}

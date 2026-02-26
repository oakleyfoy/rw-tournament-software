const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

export interface Tournament {
  id: number;
  name: string;
  location: string;
  timezone: string;
  start_date: string;
  end_date: string;
  notes?: string;
  use_time_windows: boolean;
  court_names?: string[] | null;
  public_schedule_version_id: number | null;
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
  use_time_windows?: boolean;
  court_names?: string[] | null;
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
  // Don't set Content-Type for DELETE requests (no body)
  const isDelete = options?.method === 'DELETE'
  const headers: HeadersInit = isDelete
    ? { ...options?.headers }
    : {
        'Content-Type': 'application/json',
        ...options?.headers,
      }
  
  console.log('fetchJson:', options?.method || 'GET', url, { headers, body: options?.body })
  let response: Response
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
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

// Schedule Builder — authoritative match inventory (read-only)
export interface ScheduleBuilderEvent {
  event_id: number;
  event_name: string;
  division: string;
  team_count: number;
  template_type: string;
  guarantee: number;
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
}

export async function getScheduleBuilder(tournamentId: number): Promise<ScheduleBuilderResponse> {
  return fetchJson<ScheduleBuilderResponse>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule-builder`);
}

// Time Windows interfaces and functions
export interface TimeWindow {
  id: number;
  tournament_id: number;
  day_date: string;
  start_time: string;
  end_time: string;
  courts_available: number;
  block_minutes: number;
  label?: string | null;
  is_active: boolean;
}

export interface TimeWindowCreate {
  day_date: string;
  start_time: string;
  end_time: string;
  courts_available: number;
  block_minutes: number;
  label?: string | null;
  is_active?: boolean;
}

export interface TimeWindowUpdate {
  day_date?: string;
  start_time?: string;
  end_time?: string;
  courts_available?: number;
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
 * Match IDs should be sorted deterministically before sending.
 */
export async function placeMatchSubset(
  tournamentId: number,
  versionId: number,
  matchIds: number[]
): Promise<AssignSubsetResponse> {
  return fetchJson<AssignSubsetResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/assign-subset`,
    {
      method: 'POST',
      body: JSON.stringify({ match_ids: matchIds }),
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
  reserved_courts: number
  assigned_matches: number
  spare_courts: number
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
  reserved_spares: number
  duration_ms: number | null
  batches: Array<{ name: string; attempted: number; assigned: number; failed_count: number }>
}

export interface FullPolicyRunResponse {
  total_assigned: number
  total_failed: number
  total_reserved_spares: number
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
    spare_violations: number
  } | null
  policy_run_id?: number | null
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
  total_reserved_spares: number
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
  const res = await fetch(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks/match/${matchId}`,
    { method: 'DELETE', headers: { 'Content-Type': 'application/json' } }
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
  const res = await fetch(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/locks/slot/${slotId}`,
    { method: 'DELETE', headers: { 'Content-Type': 'application/json' } }
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
}

export interface PublicWaterfallResponse {
  tournament_name: string
  event_name: string
  rows: PublicWaterfallRow[]
  division_type: 'bracket' | 'roundrobin'
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
}

export async function getPublicRoundRobin(
  tournamentId: number,
  eventId: number
): Promise<RoundRobinResponse> {
  return fetchJson<RoundRobinResponse>(
    `${API_BASE_URL}/public/tournaments/${tournamentId}/events/${eventId}/roundrobin`
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

export interface DeskSnapshotResponse {
  tournament_id: number
  tournament_name: string
  version_id: number
  version_status: string
  courts: string[]
  matches: DeskMatchItem[]
  now_playing_by_court: Record<string, DeskMatchItem>
  up_next_by_court: Record<string, DeskMatchItem>
  on_deck_by_court: Record<string, DeskMatchItem>
  board_by_court: BoardCourtSlot[]
  slots: SnapshotSlot[]
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
  payload: { version_id: number; score?: string; winner_team_id: number; is_default?: boolean; is_retired?: boolean }
): Promise<FinalizeResponse> {
  return fetchJson<FinalizeResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/finalize`,
    { method: 'PATCH', body: JSON.stringify(payload) }
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
  payload: { version_id: number; status: string }
): Promise<{ match_id: number; status: string }> {
  return fetchJson<{ match_id: number; status: string }>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/matches/${matchId}/status`,
    { method: 'PATCH', body: JSON.stringify(payload) }
  )
}

// ── Impact ──────────────────────────────────────────────────────────────

export interface ImpactTarget {
  target_match_number: number | null
  target_match_id: number | null
  target_slot: string | null
  target_current_team_display: string | null
  target_current_team_id: number | null
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

export interface AddCourtResponse {
  success: boolean
  court_label: string
  court_number: number
  courts: string[]
  created_slots: number
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

export async function deskAddCourt(
  tournamentId: number,
  payload: { version_id: number; court_label: string; create_matching_slots?: boolean }
): Promise<AddCourtResponse> {
  return fetchJson<AddCourtResponse>(
    `${API_BASE_URL}/desk/tournaments/${tournamentId}/courts`,
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
  wins: number
  losses: number
  sets_won: number
  sets_lost: number
  games_won: number
  games_lost: number
  point_diff: number | null
  played: number
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

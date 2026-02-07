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
  consolation_tier: number | null
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

export interface MatchPreviewResponse {
  matches: MatchPreviewItem[]
  counts_by_event: Record<string, number>
  counts_by_stage: Record<string, number>
  /** event_id (as string key) -> event name */
  event_names_by_id?: Record<string, string>
  duplicate_codes: string[]
  ordering_checksum: string
  diagnostics: MatchPreviewDiagnostics
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
      round_index: (m as { round_index?: number }).round_index ?? 0,
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

export interface SchedulePlanReport {
  tournament_id: number
  schedule_version_id: number | null
  version_status: string | null
  ok: boolean
  blocking_errors: PlanReportError[]
  warnings: PlanReportError[]
  events: EventReport[]
  totals: TotalsInfo
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


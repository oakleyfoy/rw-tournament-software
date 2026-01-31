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

export async function generateMatches(tournamentId: number, payload?: MatchGenerateRequest): Promise<{ schedule_version_id: number; total_matches_created: number; per_event: Record<number, { event_name: string; matches: number }> }> {
  // If payload is empty or undefined, send empty object to let backend derive version_id
  const body = payload && Object.keys(payload).length > 0 ? payload : {};
  return fetchJson<{ schedule_version_id: number; total_matches_created: number; per_event: Record<number, { event_name: string; matches: number }> }>(`${API_BASE_URL}/tournaments/${tournamentId}/schedule/matches/generate`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
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
): Promise<MatchRuntimeState> {
  return fetchJson<MatchRuntimeState>(
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

/** POST /api/tournaments/{tournamentId}/schedule/versions/{versionId}/build — Auto-Assign V2 (respects locked). */
export async function buildScheduleVersion(tournamentId: number, versionId: number): Promise<BuildScheduleResponse> {
  return fetchJson<BuildScheduleResponse>(
    `${API_BASE_URL}/tournaments/${tournamentId}/schedule/versions/${versionId}/build`,
    { method: 'POST' }
  );
}

export async function buildSchedule(tournamentId: number, versionId: number): Promise<BuildScheduleResponse> {
  // Try the single build endpoint first (if implemented)
  try {
    return await buildScheduleVersion(tournamentId, versionId);
  } catch (err: any) {
    // Only fallback on 404 (endpoint not found), not on 500/400/422 (business logic errors)
    const status = err?.status;
    const is404 = status === 404;
    
    if (is404) {
      // Build endpoint not implemented yet, use fallback: sequential calls
      console.log('Build endpoint not available (404), using sequential calls');
    } else {
      // Re-throw other errors (500, 400, 422, etc.) - these are real errors
      throw err;
    }
    
    // Generate slots
    console.log('Generating slots...');
    const slotsResult = await generateSlots(tournamentId, {
      source: 'auto',
      schedule_version_id: versionId,
      wipe_existing: true,
    });
    console.log(`Generated ${slotsResult.slots_created} slots`);
    
    // Generate matches
    console.log('Generating matches...');
    const matchesResult = await generateMatches(tournamentId, {
      schedule_version_id: versionId,
      wipe_existing: true,
    });
    console.log(`Generated ${matchesResult.total_matches_created} matches`);
    
    // Get slots and matches to calculate assignments
    console.log('Loading slots and matches...');
    const [, matches] = await Promise.all([
      getSlots(tournamentId, versionId),
      getMatches(tournamentId, versionId),
    ]);
    
    const assignedCount = matches.filter(m => m.status === 'scheduled').length;
    const unassignedCount = matches.filter(m => m.status === 'unscheduled').length;
    
    return {
      schedule_version_id: versionId,
      slots_created: slotsResult.slots_created,
      matches_created: matchesResult.total_matches_created,
      matches_assigned: assignedCount,
      matches_unassigned: unassignedCount,
    };
  }
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

export interface ConflictReportV1 {
  summary: ConflictReportSummary;
  unassigned_matches: UnassignedMatchDetail[];
  slot_pressure: SlotPressure[];
  stage_timeline: StageTimeline[];
  ordering_integrity: OrderingIntegrity;
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


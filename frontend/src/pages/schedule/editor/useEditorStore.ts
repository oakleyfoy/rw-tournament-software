import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import {
  ScheduleVersion,
  GridSlot,
  GridAssignment,
  GridMatch,
  TeamInfo,
  ConflictReportV1,
  getScheduleVersions,
  getScheduleGrid,
  getConflicts,
  cloneScheduleVersion,
  updateAssignment,
  createAssignment,
  deleteAssignment,
} from '../../../api/client';

// Editor state model (single source of truth)
export interface EditorState {
  // Core identifiers
  tournamentId: number | null;
  versionId: number | null;
  versionStatus: 'draft' | 'final' | null;

  // Data
  versions: ScheduleVersion[];
  slots: GridSlot[];
  assignments: GridAssignment[];
  matches: GridMatch[];
  teams: TeamInfo[];
  assignmentsBySlotId: Record<number, GridAssignment>;
  matchesById: Record<number, GridMatch>;
  conflicts: ConflictReportV1 | null;

  // Pending states
  pending: {
    loadingVersions: boolean;
    loadingGrid: boolean;
    loadingConflicts: boolean;
    patchingAssignmentId: number | null;
    cloning: boolean;
  };

  // Error state
  lastError: {
    scope: 'LOAD_VERSIONS' | 'LOAD_GRID' | 'LOAD_CONFLICTS' | 'PATCH' | 'CLONE';
    message: string;
    details?: any;
  } | null;
}

// Actions interface
export interface EditorActions {
  // Initialization
  initialize: (tournamentId: number, versionId?: number) => Promise<void>;
  loadVersions: () => Promise<void>;
  loadGridAndConflicts: (silent?: boolean) => Promise<void>;
  
  // Version management
  switchVersion: (versionId: number) => Promise<void>;
  cloneToEdit: () => Promise<number | null>;
  
  // Manual assignment
  moveAssignment: (assignmentId: number, newSlotId: number) => Promise<void>;
  assignMatch: (matchId: number, slotId: number) => Promise<void>;  // Assign unassigned match to slot
  unassignMatch: (assignmentId: number) => Promise<void>;  // Unassign match (remove from slot, back to unassigned queue)
  
  // Utilities
  clearError: () => void;
  reset: () => void;
}

// Combined store type
export type EditorStore = EditorState & EditorActions;

// Initial state
const initialState: EditorState = {
  tournamentId: null,
  versionId: null,
  versionStatus: null,
  versions: [],
  slots: [],
  assignments: [],
  matches: [],
  teams: [],
  assignmentsBySlotId: {},
  matchesById: {},
  conflicts: null,
  pending: {
    loadingVersions: false,
    loadingGrid: false,
    loadingConflicts: false,
    patchingAssignmentId: null,
    cloning: false,
  },
  lastError: null,
};

export const useEditorStore = create<EditorStore>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,

    // Initialize: set tournament and optionally version, then load data
    initialize: async (tournamentId: number, versionId?: number) => {
    const current = get();

    // CRITICAL: Check if already initialized BEFORE any set() calls
    // This prevents the infinite loop caused by set() → rerender → effect → initialize → set() → ...
    const isExplicitVersionChange = typeof versionId === "number" && !Number.isNaN(versionId);
    const isSameTournament = current.tournamentId === tournamentId;
    const hasVersions = current.versions.length > 0;
    const isSameOrNoVersion = !isExplicitVersionChange || current.versionId === versionId;

    if (isSameTournament && hasVersions && isSameOrNoVersion) {
      // Already initialized for this tournament; don't re-run
      return;
    }

    // If the URL didn't specify a versionId, preserve current versionId (don't clobber)
    const nextVersionId = isExplicitVersionChange ? versionId : current.versionId;

    // Now safe to set state (early return above prevents infinite loop)
    set({ tournamentId, versionId: nextVersionId ?? null, lastError: null });
    
    await get().loadVersions();
    
    // If no versionId provided, use the first draft or latest version
    if (!isExplicitVersionChange && get().versions.length > 0) {
      const draftVersion = get().versions.find(v => v.status === 'draft');
      const targetVersion = draftVersion || get().versions[0];
      set({ versionId: targetVersion.id, versionStatus: targetVersion.status });
    }
    
    if (get().versionId) {
      await get().loadGridAndConflicts();
    }
  },

  // Load all versions for the tournament
  loadVersions: async () => {
    const { tournamentId } = get();
    if (!tournamentId) return;

    set({ pending: { ...get().pending, loadingVersions: true }, lastError: null });
    
    try {
      const versions = await getScheduleVersions(tournamentId);
      set({ versions, pending: { ...get().pending, loadingVersions: false } });
    } catch (error: any) {
      set({
        lastError: {
          scope: 'LOAD_VERSIONS',
          message: error.message || 'Failed to load versions',
          details: error,
        },
        pending: { ...get().pending, loadingVersions: false },
      });
    }
  },

  // Load grid and conflicts for current version
  loadGridAndConflicts: async (silent: boolean = false) => {
    const { tournamentId, versionId } = get();
    if (!tournamentId || !versionId) return;

    if (!silent) {
      set({
        pending: {
          ...get().pending,
          loadingGrid: true,
          loadingConflicts: true,
        },
        lastError: null,
      });
    }

    try {
      // Load grid and conflicts in parallel
      const [gridData, conflictsData] = await Promise.all([
        getScheduleGrid(tournamentId, versionId),
        getConflicts(tournamentId, versionId),
      ]);

      // Build derived indexes
      const assignmentsBySlotId: Record<number, GridAssignment> = {};
      gridData.assignments.forEach(a => {
        assignmentsBySlotId[a.slot_id] = a;
      });

      const matchesById: Record<number, GridMatch> = {};
      gridData.matches.forEach(m => {
        matchesById[m.match_id] = m;
      });

      set({
        slots: gridData.slots,
        assignments: gridData.assignments,
        matches: gridData.matches,
        teams: gridData.teams,
        assignmentsBySlotId,
        matchesById,
        conflicts: conflictsData,
        pending: {
          ...get().pending,
          loadingGrid: false,
          loadingConflicts: false,
        },
      });
    } catch (error: any) {
      const scope = error.message.includes('conflict') ? 'LOAD_CONFLICTS' : 'LOAD_GRID';
      set({
        lastError: {
          scope,
          message: error.message || 'Failed to load schedule data',
          details: error,
        },
        pending: {
          ...get().pending,
          loadingGrid: false,
          loadingConflicts: false,
        },
      });
    }
  },

  // Switch to a different version
  switchVersion: async (versionId: number) => {
    const version = get().versions.find(v => v.id === versionId);
    if (!version) return;

    set({ versionId, versionStatus: version.status });
    await get().loadGridAndConflicts();
  },

  // Clone current version to draft for editing
  cloneToEdit: async (): Promise<number | null> => {
    const { tournamentId, versionId } = get();
    if (!tournamentId || !versionId) return null;

    set({ pending: { ...get().pending, cloning: true }, lastError: null });

    try {
      const newVersion = await cloneScheduleVersion(tournamentId, versionId);
      
      // Reload versions and switch to new draft
      await get().loadVersions();
      set({
        versionId: newVersion.id,
        versionStatus: newVersion.status,
        pending: { ...get().pending, cloning: false },
      });
      
      await get().loadGridAndConflicts();
      return newVersion.id;
    } catch (error: any) {
      set({
        lastError: {
          scope: 'CLONE',
          message: error.message || 'Failed to clone version',
          details: error,
        },
        pending: { ...get().pending, cloning: false },
      });
      return null;
    }
  },

  // Move an assignment to a new slot (PATCH endpoint)
  moveAssignment: async (assignmentId: number, newSlotId: number) => {
    const { tournamentId, versionStatus } = get();
    if (!tournamentId) return;

    // Guard: cannot mutate final versions
    if (versionStatus === 'final') {
      set({
        lastError: {
          scope: 'PATCH',
          message: 'Cannot modify final versions. Clone to draft first.',
        },
      });
      return;
    }

    set({
      pending: { ...get().pending, patchingAssignmentId: assignmentId },
      lastError: null,
    });

    try {
      await updateAssignment(tournamentId, assignmentId, newSlotId);
      
      // After successful PATCH, refetch grid + conflicts silently (no loading screen)
      await get().loadGridAndConflicts(true);
      
      set({ pending: { ...get().pending, patchingAssignmentId: null } });
    } catch (error: any) {
      set({
        lastError: {
          scope: 'PATCH',
          message: error.message || 'Failed to move assignment',
          details: error,
        },
        pending: { ...get().pending, patchingAssignmentId: null },
      });
      
      // Even on error, refetch to ensure alignment silently
      await get().loadGridAndConflicts(true);
    }
  },

  // Assign unassigned match to slot
  assignMatch: async (matchId: number, slotId: number) => {
    const { tournamentId, versionId, versionStatus } = get();
    if (!tournamentId || !versionId) return;

    // Guard: cannot mutate final versions
    if (versionStatus === 'final') {
      set({
        lastError: {
          scope: 'PATCH',
          message: 'Cannot modify final versions. Clone to draft first.',
        },
      });
      return;
    }

    set({
      pending: { ...get().pending, patchingAssignmentId: matchId },  // Use matchId as temporary ID
      lastError: null,
    });

    try {
      await createAssignment(tournamentId, {
        schedule_version_id: versionId,
        match_id: matchId,
        slot_id: slotId,
      });
      
      // After successful POST, refetch grid + conflicts silently (no loading screen)
      await get().loadGridAndConflicts(true);
      
      set({ pending: { ...get().pending, patchingAssignmentId: null } });
    } catch (error: any) {
      set({
        lastError: {
          scope: 'PATCH',
          message: error.message || 'Failed to assign match',
          details: error,
        },
        pending: { ...get().pending, patchingAssignmentId: null },
      });
      
      // Even on error, refetch to ensure alignment
      await get().loadGridAndConflicts();
    }
  },

  // Unassign match (remove from slot, back to unassigned queue)
  unassignMatch: async (assignmentId: number) => {
    const { tournamentId, versionStatus } = get();
    if (!tournamentId) return;

    // Guard: cannot mutate final versions
    if (versionStatus === 'final') {
      set({
        lastError: {
          scope: 'PATCH',
          message: 'Cannot modify final versions. Clone to draft first.',
        },
      });
      return;
    }

    set({
      pending: { ...get().pending, patchingAssignmentId: assignmentId },
      lastError: null,
    });

    try {
      await deleteAssignment(tournamentId, assignmentId);
      
      // After successful DELETE, refetch grid + conflicts silently (no loading screen)
      await get().loadGridAndConflicts(true);
      
      set({ pending: { ...get().pending, patchingAssignmentId: null } });
    } catch (error: any) {
      set({
        lastError: {
          scope: 'PATCH',
          message: error.message || 'Failed to unassign match',
          details: error,
        },
        pending: { ...get().pending, patchingAssignmentId: null },
      });
      
      // Even on error, refetch to ensure alignment silently
      await get().loadGridAndConflicts(true);
    }
  },

  // Clear error
  clearError: () => set({ lastError: null }),

  // Reset store to initial state
  reset: () => set(initialState),
  }))
);

// Derived selectors (can be used outside the store)
// Memoized selector: only creates new array when matches or assignments actually change
let cachedUnassigned: { matches: GridMatch[]; assignments: GridAssignment[]; result: GridMatch[] } | null = null;

export const selectUnassignedMatches = (state: EditorState): GridMatch[] => {
  // Return cached result if inputs haven't changed (reference equality)
  if (
    cachedUnassigned &&
    cachedUnassigned.matches === state.matches &&
    cachedUnassigned.assignments === state.assignments
  ) {
    return cachedUnassigned.result;
  }

  // Compute new result
  const result = state.matches.filter(m => {
    return !state.assignments.some(a => a.match_id === m.match_id);
  });

  // Cache for next call
  cachedUnassigned = {
    matches: state.matches,
    assignments: state.assignments,
    result,
  };

  return result;
};

// Stable empty array reference (never changes)
const EMPTY_LOCKED_ASSIGNMENTS: GridAssignment[] = [];

// Note: Placeholder until backend adds 'locked' field
export const selectLockedAssignments = (_state: EditorState): GridAssignment[] => {
  // Always return same empty array reference (stable)
  return EMPTY_LOCKED_ASSIGNMENTS; // TODO: Implement once backend adds 'locked' field
};

export const selectSlotOccupied = (state: EditorState, slotId: number): boolean => {
  return !!state.assignmentsBySlotId[slotId];
};

export const selectIsFinal = (state: EditorState): boolean => {
  return state.versionStatus === 'final';
};


import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useShallow } from 'zustand/react/shallow';
import { DndContext, DragEndEvent, DragStartEvent, DragOverlay } from '@dnd-kit/core';
import { useEditorStore, selectUnassignedMatches, selectIsFinal } from './useEditorStore';
import { buildScheduleVersion } from '../../../api/client';
import { showToast } from '../../../utils/toast';
import { EditorHeader } from './components/EditorHeader';
import { MatchQueuePanel } from './components/MatchQueuePanel';
import { EditorGrid } from './components/EditorGrid';
import { ConflictsPanel } from './components/ConflictsPanel';
import { EditorErrorBoundary } from './components/EditorErrorBoundary';
import { ErrorModal } from './components/ErrorModal';
import { featureFlags } from '../../../config/featureFlags';
import './ScheduleEditorPage.css';

export default function ScheduleEditorPage() {
  // Feature flag gate (defense-in-depth)
  if (!featureFlags.manualScheduleEditor) {
    return (
      <div style={{ padding: 24 }}>
        <h2>Manual Schedule Editor is disabled</h2>
        <p>Set VITE_ENABLE_MANUAL_EDITOR=true and restart dev server.</p>
      </div>
    );
  }
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const tournamentId = id ? parseInt(id) : null;
  const versionIdParam = searchParams.get('versionId');
  const versionId = versionIdParam ? parseInt(versionIdParam) : undefined;

  // Use shallow selector to prevent unnecessary rerenders
  const {
    initialize,
    versionStatus,
    versions,
    slots,
    assignments,
    teams,
    assignmentsBySlotId,
    matchesById,
    conflicts,
    pending,
    lastError,
    switchVersion,
    cloneToEdit,
    clearError,
  } = useEditorStore(
    useShallow((s) => ({
      initialize: s.initialize,
      versionStatus: s.versionStatus,
      versions: s.versions,
      slots: s.slots,
      assignments: s.assignments,
      teams: s.teams,
      assignmentsBySlotId: s.assignmentsBySlotId,
      matchesById: s.matchesById,
      conflicts: s.conflicts,
      pending: s.pending,
      lastError: s.lastError,
      switchVersion: s.switchVersion,
      cloneToEdit: s.cloneToEdit,
      clearError: s.clearError,
    }))
  );

  // Derived selectors
  const unassignedMatches = useEditorStore(selectUnassignedMatches);
  const isFinal = useEditorStore(selectIsFinal);
  const moveAssignment = useEditorStore((s) => s.moveAssignment);
  const assignMatch = useEditorStore((s) => s.assignMatch);
  const unassignMatch = useEditorStore((s) => s.unassignMatch);

  // Drag state
  const [activeId, setActiveId] = useState<string | number | null>(null);
  const [runningAutoAssign, setRunningAutoAssign] = useState(false);

  const handleRunAutoAssign = async () => {
    const state = useEditorStore.getState();
    const { tournamentId: tid, versionId: vid, loadGridAndConflicts } = state;
    if (!tid || !vid || state.versionStatus !== 'draft') return;
    setRunningAutoAssign(true);
    try {
      await buildScheduleVersion(tid, vid);
      await loadGridAndConflicts(true);
      showToast('Auto-Assign completed', 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Auto-Assign failed', 'error');
    } finally {
      setRunningAutoAssign(false);
    }
  };

  // Drag handlers
  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveId(null);

    if (!event.over) {
      return;
    }

    const activeIdValue = event.active.id;
    const newSlotId = event.over.id as number;

    // Don't allow drops on occupied slots (unless it's the same slot, which we handle later)
    const assignmentsBySlotId = useEditorStore.getState().assignmentsBySlotId;
    const existingAssignment = assignmentsBySlotId[newSlotId];
    
    // If dropping on an occupied slot, check if it's the same assignment (moving to same slot - no-op)
    if (existingAssignment) {
      if (typeof activeIdValue === 'number' && activeIdValue === existingAssignment.id) {
        return; // Same assignment, same slot - no change needed
      }
      // Slot is occupied - show error
      const existingMatch = useEditorStore.getState().matchesById[existingAssignment.match_id];
      useEditorStore.setState({
        lastError: {
          scope: 'PATCH',
          message: `Cannot place match: Slot is already occupied by ${existingMatch?.match_code || 'another match'}`,
        },
      });
      return;
    }

    // Get slot and match information for validation
    const slots = useEditorStore.getState().slots;
    const matchesById = useEditorStore.getState().matchesById;
    const newSlot = slots.find((s) => s.slot_id === newSlotId);
    
    if (!newSlot) {
      console.warn(`Slot ${newSlotId} not found`);
      return;
    }

    // Helper: Convert time string to minutes
    const timeToMinutes = (timeStr: string): number => {
      const [hours, minutes] = timeStr.split(':').map(Number);
      return hours * 60 + minutes;
    };

    // Helper: Get day end time (last slot start time + slot duration)
    const getDayEndTime = (day: string): number => {
      const daySlots = slots.filter((s) => s.day_date === day);
      if (daySlots.length === 0) return 0;
      const latestSlot = daySlots.reduce((latest, slot) => {
        return timeToMinutes(slot.start_time) > timeToMinutes(latest.start_time) ? slot : latest;
      });
      return timeToMinutes(latestSlot.start_time) + latestSlot.duration_minutes;
    };

    // Stage precedence mapping
    const STAGE_PRECEDENCE: Record<string, number> = {
      WF: 1,
      MAIN: 2,
      CONSOLATION: 3,
      PLACEMENT: 4,
    };

    // Helper: Validate stage ordering (earlier stages must end before later stages start)
    // IMPORTANT: Stage ordering only applies WITHIN the same event.
    // - Women's MAIN can start once Women's WF is done (even if Mixed WF is still playing)
    // - Mixed MAIN can start once Mixed WF is done (even if Women's WF is still playing)
    // - Different events can run different stages simultaneously
    const validateStageOrdering = (
      match: typeof matchesById[number],
      targetSlot: typeof slots[number],
      allMatches: typeof matchesById,
      allAssignments: typeof assignments,
      allSlots: typeof slots
    ): { valid: boolean; error?: string } => {
      const matchStage = match.stage;
      const matchPrecedence = STAGE_PRECEDENCE[matchStage] || 999;

      // Calculate target slot start time in minutes
      const targetStartMinutes = timeToMinutes(targetSlot.start_time);

      // Check all earlier stages - they must have ENDED before this match can START
      // NOTE: Only checks matches in the SAME EVENT (event_id === match.event_id)
      for (const [earlierStage, earlierPrecedence] of Object.entries(STAGE_PRECEDENCE)) {
        if (earlierPrecedence >= matchPrecedence) {
          // Skip same stage or later stages
          continue;
        }

        // Find all matches in earlier stages in the SAME EVENT ONLY
        const earlierMatches = Object.values(allMatches).filter(
          (m) => m.event_id === match.event_id && m.stage === earlierStage
        );

        if (earlierMatches.length === 0) {
          continue;
        }

        // Check each earlier stage match - it must have ENDED before target start
        for (const earlierMatch of earlierMatches) {
          // Check if earlier match is assigned
          const earlierAssignment = allAssignments.find((a) => a.match_id === earlierMatch.match_id);

          // Skip unassigned earlier matches - they'll be checked when assigned
          if (!earlierAssignment) {
            continue;
          }

          // Get earlier match slot
          const earlierSlot = allSlots.find((s) => s.slot_id === earlierAssignment.slot_id);
          if (!earlierSlot) {
            continue;
          }

          // Only check matches on the same day
          if (earlierSlot.day_date !== targetSlot.day_date) {
            continue;
          }

          // Calculate earlier match end time in minutes
          const earlierStartMinutes = timeToMinutes(earlierSlot.start_time);
          const earlierEndMinutes = earlierStartMinutes + earlierMatch.duration_minutes;

          // Check if earlier match ends before target start time
          if (earlierEndMinutes > targetStartMinutes) {
            return {
              valid: false,
              error: `Cannot place Match: ${matchStage} matches cannot start before ${earlierStage} matches have finished`,
            };
          }
        }
      }

      return { valid: true };
    };

    // Helper: Validate round dependencies
    const validateRoundDependencies = (
      match: typeof matchesById[number],
      targetSlot: typeof slots[number],
      allMatches: typeof matchesById,
      allAssignments: typeof assignments,
      allSlots: typeof slots
    ): { valid: boolean; error?: string } => {
      // Round 1 matches have no dependencies
      if (!match.round_index || match.round_index <= 1) {
        return { valid: true };
      }

      // Find all prerequisite matches (Round N-1 in same event and stage)
      const prerequisiteRound = match.round_index - 1;
      const prerequisiteMatches = Object.values(allMatches).filter(
        (m) =>
          m.event_id === match.event_id &&
          m.stage === match.stage &&
          m.round_index === prerequisiteRound
      );

      if (prerequisiteMatches.length === 0) {
        // No prerequisites found - allow assignment
        return { valid: true };
      }

      // Calculate target slot start time in minutes
      const targetStartMinutes = timeToMinutes(targetSlot.start_time);

      // Check each prerequisite match - ALL must be assigned and finished
      for (const prereqMatch of prerequisiteMatches) {
        // Check if prerequisite is assigned
        const prereqAssignment = allAssignments.find((a) => a.match_id === prereqMatch.match_id);

        // ALL Round N-1 matches must be assigned before ANY Round N match can be scheduled
        if (!prereqAssignment) {
          return {
            valid: false,
            error: `Cannot place Match: Round ${match.round_index} cannot start before a Round ${prerequisiteRound} Match`,
          };
        }

        // Get prerequisite slot
        const prereqSlot = allSlots.find((s) => s.slot_id === prereqAssignment.slot_id);
        if (!prereqSlot) {
          return {
            valid: false,
            error: `Round ${prerequisiteRound} match ${prereqMatch.match_code} has invalid slot`,
          };
        }

        // Calculate prerequisite match end time in minutes
        const prereqStartMinutes = timeToMinutes(prereqSlot.start_time);
        const prereqEndMinutes = prereqStartMinutes + prereqMatch.duration_minutes;

          // Check if prerequisite ends before target start time
          if (prereqEndMinutes > targetStartMinutes) {
            return {
              valid: false,
              error: `Cannot place Match: Round ${match.round_index} cannot start before a Round ${prerequisiteRound} Match`,
            };
          }
      }

      return { valid: true };
    };

    // Get match information
    let match: typeof matchesById[number] | null = null;
    
    if (typeof activeIdValue === 'string' && activeIdValue.startsWith('match_')) {
      // Unassigned match
      const matchId = parseInt(activeIdValue.replace('match_', ''), 10);
      if (isNaN(matchId)) {
        console.warn(`Invalid match ID: ${activeIdValue}`);
        return;
      }
      match = matchesById[matchId] || null;
    } else if (typeof activeIdValue === 'number') {
      // Assigned match
      const assignmentId = activeIdValue;
      const assignments = useEditorStore.getState().assignments;
      const assignment = assignments.find((a) => a.id === assignmentId);
      if (!assignment) {
        console.warn(`Assignment ${assignmentId} not found`);
        return;
      }

      // Don't allow dropping on the same slot
      if (assignment.slot_id === newSlotId) {
        return;
      }

      match = matchesById[assignment.match_id] || null;
    } else {
      console.warn(`Unknown drag ID type: ${typeof activeIdValue}`);
      return;
    }

    if (!match) {
      console.warn('Match not found');
      return;
    }

    // Validate: Check for overlaps with existing matches on the same court and day
    const assignments = useEditorStore.getState().assignments;
    const slotStartMinutes = timeToMinutes(newSlot.start_time);
    const matchStartMinutes = slotStartMinutes;
    const matchEndMinutes = slotStartMinutes + match.duration_minutes;
    
    // Get current assignment ID if moving an existing match (to exclude it from overlap check)
    let currentAssignmentId: number | null = null;
    if (typeof activeIdValue === 'number') {
      currentAssignmentId = activeIdValue;
    }
    
    // Check all assignments on the same court and day for overlaps
    for (const assignment of assignments) {
      // Skip the current assignment if we're moving it
      if (currentAssignmentId && assignment.id === currentAssignmentId) {
        continue;
      }
      
      const assignedSlot = slots.find((s) => s.slot_id === assignment.slot_id);
      if (!assignedSlot) continue;
      
      // Only check matches on the same court and day
      if (assignedSlot.court_id !== newSlot.court_id || assignedSlot.day_date !== newSlot.day_date) {
        continue;
      }
      
      const assignedMatch = matchesById[assignment.match_id];
      if (!assignedMatch) continue;
      
      // Calculate existing match's time range
      const assignedStartMinutes = timeToMinutes(assignedSlot.start_time);
      const assignedEndMinutes = assignedStartMinutes + assignedMatch.duration_minutes;
      
      // Check for overlap: [newStart, newEnd) overlaps [assignedStart, assignedEnd) if
      // newStart < assignedEnd AND assignedStart < newEnd
      if (matchStartMinutes < assignedEndMinutes && assignedStartMinutes < matchEndMinutes) {
        // Overlap detected - show error
        const overlapStart = Math.max(matchStartMinutes, assignedStartMinutes);
        const overlapEnd = Math.min(matchEndMinutes, assignedEndMinutes);
        const overlapDuration = overlapEnd - overlapStart;
        const overlapStartTime = new Date(0, 0, 0, Math.floor(overlapStart / 60), overlapStart % 60);
        const overlapStartStr = `${String(overlapStartTime.getHours()).padStart(2, '0')}:${String(overlapStartTime.getMinutes()).padStart(2, '0')}`;
        
        useEditorStore.setState({
          lastError: {
            scope: 'PATCH',
            message: `Cannot place match: ${match.match_code} (${match.duration_minutes} min) starting at ${newSlot.start_time.substring(0, 5)} would overlap with ${assignedMatch.match_code} (${assignedMatch.duration_minutes} min) starting at ${assignedSlot.start_time.substring(0, 5)}. Overlap: ${overlapStartStr} (${overlapDuration} min)`,
          },
        });
        return;
      }
    }

    // Validate: Check if match would exceed day end time
    const dayEndMinutes = getDayEndTime(newSlot.day_date);

    if (matchEndMinutes > dayEndMinutes) {
      // Show error and prevent drop
      const slotEndTime = new Date(0, 0, 0, Math.floor(dayEndMinutes / 60), dayEndMinutes % 60);
      const matchEndTime = new Date(0, 0, 0, Math.floor(matchEndMinutes / 60), matchEndMinutes % 60);
      const endTimeStr = `${String(slotEndTime.getHours()).padStart(2, '0')}:${String(slotEndTime.getMinutes()).padStart(2, '0')}`;
      const matchEndTimeStr = `${String(matchEndTime.getHours()).padStart(2, '0')}:${String(matchEndTime.getMinutes()).padStart(2, '0')}`;
      
      // Set error in store to display to user
      useEditorStore.setState({
        lastError: {
          scope: 'PATCH',
          message: `Cannot place match: ${match.match_code} (${match.duration_minutes} min) starting at ${newSlot.start_time.substring(0, 5)} would end at ${matchEndTimeStr}, but schedule ends at ${endTimeStr}`,
        },
      });
      return;
    }

    // Validate: Check stage ordering (earlier stages must end before later stages start)
    const stageOrderResult = validateStageOrdering(
      match,
      newSlot,
      matchesById,
      assignments,
      slots
    );
    if (!stageOrderResult.valid) {
      useEditorStore.setState({
        lastError: {
          scope: 'PATCH',
          message: stageOrderResult.error || 'Stage ordering violation',
        },
      });
      return;
    }

    // Validate: Check round dependencies
    const roundDepsResult = validateRoundDependencies(
      match,
      newSlot,
      matchesById,
      assignments,
      slots
    );
    if (!roundDepsResult.valid) {
      useEditorStore.setState({
        lastError: {
          scope: 'PATCH',
          message: roundDepsResult.error || 'Round dependency violation',
        },
      });
      return;
    }

    // Validation passed - proceed with assignment
    if (typeof activeIdValue === 'string' && activeIdValue.startsWith('match_')) {
      const matchId = parseInt(activeIdValue.replace('match_', ''), 10);
      assignMatch(matchId, newSlotId);
    } else if (typeof activeIdValue === 'number') {
      const assignmentId = activeIdValue;
      const assignments = useEditorStore.getState().assignments;
      const assignment = assignments.find((a) => a.id === assignmentId);
      if (assignment) {
        moveAssignment(assignment.id, newSlotId);
      }
    }
  };

  // One-shot load effect (only depends on IDs)
  // Note: initialize is NOT included in deps because Zustand actions are stable
  // Including it causes infinite loop (action recreated on every state change)
  useEffect(() => {
    if (tournamentId) {
      initialize(tournamentId, versionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournamentId, versionId]);

  // Loading states (never blank)
  if (pending.loadingVersions || pending.loadingGrid || pending.loadingConflicts) {
    return <div style={{ padding: 24 }}>Loading editor…</div>;
  }

  // Hard error guards (never blank)
  if (!tournamentId) {
    return (
      <div style={{ padding: 24 }}>
        <h2>Failed to load editor</h2>
        <pre>Tournament ID is required</pre>
      </div>
    );
  }

  // Separate fatal errors (LOAD) from validation errors (PATCH)
  const isFatalError = lastError && (lastError.scope === 'LOAD_VERSIONS' || lastError.scope === 'LOAD_GRID' || lastError.scope === 'LOAD_CONFLICTS' || lastError.scope === 'CLONE');
  const isValidationError = lastError && lastError.scope === 'PATCH';

  // Show full error panel only for fatal errors
  if (isFatalError) {
    return (
      <div style={{ padding: 24 }}>
        <h2>Manual Schedule Editor</h2>
        <p>Failed to load required schedule data.</p>
        <pre style={{ whiteSpace: "pre-wrap" }}>
          {lastError.scope}: {lastError.message}
        </pre>
        {lastError.details && (
          <details>
            <summary>Error details</summary>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(lastError.details, null, 2)}
            </pre>
          </details>
        )}
        <button
          onClick={clearError}
          style={{
            marginTop: 16,
            padding: "8px 16px",
            background: "#2196f3",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          Dismiss Error
        </button>
      </div>
    );
  }

  return (
    <EditorErrorBoundary>
      <div className="container editor-page">
        <EditorHeader
          tournamentId={tournamentId}
          versions={versions}
          activeVersionId={useEditorStore.getState().versionId}
          versionStatus={versionStatus}
          onVersionChange={switchVersion}
          onCloneToEdit={cloneToEdit}
          isCloning={pending.cloning}
          onRunAutoAssign={handleRunAutoAssign}
          isRunningAutoAssign={runningAutoAssign}
        />

      {/* Final version read-only banner */}
        {isFinal && (
          <div className="info-banner">
            <span>📄 Read-only (Final). Clone to Draft to edit.</span>
            <button
              onClick={cloneToEdit}
              disabled={pending.cloning}
              className="btn-secondary"
            >
              {pending.cloning ? 'Cloning...' : 'Clone to Draft'}
            </button>
          </div>
        )}

        {/* Main 3-column layout */}
        <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="editor-layout">
            {/* Left Panel: Match Queue */}
            <MatchQueuePanel
              unassignedMatches={unassignedMatches}
              teams={teams}
              loading={pending.loadingGrid}
              isFinal={isFinal}
              isPatchingMatchId={pending.patchingAssignmentId}
            />

            {/* Center: Schedule Grid */}
            <EditorGrid
              slots={slots}
              assignments={assignments}
              assignmentsBySlotId={assignmentsBySlotId}
              matches={matchesById}
              teams={teams}
              isFinal={isFinal}
              isPatchingAssignmentId={pending.patchingAssignmentId}
              onUnassign={unassignMatch}
            />

            {/* Right Panel: Conflicts */}
            <ConflictsPanel
              conflicts={conflicts}
              loading={pending.loadingConflicts}
              onRefresh={() => useEditorStore.getState().loadGridAndConflicts()}
            />
          </div>

          <DragOverlay>
            {activeId && (() => {
              const matches = matchesById;
              const assignments = useEditorStore.getState().assignments;
              // Handle unassigned match (string ID)
              if (typeof activeId === 'string' && activeId.startsWith('match_')) {
                const matchId = parseInt(activeId.replace('match_', ''), 10);
                const match = matches[matchId];
                return match ? (
                  <div className="match-card" style={{ opacity: 0.8 }}>
                    <div className="match-card-code">{match.match_code}</div>
                    <div className="match-card-stage">
                      {match.stage} R{match.round_index}
                    </div>
                  </div>
                ) : null;
              }
              // Handle assigned match (numeric assignment ID)
              if (typeof activeId === 'number') {
                const assignment = assignments.find((a) => a.id === activeId);
                const match = assignment ? matches[assignment.match_id] : null;
                return match ? (
                  <div className="grid-assignment" style={{ opacity: 0.8 }}>
                    {match.match_code}
                  </div>
                ) : null;
              }
              return null;
            })()}
          </DragOverlay>
        </DndContext>

        {/* Validation error modal (popup) */}
        {isValidationError && lastError && (
          <ErrorModal
            message={lastError.message}
            onClose={clearError}
          />
        )}
      </div>
    </EditorErrorBoundary>
  );
}


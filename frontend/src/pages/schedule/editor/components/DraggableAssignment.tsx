import { useDraggable } from '@dnd-kit/core';
import { GridMatch } from '../../../../api/client';

interface DraggableAssignmentProps {
  assignmentId: number;
  match: GridMatch;
  isLocked: boolean;
  isFinal: boolean;
  isPatchingAssignmentId: number | null;
  onUnassign?: (assignmentId: number) => void;
}

export function DraggableAssignment({
  assignmentId,
  match,
  isLocked,
  isFinal,
  isPatchingAssignmentId,
  onUnassign,
}: DraggableAssignmentProps) {
  const isPatching = isPatchingAssignmentId === assignmentId;
  const isDraggable = !isFinal && !isPatching;
  const canUnassign = !isFinal && !isPatching && onUnassign;
  
  // Debug logging
  console.log('[DraggableAssignment] Render:', {
    assignmentId,
    isFinal,
    isPatching,
    hasOnUnassign: !!onUnassign,
    canUnassign,
  });

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: assignmentId,
    disabled: !isDraggable,
  });

  const className = [
    'grid-assignment',
    isLocked && 'locked',
    isDragging && 'dragging',
    isPatching && 'patching',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div ref={setNodeRef} className={className} {...listeners} {...attributes} style={{ position: 'relative' }}>
      {canUnassign && (
        <div
          style={{
            position: 'absolute',
            top: '2px',
            right: '2px',
            zIndex: 100,
            pointerEvents: 'auto',
          }}
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Unassign] Pointer down on button wrapper');
            if (onUnassign) {
              onUnassign(assignmentId);
            }
          }}
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Unassign] Mouse down on button wrapper');
            if (onUnassign) {
              onUnassign(assignmentId);
            }
          }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Unassign] Click on button wrapper');
            if (onUnassign) {
              onUnassign(assignmentId);
            }
          }}
        >
          <button
            type="button"
            style={{
              background: 'rgba(255, 255, 255, 0.9)',
              border: 'none',
              borderRadius: '50%',
              width: '18px',
              height: '18px',
              cursor: 'pointer',
              fontSize: '12px',
              lineHeight: '1',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#d32f2f',
              fontWeight: 'bold',
              pointerEvents: 'auto',
            }}
            title="Unassign match (move back to unassigned queue)"
          >
            ×
          </button>
        </div>
      )}
      {match.match_code}
      <div style={{ fontSize: '10px', opacity: 0.9 }}>
        {match.stage} R{match.round_index}
      </div>
    </div>
  );
}


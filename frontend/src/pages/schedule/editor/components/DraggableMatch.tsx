import { useDraggable } from '@dnd-kit/core';
import { GridMatch } from '../../../../api/client';

interface DraggableMatchProps {
  matchId: number;
  match: GridMatch;
  isFinal: boolean;
  isPatching: boolean;
}

export function DraggableMatch({ matchId, match, isFinal, isPatching }: DraggableMatchProps) {
  const isDraggable = !isFinal && !isPatching;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `match_${matchId}`,  // Prefix to distinguish from assignment IDs
    disabled: !isDraggable,
  });

  const className = [
    'match-card',
    isDragging && 'dragging',
    isPatching && 'patching',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div ref={setNodeRef} className={className} {...listeners} {...attributes}>
      <div className="match-card-code">{match.match_code}</div>
      <div className="match-card-stage">
        {match.stage} R{match.round_index}
        {match.sequence_in_round > 0 && ` #${match.sequence_in_round}`}
      </div>
      <div className="match-card-duration">{match.duration_minutes} min</div>
    </div>
  );
}


import { useDroppable } from '@dnd-kit/core';
import { ReactNode } from 'react';

interface DroppableSlotProps {
  slotId: number;
  isOccupied: boolean;
  isFinal: boolean;
  children?: ReactNode;
}

export function DroppableSlot({
  slotId,
  isOccupied,
  isFinal,
  children,
}: DroppableSlotProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: slotId,
    disabled: isOccupied || isFinal,
  });

  const className = [
    'grid-cell',
    !isOccupied && !isFinal && 'droppable',
    isOccupied && 'occupied',
    isOver && !isOccupied && 'dragging-over',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div ref={setNodeRef} className={className}>
      {children}
    </div>
  );
}


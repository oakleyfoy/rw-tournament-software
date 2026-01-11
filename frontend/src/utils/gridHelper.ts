/**
 * Utility functions for generating 15-minute grid structure from tournament days/time windows
 */

export interface GridCell {
  dayDate: string
  timeSlot: string // HH:mm format
  courtNumber: number
  courtIndex: number // 0-based index for display
}

export interface GridDay {
  date: string
  timeSlots: string[] // Array of time slots in HH:mm format
  maxCourts: number
}

/**
 * Generate 15-minute time slots between start and end time
 */
export function generate15MinuteSlots(startTime: string, endTime: string): string[] {
  const slots: string[] = []
  const [startHour, startMin] = startTime.split(':').map(Number)
  const [endHour, endMin] = endTime.split(':').map(Number)
  
  const startMinutes = startHour * 60 + startMin
  const endMinutes = endHour * 60 + endMin
  
  let currentMinutes = startMinutes
  while (currentMinutes < endMinutes) {
    const hour = Math.floor(currentMinutes / 60)
    const min = currentMinutes % 60
    slots.push(`${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}`)
    currentMinutes += 15  // 15-minute tick interval
  }
  
  return slots
}

/**
 * @deprecated Use generate15MinuteSlots instead
 */
export function generate30MinuteSlots(startTime: string, endTime: string): string[] {
  return generate15MinuteSlots(startTime, endTime)
}

/**
 * Calculate how many 15-minute cells a match duration spans
 * Examples:
 * - 60 min (1:00) = 4 cells
 * - 90 min (1:30) = 6 cells
 * - 105 min (1:45) = 7 cells
 * - 120 min (2:00) = 8 cells
 */
export function getCellSpan(durationMinutes: number): number {
  // Each cell represents 15 minutes
  return Math.ceil(durationMinutes / 15)
}

